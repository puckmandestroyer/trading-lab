"""Actual temporary RuntimeStore histories and pure accepted transitions."""

from dataclasses import replace
from decimal import Decimal as D
import unittest
from unittest.mock import patch

from trading_lab.observability import *
from trading_lab.observability import projection as p
from trading_lab.runtime.state import RuntimeState as S, PositionEvidence as P, RuntimeReason as R, RuntimeStateSnapshot, PendingAction, PendingActionKind
from trading_lab.runtime.store import RuntimeCheckpoint, ActionPhase
from trading_lab.runtime.cycle import SingleCycleResult, CycleOutcome
from trading_lab.runtime.scheduler import SchedulerResult, SchedulerExit
from tests import test_runtime_store as fixtures
from tests import test_runtime_risk_rearm as rearm_fixtures
from tests import test_runtime_integration_regression as golden_fixtures

T = ObservabilityEventType
RUN = "0"*32
HOUR = fixtures.HOUR


def project(store, **kwargs):
    return project_retained_events(store, run_id=kwargs.get("run_id", RUN), observed_at_ms=kwargs.get("observed_at_ms", 100*HOUR))


class RetainedActionTests(fixtures.StoreCase):
    def test_empty_store_has_no_fabricated_history(self):
        self.assertEqual(project(self.store), ())

    def test_prepared_is_not_attempt_ack_fill_or_position(self):
        self.prepare()
        events = project(self.store)
        self.assertEqual([e.event_type for e in events], [T.ACTION_PREPARED])
        self.assertIsNone(events[0].occurred_at_ms)
        self.assertIsNone(events[0].checkpoint_sequence)

    def test_attempt_without_receipt_has_unavailable_occurrence(self):
        self.attempt()
        event, = project(self.store)
        self.assertIs(event.event_type, T.ACTION_ATTEMPT_STARTED)
        self.assertIsNone(event.occurred_at_ms)

    def test_acknowledged_not_fill(self):
        self.acknowledge()
        event, = project(self.store)
        self.assertIs(event.event_type, T.ACTION_ACKNOWLEDGED)
        self.assertEqual(event.occurred_at_ms, HOUR+1)

    def test_abandoned_unsent_is_not_an_attempt(self):
        action = self.prepare()
        cp = self.store.get_checkpoint()
        flat = RuntimeStateSnapshot(S.FLAT, D(0), P.CONFIRMED, 1)
        self.store.abandon_prepared(action.logical_action_id, replace(cp, sequence=cp.sequence+1, snapshot=flat),
            expected_sequence=cp.sequence, terminal_at_ms=HOUR+5)
        event, = project(self.store)
        self.assertIs(event.event_type, T.ACTION_ABANDONED_UNSENT)
        self.assertEqual(dict(event.details)["attempt_count"], 0)

    def test_confirmed_rejection_distinct_from_unknown(self):
        action = self.attempt()
        cp = self.store.get_checkpoint()
        self.store.record_observation(replace(action, phase=ActionPhase.REJECTED, rejection_code=10001, terminal_at_ms=HOUR+5),
            replace(cp, sequence=cp.sequence+1, snapshot=RuntimeStateSnapshot(S.FLAT, D(0), P.CONFIRMED, 1)),
            expected_sequence=cp.sequence)
        event, = project(self.store)
        self.assertIs(event.event_type, T.ACTION_REJECTED)
        self.assertEqual(dict(event.details)["rejection_code"], 10001)

    def test_unproven_runtime_rearm_omitted(self):
        self.flat()
        self.assertFalse(any(e.event_type is T.RUNTIME_REARMED for e in project(self.store)))

    def test_malformed_external_status_cannot_escape_validation(self):
        action = self.acknowledge()
        object.__setattr__(action, "external_status", "Authorization: synthetic-secret")
        with patch.object(self.store, "list_actions", return_value=(action,)):
            with self.assertRaises(ObservabilityProjectionError) as caught:
                project(self.store)
        self.assertNotIn("synthetic", str(caught.exception))

    def test_final_record_only_current_phase_and_owned_fill(self):
        self.settle(self.acknowledge(), fixtures.fill())
        events = project(self.store)
        self.assertEqual([e.event_type for e in events], [T.ACTION_TERMINAL_CONFIRMED, T.OWNED_EXECUTION_DISCOVERED])
        self.assertEqual(dict(events[1].details)["execution_fee"], D("-0.0000123456789"))
        self.assertIsNone(events[1].risk_epoch_id)

    def test_reprojection_stable_across_reopen_clock_and_run(self):
        self.settle(self.acknowledge(), fixtures.fill())
        ids = [e.event_id for e in project(self.store)]
        self.reopen()
        self.assertEqual(ids, [e.event_id for e in project(self.store, run_id="1"*32, observed_at_ms=200*HOUR)])

    def test_unknown_action_retains_identity_no_broker_guess(self):
        action = self.attempt()
        cp = self.store.get_checkpoint()
        uncertain = RuntimeStateSnapshot(S.UNCERTAIN, D(0), P.LAST_KNOWN, 1,
            cp.snapshot.pending_action, R.ACTION_OUTCOME_UNKNOWN)
        self.store.record_observation(replace(action, phase=ActionPhase.UNKNOWN_OUTCOME, safe_reason=R.ACTION_OUTCOME_UNKNOWN),
            replace(cp, sequence=cp.sequence+1, snapshot=uncertain), expected_sequence=cp.sequence)
        events = project(self.store)
        self.assertEqual([e.event_type for e in events], [T.ACTION_UNKNOWN_OUTCOME, T.RUNTIME_UNCERTAIN])
        self.assertTrue(all(e.action_id == action.logical_action_id and e.broker_order_id is None for e in events))

    def test_projection_uses_reads_without_trading_mutations(self):
        self.settle(self.acknowledge(), fixtures.fill())
        before = self.store.get_checkpoint(), self.store.list_actions(), self.store.list_fills()
        with patch.object(self.store, "save_checkpoint", side_effect=AssertionError("No writes")), \
                patch.object(self.store, "start_attempt", side_effect=AssertionError("No writes")):
            project(self.store)
        self.assertEqual(before, (self.store.get_checkpoint(), self.store.list_actions(), self.store.list_fills()))
        self.assertFalse(self.store._connection.in_transaction)

    def test_checkpoint_race_fails_without_retry(self):
        cp = self.store.get_checkpoint()
        with patch.object(self.store, "get_checkpoint", side_effect=[cp, replace(cp, sequence=cp.sequence+1)]) as read:
            with self.assertRaises(ObservabilityProjectionError):
                project(self.store)
            self.assertEqual(read.call_count, 2)

    def test_read_failure_has_sanitized_error(self):
        with patch.object(self.store, "list_actions", side_effect=fixtures.RuntimeStoreError("synthetic-secret")):
            with self.assertRaises(ObservabilityProjectionError) as caught:
                project(self.store)
            self.assertNotIn("synthetic", str(caught.exception))

    def test_oversized_batch_fails_never_returns_prefix(self):
        self.prepare()
        with patch.object(p, "MAX_RETAINED_RECORDS", 0):
            with self.assertRaises(ObservabilityProjectionError):
                project(self.store)


