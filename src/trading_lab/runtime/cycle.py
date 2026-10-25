"""One explicitly invoked Demo cycle; caller owns resources and activation.

Historical catch-up is bounded by the closed prefix and never sends an order.
All I/O uses public frozen boundaries; no transaction spans an external call.
Persistence errors stop execution for reopening, never trigger repair/resend.
"""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
import hashlib
import json
from time import monotonic as monotonic_clock

import pandas as pd

from ..backtest.strategy_validation import validate_strategy_output
from ..data.closed_candles import (
    ClosedCandlePrefix, MarketCandle, MarketDataIntegrityError,
    MarketDataInputError, MarketDataReadFailureKind, MarketDataResponseError,
    MarketDataTransportError, StaleMarketDataError, validate_candle_freshness,
)
from ..exchange.account_state import ReadOnlyBroker
from ..exchange.bybit_demo_orders import BybitDemoOrderAdapter, BybitDemoOrderRejectedError
from ..exchange.order_actions import SpotMarketOrderAcknowledgement, SpotMarketOrderRequest
from ..strategies.ema_trend import generate_ema_signals
from ..risk.runtime_risk import RiskReason, RiskVerdict
from .planner import CanonicalDecision, DecisionMode, PlanKind, plan_action
from .risk_gate import continue_refused_intent
from .reconciliation import reconcile_startup
from .state import (
    RuntimeEvent, RuntimeEventType, RuntimeEvidence, RuntimeReason, RuntimeState,
    transition_runtime_state,
)
from .store import (
    ActionPhase, CandleRecord, DecisionDisposition, RuntimeCheckpoint,
    RuntimeStore, RuntimeStoreError, serialize_decimal,
)


class CycleError(ValueError):
    """Invalid cycle input/boundary; fixed diagnostic text only."""


class _PreSubmitTimingRefusal(CycleError):
    """Known unsent timing refusal before invoking attempt persistence."""


class CycleOutcome(str, Enum):
    BOOTSTRAP = "BOOTSTRAP"
    REPLAY_ONLY = "REPLAY_ONLY"
    NO_NEW_DATA = "NO_NEW_DATA"
    NOOP = "NOOP"
    WAIT = "WAIT"
    RECONCILE = "RECONCILE"
    HALTED = "HALTED"
    STOPPING = "STOPPING"
    OBSERVED = "OBSERVED"
    ABANDONED_UNSENT = "ABANDONED_UNSENT"
    RISK_NOT_READY = "RISK_NOT_READY"
    RISK_BLOCKED = "RISK_BLOCKED"
    RISK_TRIPPED = "RISK_TRIPPED"


@dataclass(frozen=True, slots=True)
class SingleCycleResult:
    """Durable normalized facts; OBSERVED does not imply a fill or terminality."""

    checkpoint: RuntimeCheckpoint
    outcome: CycleOutcome
    processed_candle_open_ms: tuple[int, ...] = ()
    planner_kind: PlanKind | None = None
    logical_action_id: str | None = None
    broker_order_id: str | None = None
    new_execution_ids: tuple[str, ...] = ()
    reason: RuntimeReason | None = None
    risk_verdict: RiskVerdict | None = None
    risk_reason: RiskReason | None = None

    @property
    def processed_candle_count(self) -> int:
        return len(self.processed_candle_open_ms)


def _milliseconds(value):
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise CycleError("An explicit aware UTC clock/timestamp is required.")
    delta = value - datetime(1970, 1, 1, tzinfo=timezone.utc)
    # Match frozen reconciliation: floor observation microseconds explicitly,
    # using integer arithmetic, never a floating point epoch conversion.
    ms = (delta.days * 86400 + delta.seconds) * 1000 + delta.microseconds // 1000
    if not 0 <= ms <= 2**63 - 1:
        raise CycleError("UTC timestamp is outside the supported range.")
    return ms


