"""New-process checkpoint normalization; restart never resends an action.

Acquire the canonical account lock and open the existing store first. Call this
once before constructing external resources or starting the frozen cycle or
scheduler. This is process entry, not an in-process reset or a state-machine
event. Frozen reconciliation owns action recovery after this boundary.
"""

from dataclasses import replace

from .state import PositionEvidence, RuntimeState, RuntimeStateSnapshot
from .store import RuntimeCheckpoint, RuntimeStore


class RestartRecoveryError(RuntimeError):
    """Invalid process-entry input; fixed diagnostics without supplied values."""


def prepare_process_restart(store: RuntimeStore) -> RuntimeCheckpoint:
    """Retain durable truth, drop inherited certainty, and save at most once.

    Existing STARTING and HALTED checkpoints return unchanged. STOPPING from
    HALTED restores its exact latch; other retained states enter STARTING with
    LAST_KNOWN/UNKNOWN exposure. Actions, fills, counters and history are untouched.
    Persistence errors propagate unchanged: stop and reopen to learn old/new
    durable truth, without a retry or any external operation.
    """
    if not isinstance(store, RuntimeStore):
        raise RestartRecoveryError("An already-open existing RuntimeStore is required.")

    current = store.get_checkpoint()
    snapshot = current.snapshot
    if snapshot.state in (RuntimeState.STARTING, RuntimeState.HALTED):
        return current

    retained_halt = (snapshot.state == RuntimeState.STOPPING
                     and snapshot.stopped_from == RuntimeState.HALTED)
    normalized = RuntimeStateSnapshot(
        state=RuntimeState.HALTED if retained_halt else RuntimeState.STARTING,
        owned_base_quantity=snapshot.owned_base_quantity,
        position_evidence=(PositionEvidence.UNKNOWN if snapshot.owned_base_quantity is None
                           else PositionEvidence.LAST_KNOWN),
        desired_position=snapshot.desired_position,
        pending_action=snapshot.pending_action,
        reason=snapshot.reason if retained_halt else None,
    )
    proposed = replace(current, sequence=current.sequence + 1, snapshot=normalized,
                       halted_at_ms=current.halted_at_ms if retained_halt else None,
                       shutdown_at_ms=None)
    store.save_checkpoint(proposed, expected_sequence=current.sequence)
    return proposed