class RetainedRiskTests(rearm_fixtures.LocalRearmCase):
    def test_activation_is_not_rearm_trip_or_block(self):
        self.activate()
        self.assertEqual(project(self.store), ())

    def test_trip_origin_not_repeated_per_latched_candle(self):
        origin = self.tripped_long()
        self.live()
        self.live()
        events = [e for e in project(self.store) if e.event_type is T.RISK_TRIPPED]
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].occurred_at_ms, origin.tripped_at_ms)
        self.assertEqual(dict(events[0].details)["valued_at_ms"], origin.tripped_at_ms)

    def test_allow_exit_keeps_trip_and_does_not_create_another(self):
        self.tripped_long()
        _, action = self.live(signal="LONG_EXIT", desired=0)
        self.assertIsNotNone(action)
        self.assertEqual(len([e for e in project(self.store) if e.event_type is T.RISK_TRIPPED]), 1)

    def test_first_trip_during_allow_exit_preserves_both_facts(self):
        self.long_activation(close="100", cfg=fixtures.risk_configuration(max_daily_loss_fraction=D("0.01")))
        row, action = self.live(signal="LONG_EXIT", desired=0)
        event, = [e for e in project(self.store) if e.event_type is T.RISK_TRIPPED]
        self.assertEqual(event.occurred_at_ms, row.tripped_at_ms)
        self.assertIsNotNone(action)
        self.assertEqual(dict(event.details)["risk_verdict"].value, "ALLOW")

    def test_replay_origin_projects_trip_without_block(self):
        cfg = fixtures.risk_configuration(max_daily_loss_fraction=D("0.01"))
        self.long_activation(close="100", cfg=cfg)
        self.commit_candle(2*HOUR, "80")
        self.store.append_risk_replay_valuation(candle_open_ms=2*HOUR)
        trips = [e for e in project(self.store) if e.event_type is T.RISK_TRIPPED]
        self.assertEqual(len(trips), 1)
        self.assertEqual(dict(trips[0].details)["valuation_mode"].value, "REPLAY_ONLY")
        self.assertFalse(any(e.event_type is T.RISK_BLOCKED for e in project(self.store)))

    def test_live_block_uses_exact_candle_verdict_epoch(self):
        self.tripped_flat()
        self.live(signal="LONG_ENTRY", desired=1)
        events = [e for e in project(self.store) if e.event_type is T.RISK_BLOCKED]
        self.assertEqual(len(events), 1)
        event = events[0]
        verdict = self.store.get_risk_verdict(event.candle_open_ms)
        self.assertEqual(event.risk_epoch_id, verdict.epoch_id)
        self.assertEqual(dict(event.details)["risk_reason"], verdict.reason)

    def test_all_historical_children_proven_using_public_reads(self):
        self.tripped_long()
        children = []
        for price in ("60", "40", "20"):
            self.rearm()
            children.append(self.store.get_current_risk_epoch())
            self.live(price)
        before = self.store.list_actions(), self.store.list_fills(), self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        events = [e for e in project(self.store) if e.event_type is T.RISK_REARMED]
        self.assertEqual(len(events), 3)
        for event, child in zip(events, children):
            values = dict(event.details)
            self.assertEqual((values["parent_epoch_id"], values["child_epoch_id"], values["accepted_boundary_ms"]),
                             (child.parent_epoch_id, child.epoch_id, child.started_at_ms))
        ids = [e.event_id for e in events]
        self.assertEqual((self.store.list_actions(), self.store.list_fills(), self.store.list_risk_valuations(), self.store.list_risk_verdicts()), before)
        self.reopen()
        self.assertEqual(ids, [e.event_id for e in project(self.store, run_id="1"*32) if e.event_type is T.RISK_REARMED])

    def test_missing_activation_proof_rejected(self):
        self.tripped_long()
        self.rearm()
        rows = self.store.list_risk_valuations()
        with patch.object(self.store, "list_risk_valuations", return_value=rows[1:]):
            with self.assertRaises(ObservabilityProjectionError):
                project(self.store)

    def test_halt_latch_stable_later_checkpoint(self):
        self.tripped_long()
        self.halt()
        event = next(e for e in project(self.store) if e.event_type is T.RUNTIME_HALTED)
        self.refresh(self.now_ms+1)
        second = next(e for e in project(self.store) if e.event_type is T.RUNTIME_HALTED)
        self.assertEqual(event.event_id, second.event_id)

    def test_runtime_rearm_metadata_proves_control_not_health(self):
        self.tripped_long()
        self.halt()
        self.control_halt()
        event = next(e for e in project(self.store) if e.event_type is T.RUNTIME_REARMED)
        self.assertIs(event.runtime_state, S.SYNCHRONIZING)
        self.assertIsNone(event.checkpoint_sequence)
        self.assertTrue(dict(event.details)["reconciliation_required"])


