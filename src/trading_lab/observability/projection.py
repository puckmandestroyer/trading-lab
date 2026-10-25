"""Read-only projections, deliberately separate from runtime invocation.

Catch-up cannot recover overwritten action phases or checkpoint transitions.
The transition helper requires two already accepted checkpoints from its caller.
Nothing here runs reconciliation, acknowledges an action or opens a transaction.
"""

from contextlib import contextmanager
from dataclasses import replace
import re

from ..runtime.store import (
    RuntimeStoreError, RuntimeCheckpoint, RuntimeConfiguration, ActionRecord,
    OwnedFillRecord, RiskEpochRecord, RiskValuationRecord, RiskVerdictRecord,
    RiskValuationMode, ActionPhase, RiskConfigurationRecord,
)
from ..runtime.state import RuntimeState, PositionEvidence, RuntimeReason
from ..runtime.cycle import SingleCycleResult, CycleOutcome
from ..runtime.scheduler import SchedulerResult, SchedulerExit
from .model import (
    ObservabilityProjectionError, ObservabilityValidationError, make_event,
    ObservabilityEventType as T, MAX_RETAINED_RECORDS, ACTION_FIELDS,
    RiskVerdict, validate_run_id, validate_value, integer, require,
)


@contextmanager
def projection_errors():
    try:
        yield
    except (RuntimeStoreError, ObservabilityValidationError, TypeError, AttributeError, KeyError):
        raise ObservabilityProjectionError("Cannot establish a coherent observability boundary.") from None


def exact(record, cls):
    require(type(record) is cls)
    replace(record)  # Public record validation, never an arbitrary object dump.
    return record


def bounded(records, cls):
    require(type(records) is tuple and len(records) <= MAX_RETAINED_RECORDS)
    for record in records:
        exact(record, cls)
    return records


def retained_epochs(valuations, current):
    """Prove lineage using public records, without private SQL/hash internals.

    Public chronological reads retain one ACTIVATION per consecutive epoch.
    Candidate sequence/parent fields are accepted ONLY if RiskEpochRecord's
    public constructor verifies their entire canonical hash. The final record
    must also equal the public current epoch. Missing proof fails, not truncates.
    """
    activations = tuple(v for v in valuations if v.mode is RiskValuationMode.ACTIVATION)
    if current is None:
        require(not valuations)
        return ()
    exact(current, RiskEpochRecord)
    require(len(activations) == current.epoch_sequence)
    epochs = []
    for sequence, row in enumerate(activations, 1):
        epochs.append(RiskEpochRecord(row.epoch_id, sequence, row.risk_configuration_digest,
                                     row.valued_at_ms, epochs[-1].epoch_id if epochs else None))
    require(epochs[-1] == current)
    require(len({e.epoch_id for e in epochs}) == len(epochs))
    require({v.epoch_id for v in valuations} == {e.epoch_id for e in epochs})
    return tuple(epochs)


def _risk_fields(row, configuration, verdict=None):
    values = {name: getattr(row, name) for name in (
        "risk_configuration_digest", "valued_at_ms", "mark_price", "risk_equity",
        "peak_risk_equity", "utc_day_start_risk_equity", "daily_pnl", "entries_this_utc_day", "tripped_at_ms")}
    values.update(valuation_mode=row.mode, max_entries_per_utc_day=configuration.max_entries_per_utc_day)
    values.update({name: None if verdict is None else getattr(verdict, name) for name in
                   ("proposal_kind", "authorized_amount")})
    values.update(risk_verdict=None if verdict is None else verdict.verdict,
                  risk_reason=None if verdict is None else verdict.reason)
    return tuple(values.items())


