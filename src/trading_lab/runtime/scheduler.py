"""Serialized hourly control around the frozen cycle; no resource ownership.

Only normally returned transient read deficiencies permit bounded cycle retries.
Cycle/store exceptions propagate immediately, without shutdown writes or repair.
The caller supplies activation, clocks, stop signal and final resource cleanup.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import math
from numbers import Real
from time import monotonic as monotonic_clock

from ..exchange.account_state import ReadOnlyBroker
from ..exchange.bybit_demo_orders import BybitDemoOrderAdapter
from .cycle import CycleOutcome, SingleCycleResult, run_single_cycle
from .state import RuntimeEvent, RuntimeEventType, RuntimeReason, RuntimeState, transition_runtime_state
from .store import RuntimeCheckpoint, RuntimeStore


class SchedulerError(RuntimeError):
    """Invalid scheduler input/control evidence; fixed diagnostics only."""


class SchedulerExit(str, Enum):
    STOP_REQUESTED = "STOP_REQUESTED"
    HALTED = "HALTED"
    STOPPING = "STOPPING"


@dataclass(frozen=True, slots=True)
class SchedulerResult:
    """Final durable state and control counts, never broker payloads/resources."""

    checkpoint: RuntimeCheckpoint
    exit_reason: SchedulerExit
    cycle_count: int
    wake_count: int
    last_cycle: SingleCycleResult | None = None


def _milliseconds(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise SchedulerError("An explicit aware UTC control clock is required.")
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    ms = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    if not 0 <= ms <= 2**63 - 1:
        raise SchedulerError("UTC control time is outside the supported range.")
    return ms


def run_hourly_scheduler(
    store: RuntimeStore,
    market_reader,
    broker: ReadOnlyBroker,
    order_adapter: BybitDemoOrderAdapter,
    stop_signal,
    *,
    utc_now: Callable[[], datetime],
    monotonic: Callable[[], float] = monotonic_clock,
) -> SchedulerResult:
    """Run immediately, then on the absolute UTC grid until stop/HALT/STOPPING.

    A batch permits at most three normal transient-read attempts (1s, then 2s).
    Retry starts must fit the original monotonic budget and scheduled close's
    decision age. Exceptions never license retry, cleanup or a STOPPING write.
    """
    if (not isinstance(store, RuntimeStore) or not callable(utc_now) or not callable(monotonic)
            or not callable(getattr(stop_signal, "is_set", None))
            or not callable(getattr(stop_signal, "wait", None))):
        raise SchedulerError("Existing resources, explicit clocks and an event-like stop signal are required.")

    config = store.get_configuration()
    current = store.get_checkpoint()
    cycle_count = wake_count = 0
    last_cycle = None
    last_utc_ms = last_elapsed = None

    def control():
        nonlocal last_utc_ms, last_elapsed
        try:
            utc_ms, elapsed = _milliseconds(utc_now()), monotonic()
            if isinstance(elapsed, bool) or not isinstance(elapsed, Real) or not math.isfinite(elapsed):
                raise SchedulerError("A finite real monotonic control clock is required.")
        except Exception:
            raise SchedulerError("Invalid scheduler control clock.") from None
        if last_utc_ms is not None and utc_ms < last_utc_ms:
            raise SchedulerError("Scheduler UTC control clock regressed.")
        if last_elapsed is not None and elapsed < last_elapsed:
            raise SchedulerError("Scheduler monotonic control clock regressed.")
        last_utc_ms, last_elapsed = utc_ms, elapsed
        return utc_ms, elapsed

    def stopped():
        try:
            requested = stop_signal.is_set()
            if type(requested) is not bool:
                raise SchedulerError("Stop signal must return explicit booleans.")
            return requested
        except Exception:
            raise SchedulerError("Invalid scheduler stop signal.") from None

    def wait(seconds):
        try:
            requested = stop_signal.wait(seconds)
            if type(requested) is not bool:
                raise SchedulerError("Stop wait must return an explicit boolean.")
        except Exception:
            raise SchedulerError("Invalid scheduler stop wait.") from None
        # A true wait result records a stop even if another caller clears the
        # signal immediately afterward. False/spurious wakes recheck is_set.
        return requested or stopped()

    def finish(checkpoint, reason):
        return SchedulerResult(checkpoint, reason, cycle_count, wake_count, last_cycle)

    def shutdown():
        cp = store.get_checkpoint()
        if cp.snapshot.state != RuntimeState.STOPPING:
            utc_ms, _ = control()
            snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED))
            proposed = replace(cp, sequence=cp.sequence + 1, snapshot=snapshot, shutdown_at_ms=utc_ms)
            store.save_checkpoint(proposed, expected_sequence=cp.sequence)
            cp = proposed
        return finish(cp, SchedulerExit.STOP_REQUESTED)

    def retry_in_window(utc_ms, elapsed, batch_start, boundary_ms, delay=0):
        if (elapsed - batch_start + delay) * 1000 > config.reconciliation_timeout_ms:
            return False
        return boundary_ms is None or utc_ms - boundary_ms + delay * 1000 <= config.decision_max_age_ms

    def batch(boundary_ms):
        nonlocal cycle_count, last_cycle
        _, batch_start = control()
        for attempt in range(3):
            if stopped():
                return shutdown()
            utc_ms, elapsed = control()
            if attempt and not retry_in_window(utc_ms, elapsed, batch_start, boundary_ms):
                return None
            cycle_count += 1
            # Deliberately no try/finally: an exception can mean an indeterminate
            # durable send boundary. Only later approved restart code may recover.
            last_cycle = run_single_cycle(store, market_reader, broker, order_adapter,
                                           utc_now=utc_now, monotonic=monotonic)
            if (type(last_cycle) is not SingleCycleResult
                    or not isinstance(last_cycle.outcome, CycleOutcome)
                    or (last_cycle.reason is not None and not isinstance(last_cycle.reason, RuntimeReason))):
                raise SchedulerError("Invalid normalized cycle control result.")
            cp = store.get_checkpoint()
            if last_cycle.checkpoint != cp:
                raise SchedulerError("Cycle control result differs from durable checkpoint.")
            utc_ms, elapsed = control()
            if stopped():
                return shutdown()
            if cp.snapshot.state == RuntimeState.STOPPING or last_cycle.outcome == CycleOutcome.STOPPING:
                return finish(cp, SchedulerExit.STOPPING)
            if cp.snapshot.state == RuntimeState.HALTED or last_cycle.outcome == CycleOutcome.HALTED:
                return finish(cp, SchedulerExit.HALTED)
            retryable = (last_cycle.outcome in (CycleOutcome.WAIT, CycleOutcome.RECONCILE, CycleOutcome.NO_NEW_DATA)
                         and last_cycle.reason in (RuntimeReason.EVIDENCE_MISSING, RuntimeReason.ACTION_OUTCOME_UNKNOWN))
            delay = attempt + 1
            if not retryable or attempt == 2 or not retry_in_window(utc_ms, elapsed, batch_start, boundary_ms, delay):
                return None
            backoff_until = elapsed + delay
            while elapsed < backoff_until:
                requested = wait(backoff_until - elapsed)
                utc_ms, elapsed = control()
                if requested or stopped():
                    return shutdown()
                if not retry_in_window(utc_ms, elapsed, batch_start, boundary_ms):
                    return None
        return None

    if stopped():
        return shutdown()
    if current.snapshot.state == RuntimeState.STOPPING:
        return finish(current, SchedulerExit.STOPPING)

    utc_ms, _ = control()
    # Reserve BEFORE startup work: its latency must not skip this next hour.
    target_ms = (utc_ms // config.interval_ms + 1) * config.interval_ms
    completed = batch(None)
    if completed is not None:
        return completed

    while True:
        if stopped():
            return shutdown()
        utc_ms, _ = control()
        if utc_ms < target_ms:
            requested = wait((target_ms - utc_ms) / 1000)
            control()  # Validate clocks even on a signaled/spurious wake.
            if requested or stopped():
                return shutdown()
            continue
        wake_count += 1
        completed = batch(target_ms)
        if completed is not None:
            return completed
        utc_ms, _ = control()
        # One catch-up batch, then jump directly over all missed UTC boundaries.
        target_ms = (utc_ms // config.interval_ms + 1) * config.interval_ms