def confirmed(quantity, sequence, *, pending=False, reconciled=10):
    state = RuntimeStateSnapshot(S.ORDER_PENDING if pending else S.FLAT if quantity == 0 else S.LONG,
        D(quantity), P.CONFIRMED, 1 if quantity else 0,
        PendingAction(fixtures.ACTION_ID, PendingActionKind.ENTRY) if pending else None)
    return RuntimeCheckpoint(sequence, state, last_reconciled_at_ms=reconciled, observed_at_ms=reconciled)


class TransitionTests(unittest.TestCase):
    def events(self, before, after):
        return project_checkpoint_transition(fixtures.configuration(), before, after, run_id=RUN,
            observed_at_ms=100, contributing_execution_ids=("fill-1",))

    def test_first_partial_buy_opens_while_pending(self):
        events = self.events(confirmed(0, 1), confirmed("0.1", 2, pending=True, reconciled=11))
        self.assertEqual([e.event_type for e in events], [T.RECONCILIATION_CONFIRMED, T.POSITION_OPEN_CONFIRMED])
        self.assertIs(events[-1].runtime_state, S.ORDER_PENDING)

    def test_later_partial_buy_changes_quantity_only(self):
        events = self.events(confirmed("0.1", 1, pending=True), confirmed("0.2", 2, pending=True, reconciled=11))
        self.assertIs(events[-1].event_type, T.POSITION_QUANTITY_CHANGED)

    def test_partial_sell_and_dust_not_close(self):
        events = self.events(confirmed(1, 1), confirmed("0.000000000001", 2, reconciled=11))
        self.assertIs(events[-1].event_type, T.POSITION_QUANTITY_CHANGED)
        self.assertEqual(dict(events[-1].details)["owned_base_quantity"], D("0.000000000001"))

    def test_confirmed_exact_zero_closes(self):
        self.assertIs(self.events(confirmed(1, 1), confirmed(0, 2, reconciled=11))[-1].event_type, T.POSITION_CLOSE_CONFIRMED)

    def test_unchanged_confirmed_exposure_no_new_position(self):
        self.assertEqual([e.event_type for e in self.events(confirmed(1, 1), confirmed(1, 2, reconciled=11))], [T.RECONCILIATION_CONFIRMED])

    def test_ack_and_prepared_no_reconciliation_no_position(self):
        self.assertEqual(self.events(confirmed(0, 1), confirmed(0, 2, pending=True)), ())

    def test_unknown_restart_no_fabricated_open(self):
        cp = RuntimeCheckpoint(1, RuntimeStateSnapshot())
        self.assertEqual([e.event_type for e in self.events(cp, confirmed(1, 2))], [T.RECONCILIATION_CONFIRMED])

    def test_last_known_holding_restoration_no_new_open(self):
        for state in (S.STARTING, S.SYNCHRONIZING):
            before = RuntimeCheckpoint(1, RuntimeStateSnapshot(state, D(1), P.LAST_KNOWN, 1))
            self.assertEqual([e.event_type for e in self.events(before, confirmed(1, 2))], [T.RECONCILIATION_CONFIRMED])

    def test_halt_uncertainty_and_rearm_exactly_proven(self):
        before = confirmed(1, 1)
        halted = RuntimeCheckpoint(2, RuntimeStateSnapshot(S.HALTED, D(1), P.LAST_KNOWN, 1, reason=R.INCONSISTENT_EVIDENCE), halted_at_ms=12)
        self.assertIs(self.events(before, halted)[0].event_type, T.RUNTIME_HALTED)
        rearmed = RuntimeCheckpoint(3, RuntimeStateSnapshot(S.SYNCHRONIZING, D(1), P.LAST_KNOWN, 1), rearmed_at_ms=13)
        self.assertIs(self.events(halted, rearmed)[0].event_type, T.RUNTIME_REARMED)
        uncertain = RuntimeCheckpoint(2, RuntimeStateSnapshot(S.UNCERTAIN, D(1), P.LAST_KNOWN, 1, reason=R.EVIDENCE_MISSING))
        self.assertIs(self.events(before, uncertain)[0].event_type, T.RUNTIME_UNCERTAIN)

    def test_sequence_must_advance(self):
        with self.assertRaises(ObservabilityProjectionError):
            self.events(confirmed(0, 1), confirmed(1, 1))

    def test_nonadjacent_checkpoints_not_an_invented_transition(self):
        with self.assertRaises(ObservabilityProjectionError):
            self.events(confirmed(0, 1), confirmed(1, 3))

    def test_transition_id_stable_not_observer_clock(self):
        a, b = confirmed(0, 1), confirmed(1, 2, reconciled=11)
        first = self.events(a, b)
        again = project_checkpoint_transition(fixtures.configuration(), a, b, run_id="1"*32, observed_at_ms=200)
        self.assertEqual([e.event_id for e in first], [e.event_id for e in again])