def project_retained_events(store, *, run_id: str, observed_at_ms: int):
    """Bounded catch-up of provable retained facts; duplicates are intentional.

    No cursor or historical position/PnL reconstruction is claimed. The frozen
    public reads return complete tuples; oversized histories fail as a whole.
    """
    with projection_errors():
        validate_run_id(run_id)
        integer(observed_at_ms)
        before = exact(store.get_checkpoint(), RuntimeCheckpoint)
        cfg = exact(store.get_configuration(), RuntimeConfiguration)
        current = store.get_current_risk_epoch()
        actions = bounded(store.list_actions(), ActionRecord)
        fills = bounded(store.list_fills(), OwnedFillRecord)
        valuations = bounded(store.list_risk_valuations(), RiskValuationRecord)
        verdicts = bounded(store.list_risk_verdicts(), RiskVerdictRecord)
        epochs = retained_epochs(valuations, current)
        configs = {e.risk_configuration_digest: store.get_risk_configuration(e.risk_configuration_digest) for e in epochs}
        for configuration in configs.values():
            exact(configuration, RiskConfigurationRecord)
        require(before == store.get_checkpoint() and current == store.get_current_risk_epoch())
        epoch_by_id = {e.epoch_id: e for e in epochs}
        valuation_by_key = {(v.epoch_id, v.valued_at_ms): v for v in valuations}
        verdict_by_key = {(v.epoch_id, v.valued_at_ms): v for v in verdicts}
        require(len(valuation_by_key) == len(valuations))
        require(len({a.logical_action_id for a in actions}) == len(actions))
        require(len({f.broker_execution_id for f in fills}) == len(fills))
        events = []

        def emit(kind, **fields):
            require(len(events) < MAX_RETAINED_RECORDS)
            events.append(make_event(cfg, kind, run_id=run_id, observed_at_ms=observed_at_ms, **fields))

        for action in actions:
            values = {name: getattr(action, {"action_kind": "kind", "action_phase": "phase"}.get(name, name))
                      for name in ACTION_FIELDS}
            # An arbitrary broker string fitting a length bound is not safe text.
            if values["external_status"] is not None and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", values["external_status"]) is None:
                values["external_status"] = None
            occurred = action.terminal_at_ms if action.terminal_at_ms is not None else (
                action.acknowledgement_broker_ms if action.phase is ActionPhase.ACKNOWLEDGED else None)
            emit(T("ACTION_" + action.phase.value), action_id=action.logical_action_id,
                 broker_order_id=action.broker_order_id, candle_open_ms=action.candle_open_ms,
                 occurred_at_ms=occurred, details=tuple(values.items()))
        for fill in fills:
            require((fill.broker_id, fill.account_binding, fill.symbol) == (cfg.broker_id, cfg.account_binding, cfg.symbol))
            values = {name: getattr(fill, name) for name in (
                "broker_execution_id", "order_link_id", "side", "executed_quantity", "execution_price",
                "execution_fee", "fee_currency", "executed_at_ms")}
            values["first_observed_at_ms"] = fill.observed_at_ms
            emit(T.OWNED_EXECUTION_DISCOVERED, occurred_at_ms=fill.executed_at_ms,
                 action_id=fill.action_id, broker_order_id=fill.broker_order_id, details=tuple(values.items()))
        for verdict in verdicts:
            if verdict.verdict is RiskVerdict.BLOCK:
                row = valuation_by_key[(verdict.epoch_id, verdict.valued_at_ms)]
                require(row.mode is RiskValuationMode.LIVE)
                epoch = epoch_by_id[row.epoch_id]
                emit(T.RISK_BLOCKED, occurred_at_ms=verdict.evaluated_at_ms,
                     risk_epoch_id=epoch.epoch_id, risk_epoch_sequence=epoch.epoch_sequence,
                     risk_trip_reason=row.trip_reason, candle_open_ms=verdict.candle_open_ms,
                     details=_risk_fields(row, configs[row.risk_configuration_digest], verdict))
        seen_trips = set()
        for row in valuations:
            if row.trip_reason is None:
                continue
            key = row.epoch_id, row.trip_reason, row.tripped_at_ms
            if key in seen_trips:
                continue
            # Only the actual original accepted latch boundary proves the origin.
            origin = valuation_by_key.get((row.epoch_id, row.tripped_at_ms))
            require(origin is not None and origin.trip_reason is row.trip_reason)
            seen_trips.add(key)
            epoch = epoch_by_id[row.epoch_id]
            emit(T.RISK_TRIPPED, occurred_at_ms=origin.tripped_at_ms,
                 risk_epoch_id=epoch.epoch_id, risk_epoch_sequence=epoch.epoch_sequence,
                 risk_trip_reason=origin.trip_reason, candle_open_ms=origin.candle_open_ms,
                 details=_risk_fields(origin, configs[origin.risk_configuration_digest],
                                      verdict_by_key.get((origin.epoch_id, origin.valued_at_ms))))
        for epoch in epochs[1:]:
            emit(T.RISK_REARMED, occurred_at_ms=epoch.started_at_ms,
                 risk_epoch_id=epoch.epoch_id, risk_epoch_sequence=epoch.epoch_sequence,
                 details=(("parent_epoch_id", epoch.parent_epoch_id), ("child_epoch_id", epoch.epoch_id),
                          ("accepted_boundary_ms", epoch.started_at_ms),
                          ("risk_configuration_digest", epoch.risk_configuration_digest)))
        cp = before
        state = cp.snapshot
        exposure = (("owned_base_quantity", state.owned_base_quantity), ("position_evidence", state.position_evidence),
                    ("pending_action_id", None if state.pending_action is None else state.pending_action.logical_action_id))
        if cp.halted_at_ms is not None:
            emit(T.RUNTIME_HALTED, occurred_at_ms=cp.halted_at_ms, checkpoint_sequence=cp.sequence,
                 runtime_state=RuntimeState.HALTED, runtime_reason=state.reason,
                 details=exposure + (("halted_at_ms", cp.halted_at_ms),))
        unresolved = tuple(a for a in actions if a.phase is ActionPhase.UNKNOWN_OUTCOME)
        if state.state is RuntimeState.UNCERTAIN and not unresolved:
            emit(T.RUNTIME_UNCERTAIN, checkpoint_sequence=cp.sequence, runtime_state=state.state,
                 runtime_reason=state.reason, details=exposure)
        for action in unresolved:
            emit(T.RUNTIME_UNCERTAIN, action_id=action.logical_action_id, broker_order_id=action.broker_order_id,
                 runtime_reason=action.safe_reason, details=(("action_phase", action.phase),))
        if cp.rearmed_at_ms is not None:
            # Frozen store metadata proves that the control committed, not that
            # today's sequence/state was the original rearm checkpoint.
            emit(T.RUNTIME_REARMED, occurred_at_ms=cp.rearmed_at_ms, runtime_state=RuntimeState.SYNCHRONIZING,
                 details=(("rearmed_at_ms", cp.rearmed_at_ms), ("previous_runtime_state", RuntimeState.HALTED),
                          ("reconciliation_required", True)))
        return tuple(events)


