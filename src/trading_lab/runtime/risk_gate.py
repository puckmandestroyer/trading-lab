"""Pure adapters and complete refusal provenance under Decision 020.

These functions interpret supplied immutable facts only. They cannot authorize
durably, change an amount, create an action, or observe an external resource.
Accounting and policy remain in risk.runtime_risk; the store owns atomicity.
"""

from dataclasses import replace

from ..risk.runtime_risk import RiskActionKind, RiskActionProposal, RiskVerdict
from .planner import ActionPlan, PlanKind
from .state import PositionEvidence, RuntimeEvent, RuntimeEventType, RuntimeReason, RuntimeState
from .store import (
    ActionPhase, ActionRecord, DecisionDisposition, DecisionRecord,
    JournalActionKind, RiskEpochRecord, RiskValuationMode, RiskValuationRecord,
    RiskVerdictRecord, RuntimeStoreError,
)


_HOUR_MS = 3_600_000
_MAX_HISTORY = 100_000


def risk_proposal(action: ActionRecord | None) -> RiskActionProposal | None:
    """Preserve the planner's exact quote ENTRY or base EXIT authorization."""
    if action is None:
        return None
    if type(action) is not ActionRecord:
        raise RuntimeStoreError("A validated planner placement proposal is required.")
    replace(action)
    if action.phase is not ActionPhase.PREPARED or action.kind is JournalActionKind.CANCEL:
        raise RuntimeStoreError("Only a fresh planner ENTRY or EXIT may be risk evaluated.")
    return RiskActionProposal(RiskActionKind(action.kind.value), action.authorized_amount)


def refusal_frontiers(config, epoch, history, action_history) -> frozenset[int]:
    """Return proved refused-intent frontiers from a complete epoch history.

    history contains (decision, valuation, optional verdict) for EVERY hour,
    starting at ACTIVATION. A broken link ends a chain; an omitted/malformed
    record invalidates the complete proof. Never skip to a convenient suffix.
    An origin is included so its very next HOLD can continue without an action.
    """
    if (type(epoch) is not RiskEpochRecord or type(history) is not tuple
            or not 0 < len(history) <= _MAX_HISTORY or type(action_history) is not tuple
            or len(action_history) > _MAX_HISTORY):
        return frozenset()
    proved, continuing = set(), False
    try:
        replace(epoch)
        action_candles = set()
        for action in action_history:
            if type(action) is not ActionRecord:
                return frozenset()
            replace(action)
            if action.kind is not JournalActionKind.CANCEL:
                action_candles.add(action.candle_open_ms)
        for index, link in enumerate(history):
            if type(link) is not tuple or len(link) != 3:
                return frozenset()
            decision, valuation, verdict = link
            if type(decision) is not DecisionRecord or type(valuation) is not RiskValuationRecord:
                return frozenset()
            replace(decision)
            replace(valuation)
            if (valuation.epoch_id != epoch.epoch_id
                    or valuation.risk_configuration_digest != epoch.risk_configuration_digest
                    or valuation.valued_at_ms != epoch.started_at_ms + index * _HOUR_MS
                    or (decision.symbol, decision.timeframe, decision.candle_open_ms, decision.available_at_ms)
                    != (config.symbol, config.timeframe, valuation.candle_open_ms, valuation.valued_at_ms)
                    or (valuation.symbol, valuation.timeframe) != (config.symbol, config.timeframe)):
                return frozenset()
            if (index == 0) != (valuation.mode is RiskValuationMode.ACTIVATION):
                return frozenset()
            if valuation.mode is not RiskValuationMode.LIVE:
                if verdict is not None:
                    return frozenset()
                continuing = False
                continue
            if type(verdict) is not RiskVerdictRecord:
                return frozenset()
            replace(verdict)
            if (verdict.epoch_id, verdict.risk_configuration_digest, verdict.symbol,
                    verdict.timeframe, verdict.candle_open_ms, verdict.valued_at_ms) != (
                    epoch.epoch_id, epoch.risk_configuration_digest, config.symbol,
                    config.timeframe, valuation.candle_open_ms, valuation.valued_at_ms):
                return frozenset()
            if verdict.action_id != decision.action_id:
                return frozenset()
            no_action = (decision.action_id is None and verdict.action_id is None
                         and decision.candle_open_ms not in action_candles
                         and valuation.owned_base_quantity == 0 and decision.desired_position == 1)
            origin = (no_action and decision.signal == "LONG_ENTRY"
                      and decision.disposition is DecisionDisposition.WAIT
                      and verdict.verdict in (RiskVerdict.BLOCK, RiskVerdict.TRIP)
                      and verdict.proposal_kind is RiskActionKind.ENTRY
                      and verdict.authorized_amount == config.buy_quote_budget)
            hold = (continuing and no_action and decision.signal == "HOLD"
                    and decision.disposition is DecisionDisposition.NOOP
                    and verdict.verdict is RiskVerdict.ALLOW
                    and verdict.proposal_kind is None and verdict.authorized_amount is None)
            continuing = origin or hold
            if continuing:
                proved.add(decision.candle_open_ms)
    except (RuntimeStoreError, AttributeError, TypeError, ValueError):
        return frozenset()
    return frozenset(proved)