def _candle_bytes(candle):
    payload = {"candle_open_ms": candle.candle_open_ms,
               "symbol": candle.symbol, "timeframe": candle.timeframe}
    for field in ("open", "high", "low", "close", "volume"):
        payload[field] = serialize_decimal(getattr(candle, field))
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _candle_record(candle):
    if type(candle) is not MarketCandle:
        raise CycleError("A normalized market candle is required.")
    replace(candle)  # Revalidate without sorting, repairing or changing money.
    return CandleRecord(candle.symbol, candle.timeframe, candle.candle_open_ms,
                        hashlib.sha256(_candle_bytes(candle)).hexdigest(),
                        candle.open, candle.high, candle.low, candle.close, candle.volume)


def _strategy_decisions(prefix, config):
    records = tuple(_candle_record(candle) for candle in prefix.candles)
    # This is the only float boundary. Durable OHLCV and order money stay Decimal.
    frame = pd.DataFrame({
        "timestamp": pd.to_datetime([c.candle_open_ms for c in records], unit="ms", utc=True),
        "close": [float(c.close) for c in records],
    })
    generated = generate_ema_signals(frame.copy(deep=True), **dict(config.strategy_parameters))
    # Reuse Decision 010's pure intent validator, never backtest execution/fills.
    output = validate_strategy_output(frame, generated)
    decisions = []
    for record, signal, desired in zip(records, output["signal"], output["desired_position"]):
        decisions.append(CanonicalDecision(record.symbol, record.timeframe, record.candle_open_ms,
                                           record.input_fingerprint, signal, int(desired),
                                           record.candle_open_ms + config.interval_ms))
    return records, tuple(decisions)


def _history_matches(store, checkpoint, records, decisions):
    canonical_fields = ("symbol", "timeframe", "candle_open_ms", "input_fingerprint",
                        "signal", "desired_position", "available_at_ms")
    for record, decision in zip(records, decisions):
        saved_candle = store.get_candle(record.candle_open_ms)
        saved_decision = store.get_decision(record.candle_open_ms)
        handled = (checkpoint.last_processed_candle_ms is not None
                   and record.candle_open_ms <= checkpoint.last_processed_candle_ms)
        if handled:
            if (saved_candle != record or saved_decision is None
                    or any(getattr(saved_decision, field) != getattr(decision, field) for field in canonical_fields)):
                return False
        elif saved_candle is not None or saved_decision is not None:
            return False
    return True


def _proposed(current, events, now_ms, **changes):
    snapshot = current.snapshot
    for event in events:
        snapshot = transition_runtime_state(snapshot, event)
    return replace(current, sequence=current.sequence + 1, snapshot=snapshot,
                   halted_at_ms=now_ms if snapshot.state == RuntimeState.HALTED else current.halted_at_ms,
                   **changes)


def _clear_pending(current, action_id):
    quantity = current.snapshot.owned_base_quantity
    return RuntimeEvent(RuntimeEventType.RECONCILED_FLAT if quantity == 0 else RuntimeEventType.RECONCILED_LONG,
                        evidence=RuntimeEvidence(quantity, terminal_action_id=action_id))


def _receipt_action(action, receipt, config, now_ms):
    if (type(receipt) is not SpotMarketOrderAcknowledgement or receipt.broker_id != config.broker_id
            or receipt.order_link_id != action.order_link_id or receipt.symbol != action.symbol
            or receipt.side != action.side or receipt.order_type != "MARKET"
            or receipt.amount_unit != action.amount_unit):
        raise CycleError("Placement receipt identity does not match durable authorization.")
    broker_ms, observed_ms = _milliseconds(receipt.broker_timestamp), _milliseconds(receipt.fetched_at)
    if (abs(broker_ms - observed_ms) > config.max_clock_skew_ms
            or observed_ms > now_ms + config.max_clock_skew_ms
            or now_ms - observed_ms > config.observation_max_age_ms
            or min(broker_ms, observed_ms) < action.candle_open_ms + config.interval_ms):
        raise CycleError("Placement receipt timing is untrustworthy.")
    # Frozen record validation checks exact Decimal amount, authorization bounds
    # and safe broker ID. This is validation, not a persistence operation.
    return replace(action, phase=ActionPhase.ACKNOWLEDGED, broker_order_id=receipt.broker_order_id,
                   submitted_amount=receipt.submitted_amount,
                   acknowledgement_broker_ms=broker_ms, acknowledgement_observed_ms=observed_ms)