def project_checkpoint_transition(configuration, before, after, *, run_id, observed_at_ms,
                                  contributing_execution_ids=(), accepted_reconciliation=False):
    """Describe accepted post-commit facts only; never call from a lost commit.

    The explicit mode is only for the direct successful reconciliation-commit
    callback, not catch-up or cycle-level inference. Generic callers keep the
    stricter confirmation/time-change requirements used before this extension.
    """
    with projection_errors():
        exact(configuration, RuntimeConfiguration)
        exact(before, RuntimeCheckpoint)
        exact(after, RuntimeCheckpoint)
        require(after.sequence == before.sequence + 1)
        events = []
        b, a = before.snapshot, after.snapshot
        require(type(accepted_reconciliation) is bool)
        if accepted_reconciliation:
            require(type(contributing_execution_ids) is tuple)
            validate_value("contributing_execution_ids", contributing_execution_ids)
            require(a.position_evidence is PositionEvidence.CONFIRMED
                    and a.owned_base_quantity is not None
                    and after.last_reconciled_at_ms is not None
                    and after.observed_at_ms is not None
                    and after.observed_at_ms == after.last_reconciled_at_ms
                    and (before.last_reconciled_at_ms is None
                         or after.last_reconciled_at_ms >= before.last_reconciled_at_ms))

        def emit(kind, **fields):
            events.append(make_event(configuration, kind, run_id=run_id, observed_at_ms=observed_at_ms,
                checkpoint_sequence=after.sequence, runtime_state=a.state, runtime_reason=a.reason, **fields))

        if (accepted_reconciliation or (a.position_evidence is PositionEvidence.CONFIRMED
                and after.last_reconciled_at_ms is not None
                and after.last_reconciled_at_ms != before.last_reconciled_at_ms)):
            emit(T.RECONCILIATION_CONFIRMED, occurred_at_ms=after.last_reconciled_at_ms,
                 details=(("position_evidence", a.position_evidence), ("owned_base_quantity", a.owned_base_quantity),
                          ("pending_action_id", None if a.pending_action is None else a.pending_action.logical_action_id),
                          ("last_reconciled_at_ms", after.last_reconciled_at_ms),
                          ("last_broker_observation_at_ms", after.observed_at_ms)))
            known_before = (b.position_evidence is PositionEvidence.CONFIRMED or
                (accepted_reconciliation and b.position_evidence is PositionEvidence.LAST_KNOWN
                 and b.owned_base_quantity is not None and bool(contributing_execution_ids)))
            if known_before and b.owned_base_quantity != a.owned_base_quantity:
                kind = (T.POSITION_OPEN_CONFIRMED if b.owned_base_quantity == 0 else
                        T.POSITION_CLOSE_CONFIRMED if a.owned_base_quantity == 0 else T.POSITION_QUANTITY_CHANGED)
                emit(kind, occurred_at_ms=after.last_reconciled_at_ms,
                     details=(("position_evidence", a.position_evidence),
                              ("previous_owned_base_quantity", b.owned_base_quantity),
                              ("owned_base_quantity", a.owned_base_quantity),
                              ("pending_action_id", None if a.pending_action is None else a.pending_action.logical_action_id),
                              ("contributing_execution_ids", contributing_execution_ids)))
        if after.halted_at_ms is not None and after.halted_at_ms != before.halted_at_ms:
            # STOPPING retains a HALT latch as well; retained projection handles it.
            if a.state is RuntimeState.HALTED:
                emit(T.RUNTIME_HALTED, occurred_at_ms=after.halted_at_ms,
                     details=(("halted_at_ms", after.halted_at_ms), ("owned_base_quantity", a.owned_base_quantity),
                              ("position_evidence", a.position_evidence),
                              ("pending_action_id", None if a.pending_action is None else a.pending_action.logical_action_id)))
        if a.state is RuntimeState.UNCERTAIN and b.state is not RuntimeState.UNCERTAIN:
            emit(T.RUNTIME_UNCERTAIN, details=(("owned_base_quantity", a.owned_base_quantity),
                 ("position_evidence", a.position_evidence),
                 ("pending_action_id", None if a.pending_action is None else a.pending_action.logical_action_id)))
        if (b.state is RuntimeState.HALTED and a.state is RuntimeState.SYNCHRONIZING
                and after.rearmed_at_ms is not None and after.rearmed_at_ms != before.rearmed_at_ms):
            emit(T.RUNTIME_REARMED, occurred_at_ms=after.rearmed_at_ms,
                 details=(("rearmed_at_ms", after.rearmed_at_ms), ("previous_runtime_state", b.state),
                          ("reconciliation_required", True)))
        return tuple(events)


