"""Pure operational state transitions under Decision 017; no broker or I/O.

Events assert facts already validated by a caller. This module checks their
consistency, not broker ownership, freshness, authorization or fill completeness.
Those checks belong to later layers. It never generates IDs, sizes an order,
records journal phases, or treats acknowledgement/desired intent as a fill.
"""

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from numbers import Integral
from types import MappingProxyType


class RuntimeStateError(ValueError):
    """Invalid record/evidence or forbidden transition; diagnostics are fixed text."""


class RuntimeState(str, Enum):
    """Operational states, separate from intent, order status and action phase."""

    STARTING = "STARTING"
    SYNCHRONIZING = "SYNCHRONIZING"
    FLAT = "FLAT"
    LONG = "LONG"
    ORDER_PENDING = "ORDER_PENDING"
    UNCERTAIN = "UNCERTAIN"
    HALTED = "HALTED"
    STOPPING = "STOPPING"


class PositionEvidence(str, Enum):
    """CONFIRMED is supplied evidence, LAST_KNOWN is retained but stale exposure."""

    UNKNOWN = "UNKNOWN"
    LAST_KNOWN = "LAST_KNOWN"
    CONFIRMED = "CONFIRMED"


class PendingActionKind(str, Enum):
    """The original order lifecycle's direction; not a new order instruction."""

    ENTRY = "ENTRY"
    EXIT = "EXIT"


class RuntimeReason(str, Enum):
    """Safe codes only; no arbitrary diagnostic text or broker payload."""

    EVIDENCE_MISSING = "EVIDENCE_MISSING"
    ACTION_OUTCOME_UNKNOWN = "ACTION_OUTCOME_UNKNOWN"
    RECOVERY_EXHAUSTED = "RECOVERY_EXHAUSTED"
    INVALID_CONFIGURATION = "INVALID_CONFIGURATION"
    OWNERSHIP_CONFLICT = "OWNERSHIP_CONFLICT"
    INCONSISTENT_EVIDENCE = "INCONSISTENT_EVIDENCE"


class RuntimeEventType(str, Enum):
    """Normalized facts/control inputs, never API calls or planner outputs."""

    STARTUP_VALIDATED = "STARTUP_VALIDATED"
    RECONCILED_FLAT = "RECONCILED_FLAT"
    RECONCILED_LONG = "RECONCILED_LONG"
    RECONCILED_PENDING = "RECONCILED_PENDING"
    RECOVERY_VALIDATED = "RECOVERY_VALIDATED"
    NO_CHANGE = "NO_CHANGE"
    ENTRY_PREPARED = "ENTRY_PREPARED"
    EXIT_PREPARED = "EXIT_PREPARED"
    FRESHNESS_LOST = "FRESHNESS_LOST"
    UNCERTAINTY_DETECTED = "UNCERTAINTY_DETECTED"
    FATAL_INCONSISTENCY = "FATAL_INCONSISTENCY"
    SHUTDOWN_REQUESTED = "SHUTDOWN_REQUESTED"
    OPERATOR_REARMED = "OPERATOR_REARMED"
    PLACEMENT_ACKNOWLEDGED = "PLACEMENT_ACKNOWLEDGED"
    CANCELLATION_ACKNOWLEDGED = "CANCELLATION_ACKNOWLEDGED"


def _enum(value, enum_type, name: str) -> None:
    if not isinstance(value, enum_type):
        raise RuntimeStateError(f"{name} must use its explicit enum.")


def _quantity(value) -> None:
    if not isinstance(value, Decimal) or not value.is_finite() or value < 0:
        raise RuntimeStateError("owned_base_quantity must be a finite nonnegative Decimal.")


def _desired(value) -> None:
    if value is not None and (
        isinstance(value, bool) or not isinstance(value, Integral) or value not in (0, 1)
    ):
        raise RuntimeStateError("desired_position must be integer 0/1 or None.")