class ProcessProjectionTests(unittest.TestCase):
    def test_cycle_observed_not_filled_and_exact_fields(self):
        result = SingleCycleResult(confirmed(0, 1), CycleOutcome.OBSERVED, (0,), logical_action_id=fixtures.ACTION_ID)
        event = cycle_completed(fixtures.configuration(), result, run_id=RUN, observed_at_ms=100, occurrence_reference="cycle-1")
        self.assertIs(event.event_type, T.CYCLE_COMPLETED)
        self.assertEqual(dict(event.details)["cycle_outcome"], "OBSERVED")
        self.assertEqual(dict(event.details)["new_execution_ids"], ())

    def test_scheduler_preserves_all_exit_reasons(self):
        for reason in SchedulerExit:
            result = SchedulerResult(confirmed(0, 1), reason, 1, 0)
            event = scheduler_exited(fixtures.configuration(), result, run_id=RUN, observed_at_ms=100, occurrence_reference="exit")
            self.assertEqual(dict(event.details)["scheduler_exit_reason"], reason.value)

    def test_explicit_start_stop_and_degradation_helpers(self):
        cfg = fixtures.configuration()
        start = process_started(cfg, run_id=RUN, observed_at_ms=1, process_started_at_ms=0)
        stop = process_stopped(cfg, run_id=RUN, observed_at_ms=2, process_started_at_ms=0, process_stopped_at_ms=2, stop_reason="NORMAL")
        scheduler = scheduler_started(cfg, run_id=RUN, observed_at_ms=1, scheduler_started_at_ms=1)
        degraded = observability_degraded(cfg, run_id=RUN, observed_at_ms=2, occurrence_reference="error-1",
            sink="LOCAL", operation="WRITE", failure_kind="IO", exception_type="OSError")
        self.assertEqual([x.event_type for x in (start, stop, scheduler, degraded)],
                         [T.PROCESS_STARTED, T.PROCESS_STOPPED, T.SCHEDULER_STARTED, T.OBSERVABILITY_DEGRADED])