def continue_refused_intent(config, checkpoint, decision, plan, *, evaluated_at_ms,
                            epoch, history, action_history) -> ActionPlan:
    """Interpret only the frozen planner's fresh FLAT/HOLD intent mismatch.

    Every earlier planner guard still runs normally. Explicit timing checks also
    distinguish its identically shaped expired-intent HALT. The returned NOOP
    carries no proposal, so price recovery/midnight can never resurrect a BUY.
    """
    snapshot = checkpoint.snapshot
    expected_events = (
        RuntimeEvent(RuntimeEventType.NO_CHANGE, desired_position=1),
        RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.INCONSISTENT_EVIDENCE),
    )
    if (plan.kind is not PlanKind.HALT or plan.reason is not RuntimeReason.INCONSISTENT_EVIDENCE
            or plan.events != expected_events or plan.decision is None
            or plan.decision.disposition is not DecisionDisposition.HALT
            or snapshot.state is not RuntimeState.FLAT
            or snapshot.position_evidence is not PositionEvidence.CONFIRMED
            or snapshot.owned_base_quantity != 0 or snapshot.pending_action is not None
            or snapshot.desired_position != 1 or decision.signal != "HOLD" or decision.desired_position != 1
            or (plan.decision.symbol, plan.decision.timeframe, plan.decision.candle_open_ms,
                plan.decision.input_fingerprint, plan.decision.signal, plan.decision.desired_position,
                plan.decision.available_at_ms) != (decision.symbol, decision.timeframe,
                decision.candle_open_ms, decision.input_fingerprint, decision.signal,
                decision.desired_position, decision.available_at_ms)
            or checkpoint.last_processed_candle_ms is None
            or decision.candle_open_ms != checkpoint.last_processed_candle_ms + _HOUR_MS
            or (decision.symbol, decision.timeframe) != (config.symbol, config.timeframe)
            or not 0 <= evaluated_at_ms - decision.available_at_ms <= config.decision_max_age_ms
            or evaluated_at_ms >= decision.available_at_ms + config.reconciliation_timeout_ms
            or any(time is None or not 0 <= evaluated_at_ms - time <= config.observation_max_age_ms
                   for time in (checkpoint.last_reconciled_at_ms, checkpoint.observed_at_ms))
            or any(cutoff is not None and decision.candle_open_ms <= cutoff
                   for cutoff in (checkpoint.bootstrap_until_ms, checkpoint.replay_until_ms))
            or any(action.phase in (ActionPhase.PREPARED, ActionPhase.ATTEMPT_STARTED,
                                    ActionPhase.ACKNOWLEDGED, ActionPhase.UNKNOWN_OUTCOME)
                   for action in action_history)):
        return plan
    frontiers = refusal_frontiers(config, epoch, history, action_history)
    if (not history or history[-1][1].candle_open_ms != checkpoint.last_processed_candle_ms
            or checkpoint.last_processed_candle_ms not in frontiers):
        return plan
    return ActionPlan(PlanKind.NOOP, replace(plan.decision, disposition=DecisionDisposition.NOOP),
                      events=(RuntimeEvent(RuntimeEventType.NO_CHANGE, desired_position=1),))
