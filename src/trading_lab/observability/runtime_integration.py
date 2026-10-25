"""Non-authoritative, post-cycle capture with bounded asynchronous sinks.

The calling thread alone reads accepted RuntimeStore facts. The worker receives
immutable batches, never the store or any trading resource. Callers own resource
creation/cleanup and must prepare process restart before entering this wrapper.
"""

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from queue import Empty, Full, Queue
import sys
from threading import Event, Thread
from time import monotonic as monotonic_clock

from ..runtime.scheduler import SchedulerResult, run_hourly_scheduler
from .health import HealthSnapshot, build_health_snapshot
from .model import MAX_RETAINED_RECORDS, ObservabilityEvent, new_run_id, validate_run_id
from .projection import (
    critical_failure, cycle_completed, process_started, process_stopped,
    project_checkpoint_transition, project_retained_events, scheduler_exited, scheduler_started,
)
from .storage import ObservabilityStorage, safe_append_event, safe_write_health
from .telegram import (
    TelegramDeliveryStatus, TelegramDeliveryStore, TelegramHttpTransport,
    deliver_telegram_event, is_telegram_alert_event,
)

QUEUE_CAPACITY = 64
DRAIN_TIMEOUT_SECONDS = 2.0
_FALLBACK = "Runtime observability degraded.\n"
_DELIVERY_OK = frozenset((TelegramDeliveryStatus.DELIVERED,
    TelegramDeliveryStatus.ALREADY_DELIVERED, TelegramDeliveryStatus.NOT_ALERTABLE))


def _degrade(degraded):
    degraded.set()  # A run-scoped latch, never an input to trading control.
    try:
        sys.stderr.write(_FALLBACK)
    except Exception:
        pass


@dataclass(frozen=True, slots=True)
class _ObservationBatch:
    events: tuple[ObservabilityEvent, ...]
    health: HealthSnapshot | None


def _sink_worker(queue, closing, degraded, storage, transport, receipts, now_ms):
    """Deliberately a standalone target: no bound session/store reference.

    Local sink failures do not suppress Telegram attempts for immutable events.
    Each alert uses the frozen delivery policy, including receipt deduplication;
    no integration-level delivery retry or recursive failure event is added.
    """
    while not closing.is_set() or not queue.empty():
        try:
            batch = queue.get(timeout=0.05)
        except Empty:
            continue
        try:
            for event in batch.events:
                try:
                    if not safe_append_event(storage, event):
                        degraded.set()  # The frozen safe sink already reports failure.
                except Exception:
                    _degrade(degraded)
            if batch.health is not None:
                try:
                    if not safe_write_health(storage, batch.health):
                        degraded.set()
                except Exception:
                    _degrade(degraded)
            if transport is not None:
                for event in batch.events:
                    try:
                        if is_telegram_alert_event(event):
                            outcome = deliver_telegram_event(event, transport, receipts, utc_now_ms=now_ms)
                            if outcome.status not in _DELIVERY_OK:
                                _degrade(degraded)
                    except Exception:
                        _degrade(degraded)
        finally:
            queue.task_done()


