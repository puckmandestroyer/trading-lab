"""Pure Demo authorization under Decision 017; no observation or dispatch.

The caller supplies validated records, complete relevant action history and an
explicit control time. Results are proposals only: no checkpoint or journal is
changed, and PREPARED never means submitted. Import this submodule explicitly.
"""

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
import json

from .state import (
    PendingAction, PendingActionKind, RuntimeEvent, RuntimeEventType,
    RuntimeReason, RuntimeState, RuntimeStateError, RuntimeStateSnapshot,
)
from .store import (
    ActionPhase, ActionRecord, DecisionDisposition, DecisionRecord,
    JournalActionKind, RuntimeCheckpoint, RuntimeConfiguration,
    RuntimeStoreError, serialize_decimal,
)


class PlannerError(ValueError):
    """Invalid pure planning input; diagnostics never contain caller values."""


class PlanKind(str, Enum):
    NOOP = "NOOP"
    PLACE_BUY = "PLACE_BUY"
    PLACE_SELL = "PLACE_SELL"
    WAIT = "WAIT"
    RECONCILE = "RECONCILE"
    HALT = "HALT"


class DecisionMode(str, Enum):
    """Caller-proven eligibility, separate from strategy desire."""

    LIVE = "LIVE"
    BOOTSTRAP = "BOOTSTRAP"
    REPLAY_ONLY = "REPLAY_ONLY"


@dataclass(frozen=True, slots=True)
class CanonicalDecision:
    """One already-generated closed-candle decision, before its disposition."""

    symbol: str
    timeframe: str
    candle_open_ms: int
    input_fingerprint: str
    signal: str
    desired_position: int
    available_at_ms: int

    def __post_init__(self):
        try:
            # Reuse the frozen integer/grid/fingerprint/signal contract without
            # requiring an action ID before the planner has authorized an action.
            _decision(self, DecisionDisposition.NOOP)
        except RuntimeStoreError:
            raise PlannerError("Invalid canonical decision.") from None


@dataclass(frozen=True, slots=True)
class ActionPlan:
    """Immutable proposal for later persistence; control refusals may lack a decision."""

    kind: PlanKind
    decision: DecisionRecord | None = None
    action: ActionRecord | None = None
    events: tuple[RuntimeEvent, ...] = ()
    reason: RuntimeReason | None = None

    def __post_init__(self):
        if (not isinstance(self.kind, PlanKind)
                or (self.decision is not None and not isinstance(self.decision, DecisionRecord))
                or type(self.events) is not tuple
                or not all(isinstance(event, RuntimeEvent) for event in self.events)
                or (self.reason is not None and not isinstance(self.reason, RuntimeReason))):
            raise PlannerError("Invalid planner result records.")
        placement = self.kind in (PlanKind.PLACE_BUY, PlanKind.PLACE_SELL)
        if not placement:
            if (self.action is not None
                    or (self.decision is not None and self.decision.disposition == DecisionDisposition.ACTION)
                    or any(event.kind in (RuntimeEventType.ENTRY_PREPARED, RuntimeEventType.EXIT_PREPARED) for event in self.events)):
                raise PlannerError("Non-placement results cannot authorize an action.")
            return
        entry = self.kind == PlanKind.PLACE_BUY
        if (not isinstance(self.action, ActionRecord) or self.decision is None
                or self.action.phase != ActionPhase.PREPARED or self.action.attempt_count != 0
                or self.action.kind != (JournalActionKind.ENTRY if entry else JournalActionKind.EXIT)
                or self.decision.disposition != DecisionDisposition.ACTION
                or self.decision.action_id != self.action.logical_action_id
                or self.decision.symbol != self.action.symbol
                or self.decision.candle_open_ms != self.action.candle_open_ms
                or self.decision.signal != ("LONG_ENTRY" if entry else "LONG_EXIT")
                or self.decision.desired_position != int(entry)
                or self.events != (RuntimeEvent(
                    RuntimeEventType.ENTRY_PREPARED if entry else RuntimeEventType.EXIT_PREPARED,
                    pending_action=PendingAction(self.action.logical_action_id,
                                                 PendingActionKind.ENTRY if entry else PendingActionKind.EXIT),
                    desired_position=int(entry)),)):
            raise PlannerError("Placement requires matching PREPARED action, decision and event.")


def _decision(decision, disposition, action_id=None):
    return DecisionRecord(decision.symbol, decision.timeframe, decision.candle_open_ms,
                          decision.input_fingerprint, decision.signal, decision.desired_position,
                          disposition, decision.available_at_ms, action_id)