def run_single_cycle(
    store: RuntimeStore,
    market_reader,
    broker: ReadOnlyBroker,
    order_adapter: BybitDemoOrderAdapter,
    *,
    utc_now: Callable[[], datetime],
    monotonic: Callable[[], float] = monotonic_clock,
    reconciliation_observer: Callable[[RuntimeCheckpoint, RuntimeCheckpoint, tuple[str, ...]], object] | None = None,
) -> SingleCycleResult:
    """Reconcile, handle one bounded prefix, optionally send once and observe once.

    Initial history and multi-candle backlog are historical-only. Their full
    cutoff is saved before sequential commits so a crash cannot make the last
    historical candle LIVE on restart. No adapter/resource is constructed here.
    RuntimeStore errors propagate; callers must reopen/reconcile, never resend.
    """
    if (not isinstance(store, RuntimeStore) or not callable(utc_now) or not callable(monotonic)
            or not callable(getattr(market_reader, "get_closed_candles", None))
            or not callable(getattr(order_adapter, "place_market_order", None))):
        raise CycleError("Existing store/read/action boundaries and explicit clocks are required.")

    initial = reconcile_startup(store, broker, utc_now=utc_now, monotonic=monotonic,
                                reconciliation_observer=reconciliation_observer)
    config, current = store.get_configuration(), initial.checkpoint
    processed, execution_ids = [], list(initial.new_execution_ids)
    last_ms = current.observed_at_ms or 0
    planner_kind = None
    action_id = None
    risk_verdict = risk_reason = None

    def now():
        nonlocal last_ms
        try:
            value = _milliseconds(utc_now())
        except Exception:
            raise CycleError("Invalid cycle control clock.") from None
        if value < last_ms:
            raise CycleError("Cycle control clock regressed.")
        last_ms = value
        return value

    def result(outcome, reason=None):
        cp = store.get_checkpoint()
        selected_id = action_id or (cp.snapshot.pending_action.logical_action_id if cp.snapshot.pending_action else None)
        action = store.get_action(selected_id) if selected_id is not None else None
        return SingleCycleResult(cp, outcome, tuple(processed), planner_kind, selected_id,
                                 action.broker_order_id if action is not None and action.acknowledgement_broker_ms is not None else None,
                                 tuple(dict.fromkeys(execution_ids)), reason or cp.snapshot.reason,
                                 risk_verdict, risk_reason)

    def halt(reason):
        cp = store.get_checkpoint()
        proposed = _proposed(cp, (RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY, reason=reason),), now())
        store.save_checkpoint(proposed, expected_sequence=cp.sequence)
        return result(CycleOutcome.HALTED, reason)

    def market_unavailable(outcome=CycleOutcome.WAIT):
        cp = store.get_checkpoint()
        if cp.snapshot.state in (RuntimeState.FLAT, RuntimeState.LONG):
            proposed = _proposed(cp, (RuntimeEvent(RuntimeEventType.FRESHNESS_LOST),), now())
            store.save_checkpoint(proposed, expected_sequence=cp.sequence)
        return result(outcome, RuntimeReason.EVIDENCE_MISSING)

    if current.snapshot.state == RuntimeState.HALTED:
        return result(CycleOutcome.HALTED)
    if current.snapshot.state == RuntimeState.STOPPING:
        return result(CycleOutcome.STOPPING)
    if current.snapshot.state not in (RuntimeState.FLAT, RuntimeState.LONG, RuntimeState.ORDER_PENDING):
        return result(CycleOutcome.RECONCILE, current.snapshot.reason or RuntimeReason.EVIDENCE_MISSING)

    before_market_ms = now()
    try:
        prefix = market_reader.get_closed_candles(symbol=config.symbol, timeframe=config.timeframe,
                                                  history_anchor_ms=config.history_anchor_ms,
                                                  max_data_age_ms=config.decision_max_age_ms)
    except (MarketDataIntegrityError, MarketDataInputError, MarketDataResponseError):
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    except StaleMarketDataError:
        return market_unavailable()
    except MarketDataTransportError as error:
        if error.kind is MarketDataReadFailureKind.TRANSIENT:
            return market_unavailable()
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    except Exception:
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    after_market_ms = now()
    try:
        if type(prefix) is not ClosedCandlePrefix:
            raise CycleError("A complete normalized closed prefix is required.")
        replace(prefix)
        for candle in prefix.candles:
            replace(candle)
        if (prefix.symbol != config.symbol or prefix.timeframe != config.timeframe
                or prefix.history_anchor_ms != config.history_anchor_ms
                or prefix.end_ms != prefix.server_time_ms // config.interval_ms * config.interval_ms
                or (current.last_processed_candle_ms is not None and current.last_processed_candle_ms >= prefix.end_ms)):
            raise CycleError("Market prefix contradicts anchored durable history.")
    except Exception:
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    # Both authoritative samples must fit the UTC interval of this bounded read.
    # Comparing the early sample to the final local instant would mistake
    # pagination latency for clock skew.
    if any(not before_market_ms - config.max_clock_skew_ms <= sample <= after_market_ms + config.max_clock_skew_ms
           for sample in (prefix.server_time_ms, prefix.observed_at_ms)):
        return halt(RuntimeReason.INVALID_CONFIGURATION)
    if not prefix.candles:
        return market_unavailable(CycleOutcome.NO_NEW_DATA)
    try:
        validate_candle_freshness(newest_closed_candle_open_ms=prefix.candles[-1].candle_open_ms,
                                  server_time_ms=prefix.observed_at_ms, max_data_age_ms=config.decision_max_age_ms)
    except StaleMarketDataError:
        return market_unavailable()
    except Exception:
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    try:
        records, decisions = _strategy_decisions(prefix, config)
    except Exception:
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    if not _history_matches(store, current, records, decisions):
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE)
    first = 0 if current.last_processed_candle_ms is None else (current.last_processed_candle_ms - config.history_anchor_ms) // config.interval_ms + 1
    if first == len(records):
        return result(CycleOutcome.NO_NEW_DATA)
    # Reserve history before commits, but never extend an interrupted bootstrap.
    # Its cutoff is durable even if the first decision never committed.
    cutoffs = {}
    if (current.last_processed_candle_ms is None and current.bootstrap_until_ms is None
            and current.replay_until_ms is None):
        cutoffs["bootstrap_until_ms"] = records[-1].candle_open_ms
    elif (len(records) - first > 1
          and (current.bootstrap_until_ms is None or records[-1].candle_open_ms > current.bootstrap_until_ms)
          and (current.replay_until_ms is None or records[-1].candle_open_ms > current.replay_until_ms)):
        cutoffs["replay_until_ms"] = records[-1].candle_open_ms
    if cutoffs:
        proposed = replace(current, sequence=current.sequence + 1, **cutoffs)
        store.save_checkpoint(proposed, expected_sequence=current.sequence)

    for record, decision in zip(records[first:], decisions[first:]):
        current = store.get_checkpoint()
        # A restarted prefix can contain both unfinished bootstrap and later
        # backlog. Classify each candle from the reserved cutoffs, in that order.
        if current.bootstrap_until_ms is not None and record.candle_open_ms <= current.bootstrap_until_ms:
            mode = DecisionMode.BOOTSTRAP
        elif current.replay_until_ms is not None and record.candle_open_ms <= current.replay_until_ms:
            mode = DecisionMode.REPLAY_ONLY
        else:
            mode = DecisionMode.LIVE
        evaluated_ms = now()
        plan = plan_action(config, current, decision, evaluated_at_ms=evaluated_ms,
                           mode=mode, action_history=store.list_actions())
        # Operational planner refusals retain precedence. Only an eligible LIVE
        # decision (or the specific refusal-continuation candidate) consults risk.
        live = (mode is DecisionMode.LIVE and plan.decision is not None
                and plan.decision.disposition in (DecisionDisposition.ACTION,
                                                  DecisionDisposition.NOOP, DecisionDisposition.WAIT))
        continuation = (mode is DecisionMode.LIVE and plan.kind is PlanKind.HALT
                        and plan.reason is RuntimeReason.INCONSISTENT_EVIDENCE
                        and decision.signal == "HOLD" and decision.desired_position == 1)
        if live or continuation:
            epoch = store.get_current_risk_epoch()
            if epoch is None and live:
                planner_kind = plan.kind
                return result(CycleOutcome.RISK_NOT_READY)
            if epoch is not None:
                latest = store.get_latest_risk_valuation()
                # Bounded by the complete durable decision history. Separate
                # historical commits authorize nothing and are crash recoverable.
                for at in range(latest.candle_open_ms + config.interval_ms,
                                current.last_processed_candle_ms + 1, config.interval_ms):
                    store.append_risk_replay_valuation(candle_open_ms=at)
                if continuation:
                    verdicts = {row.candle_open_ms: row for row in store.list_risk_verdicts(epoch.epoch_id)}
                    history = tuple((store.get_decision(row.candle_open_ms), row,
                                     verdicts.get(row.candle_open_ms))
                                    for row in store.list_risk_valuations(epoch.epoch_id))
                    plan = continue_refused_intent(config, current, decision, plan,
                        evaluated_at_ms=evaluated_ms, epoch=epoch, history=history,
                        action_history=store.list_actions())
                    live = plan.kind is PlanKind.NOOP
        planner_kind = plan.kind
        changes = {}
        if plan.decision is not None:
            changes["last_processed_candle_ms"] = decision.candle_open_ms
            for disposition, field in ((DecisionDisposition.BOOTSTRAP, "bootstrap_until_ms"),
                                       (DecisionDisposition.REPLAY_ONLY, "replay_until_ms")):
                if plan.decision.disposition == disposition:
                    changes[field] = max(getattr(current, field) or 0, decision.candle_open_ms)
        proposed = _proposed(current, plan.events, evaluated_ms, **changes)
        if plan.decision is None:
            if plan.events:
                store.save_checkpoint(proposed, expected_sequence=current.sequence)
            return result({PlanKind.HALT: CycleOutcome.HALTED, PlanKind.RECONCILE: CycleOutcome.RECONCILE}.get(plan.kind, CycleOutcome.WAIT), plan.reason)
        if live:
            committed = store.commit_live_risk_decision(record, plan.decision, proposed,
                expected_sequence=current.sequence, evaluated_at_ms=evaluated_ms,
                proposed_action=plan.action)
        else:
            committed = store.commit_decision(record, plan.decision, proposed,
                                               expected_sequence=current.sequence, action=plan.action)
        if not committed:
            return result(CycleOutcome.WAIT)  # Reload only; replay never licenses a send.
        processed.append(decision.candle_open_ms)
        if live:
            verdict = store.get_risk_verdict(decision.candle_open_ms)
            if verdict is None:
                raise RuntimeStoreError("Committed LIVE decision requires its durable risk verdict.")
            risk_verdict, risk_reason = verdict.verdict, verdict.reason
            if risk_verdict is not RiskVerdict.ALLOW:
                return result(CycleOutcome.RISK_BLOCKED if risk_verdict is RiskVerdict.BLOCK else CycleOutcome.RISK_TRIPPED)
            if verdict.action_id != (None if plan.action is None else plan.action.logical_action_id):
                raise RuntimeStoreError("Durable risk approval must match the proposed placement.")
        if plan.kind == PlanKind.HALT:
            return result(CycleOutcome.HALTED, plan.reason)
        if plan.action is None:
            continue

        action_id = plan.action.logical_action_id
        request = SpotMarketOrderRequest(plan.action.symbol, plan.action.side, plan.action.authorized_amount,
                                         plan.action.amount_unit, plan.action.order_link_id)
        callback_entered = pre_submit_timing_accepted = False
        start_attempt_call_begun = attempt_commit_returned = False

        def before_submit():
            nonlocal callback_entered, pre_submit_timing_accepted, start_attempt_call_begun, attempt_commit_returned
            if callback_entered:
                raise CycleError("The attempt boundary may be entered only once.")
            callback_entered = True
            submit_ms = now()
            if (submit_ms < decision.available_at_ms
                    or submit_ms - decision.available_at_ms > config.decision_max_age_ms
                    or submit_ms >= plan.action.reconciliation_deadline_ms):
                raise _PreSubmitTimingRefusal("Pre-submit authorization timing is no longer valid.")
            pre_submit_timing_accepted = True
            cp = store.get_checkpoint()
            attempted_checkpoint = replace(cp, sequence=cp.sequence + 1)
            start_attempt_call_begun = True
            store.start_attempt(action_id, attempted_checkpoint, expected_sequence=cp.sequence)
            attempt_commit_returned = True

        failure = None
        try:
            receipt = order_adapter.place_market_order(request, before_submit=before_submit)
        except Exception as error:
            if start_attempt_call_begun and not attempt_commit_returned:
                # No further read/write: the commit may actually have completed.
                raise RuntimeStoreError("Attempt persistence requires reopening; no further cycle action.") from None
            if (callback_entered and not attempt_commit_returned
                    and not (isinstance(error, _PreSubmitTimingRefusal) and not pre_submit_timing_accepted)):
                # A failed clock/read is not a known timing refusal. Stop safely
                # without trying another store read, abandon or placement.
                if isinstance(error, RuntimeStoreError):
                    raise RuntimeStoreError("Pre-submit persistence read requires reopening; no further cycle action.") from None
                raise CycleError("Pre-submit control failed; reopen and reconcile.") from None
            failure = error
        if not callback_entered or (isinstance(failure, _PreSubmitTimingRefusal)
                                    and not pre_submit_timing_accepted and not start_attempt_call_begun):
            if failure is None:
                raise CycleError("Adapter did not confirm the required attempt boundary.")
            cp = store.get_checkpoint()
            proposed = _proposed(cp, (_clear_pending(cp, action_id),), now())
            store.abandon_prepared(action_id, proposed, expected_sequence=cp.sequence, terminal_at_ms=last_ms)
            return result(CycleOutcome.ABANDONED_UNSENT)
        if not attempt_commit_returned:
            raise RuntimeStoreError("Attempt persistence requires reopening; no further cycle action.")
        cp, attempted = store.get_checkpoint(), store.get_action(action_id)
        outcome_ms = now()
        if (isinstance(failure, BybitDemoOrderRejectedError) and failure.operation == "place_order"
                and type(failure.ret_code) is int and -(2**63) <= failure.ret_code < 2**63 and failure.ret_code != 0):
            rejected = replace(attempted, phase=ActionPhase.REJECTED, rejection_code=failure.ret_code,
                               terminal_at_ms=outcome_ms, safe_reason=RuntimeReason.INCONSISTENT_EVIDENCE)
            proposed = _proposed(cp, (_clear_pending(cp, action_id), RuntimeEvent(
                RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.INCONSISTENT_EVIDENCE)), outcome_ms)
            store.record_observation(rejected, proposed, expected_sequence=cp.sequence)
            return result(CycleOutcome.HALTED)
        acknowledged = None
        if failure is None:
            try:
                acknowledged = _receipt_action(attempted, receipt, config, outcome_ms)
            except Exception:
                pass  # Malformed normalized receipt is post-attempt uncertainty.
        if acknowledged is not None:
            event = RuntimeEvent(RuntimeEventType.PLACEMENT_ACKNOWLEDGED, pending_action=cp.snapshot.pending_action)
            observed = acknowledged
        else:
            event = RuntimeEvent(RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            observed = replace(attempted, phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        proposed = _proposed(cp, (event,), outcome_ms)
        # Persistence is outside exception classification. Failure stops here;
        # no second send, observation repair or reconciliation after a failed write.
        store.record_observation(observed, proposed, expected_sequence=cp.sequence)
        final = reconcile_startup(store, broker, utc_now=utc_now, monotonic=monotonic,
                                  reconciliation_observer=reconciliation_observer)
        execution_ids.extend(final.new_execution_ids)
        return result(CycleOutcome.OBSERVED)

    return result({DecisionMode.BOOTSTRAP: CycleOutcome.BOOTSTRAP,
                   DecisionMode.REPLAY_ONLY: CycleOutcome.REPLAY_ONLY}.get(mode,
                   CycleOutcome.WAIT if planner_kind == PlanKind.WAIT else CycleOutcome.NOOP))