class FrozenGoldenProjectionTests(golden_fixtures.IntegrationCase):
    def test_golden_read_only_projection_and_artifact_deletion_independent(self):
        history, actions, fills, snapshot = self.golden()
        self.assertEqual((len(history), len(self.sends), len(fills), len(self.cancels), self.store.get_current_risk_epoch().epoch_sequence), (54, 2, 2, 0, 1))
        cp = self.store.get_checkpoint()
        before = self.store.list_actions(), self.store.list_fills(), self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        events = project(self.store, observed_at_ms=self.clock.ms)
        self.assertEqual(sum(e.event_type is T.ACTION_TERMINAL_CONFIRMED for e in events), 2)
        self.assertEqual(sum(e.event_type is T.OWNED_EXECUTION_DISCOVERED for e in events), 2)
        self.assertFalse(any(e.event_type in (T.POSITION_OPEN_CONFIRMED, T.POSITION_CLOSE_CONFIRMED) for e in events))
        self.assertEqual(self.store.get_checkpoint(), cp)
        self.assertEqual((self.store.list_actions(), self.store.list_fills(), self.store.list_risk_valuations(), self.store.list_risk_verdicts()), before)
        self.assertEqual(self.store.list_actions(), tuple(sorted(actions, key=lambda a:a.logical_action_id)))
        # Local artifacts can disappear without affecting replay decisions or
        # any durable row. Only a temporary test directory is touched.
        from pathlib import Path
        output = ObservabilityStorage(Path(self.directory).resolve()/"derived", self.config)
        snapshot = build_health_snapshot(self.store, run_id=RUN, process_started_at_ms=0, generated_at_ms=self.clock.ms)
        for event in events:
            output.append_event(event)
        output.write_health(snapshot)
        for file in output.instance_directory.iterdir():
            file.unlink()
        self.assertEqual((self.store.list_actions(), self.store.list_fills(), self.store.list_risk_valuations(), self.store.list_risk_verdicts()), before)
        self.assertEqual(self.store.get_checkpoint(), cp)