def cycle_completed(configuration, result, *, run_id, observed_at_ms, occurrence_reference):
    require(type(result) is SingleCycleResult and type(result.outcome) is CycleOutcome)
    exact(result.checkpoint, RuntimeCheckpoint)
    return make_event(configuration, T.CYCLE_COMPLETED, run_id=run_id, observed_at_ms=observed_at_ms,
        occurrence_reference=occurrence_reference, checkpoint_sequence=result.checkpoint.sequence,
        runtime_state=result.checkpoint.snapshot.state, runtime_reason=result.reason,
        action_id=result.logical_action_id, broker_order_id=result.broker_order_id,
        details=(("cycle_outcome", result.outcome.value), ("processed_candle_count", result.processed_candle_count),
                 ("processed_candle_open_ms", result.processed_candle_open_ms), ("new_execution_ids", result.new_execution_ids),
                 ("planner_kind", None if result.planner_kind is None else result.planner_kind.value),
                 ("risk_verdict", result.risk_verdict), ("risk_reason", result.risk_reason)))


def scheduler_exited(configuration, result, *, run_id, observed_at_ms, occurrence_reference):
    require(type(result) is SchedulerResult and type(result.exit_reason) is SchedulerExit)
    exact(result.checkpoint, RuntimeCheckpoint)
    return make_event(configuration, T.SCHEDULER_EXITED, run_id=run_id, observed_at_ms=observed_at_ms,
        occurrence_reference=occurrence_reference, checkpoint_sequence=result.checkpoint.sequence,
        runtime_state=result.checkpoint.snapshot.state, runtime_reason=result.checkpoint.snapshot.reason,
        details=(("scheduler_exit_reason", result.exit_reason.value), ("cycle_count", result.cycle_count),
                 ("wake_count", result.wake_count),
                 ("last_cycle_outcome", None if result.last_cycle is None else result.last_cycle.outcome.value)))