class _RuntimeObservationSession:
    """Main-thread capture only; its observation frontier is never durable truth."""

    def __init__(self, store, storage, now_ms, run_id, transport, receipts):
        self.store, self.now_ms, self.run_id = store, now_ms, run_id
        self.configuration = self.last_observed_checkpoint = None
        self.started_at_ms = self.last_cycle_at_ms = self.last_cycle = None
        self.cycle_count = 0
        self.seen = OrderedDict()
        self.degraded, self.closing = Event(), Event()
        self.queue = Queue(maxsize=QUEUE_CAPACITY)
        self.worker = Thread(target=_sink_worker, name="trading-lab-observability", daemon=True,
            args=(self.queue, self.closing, self.degraded, storage, transport, receipts, now_ms))
        self.worker_started = False
        try:
            self.worker.start()
            self.worker_started = True
        except Exception:
            _degrade(self.degraded)

    def _enqueue(self, events, health=None):
        # Process IDs include their run/occurrence and are never deduped here.
        # Durable IDs are stable across runs; cache only successfully enqueued
        # facts. A dropped batch can therefore be recovered by later catch-up.
        retained = OrderedDict()
        selected = []
        for event in events:
            if event.source == "DURABLE":
                if event.event_id in self.seen or event.event_id in retained:
                    continue
                retained[event.event_id] = None
            selected.append(event)
        try:
            self.queue.put_nowait(_ObservationBatch(tuple(selected), health))
        except Full:
            _degrade(self.degraded)
            return
        self.seen.update(retained)
        while len(self.seen) > MAX_RETAINED_RECORDS:
            self.seen.popitem(last=False)

    def _time(self):
        at = self.now_ms()
        # Frozen event/health constructors validate the integer UTC timestamp.
        if self.started_at_ms is None:
            self.started_at_ms = at
        return at

    def _health(self, at):
        return build_health_snapshot(self.store, run_id=self.run_id,
            process_started_at_ms=self.started_at_ms, generated_at_ms=at,
            last_scheduler_activity_ms=at, last_cycle_activity_ms=self.last_cycle_at_ms,
            last_cycle_result=self.last_cycle,
            observability_status="DEGRADED" if self.degraded.is_set() else "OK")

    def start(self):
        try:
            self.configuration = self.store.get_configuration()
            self.last_observed_checkpoint = self.store.get_checkpoint()
            at = self._time()
            events = (process_started(self.configuration, run_id=self.run_id, observed_at_ms=at,
                                     process_started_at_ms=self.started_at_ms),
                      scheduler_started(self.configuration, run_id=self.run_id, observed_at_ms=at,
                                        scheduler_started_at_ms=at))
            events += project_retained_events(self.store, run_id=self.run_id, observed_at_ms=at)
            self._enqueue(events, self._health(at))
        except Exception:
            _degrade(self.degraded)

    def observe(self, result):
        self.cycle_count += 1
        before, after = self.last_observed_checkpoint, result.checkpoint
        try:
            at = self._time()
            self.last_cycle_at_ms, self.last_cycle = at, result
            events = (cycle_completed(self.configuration, result, run_id=self.run_id, observed_at_ms=at,
                                      occurrence_reference=f"cycle-{self.cycle_count:06d}"),)
            if before is not None and after.sequence == before.sequence + 1:
                events += project_checkpoint_transition(self.configuration, before, after, run_id=self.run_id,
                    observed_at_ms=at, contributing_execution_ids=result.new_execution_ids)
            events += project_retained_events(self.store, run_id=self.run_id, observed_at_ms=at)
            self._enqueue(events, self._health(at))
        except Exception:
            _degrade(self.degraded)
        finally:
            # Even failed capture advances this non-authoritative boundary.
            # A missed intermediate transition must remain a visible gap.
            self.last_observed_checkpoint = after

    def finish(self, result):
        try:
            at = self._time()
            events = project_retained_events(self.store, run_id=self.run_id, observed_at_ms=at)
            events += (scheduler_exited(self.configuration, result, run_id=self.run_id, observed_at_ms=at,
                                        occurrence_reference="scheduler-exit"),
                       process_stopped(self.configuration, run_id=self.run_id, observed_at_ms=at,
                           process_started_at_ms=self.started_at_ms, process_stopped_at_ms=at,
                           stop_reason=result.exit_reason.value))
            self._enqueue(events, self._health(at))
        except Exception:
            _degrade(self.degraded)

    def failed(self, error):
        # NO store access: scheduler failure can mean an indeterminate send.
        try:
            event = critical_failure(self.configuration, run_id=self.run_id, observed_at_ms=self._time(),
                occurrence_reference="scheduler-failure", operation="HOURLY_SCHEDULER",
                failure_kind="SCHEDULER_EXCEPTION", exception_type=type(error).__name__,
                safe_error_code="SCHEDULER_FAILED")
            self._enqueue((event,))
        except Exception:
            _degrade(self.degraded)

    def drain(self):
        self.closing.set()
        try:
            if self.worker_started:
                self.worker.join(timeout=DRAIN_TIMEOUT_SECONDS)
                if self.worker.is_alive():
                    _degrade(self.degraded)
        except Exception:
            _degrade(self.degraded)


def run_observed_hourly_scheduler(
    store, market_reader, broker, order_adapter, stop_signal, *,
    storage: ObservabilityStorage,
    utc_now: Callable[[], datetime],
    observability_now_ms: Callable[[], int],
    monotonic: Callable[[], float] = monotonic_clock,
    telegram_transport: TelegramHttpTransport | None = None,
    telegram_receipts: TelegramDeliveryStore | None = None,
    run_id: str | None = None,
) -> SchedulerResult:
    """Canonical Stage-12 entrypoint; explicit pre-created resources only.

    After canonical lock/open and prepare_process_restart, create resources and
    call here. No environment/client discovery, activation, rearm or server is
    performed. The caller retains ownership of all supplied resources, including
    sink resources until any timed-out daemon drain has completed. Queue overflow
    drops observations; worker drain is limited to two seconds. Health records
    describe capture time; a later asynchronous failure latches DEGRADED for
    subsequent captures, without rewriting earlier queued snapshots.
    """
    if not isinstance(storage, ObservabilityStorage) or not callable(observability_now_ms):
        raise ValueError("Explicit observability storage and clock are required.")
    if ((telegram_transport is None) != (telegram_receipts is None)
            or (telegram_transport is not None and
                (type(telegram_transport) is not TelegramHttpTransport
                 or type(telegram_receipts) is not TelegramDeliveryStore
                 or telegram_transport.target_hash != telegram_receipts.target_hash))):
        raise ValueError("Matching explicit Telegram transport and receipts are required.")
    run_id = new_run_id() if run_id is None else run_id
    validate_run_id(run_id)
    session = _RuntimeObservationSession(store, storage, observability_now_ms, run_id,
                                         telegram_transport, telegram_receipts)
    session.start()
    try:
        result = run_hourly_scheduler(store, market_reader, broker, order_adapter, stop_signal,
            utc_now=utc_now, monotonic=monotonic, cycle_observer=session.observe)
    except BaseException as error:
        session.failed(error)
        session.drain()
        raise
    session.finish(result)
    session.drain()
    return result