def _canonical_intent(config, decision, kind, amount):
    entry = kind == JournalActionKind.ENTRY
    payload = {
        "action_kind": kind.value,
        "authorized_amount": serialize_decimal(amount),
        "candle_open_ms": decision.candle_open_ms,
        "configuration_digest": config.configuration_digest,
        "instance_key": {"account_binding": config.account_binding,
                         "bot_id": config.bot_id, "broker_id": config.broker_id},
        "runtime_contract_version": config.runtime_contract_version,
        "side": "BUY" if entry else "SELL",
        "unit": "QUOTE" if entry else "BASE",
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def _action(config, decision, snapshot):
    entry = snapshot.state == RuntimeState.FLAT
    kind = JournalActionKind.ENTRY if entry else JournalActionKind.EXIT
    amount = config.buy_quote_budget if entry else snapshot.owned_base_quantity
    action_id = hashlib.sha256(_canonical_intent(config, decision, kind, amount)).hexdigest()
    return ActionRecord(
        action_id, kind, config.symbol, decision.available_at_ms + config.reconciliation_timeout_ms,
        config.reconciliation_round_limit, config.read_attempt_limit,
        config.bot_id + "-" + action_id[:23], decision.candle_open_ms,
        side="BUY" if entry else "SELL", amount_unit="QUOTE" if entry else "BASE",
        currency=config.quote_currency if entry else config.base_currency,
        authorized_amount=amount,
    )


def _history_conflict(config, history):
    ids, links, candles = {}, {}, {}
    for action in history:
        if (action.symbol != config.symbol
                or action.remaining_reconciliation_rounds > config.reconciliation_round_limit
                or action.remaining_read_attempts > config.read_attempt_limit):
            return True
        previous = ids.get(action.logical_action_id)
        if previous is not None and previous != action:
            return True
        ids[action.logical_action_id] = action
        if action.kind == JournalActionKind.CANCEL:
            continue
        if (action.order_link_id != config.bot_id + "-" + action.logical_action_id[:23]
                or action.currency != (config.quote_currency if action.kind == JournalActionKind.ENTRY else config.base_currency)):
            return True
        for mapping, key in ((links, action.order_link_id), (candles, action.candle_open_ms)):
            previous = mapping.get(key)
            if previous is not None and previous != action.logical_action_id:
                return True
            mapping[key] = action.logical_action_id
    return False


def plan_action(
    config: RuntimeConfiguration,
    checkpoint: RuntimeCheckpoint,
    decision: CanonicalDecision,
    *,
    evaluated_at_ms: int,
    mode: DecisionMode,
    action_history: tuple[ActionRecord, ...],
) -> ActionPlan:
    """Authorize at most one new intent, without reading/writing any resource.

    Freshness accepts equality with the configured age bound; future evidence
    is a clock contradiction. The deterministic recovery deadline is exclusive.
    LIVE cannot override durable bootstrap/replay cutoffs. An already handled
    candle or compatible consumed action returns WAIT without a new journal row.
    Stage 10.7 must supply complete relevant history and commit/apply proposals.
    """
    if (type(config) is not RuntimeConfiguration or type(checkpoint) is not RuntimeCheckpoint
            or type(checkpoint.snapshot) is not RuntimeStateSnapshot
            or type(decision) is not CanonicalDecision or not isinstance(mode, DecisionMode)
            or type(action_history) is not tuple
            or not all(type(action) is ActionRecord for action in action_history)
            or type(evaluated_at_ms) is not int or not 0 <= evaluated_at_ms <= 2**63 - 1):
        raise PlannerError("Validated records, immutable action history and integer UTC time are required.")
    try:
        # Frozen dataclasses are validated again so bypassed constructors cannot
        # turn impossible exposure, float money or invalid timing into authority.
        replace(config)
        replace(checkpoint, snapshot=replace(checkpoint.snapshot))
        replace(decision)
        for action in action_history:
            replace(action)
    except (RuntimeStoreError, RuntimeStateError, PlannerError):
        raise PlannerError("Invalid planning evidence.") from None

    snapshot = checkpoint.snapshot

    def halt(reason, *, journal=False):
        events = () if snapshot.state in (RuntimeState.HALTED, RuntimeState.STOPPING) else (
            RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY, reason=reason),)
        if journal:
            # A fatal event preserves prior desired intent. Record the new intent
            # first, so the final proposed HALT matches its durable decision.
            events = (RuntimeEvent(RuntimeEventType.NO_CHANGE, desired_position=decision.desired_position), *events)
        return ActionPlan(PlanKind.HALT, _decision(decision, DecisionDisposition.HALT) if journal else None,
                          events=events, reason=reason)

    def reconcile():
        events = (RuntimeEvent(RuntimeEventType.FRESHNESS_LOST),) if snapshot.state in (RuntimeState.FLAT, RuntimeState.LONG) else ()
        return ActionPlan(PlanKind.RECONCILE, events=events, reason=RuntimeReason.EVIDENCE_MISSING)

    def no_change(kind, disposition):
        return ActionPlan(kind, _decision(decision, disposition),
                          events=(RuntimeEvent(RuntimeEventType.NO_CHANGE, desired_position=decision.desired_position),))

    if snapshot.state == RuntimeState.HALTED:
        return halt(snapshot.reason)
    if snapshot.state == RuntimeState.STOPPING:
        return halt(snapshot.reason or RuntimeReason.EVIDENCE_MISSING)
    if (decision.symbol != config.symbol or decision.timeframe != config.timeframe
            or decision.candle_open_ms < config.history_anchor_ms
            or decision.available_at_ms != decision.candle_open_ms + config.interval_ms):
        return halt(RuntimeReason.INVALID_CONFIGURATION)
    if _history_conflict(config, action_history):
        return halt(RuntimeReason.OWNERSHIP_CONFLICT)
    if snapshot.state in (RuntimeState.STARTING, RuntimeState.SYNCHRONIZING, RuntimeState.UNCERTAIN):
        return reconcile()
    if evaluated_at_ms < decision.available_at_ms:
        return ActionPlan(PlanKind.WAIT, reason=RuntimeReason.EVIDENCE_MISSING)
    if any(time is not None and time > evaluated_at_ms for time in
           (checkpoint.last_reconciled_at_ms, checkpoint.observed_at_ms)):
        return halt(RuntimeReason.INVALID_CONFIGURATION)
    if checkpoint.last_processed_candle_ms is not None and decision.candle_open_ms <= checkpoint.last_processed_candle_ms:
        return ActionPlan(PlanKind.WAIT)  # Already handled; do not recreate its disposition or attempt.
    expected = config.history_anchor_ms if checkpoint.last_processed_candle_ms is None else checkpoint.last_processed_candle_ms + config.interval_ms
    if decision.candle_open_ms != expected:
        return reconcile()  # Missing history is backfill work, never skipped authorization.
    historical = {DecisionMode.BOOTSTRAP: DecisionDisposition.BOOTSTRAP,
                  DecisionMode.REPLAY_ONLY: DecisionDisposition.REPLAY_ONLY}
    if snapshot.state == RuntimeState.ORDER_PENDING:
        return no_change(PlanKind.WAIT, historical.get(mode, DecisionDisposition.WAIT))
    if any(time is None or evaluated_at_ms - time > config.observation_max_age_ms for time in
           (checkpoint.last_reconciled_at_ms, checkpoint.observed_at_ms)):
        return reconcile()
    if mode in historical:
        return no_change(PlanKind.NOOP, historical[mode])
    if any(cutoff is not None and decision.candle_open_ms <= cutoff for cutoff in
           (checkpoint.bootstrap_until_ms, checkpoint.replay_until_ms)):
        return halt(RuntimeReason.INVALID_CONFIGURATION)
    owned_intent = int(snapshot.state == RuntimeState.LONG)
    if evaluated_at_ms - decision.available_at_ms > config.decision_max_age_ms:
        if decision.desired_position != owned_intent:
            return halt(RuntimeReason.INCONSISTENT_EVIDENCE, journal=True)
        return no_change(PlanKind.NOOP, DecisionDisposition.REPLAY_ONLY)
    if decision.desired_position == owned_intent:
        return no_change(PlanKind.NOOP, DecisionDisposition.NOOP)
    if decision.signal == "HOLD":
        return halt(RuntimeReason.INCONSISTENT_EVIDENCE, journal=True)
    if evaluated_at_ms >= decision.available_at_ms + config.reconciliation_timeout_ms:
        return halt(RuntimeReason.RECOVERY_EXHAUSTED, journal=True)
    try:
        action = _action(config, decision, snapshot)
    except RuntimeStoreError:
        raise PlannerError("Authorization exceeds the frozen record bounds.") from None
    intent_fields = ("kind", "symbol", "candle_open_ms", "order_link_id", "side", "amount_unit",
                     "currency", "authorized_amount", "reconciliation_deadline_ms")
    for previous in action_history:
        if previous.logical_action_id == action.logical_action_id:
            if any(getattr(previous, field) != getattr(action, field) for field in intent_fields):
                return halt(RuntimeReason.OWNERSHIP_CONFLICT, journal=True)
            return ActionPlan(PlanKind.WAIT)  # Compatible original intent, never another authorization.
        if previous.kind == JournalActionKind.CANCEL:
            continue
        if previous.order_link_id == action.order_link_id and previous.logical_action_id != action.logical_action_id:
            return halt(RuntimeReason.OWNERSHIP_CONFLICT, journal=True)
        if previous.candle_open_ms == action.candle_open_ms and previous.logical_action_id != action.logical_action_id:
            return halt(RuntimeReason.OWNERSHIP_CONFLICT, journal=True)
        if previous.phase in (ActionPhase.PREPARED, ActionPhase.ATTEMPT_STARTED,
                              ActionPhase.ACKNOWLEDGED, ActionPhase.UNKNOWN_OUTCOME):
            return halt(RuntimeReason.INCONSISTENT_EVIDENCE, journal=True)
    entry = action.kind == JournalActionKind.ENTRY
    event = RuntimeEvent(RuntimeEventType.ENTRY_PREPARED if entry else RuntimeEventType.EXIT_PREPARED,
                         pending_action=PendingAction(action.logical_action_id,
                                                      PendingActionKind.ENTRY if entry else PendingActionKind.EXIT),
                         desired_position=decision.desired_position)
    return ActionPlan(PlanKind.PLACE_BUY if entry else PlanKind.PLACE_SELL,
                      _decision(decision, DecisionDisposition.ACTION, action.logical_action_id), action, (event,))