def critical_failure(configuration, *, run_id, observed_at_ms, occurrence_reference,
                     operation, failure_kind, exception_type, safe_error_code=None):
    """Caller supplies safe codes, never an exception/message/traceback object."""
    return make_event(configuration, T.CRITICAL_FAILURE, run_id=run_id, observed_at_ms=observed_at_ms,
        occurrence_reference=occurrence_reference, details=(("operation", operation), ("failure_kind", failure_kind),
        ("exception_type", exception_type), ("safe_error_code", safe_error_code)))


def process_started(configuration, *, run_id, observed_at_ms, process_started_at_ms):
    return make_event(configuration, T.PROCESS_STARTED, run_id=run_id, observed_at_ms=observed_at_ms,
        occurred_at_ms=process_started_at_ms, occurrence_reference="process-start",
        details=(("process_started_at_ms", process_started_at_ms),))


def process_stopped(configuration, *, run_id, observed_at_ms, process_started_at_ms,
                    process_stopped_at_ms, stop_reason):
    return make_event(configuration, T.PROCESS_STOPPED, run_id=run_id, observed_at_ms=observed_at_ms,
        occurred_at_ms=process_stopped_at_ms, occurrence_reference="process-stop",
        details=(("process_started_at_ms", process_started_at_ms), ("process_stopped_at_ms", process_stopped_at_ms),
                 ("stop_reason", stop_reason)))


def scheduler_started(configuration, *, run_id, observed_at_ms, scheduler_started_at_ms):
    return make_event(configuration, T.SCHEDULER_STARTED, run_id=run_id, observed_at_ms=observed_at_ms,
        occurred_at_ms=scheduler_started_at_ms, occurrence_reference="scheduler-start",
        details=(("scheduler_started_at_ms", scheduler_started_at_ms),))


def observability_degraded(configuration, *, run_id, observed_at_ms, occurrence_reference,
                           sink, operation, failure_kind, exception_type, safe_error_code=None):
    return make_event(configuration, T.OBSERVABILITY_DEGRADED, run_id=run_id, observed_at_ms=observed_at_ms,
        occurrence_reference=occurrence_reference,
        details=(("sink", sink), ("operation", operation), ("failure_kind", failure_kind),
                 ("exception_type", exception_type), ("safe_error_code", safe_error_code)))