def _action_id(value) -> None:
    if (
        not isinstance(value, str) or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise RuntimeStateError("logical_action_id must be a full lowercase SHA256 hex ID.")


@dataclass(frozen=True, slots=True)
class PendingAction:
    """One unresolved owned lifecycle reference; ID generation is deferred."""

    logical_action_id: str
    kind: PendingActionKind

    def __post_init__(self) -> None:
        _action_id(self.logical_action_id)
        _enum(self.kind, PendingActionKind, "kind")


@dataclass(frozen=True, slots=True)
class RuntimeEvidence:
    """Caller assertion of complete normalized ownership/terminal evidence.

    With a current pending action, clearing it requires its exact terminal ID.
    A still-pending lifecycle instead carries the same PendingAction. A receipt
    alone cannot construct terminal evidence legitimately; broker observation
    and completeness validation are outside this pure module.
    """

    owned_base_quantity: Decimal
    pending_action: PendingAction | None = None
    terminal_action_id: str | None = None

    def __post_init__(self) -> None:
        _quantity(self.owned_base_quantity)
        if self.pending_action is not None and not isinstance(self.pending_action, PendingAction):
            raise RuntimeStateError("pending_action must be a PendingAction or None.")
        if self.terminal_action_id is not None:
            _action_id(self.terminal_action_id)
            if self.pending_action is not None:
                raise RuntimeStateError("Evidence cannot both retain and terminate a pending lifecycle.")


@dataclass(frozen=True, slots=True)
class RuntimeStateSnapshot:
    """Immutable operational state; desired intent is independent of owned exposure.

    Unknown quantity is None, never fabricated zero. Nonoperational states keep
    only LAST_KNOWN/UNKNOWN exposure. STOPPING retains the prior state/reason and
    unresolved work; it cannot resume in this process. Later restart code must
    respect the retained HALT latch and reconcile, not initialize a fresh claim.
    """

    state: RuntimeState = RuntimeState.STARTING
    owned_base_quantity: Decimal | None = None
    position_evidence: PositionEvidence = PositionEvidence.UNKNOWN
    desired_position: int | None = None
    pending_action: PendingAction | None = None
    reason: RuntimeReason | None = None
    stopped_from: RuntimeState | None = None

    def __post_init__(self) -> None:
        _enum(self.state, RuntimeState, "state")
        _enum(self.position_evidence, PositionEvidence, "position_evidence")
        _desired(self.desired_position)
        if self.owned_base_quantity is not None:
            _quantity(self.owned_base_quantity)
        if (self.owned_base_quantity is None) != (self.position_evidence == PositionEvidence.UNKNOWN):
            raise RuntimeStateError("UNKNOWN requires None quantity; known evidence requires a quantity.")
        if self.pending_action is not None and not isinstance(self.pending_action, PendingAction):
            raise RuntimeStateError("pending_action must be a PendingAction or None.")

        confirmed = self.state in (RuntimeState.FLAT, RuntimeState.LONG, RuntimeState.ORDER_PENDING)
        if confirmed != (self.position_evidence == PositionEvidence.CONFIRMED):
            raise RuntimeStateError("Only FLAT/LONG/ORDER_PENDING require and may carry CONFIRMED exposure.")
        if self.state == RuntimeState.FLAT and self.owned_base_quantity != 0:
            raise RuntimeStateError("FLAT requires exact zero owned exposure.")
        if self.state == RuntimeState.LONG and self.owned_base_quantity <= 0:
            raise RuntimeStateError("LONG requires positive owned exposure.")
        if self.state in (RuntimeState.FLAT, RuntimeState.LONG) and self.pending_action is not None:
            raise RuntimeStateError("FLAT/LONG cannot retain an unresolved action.")
        if self.state == RuntimeState.ORDER_PENDING and self.pending_action is None:
            raise RuntimeStateError("ORDER_PENDING requires exactly one unresolved action.")

        if self.reason is not None:
            _enum(self.reason, RuntimeReason, "reason")
        if self.state in (RuntimeState.UNCERTAIN, RuntimeState.HALTED):
            if self.reason is None:
                raise RuntimeStateError("UNCERTAIN/HALTED requires a safe reason code.")
        elif self.state != RuntimeState.STOPPING and self.reason is not None:
            raise RuntimeStateError("A reason belongs only to UNCERTAIN/HALTED or their shutdown record.")
        if self.state == RuntimeState.STOPPING:
            _enum(self.stopped_from, RuntimeState, "stopped_from")
            if self.stopped_from == RuntimeState.STOPPING:
                raise RuntimeStateError("STOPPING must retain a prior operational state.")
            needs_reason = self.stopped_from in (RuntimeState.UNCERTAIN, RuntimeState.HALTED)
            if needs_reason != (self.reason is not None):
                raise RuntimeStateError("Shutdown must preserve the prior uncertainty/HALT reason.")
            if self.stopped_from in (RuntimeState.FLAT, RuntimeState.LONG):
                if self.pending_action is not None or self.owned_base_quantity is None:
                    raise RuntimeStateError("Shutdown must preserve confirmed prior position without pending work.")
                if (self.stopped_from == RuntimeState.FLAT) != (self.owned_base_quantity == 0):
                    raise RuntimeStateError("Shutdown quantity contradicts the prior position.")
            if self.stopped_from == RuntimeState.ORDER_PENDING and (
                self.pending_action is None or self.owned_base_quantity is None
            ):
                raise RuntimeStateError("Shutdown must retain the pending lifecycle and known quantity.")
        elif self.stopped_from is not None:
            raise RuntimeStateError("stopped_from belongs only to STOPPING.")


_RECONCILED_EVENTS = frozenset({
    RuntimeEventType.RECONCILED_FLAT, RuntimeEventType.RECONCILED_LONG,
    RuntimeEventType.RECONCILED_PENDING, RuntimeEventType.RECOVERY_VALIDATED,
})
_ACK_EVENTS = frozenset({
    RuntimeEventType.PLACEMENT_ACKNOWLEDGED, RuntimeEventType.CANCELLATION_ACKNOWLEDGED,
})


@dataclass(frozen=True, slots=True)
class RuntimeEvent:
    """Explicit facts; irrelevant/missing fields are rejected, never ignored.

    ENTRY/EXIT_PREPARED assert external authorization and canonical intent, but
    only record pending state here. ACK events preserve exposure/uncertainty.
    Journal action phases remain a separate later concern.
    """

    kind: RuntimeEventType
    evidence: RuntimeEvidence | None = None
    pending_action: PendingAction | None = None
    desired_position: int | None = None
    reason: RuntimeReason | None = None

    def __post_init__(self) -> None:
        _enum(self.kind, RuntimeEventType, "kind")
        _desired(self.desired_position)
        allowed = set()
        if self.kind in _RECONCILED_EVENTS:
            allowed = {"evidence"}
            if not isinstance(self.evidence, RuntimeEvidence):
                raise RuntimeStateError("Reconciliation/recovery requires complete RuntimeEvidence.")
        elif self.kind in (RuntimeEventType.ENTRY_PREPARED, RuntimeEventType.EXIT_PREPARED) or self.kind in _ACK_EVENTS:
            allowed = {"pending_action"}
            if not isinstance(self.pending_action, PendingAction):
                raise RuntimeStateError("Action/acknowledgement requires an explicit PendingAction.")
            if self.kind not in _ACK_EVENTS:
                allowed.add("desired_position")
                entry = self.kind == RuntimeEventType.ENTRY_PREPARED
                expected_kind = PendingActionKind.ENTRY if entry else PendingActionKind.EXIT
                if self.pending_action.kind != expected_kind or self.desired_position != int(entry):
                    raise RuntimeStateError("Prepared action kind and explicit desired intent must agree.")
        elif self.kind == RuntimeEventType.NO_CHANGE:
            allowed = {"desired_position"}
        elif self.kind in (RuntimeEventType.UNCERTAINTY_DETECTED, RuntimeEventType.FATAL_INCONSISTENCY):
            allowed = {"reason"}
            _enum(self.reason, RuntimeReason, "reason")
        for name in ("evidence", "pending_action", "desired_position", "reason"):
            if name not in allowed and getattr(self, name) is not None:
                raise RuntimeStateError(f"{name} is not allowed for this event.")


# Closed table: every omitted state/event pair is forbidden. Nested read-only
# mappings keep accidental edits from changing the transition contract at runtime.
_S, _E = RuntimeState, RuntimeEventType
_TRANSITIONS = MappingProxyType({
    _S.STARTING: MappingProxyType({
        _E.STARTUP_VALIDATED: _S.SYNCHRONIZING,
        _E.FATAL_INCONSISTENCY: _S.HALTED, _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.SYNCHRONIZING: MappingProxyType({
        _E.RECONCILED_FLAT: _S.FLAT, _E.RECONCILED_LONG: _S.LONG,
        _E.RECONCILED_PENDING: _S.ORDER_PENDING,
        _E.UNCERTAINTY_DETECTED: _S.UNCERTAIN,
        _E.FATAL_INCONSISTENCY: _S.HALTED, _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.FLAT: MappingProxyType({
        _E.NO_CHANGE: _S.FLAT, _E.ENTRY_PREPARED: _S.ORDER_PENDING,
        _E.FRESHNESS_LOST: _S.SYNCHRONIZING, _E.UNCERTAINTY_DETECTED: _S.UNCERTAIN,
        _E.FATAL_INCONSISTENCY: _S.HALTED, _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.LONG: MappingProxyType({
        _E.NO_CHANGE: _S.LONG, _E.EXIT_PREPARED: _S.ORDER_PENDING,
        _E.FRESHNESS_LOST: _S.SYNCHRONIZING, _E.UNCERTAINTY_DETECTED: _S.UNCERTAIN,
        _E.FATAL_INCONSISTENCY: _S.HALTED, _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.ORDER_PENDING: MappingProxyType({
        _E.NO_CHANGE: _S.ORDER_PENDING, _E.RECONCILED_PENDING: _S.ORDER_PENDING,
        _E.RECONCILED_FLAT: _S.FLAT, _E.RECONCILED_LONG: _S.LONG,
        _E.PLACEMENT_ACKNOWLEDGED: _S.ORDER_PENDING,
        _E.CANCELLATION_ACKNOWLEDGED: _S.ORDER_PENDING,
        _E.UNCERTAINTY_DETECTED: _S.UNCERTAIN,
        _E.FATAL_INCONSISTENCY: _S.HALTED, _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.UNCERTAIN: MappingProxyType({
        _E.RECOVERY_VALIDATED: _S.SYNCHRONIZING,
        _E.RECONCILED_FLAT: _S.FLAT, _E.RECONCILED_LONG: _S.LONG,
        _E.RECONCILED_PENDING: _S.ORDER_PENDING,
        _E.PLACEMENT_ACKNOWLEDGED: _S.UNCERTAIN,
        _E.CANCELLATION_ACKNOWLEDGED: _S.UNCERTAIN,
        _E.UNCERTAINTY_DETECTED: _S.UNCERTAIN,
        _E.FATAL_INCONSISTENCY: _S.HALTED, _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.HALTED: MappingProxyType({
        _E.NO_CHANGE: _S.HALTED, _E.OPERATOR_REARMED: _S.SYNCHRONIZING,
        _E.SHUTDOWN_REQUESTED: _S.STOPPING,
    }),
    _S.STOPPING: MappingProxyType({}),
})


def _check_recovered_action(current: RuntimeStateSnapshot, evidence: RuntimeEvidence) -> None:
    if current.pending_action is None:
        if evidence.terminal_action_id is not None:
            raise RuntimeStateError("Terminal evidence has no matching current pending action.")
    elif evidence.pending_action is not None:
        if evidence.pending_action != current.pending_action:
            raise RuntimeStateError("Recovered evidence cannot replace the unresolved action identity/kind.")
    elif evidence.terminal_action_id != current.pending_action.logical_action_id:
        raise RuntimeStateError("Clearing pending work requires its exact terminal action identity.")


def transition_runtime_state(
    current: RuntimeStateSnapshot, event: RuntimeEvent,
) -> RuntimeStateSnapshot:
    """Return a validated new snapshot, or reject an unlisted/incoherent event.

    No I/O, implicit clock, rounding, sizing, ID generation or broker lookup.
    RuntimeEvidence is caller-supplied complete evidence, not proof produced by
    this function. An acknowledgement can never change quantity or finalize work.
    """
    if not isinstance(current, RuntimeStateSnapshot) or not isinstance(event, RuntimeEvent):
        raise RuntimeStateError("transition requires RuntimeStateSnapshot and RuntimeEvent.")
    target = _TRANSITIONS[current.state].get(event.kind)
    if target is None:
        raise RuntimeStateError("Event is forbidden in the current runtime state.")
    last_known = PositionEvidence.UNKNOWN if current.owned_base_quantity is None else PositionEvidence.LAST_KNOWN

    if event.kind in _RECONCILED_EVENTS:
        evidence = event.evidence
        _check_recovered_action(current, evidence)
        if event.kind == RuntimeEventType.RECONCILED_PENDING:
            if evidence.pending_action is None:
                raise RuntimeStateError("Pending evidence must identify an unresolved lifecycle.")
        elif event.kind != RuntimeEventType.RECOVERY_VALIDATED:
            if evidence.pending_action is not None:
                raise RuntimeStateError("Confirmed FLAT/LONG evidence cannot leave unresolved work.")
            if (event.kind == RuntimeEventType.RECONCILED_FLAT) != (evidence.owned_base_quantity == 0):
                raise RuntimeStateError("Confirmed event contradicts the supplied owned quantity.")
        return replace(
            current, state=target, owned_base_quantity=evidence.owned_base_quantity,
            position_evidence=(PositionEvidence.LAST_KNOWN if target == RuntimeState.SYNCHRONIZING else PositionEvidence.CONFIRMED),
            pending_action=evidence.pending_action, reason=None,
        )
    if event.kind in (RuntimeEventType.ENTRY_PREPARED, RuntimeEventType.EXIT_PREPARED):
        return replace(current, state=target, pending_action=event.pending_action, desired_position=event.desired_position)
    if event.kind in _ACK_EVENTS:
        if current.pending_action is None or event.pending_action != current.pending_action:
            raise RuntimeStateError("Acknowledgement must refer to the exact unresolved lifecycle.")
        return replace(current)
    if event.kind == RuntimeEventType.NO_CHANGE:
        if current.state == RuntimeState.HALTED and event.desired_position is not None:
            raise RuntimeStateError("HALTED cannot process new strategy decisions.")
        desired = current.desired_position if event.desired_position is None else event.desired_position
        return replace(current, desired_position=desired)
    if event.kind in (RuntimeEventType.STARTUP_VALIDATED, RuntimeEventType.FRESHNESS_LOST, RuntimeEventType.OPERATOR_REARMED):
        return replace(current, state=target, position_evidence=last_known, reason=None)
    if event.kind in (RuntimeEventType.UNCERTAINTY_DETECTED, RuntimeEventType.FATAL_INCONSISTENCY):
        return replace(current, state=target, position_evidence=last_known, reason=event.reason)
    if event.kind == RuntimeEventType.SHUTDOWN_REQUESTED:
        # Retain exposure, pending work and the prior HALT/uncertainty reason.
        return replace(current, state=target, position_evidence=last_known, stopped_from=current.state)
    raise RuntimeStateError("Event has no explicit transition handler.")
