"""Offline process boundaries, original lifecycle recovery and no-resend proofs."""

import ast
from dataclasses import replace
import hashlib
import inspect
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

import requests

from trading_lab.exchange.account_state import BrokerOrderNotFoundError, OrderStatus
from trading_lab.runtime.cycle import CycleOutcome
from trading_lab.runtime.locking import RuntimeAccountLock, RuntimeLockError
from trading_lab.runtime.recovery import RestartRecoveryError, prepare_process_restart
import trading_lab.runtime.recovery as module
from trading_lab.runtime.reconciliation import reconcile_startup
from trading_lab.runtime.scheduler import SchedulerExit, run_hourly_scheduler
from trading_lab.runtime.state import (
    PendingAction, PendingActionKind, PositionEvidence, RuntimeEvent, RuntimeEventType,
    RuntimeReason, RuntimeState, RuntimeStateSnapshot, transition_runtime_state,
)
from trading_lab.runtime.store import (
    ActionPhase, DecisionDisposition, RuntimeCheckpoint, RuntimeStore, RuntimeStoreError,
)
from tests import test_runtime_cycle as cycle_fixtures
from tests import test_runtime_reconciliation as read_fixtures
from tests import test_runtime_scheduler as scheduler_fixtures
from tests.test_runtime_store import ACTION_ID, D, HOUR, StoreCase, configuration, decision, fill


def close_current(case):
    case.store.close()
    case.lock.release()


def process_boundary(case, *, config=None):
    """A different lock/connection simulates the next cooperating OS process."""
    previous_lock, path = case.lock, case.lock.database_path
    case.store.close()
    previous_lock.release()
    case.lock = RuntimeAccountLock(Path(case.directory), "research").acquire()
    case.assertIsNot(case.lock, previous_lock)
    case.assertEqual(case.lock.database_path, path)
    case.store = RuntimeStore.open(case.lock, config or case.config, initialize=False)


def offline_guards(case):
    case.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("No network")))
    case.enterContext(patch.object(requests.Session, "request", side_effect=AssertionError("No network")))
    case.enterContext(patch("socket.create_connection", side_effect=AssertionError("No network")))
    case.enterContext(patch("os.getenv", side_effect=AssertionError("No credentials")))
    case.enterContext(patch("time.sleep", side_effect=AssertionError("No real sleep")))


class RestartCase(StoreCase):
    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = configuration()
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.addCleanup(close_current, self)
        offline_guards(self)
        self.now_ms = read_fixtures.NOW_MS
        self.broker = read_fixtures.FakeReadOnlyBroker(self.store)

    def reopen(self, config=None):
        process_boundary(self, config=config)
        self.broker.store = self.store

    def normalize(self):
        before = self.store.get_checkpoint()
        actions, fills = self.store.list_actions(), self.store.list_fills()
        history = tuple((self.store.get_candle(ms), self.store.get_decision(ms))
                        for ms in range(0, (before.last_processed_candle_ms or 0) + HOUR, HOUR))
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), before)
        with patch.object(self.store, "get_checkpoint", wraps=self.store.get_checkpoint) as get, \
             patch.object(self.store, "save_checkpoint", wraps=self.store.save_checkpoint) as save:
            result = prepare_process_restart(self.store)
        get.assert_called_once_with()
        unchanged = before.snapshot.state in (RuntimeState.STARTING, RuntimeState.HALTED)
        if unchanged:
            save.assert_not_called()
            self.assertEqual(result, before)
        else:
            save.assert_called_once_with(result, expected_sequence=before.sequence)
            self.assertEqual(result.sequence, before.sequence + 1)
        self.assertEqual(self.store.get_checkpoint(), result)
        self.assertEqual(self.store.list_actions(), actions)
        self.assertEqual(self.store.list_fills(), fills)
        self.assertEqual(tuple((self.store.get_candle(ms), self.store.get_decision(ms))
                               for ms in range(0, (before.last_processed_candle_ms or 0) + HOUR, HOUR)), history)
        for name in ("last_processed_candle_ms", "last_reconciled_at_ms", "observed_at_ms",
                     "coverage_start_ms", "coverage_end_ms", "rearmed_at_ms", "bootstrap_until_ms", "replay_until_ms"):
            self.assertEqual(getattr(result, name), getattr(before, name), name)
        self.assertEqual(result.snapshot.owned_base_quantity, before.snapshot.owned_base_quantity)
        self.assertEqual(result.snapshot.pending_action, before.snapshot.pending_action)
        self.assertEqual(result.snapshot.desired_position, before.snapshot.desired_position)
        self.assertIsNone(result.snapshot.stopped_from)
        self.assertIsNone(result.shutdown_at_ms)
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), result)
        self.assertEqual(self.store.list_actions(), actions)
        self.assertEqual(self.store.list_fills(), fills)
        return result

    def round(self):
        return reconcile_startup(self.store, self.broker,
                                 utc_now=lambda: read_fixtures.utc(self.now_ms), monotonic=lambda: 1.0)

    def unknown(self):
        action = replace(self.attempt(), phase=ActionPhase.UNKNOWN_OUTCOME,
                         safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
        cp = self.store.get_checkpoint()
        snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(
            RuntimeEventType.UNCERTAINTY_DETECTED, reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
        self.store.record_observation(action, self.next_checkpoint(snapshot=snapshot), expected_sequence=cp.sequence)
        return action

    def halt(self, reason=RuntimeReason.RECOVERY_EXHAUSTED):
        cp = self.store.get_checkpoint()
        snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY, reason=reason))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=snapshot, halted_at_ms=self.now_ms), expected_sequence=cp.sequence)
        return self.store.get_checkpoint()

    def stop(self):
        cp = self.store.get_checkpoint()
        snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED))
        self.store.save_checkpoint(self.next_checkpoint(snapshot=snapshot, shutdown_at_ms=self.now_ms + 1),
                                   expected_sequence=cp.sequence)
        return self.store.get_checkpoint()

    def assert_starting(self, cp, quantity):
        self.assertIs(cp.snapshot.state, RuntimeState.STARTING)
        self.assertEqual(cp.snapshot.owned_base_quantity, quantity)
        self.assertIs(cp.snapshot.position_evidence,
                      PositionEvidence.UNKNOWN if quantity is None else PositionEvidence.LAST_KNOWN)
        self.assertIsNone(cp.snapshot.reason)
        self.assertIsNone(cp.halted_at_ms)

    def assert_intent(self, before, after):
        for name in ("logical_action_id", "order_link_id", "kind", "symbol", "candle_open_ms", "side",
                     "amount_unit", "currency", "authorized_amount", "reconciliation_deadline_ms", "attempt_count"):
            self.assertEqual(getattr(after, name), getattr(before, name), name)
        if before.broker_order_id is not None:
            self.assertEqual(after.broker_order_id, before.broker_order_id)


class NormalizationTests(RestartCase):
    def test_existing_starting_returns_same_checkpoint_object_without_write(self):
        cp = self.store.get_checkpoint()
        self.reopen()
        with patch.object(self.store, "get_checkpoint", return_value=cp), patch.object(self.store, "save_checkpoint") as save:
            self.assertIs(prepare_process_restart(self.store), cp)
        save.assert_not_called()
        self.assertEqual(self.store.get_checkpoint(), cp)

    def test_existing_starting_with_unknown_action_remains_exact(self):
        self.unknown()
        self.assert_starting(self.normalize(), D("0"))
        before = self.store.get_checkpoint()
        self.assertEqual(self.normalize(), before)

    def test_synchronizing_unknown_quantity_enters_starting(self):
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING))
        self.store.save_checkpoint(cp, expected_sequence=cp.sequence - 1)
        self.assert_starting(self.normalize(), None)

    def test_synchronizing_known_quantity_enters_starting(self):
        self.flat()
        cp = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(snapshot=transition_runtime_state(
            cp.snapshot, RuntimeEvent(RuntimeEventType.FRESHNESS_LOST))), expected_sequence=cp.sequence)
        self.assert_starting(self.normalize(), D("0"))

    def test_flat_loses_confirmed_freshness_and_reconciles_again(self):
        self.flat()
        self.assert_starting(self.normalize(), D("0"))
        self.assertIs(self.round().checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(self.store.list_actions(), ())

    def test_long_preserves_exact_decimal_and_requires_reconciliation(self):
        self.settle(self.acknowledge(), fill())
        self.assert_starting(self.normalize(), D("0.1234691346789"))
        self.assertIs(self.round().checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(self.store.list_fills(), (fill(),))

    def test_pending_entry_preserves_original_identity_and_intent(self):
        self.acknowledge()
        cp = self.normalize()
        self.assert_starting(cp, D("0"))
        self.assertEqual(cp.snapshot.pending_action, PendingAction(ACTION_ID, PendingActionKind.ENTRY))
        self.assertEqual(cp.snapshot.desired_position, 1)

    def test_uncertain_known_quantity_clears_only_snapshot_reason(self):
        action = self.unknown()
        cp = self.normalize()
        self.assert_starting(cp, D("0"))
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertIs(action.safe_reason, RuntimeReason.ACTION_OUTCOME_UNKNOWN)

    def test_uncertain_unknown_quantity_is_not_fabricated_zero(self):
        self.unknown()
        cp = self.store.get_checkpoint()
        snapshot = replace(cp.snapshot, owned_base_quantity=None, position_evidence=PositionEvidence.UNKNOWN)
        self.store.save_checkpoint(self.next_checkpoint(snapshot=snapshot), expected_sequence=cp.sequence)
        self.assert_starting(self.normalize(), None)

    def test_halted_returns_exact_checkpoint_without_rearm_or_reads(self):
        self.unknown()
        before = self.halt()
        self.assertEqual(self.normalize(), before)
        self.assertEqual(self.round().checkpoint, before)
        self.assertEqual(self.broker.calls, [])

    def test_halted_returns_same_object_without_save(self):
        cp = self.halt(RuntimeReason.OWNERSHIP_CONFLICT)
        self.reopen()
        with patch.object(self.store, "get_checkpoint", return_value=cp), patch.object(self.store, "save_checkpoint") as save:
            self.assertIs(prepare_process_restart(self.store), cp)
        save.assert_not_called()

    def test_stopping_from_starting_consumes_shutdown_marker(self):
        self.stop()
        self.assert_starting(self.normalize(), None)

    def test_stopping_from_synchronizing_consumes_shutdown_marker(self):
        cp = self.next_checkpoint(snapshot=RuntimeStateSnapshot(RuntimeState.SYNCHRONIZING))
        self.store.save_checkpoint(cp, expected_sequence=cp.sequence - 1)
        self.stop()
        self.assert_starting(self.normalize(), None)

    def test_stopping_from_flat_requires_new_confirmation(self):
        self.flat()
        self.stop()
        self.assert_starting(self.normalize(), D("0"))

    def test_stopping_from_long_keeps_exact_owned_history(self):
        self.settle(self.acknowledge(), fill())
        self.stop()
        self.assert_starting(self.normalize(), D("0.1234691346789"))

    def test_stopping_from_pending_retains_lifecycle(self):
        self.acknowledge()
        self.stop()
        self.assert_starting(self.normalize(), D("0"))

    def test_stopping_from_uncertain_retains_unknown_action(self):
        action = self.unknown()
        self.stop()
        self.assert_starting(self.normalize(), D("0"))
        self.assertEqual(self.store.get_action(ACTION_ID), action)

    def test_stopping_from_halted_restores_exact_latch_not_starting(self):
        self.unknown()
        halted = self.halt(RuntimeReason.OWNERSHIP_CONFLICT)
        stopping = self.stop()
        cp = self.normalize()
        self.assertIs(cp.snapshot.state, RuntimeState.HALTED)
        self.assertEqual(cp.snapshot, halted.snapshot)
        self.assertEqual(cp.halted_at_ms, halted.halted_at_ms)
        self.assertEqual(cp.sequence, stopping.sequence + 1)
        self.assertEqual(self.round().checkpoint, cp)
        self.assertEqual(self.broker.calls, [])

    def test_all_checkpoint_history_fields_survive_normalization(self):
        self.unknown()
        cp = self.next_checkpoint(last_reconciled_at_ms=HOUR + 2, observed_at_ms=HOUR + 3,
                                  coverage_start_ms=0, coverage_end_ms=HOUR,
                                  rearmed_at_ms=1, bootstrap_until_ms=0, replay_until_ms=HOUR)
        self.store.save_checkpoint(cp, expected_sequence=cp.sequence - 1)
        self.assert_starting(self.normalize(), D("0"))

    def test_crash_after_normalization_is_idempotent_in_next_process(self):
        self.flat()
        self.stop()
        first = self.normalize()
        self.assertEqual(self.normalize(), first)
        self.assertEqual(self.normalize(), first)
        self.assertIs(self.round().checkpoint.snapshot.state, RuntimeState.FLAT)

    def test_unknown_quantity_stopping_remains_unknown(self):
        self.unknown()
        cp = self.store.get_checkpoint()
        self.store.save_checkpoint(self.next_checkpoint(snapshot=replace(
            cp.snapshot, owned_base_quantity=None, position_evidence=PositionEvidence.UNKNOWN)), expected_sequence=cp.sequence)
        self.stop()
        self.assert_starting(self.normalize(), None)


class JournalRecoveryTests(RestartCase):
    def test_prepared_is_retired_without_action_reauthorization(self):
        before = self.prepare()
        self.normalize()
        self.assertIs(self.round().checkpoint.snapshot.state, RuntimeState.FLAT)
        after = self.store.get_action(ACTION_ID)
        self.assertIs(after.phase, ActionPhase.ABANDONED_UNSENT)
        self.assert_intent(before, after)
        self.assertEqual(self.store.get_decision(0), decision(action=True))
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 0)
        self.normalize()
        self.round()
        self.assertEqual(self.store.get_action(ACTION_ID), after)

    def test_attempt_without_send_becomes_unknown_not_abandoned(self):
        original = self.attempt()
        self.normalize()
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIs(result.placement.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assert_intent(original, result.placement)
        self.assertEqual(result.placement.remaining_read_attempts, 2)
        self.assertIsNone(result.placement.terminal_at_ms)

    def test_restart_counters_never_reset_and_missing_history_eventually_halts(self):
        original = self.attempt()
        previous = original
        for remaining in (2, 1, 0):
            self.normalize()
            self.assertEqual(self.store.get_action(ACTION_ID), previous)
            result = self.round()
            previous = result.placement
            self.assert_intent(original, previous)
            self.assertEqual(previous.remaining_read_attempts, remaining)
            self.assertEqual(previous.remaining_reconciliation_rounds, remaining + 2)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)
        calls = tuple(self.broker.calls)
        self.normalize()
        self.round()
        self.assertEqual(tuple(self.broker.calls), calls)

    def test_exhausted_round_budget_cannot_be_reset_by_restart(self):
        original = self.unknown()
        cp = self.store.get_checkpoint()
        bounded = replace(original, remaining_reconciliation_rounds=1)
        self.store.record_observation(bounded, self.next_checkpoint(), expected_sequence=cp.sequence)
        self.normalize()
        result = self.round()
        self.assertEqual(result.placement.remaining_reconciliation_rounds, 0)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)

    def test_expired_deadline_halts_before_any_broker_read(self):
        original = self.unknown()
        self.normalize()
        self.now_ms = original.reconciliation_deadline_ms
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)
        self.assertEqual(result.placement, original)
        self.assertEqual(self.broker.calls, [])

    def test_lost_ack_open_discovers_original_order_without_fabricated_receipt(self):
        original = self.attempt()
        self.normalize()
        self.broker.opens = (read_fixtures.order(),)
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assert_intent(original, result.placement)
        self.assertEqual(result.placement.broker_order_id, "order-1")
        self.assertIs(result.placement.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIsNone(result.placement.submitted_amount)
        self.assertIsNone(result.placement.acknowledgement_broker_ms)
        self.assertIsNone(result.placement.acknowledgement_observed_ms)

    def test_lost_ack_execution_discovery_uses_exact_order_and_execution_queries(self):
        original = self.attempt()
        self.normalize()
        self.broker.executions = (read_fixtures.execution(),)
        self.broker.order = read_fixtures.order(OrderStatus.FILLED, quantity="0.05")
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.04995"))
        self.assert_intent(original, result.placement)
        self.assertIn(("get_order", {"order_id": "order-1"}), self.broker.calls)
        self.assertIn(("get_executions", {"order_id": "order-1", "symbol": None}), self.broker.calls)
        self.assertIsNone(result.placement.acknowledgement_broker_ms)

    def test_lost_ack_base_rebate_is_exact_owned_quantity(self):
        self.attempt()
        self.normalize()
        self.broker.executions = (read_fixtures.execution(fee="-0.00005"),)
        self.broker.order = read_fixtures.order(OrderStatus.FILLED, quantity="0.05")
        result = self.round()
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.05005"))
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)

    def test_acknowledged_open_reuses_known_id_and_retains_zero_exposure(self):
        original = self.acknowledge()
        self.assert_starting(self.normalize(), D("0"))
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assert_intent(original, result.placement)
        self.assertEqual(result.placement.acknowledgement_broker_ms, original.acknowledgement_broker_ms)
        self.assertEqual(result.placement.submitted_amount, original.submitted_amount)
        self.assertEqual(self.store.list_fills(), ())

    def test_acknowledged_partial_recovers_exact_fill_once(self):
        self.acknowledge()
        self.normalize()
        self.broker.order = read_fixtures.order(OrderStatus.PARTIALLY_FILLED, quantity="0.05")
        self.broker.executions = (read_fixtures.execution(),)
        result = self.round()
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.04995"))
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.new_execution_ids, ("exec-1",))

    def test_acknowledged_filled_buy_recovers_long(self):
        self.acknowledge()
        self.normalize()
        self.broker.order = read_fixtures.order(OrderStatus.FILLED, quantity="0.05")
        self.broker.executions = (read_fixtures.execution(),)
        self.assertIs(self.round().checkpoint.snapshot.state, RuntimeState.LONG)

    def test_durable_unknown_outcome_can_restart_then_recover_open(self):
        original = self.unknown()
        self.normalize()
        self.broker.opens = (read_fixtures.order(),)
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertIs(result.placement.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assert_intent(original, result.placement)

    def test_durable_unknown_outcome_missing_evidence_stays_uncertain(self):
        original = self.unknown()
        self.normalize()
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIs(result.placement.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assert_intent(original, result.placement)

    def test_terminal_long_survives_empty_current_execution_window(self):
        self.settle(self.acknowledge(), fill())
        original = self.store.get_action(ACTION_ID)
        self.normalize()
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.1234691346789"))
        self.assertEqual(self.store.get_action(ACTION_ID), original)
        self.assertEqual(self.store.list_fills(), (fill(),))
        self.assertFalse(any(name == "get_order" for name, _ in self.broker.calls))

    def test_abandoned_unsent_keeps_consumed_action_and_link(self):
        self.prepare()
        cp = self.store.get_checkpoint()
        flat = RuntimeStateSnapshot(RuntimeState.FLAT, D("0"), PositionEvidence.CONFIRMED, 1)
        self.store.abandon_prepared(ACTION_ID, self.next_checkpoint(snapshot=flat),
                                    expected_sequence=cp.sequence, terminal_at_ms=self.now_ms)
        original = self.store.get_action(ACTION_ID)
        self.normalize()
        self.assertIs(self.round().checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(self.store.get_action(ACTION_ID), original)
        self.assertEqual(self.store.get_decision(0), decision(action=True))

    def test_rejected_halt_remains_latched_with_exact_rejection_code(self):
        action = replace(self.attempt(), phase=ActionPhase.REJECTED, rejection_code=10001,
                         terminal_at_ms=self.now_ms, safe_reason=RuntimeReason.INCONSISTENT_EVIDENCE)
        cp = self.store.get_checkpoint()
        halt = RuntimeStateSnapshot(RuntimeState.HALTED, D("0"), PositionEvidence.LAST_KNOWN, 1,
                                    reason=RuntimeReason.INCONSISTENT_EVIDENCE)
        self.store.record_observation(action, self.next_checkpoint(snapshot=halt, halted_at_ms=self.now_ms),
                                      expected_sequence=cp.sequence)
        before = self.store.get_checkpoint()
        self.assertEqual(self.normalize(), before)
        self.assertEqual(self.round().checkpoint, before)
        self.assertEqual(self.store.get_action(ACTION_ID), action)
        self.assertEqual(self.broker.calls, [])

    def test_namespace_prefix_collision_halts_without_adoption(self):
        self.unknown()
        self.normalize()
        self.broker.opens = (replace(read_fixtures.order(), order_link_id="bot1-unrecorded"),)
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertIsNone(result.placement.broker_order_id)

    def test_foreign_managed_symbol_open_order_blocks_restart(self):
        self.flat()
        self.normalize()
        self.broker.opens = (replace(read_fixtures.order(), order_link_id="manual"),)
        self.assertIs(self.round().checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual(self.store.list_actions(), ())

    def test_unowned_execution_cannot_be_adopted_as_bot_history(self):
        self.unknown()
        self.normalize()
        self.broker.executions = (replace(read_fixtures.execution(), order_link_id="bot1-foreign"),)
        self.assertIs(self.round().checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual(self.store.list_fills(), ())

    def test_missing_known_order_after_restart_is_uncertainty_not_rejection(self):
        self.acknowledge()
        self.normalize()
        self.broker.errors["get_order"] = BrokerOrderNotFoundError("Synthetic history absent")
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIs(result.placement.phase, ActionPhase.ACKNOWLEDGED)
        self.assertIsNone(result.placement.terminal_at_ms)

    def test_unknown_cancel_control_stays_subordinate_and_is_never_resent(self):
        parent = self.acknowledge()
        # This fixture writes a previously authorized local control only. It
        # contains no SDK cancellation and is not a runtime cancellation API.
        cancel = read_fixtures.ReconciliationTests.cancel_control(self)
        self.normalize()
        self.assertEqual(self.store.get_action(cancel.logical_action_id), cancel)
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIs(result.cancellation.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(result.cancellation.parent_action_id, parent.logical_action_id)
        self.assertEqual(result.cancellation.target_broker_order_id, parent.broker_order_id)
        self.assertEqual(result.cancellation.control_id, cancel.control_id)
        self.assertEqual(result.cancellation.attempt_count, 1)
        self.assertEqual(result.cancellation.remaining_read_attempts, 2)
        self.assertEqual(result.checkpoint.snapshot.pending_action.logical_action_id, parent.logical_action_id)

    def test_terminal_parent_settles_retained_unknown_cancel_without_sending_cancel(self):
        parent = self.acknowledge()
        cancel = read_fixtures.ReconciliationTests.cancel_control(self)
        self.normalize()
        self.broker.order = read_fixtures.order(OrderStatus.FILLED, quantity="0.05")
        self.broker.executions = (read_fixtures.execution(),)
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertIs(result.placement.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertIs(result.cancellation.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertEqual(result.cancellation.order_status, "FILLED")
        self.assertEqual(result.cancellation.parent_action_id, parent.logical_action_id)
        self.assertEqual(result.cancellation.logical_action_id, cancel.logical_action_id)
        self.assertIsNone(result.cancellation.acknowledgement_broker_ms)

    def test_known_order_execution_with_foreign_link_halts_instead_of_adoption(self):
        self.acknowledge()
        self.normalize()
        self.broker.executions = (replace(read_fixtures.execution(), order_link_id="manual-link"),)
        result = self.round()
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual(self.store.list_fills(), ())


class StoreRestartSafetyTests(RestartCase):
    def test_missing_database_restart_fails_without_initialization(self):
        self.store.close()
        self.lock.release()
        self.lock = RuntimeAccountLock(Path(self.directory), "missing").acquire()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, replace(self.config, account_binding="missing"), initialize=False)
        self.assertFalse(self.lock.database_path.exists())
        self.assertEqual(self.broker.calls, [])

    def test_configuration_changes_fail_without_migration_or_overwrite(self):
        self.attempt()
        self.store.close()
        self.lock.release()
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        before = self.lock.database_path.read_bytes()
        changes = ({"bot_id": "bot2"}, {"account_binding": "other"},
                   {"strategy_implementation_digest": "f" * 64},
                   {"symbol": "ETHUSDT", "base_currency": "ETH"},
                   {"configuration_digest": "f" * 64}, {"buy_quote_budget": D("11")})
        for change in changes:
            with self.subTest(change=change), self.assertRaises(RuntimeStoreError):
                RuntimeStore.open(self.lock, replace(self.config, **change), initialize=False)
            self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.store = RuntimeStore.open(self.lock, self.config, initialize=False)
        self.assertIs(self.store.get_action(ACTION_ID).phase, ActionPhase.ATTEMPT_STARTED)

    def test_corrupt_database_is_not_recreated_or_repaired(self):
        self.store.close()
        self.lock.release()
        self.lock.database_path.write_bytes(b"synthetic-invalid-sqlite")
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config, initialize=False)
        self.assertEqual(self.lock.database_path.read_bytes(), before)
        self.assertEqual(self.broker.calls, [])

    def test_unsupported_schema_is_not_migrated(self):
        self.store.close()
        self.lock.release()
        with sqlite3.connect(self.lock.database_path) as connection:
            connection.execute("PRAGMA user_version=3")
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config, initialize=False)
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_checkpoint_journal_integrity_failure_is_not_repaired(self):
        self.attempt()
        self.store.close()
        self.lock.release()
        with sqlite3.connect(self.lock.database_path) as connection:
            connection.execute("UPDATE checkpoint SET pending_action_kind='EXIT'")
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        before = self.lock.database_path.read_bytes()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config, initialize=False)
        self.assertEqual(self.lock.database_path.read_bytes(), before)

    def test_restart_requires_canonical_lock_before_store_access(self):
        unlocked = RuntimeAccountLock(Path(self.directory), "research")
        with self.assertRaises(RuntimeLockError):
            RuntimeStore.open(unlocked, self.config, initialize=False)

    def test_closed_store_error_propagates_without_reopening(self):
        self.store.close()
        with self.assertRaises(RuntimeStoreError):
            prepare_process_restart(self.store)
        self.assertEqual(self.broker.calls, [])

    def test_save_failure_propagates_same_store_error_without_retry(self):
        self.flat()
        self.reopen()
        before = self.store.get_checkpoint()
        error = RuntimeStoreError("Synthetic uncertain persistence")
        with patch.object(self.store, "save_checkpoint", side_effect=error) as save, self.assertRaises(RuntimeStoreError) as caught:
            prepare_process_restart(self.store)
        self.assertIs(caught.exception, error)
        save.assert_called_once()
        self.assertEqual(self.broker.calls, [])
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), before)

    def test_failed_preparation_commit_reopens_old_durable_truth(self):
        self.flat()
        self.reopen()
        before = self.store.get_checkpoint()
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic failure")), \
             patch.object(self.store, "save_checkpoint", wraps=self.store.save_checkpoint) as save, \
             self.assertRaises(RuntimeStoreError):
            prepare_process_restart(self.store)
        save.assert_called_once()
        self.assertEqual(self.broker.calls, [])
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), before)

    def test_indeterminate_preparation_commit_reopens_new_durable_truth(self):
        self.flat()
        self.stop()
        self.reopen()
        before = self.store.get_checkpoint()
        commit = self.store._commit

        def committed_then_failed():
            commit()
            raise sqlite3.OperationalError("Synthetic failure after commit")

        with patch.object(self.store, "_commit", side_effect=committed_then_failed), \
             patch.object(self.store, "save_checkpoint", wraps=self.store.save_checkpoint) as save, \
             self.assertRaises(RuntimeStoreError):
            prepare_process_restart(self.store)
        save.assert_called_once()
        self.assertEqual(self.broker.calls, [])
        self.reopen()
        cp = self.store.get_checkpoint()
        self.assertEqual(cp.sequence, before.sequence + 1)
        self.assert_starting(cp, D("0"))
        with patch.object(self.store, "save_checkpoint") as save:
            self.assertEqual(prepare_process_restart(self.store), cp)
        save.assert_not_called()

    def test_checkpoint_read_error_propagates_without_write_or_retry(self):
        error = RuntimeStoreError("Synthetic invalid durable truth")
        with patch.object(self.store, "get_checkpoint", side_effect=error) as get, \
             patch.object(self.store, "save_checkpoint") as save, self.assertRaises(RuntimeStoreError) as caught:
            prepare_process_restart(self.store)
        self.assertIs(caught.exception, error)
        get.assert_called_once_with()
        save.assert_not_called()
        self.assertEqual(self.broker.calls, [])

    def test_checkpoint_cas_conflict_propagates_without_overwriting_newer_truth(self):
        self.flat()
        self.reopen()
        before = self.store.get_checkpoint()
        save = self.store.save_checkpoint
        newer = replace(before, sequence=before.sequence + 1)

        def competing_write(proposed, *, expected_sequence):
            save(newer, expected_sequence=expected_sequence)
            save(proposed, expected_sequence=expected_sequence)

        with patch.object(self.store, "save_checkpoint", side_effect=competing_write) as attempted, self.assertRaises(RuntimeStoreError):
            prepare_process_restart(self.store)
        attempted.assert_called_once()
        self.reopen()
        self.assertEqual(self.store.get_checkpoint(), newer)
        self.assertEqual(self.broker.calls, [])

    def test_preparation_never_invokes_action_history_or_action_write_apis(self):
        self.unknown()
        self.reopen()
        forbidden = {name: Mock(side_effect=AssertionError("Checkpoint-only process entry")) for name in (
            "list_actions", "list_fills", "commit_decision", "start_attempt", "abandon_prepared",
            "record_observation", "prepare_cancellation")}
        with patch.multiple(self.store, **forbidden):
            self.assertIs(prepare_process_restart(self.store).snapshot.state, RuntimeState.STARTING)
        for operation in forbidden.values():
            operation.assert_not_called()
        self.assertEqual(self.broker.calls, [])


class CycleRestartCase(cycle_fixtures.CycleCase):
    """Frozen cycle fixtures with explicit new lock lifetimes and fake resources."""

    def setUp(self):
        self.directory = self.enterContext(TemporaryDirectory())
        self.config = self.runtime_configuration()
        self.lock = RuntimeAccountLock(Path(self.directory), "research").acquire()
        self.store = RuntimeStore.open(self.lock, self.config, initialize=True)
        self.addCleanup(close_current, self)
        offline_guards(self)
        self.trace, self.prices, self.now_ms = [], ["100"] * 50, 50 * HOUR + 1000
        self.broker = cycle_fixtures.FakeBroker(self)
        self.external_resources()
        clock = self.enterContext(patch.object(cycle_fixtures.adapter_module, "datetime", wraps=cycle_fixtures.datetime))
        clock.now.side_effect = lambda tz=None: cycle_fixtures.utc(self.now_ms)

    def external_resources(self):
        self.market = cycle_fixtures.FakeMarketReader(self)
        self.session = cycle_fixtures.TransactionCheckedSession(self)
        self.order_adapter = cycle_fixtures.FakeOrderAdapter(self)

    def restart(self):
        before = self.store.get_checkpoint()
        actions, fills = self.store.list_actions(), self.store.list_fills()
        process_boundary(self)
        self.assertEqual(self.store.get_checkpoint(), before)
        cp = prepare_process_restart(self.store)
        self.assertEqual(self.store.list_actions(), actions)
        self.assertEqual(self.store.list_fills(), fills)
        for name in ("last_processed_candle_ms", "bootstrap_until_ms", "replay_until_ms", "last_reconciled_at_ms",
                     "observed_at_ms", "coverage_start_ms", "coverage_end_ms", "rearmed_at_ms"):
            self.assertEqual(getattr(cp, name), getattr(before, name), name)
        self.assertEqual(cp.snapshot.pending_action, before.snapshot.pending_action)
        self.assertEqual(cp.snapshot.owned_base_quantity, before.snapshot.owned_base_quantity)
        self.assertEqual(cp.snapshot.desired_position, before.snapshot.desired_position)
        self.assertIsNot(cp.snapshot.position_evidence, PositionEvidence.CONFIRMED)
        # A new process constructs its own fake external resources only AFTER
        # preparation. Broker observations model retained remote truth separately.
        self.external_resources()
        self.trace.clear()
        return cp

    def recover_cycle(self):
        with patch.object(self.order_adapter, "place_market_order", side_effect=AssertionError("Restart cannot resend")) as place, \
             patch.object(self.session, "place_order", side_effect=AssertionError("No placement")) as sdk_place, \
             patch.object(self.session, "cancel_order", side_effect=AssertionError("No cancellation")) as cancel:
            result = self.run_cycle()
        place.assert_not_called()
        sdk_place.assert_not_called()
        cancel.assert_not_called()
        self.assertEqual(self.order_adapter.calls, [])
        self.assert_no_send()
        return result

    def crash_action(self, phase, *, committed=False):
        """Stop before/after a public observation commit, not by rewriting SQL."""
        observe = self.store.record_observation
        interrupted_id = None

        def interrupted(action, *args, **kwargs):
            nonlocal interrupted_id
            if action.phase == phase:
                interrupted_id = action.logical_action_id
                if committed:
                    observe(action, *args, **kwargs)
                raise RuntimeStoreError("Synthetic process death at observation boundary")
            return observe(action, *args, **kwargs)

        with patch.object(self.store, "record_observation", side_effect=interrupted), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.assertIsNotNone(interrupted_id)
        return self.store.get_action(interrupted_id)

    def crash_attempt_before_send(self):
        self.bootstrap()
        self.advance("110")
        start = self.store.start_attempt

        def died_after_commit(*args, **kwargs):
            start(*args, **kwargs)
            raise RuntimeStoreError("Synthetic death after attempt boundary")

        with patch.object(self.store, "start_attempt", side_effect=died_after_commit), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.assert_no_send()
        action = self.store.list_actions()[0]
        self.assertIs(action.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertEqual(action.attempt_count, 1)
        return action

    def assert_original(self, action):
        saved = self.store.get_action(action.logical_action_id)
        for name in ("logical_action_id", "order_link_id", "candle_open_ms", "kind", "side", "amount_unit",
                     "currency", "authorized_amount", "reconciliation_deadline_ms", "attempt_count"):
            self.assertEqual(getattr(saved, name), getattr(action, name), name)
        if action.broker_order_id is not None:
            self.assertEqual(saved.broker_order_id, action.broker_order_id)
        self.assertIs(self.store.get_decision(action.candle_open_ms).disposition, DecisionDisposition.ACTION)
        return saved


class FrozenCycleCrashTests(CycleRestartCase):
    def test_crash_a_failed_prepared_transaction_has_no_partial_history_or_send(self):
        self.bootstrap()
        self.advance("110")
        commit = self.store.commit_decision

        def failed(*args, **kwargs):
            with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic disk failure")):
                return commit(*args, **kwargs)

        with patch.object(self.store, "commit_decision", side_effect=failed), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.assert_no_send()
        self.restart()
        self.assertEqual(self.store.list_actions(), ())
        self.assertIsNone(self.store.get_candle(50 * HOUR))
        self.assertIsNone(self.store.get_decision(50 * HOUR))
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 49 * HOUR)
        # Nothing was committed/attempted: normal fresh recomputation can make
        # its first authorization, through the real cycle and fake SDK only.
        result = self.run_cycle()
        self.assertIs(result.outcome, CycleOutcome.OBSERVED)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(len(self.store.list_actions()), 1)

    def test_crash_b_prepared_commit_is_abandoned_and_never_reauthorized(self):
        self.bootstrap()
        self.advance("110")
        commit = self.store.commit_decision

        def committed_then_died(*args, **kwargs):
            commit(*args, **kwargs)
            raise RuntimeStoreError("Synthetic death after prepared commit")

        with patch.object(self.store, "commit_decision", side_effect=committed_then_died), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        original = self.store.list_actions()[0]
        original_decision = self.store.get_decision(50 * HOUR)
        self.assert_no_send()
        self.restart()
        result = self.recover_cycle()
        saved = self.assert_original(original)
        self.assertIs(result.outcome, CycleOutcome.NO_NEW_DATA)
        self.assertIs(saved.phase, ActionPhase.ABANDONED_UNSENT)
        self.assertEqual(self.store.get_decision(50 * HOUR), original_decision)
        self.assertEqual(result.checkpoint.last_processed_candle_ms, 50 * HOUR)
        self.advance("110")  # Historical entry remains consumed on later HOLD.
        self.recover_cycle()
        self.assertEqual(self.store.list_actions(), (saved,))

    def test_crash_c_attempt_before_send_is_unknown_and_never_abandoned(self):
        original = self.crash_attempt_before_send()
        self.restart()
        result = self.recover_cycle()
        saved = self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.UNCERTAIN)
        self.assertIs(saved.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertIsNone(saved.terminal_at_ms)
        self.assertIsNone(saved.broker_order_id)

    def test_crash_d_lost_ack_open_recovers_original_link_without_receipt(self):
        self.bootstrap()
        self.broker.status = OrderStatus.OPEN
        self.advance("110")
        original = self.crash_action(ActionPhase.ACKNOWLEDGED)
        self.assertIs(original.phase, ActionPhase.ATTEMPT_STARTED)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)
        self.restart()
        result = self.recover_cycle()
        saved = self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertIs(saved.phase, ActionPhase.UNKNOWN_OUTCOME)
        self.assertEqual(saved.broker_order_id, "order-1")
        self.assertIsNone(saved.submitted_amount)
        self.assertIsNone(saved.acknowledgement_broker_ms)
        self.assertIsNone(saved.acknowledgement_observed_ms)

    def test_crash_d_lost_ack_filled_recovers_owned_buy_once(self):
        self.bootstrap()
        self.broker.fee, self.broker.fee_currency = D("0.00005"), "BTC"
        self.advance("110")
        original = self.crash_action(ActionPhase.ACKNOWLEDGED)
        self.restart()
        result = self.recover_cycle()
        saved = self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.04995"))
        self.assertIs(saved.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertIsNone(saved.acknowledgement_broker_ms)
        self.assertEqual(result.new_execution_ids, ("exec-order-1",))
        self.assertEqual(len(self.store.list_fills()), 1)

    def test_crash_e_acknowledged_open_reuses_exact_known_order(self):
        self.bootstrap()
        self.broker.status = OrderStatus.OPEN
        self.advance("110")
        original = self.crash_action(ActionPhase.ACKNOWLEDGED, committed=True)
        self.assertIs(original.phase, ActionPhase.ACKNOWLEDGED)
        self.restart()
        result = self.recover_cycle()
        saved = self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(saved.submitted_amount, original.submitted_amount)
        self.assertEqual(saved.acknowledgement_broker_ms, original.acknowledgement_broker_ms)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))

    def test_crash_e_acknowledged_partial_recovers_pending_exposure(self):
        self.bootstrap()
        self.broker.status = OrderStatus.PARTIALLY_FILLED
        self.advance("110")
        original = self.crash_action(ActionPhase.ACKNOWLEDGED, committed=True)
        self.restart()
        result = self.recover_cycle()
        self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.02"))
        self.assertEqual(len(self.store.list_fills()), 1)

    def test_crash_e_acknowledged_filled_buy_becomes_long(self):
        self.bootstrap()
        self.advance("110")
        original = self.crash_action(ActionPhase.ACKNOWLEDGED, committed=True)
        self.restart()
        self.assertIs(self.recover_cycle().checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertIs(self.assert_original(original).phase, ActionPhase.TERMINAL_CONFIRMED)

    def test_crash_e_acknowledged_filled_sell_zero_becomes_flat(self):
        self.entry()
        self.advance("80")
        self.crash_action(ActionPhase.ACKNOWLEDGED, committed=True)
        original = self.store.get_action(self.pending_id())
        self.assertEqual((original.side, original.amount_unit), ("SELL", "BASE"))
        self.restart()
        result = self.recover_cycle()
        self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0"))

    def test_crash_e_acknowledged_filled_sell_remainder_stays_long(self):
        self.broker.buy_quantity = D("0.0500009")
        self.entry()
        self.advance("80")
        self.crash_action(ActionPhase.ACKNOWLEDGED, committed=True)
        original = self.store.get_action(self.pending_id())
        self.restart()
        result = self.recover_cycle()
        self.assert_original(original)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.0000009"))

    def test_crash_f_persisted_partial_fill_is_deduplicated_after_restart(self):
        self.broker.fee = D("0.00002")
        result = self.entry(status=OrderStatus.PARTIALLY_FILLED)
        original, fills = self.action(result), self.store.list_fills()
        self.restart()
        recovered = self.recover_cycle()
        self.assert_original(original)
        self.assertIs(recovered.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(recovered.checkpoint.snapshot.owned_base_quantity, D("0.01998"))
        self.assertEqual(recovered.new_execution_ids, ())
        self.assertEqual(self.store.list_fills(), fills)

    def test_crash_f_repeated_and_new_partial_fills_each_apply_once(self):
        result = self.entry(status=OrderStatus.PARTIALLY_FILLED)
        original = self.action(result)
        first = self.broker.fills[0]
        self.now_ms += 1000
        stamp = cycle_fixtures.utc(self.now_ms)
        second = replace(first, broker_execution_id="exec-new", executed_at=stamp,
                         broker_timestamp=stamp, fetched_at=stamp)
        self.broker.fills = [first, first, second, second]
        self.broker.orders["order-1"] = replace(self.broker.orders["order-1"], filled_quantity=D("4"),
                                                remaining_quantity=original.submitted_amount - D("4"),
                                                filled_base_quantity=D("0.04"), filled_quote_amount=D("4"), updated_at=stamp)
        self.restart()
        recovered = self.recover_cycle()
        self.assert_original(original)
        self.assertEqual(recovered.checkpoint.snapshot.owned_base_quantity, D("0.04"))
        self.assertEqual(recovered.new_execution_ids, ("exec-new",))
        self.assertEqual(len(self.store.list_fills()), 2)
        self.assertIs(recovered.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)

    def test_crash_f_partial_then_terminal_fill_clears_only_proven_pending(self):
        result = self.entry(status=OrderStatus.PARTIALLY_FILLED)
        original = self.action(result)
        first = self.broker.fills[0]
        self.now_ms += 1000
        stamp = cycle_fixtures.utc(self.now_ms)
        self.broker.fills.append(replace(first, broker_execution_id="exec-final", executed_quantity=D("0.03"),
                                        executed_at=stamp, broker_timestamp=stamp, fetched_at=stamp))
        self.broker.orders["order-1"] = replace(self.broker.orders["order-1"], status=OrderStatus.FILLED,
                                                external_status="Filled", filled_quantity=D("5"),
                                                remaining_quantity=original.submitted_amount - D("5"),
                                                filled_base_quantity=D("0.05"), filled_quote_amount=D("5"), updated_at=stamp)
        self.restart()
        recovered = self.recover_cycle()
        self.assertIs(recovered.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertIsNone(recovered.checkpoint.snapshot.pending_action)
        self.assertEqual(recovered.checkpoint.snapshot.owned_base_quantity, D("0.05"))
        self.assertIs(self.assert_original(original).phase, ActionPhase.TERMINAL_CONFIRMED)
        self.assertEqual(len(self.store.list_fills()), 2)

    def conflicting_fill(self, **changes):
        self.entry(status=OrderStatus.PARTIALLY_FILLED)
        original_fills = self.store.list_fills()
        self.broker.fills[0] = replace(self.broker.fills[0], **changes)
        self.restart()
        result = self.recover_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.OWNERSHIP_CONFLICT)
        self.assertEqual(self.store.list_fills(), original_fills)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.02"))

    def test_conflicting_duplicate_execution_quantity_halts_without_overwrite(self):
        self.conflicting_fill(executed_quantity=D("0.03"))

    def test_conflicting_duplicate_execution_price_halts_without_overwrite(self):
        self.conflicting_fill(execution_price=D("101"))

    def test_conflicting_duplicate_execution_fee_halts_without_overwrite(self):
        self.conflicting_fill(execution_fee=D("0.001"))

    def test_conflicting_duplicate_execution_identity_halts_without_adoption(self):
        self.conflicting_fill(order_link_id="bot1-unrecorded")

    def test_conflicting_duplicate_execution_fee_currency_halts_without_overwrite(self):
        self.conflicting_fill(fee_currency="USDT")

    def test_crash_g_already_durable_unknown_recovers_original_open_order(self):
        self.bootstrap()
        self.session.errors["place_order"] = TimeoutError("Synthetic lost response")
        self.session.publish_on_error = True
        self.broker.status = OrderStatus.OPEN
        self.advance("110")
        initial = self.run_cycle()
        original = self.action(initial)
        self.assertIs(original.phase, ActionPhase.UNKNOWN_OUTCOME)
        cp = self.restart()
        self.assertIs(cp.snapshot.state, RuntimeState.STARTING)
        recovered = self.recover_cycle()
        self.assertIs(recovered.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertIs(self.assert_original(original).phase, ActionPhase.UNKNOWN_OUTCOME)

    def test_crash_h_terminal_commit_return_lost_keeps_durable_truth(self):
        self.bootstrap()
        self.advance("110")
        self.crash_action(ActionPhase.TERMINAL_CONFIRMED, committed=True)
        original, fills = self.store.list_actions()[0], self.store.list_fills()
        self.assertIs(original.phase, ActionPhase.TERMINAL_CONFIRMED)
        self.restart()
        result = self.recover_cycle()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertIsNone(result.checkpoint.snapshot.pending_action)
        self.assertEqual(result.new_execution_ids, ())
        self.assertEqual(self.store.list_fills(), fills)
        self.assertEqual(self.store.get_action(original.logical_action_id), original)

    def test_terminal_history_outside_execution_window_survives_real_cycle(self):
        result = self.entry()
        original, fills = self.action(result), self.store.list_fills()
        self.broker.fills.clear()
        self.restart()
        self.assertIs(self.recover_cycle().checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(self.store.list_fills(), fills)
        self.assertEqual(self.store.get_action(original.logical_action_id), original)

    def test_pending_opposite_desire_survives_without_queue_or_cancel(self):
        result = self.entry(status=OrderStatus.OPEN)
        self.advance("80")
        self.run_cycle()
        original = self.action(result)
        self.assertEqual(self.store.get_checkpoint().snapshot.desired_position, 0)
        self.restart()
        recovered = self.recover_cycle()
        self.assertIs(recovered.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(recovered.checkpoint.snapshot.desired_position, 0)
        self.assertEqual(recovered.checkpoint.snapshot.pending_action.logical_action_id, original.logical_action_id)
        self.assertEqual(len(self.store.list_actions()), 1)

    def test_rejected_graceful_stop_restores_halt_without_external_reads(self):
        self.bootstrap()
        self.session.raw_ack = {"retCode": 10001}
        self.advance("110")
        result = self.run_cycle()
        original = self.action(result)
        cp = result.checkpoint
        stopped = replace(cp, sequence=cp.sequence + 1,
                          snapshot=transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED)),
                          shutdown_at_ms=self.now_ms)
        self.store.save_checkpoint(stopped, expected_sequence=cp.sequence)
        self.restart()
        self.broker.calls.clear()
        self.assertIs(self.recover_cycle().checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertEqual(self.broker.calls, [])
        self.assertEqual(self.store.get_action(original.logical_action_id), original)

    def test_interrupted_bootstrap_and_backlog_keep_original_cutoffs(self):
        commit = self.store.commit_decision

        def interrupted(candle, *args, **kwargs):
            if candle.candle_open_ms == 11 * HOUR:
                raise RuntimeStoreError("Synthetic bootstrap death")
            return commit(candle, *args, **kwargs)

        with patch.object(self.store, "commit_decision", side_effect=interrupted), self.assertRaises(RuntimeStoreError):
            self.run_cycle()
        self.advance(*(["110"] * 6))
        self.restart()
        result = self.recover_cycle()
        self.assertEqual(result.checkpoint.bootstrap_until_ms, 49 * HOUR)
        self.assertEqual(result.checkpoint.replay_until_ms, 55 * HOUR)
        self.assertEqual(result.checkpoint.last_processed_candle_ms, 55 * HOUR)
        for index in range(50):
            self.assertIs(self.store.get_decision(index * HOUR).disposition, DecisionDisposition.BOOTSTRAP)
        for index in range(50, 56):
            self.assertIs(self.store.get_decision(index * HOUR).disposition, DecisionDisposition.REPLAY_ONLY)
        self.assertEqual(self.store.list_actions(), ())


class FrozenSchedulerRestartTests(CycleRestartCase):
    def recover_scheduler(self):
        clock = scheduler_fixtures.FakeClock(self.now_ms)
        stop = scheduler_fixtures.FakeStop(clock)

        def backoff(seconds):
            clock.advance(round(seconds * 1000))
            self.now_ms = clock.ms
            return False

        stop.steps = [backoff, backoff]
        with patch.object(self.order_adapter, "place_market_order", side_effect=AssertionError("Restart cannot resend")) as place, \
             patch.object(self.session, "place_order", side_effect=AssertionError("No placement")) as sdk_place, \
             patch.object(self.session, "cancel_order", side_effect=AssertionError("No cancellation")) as cancel:
            result = run_hourly_scheduler(self.store, self.market, self.broker, self.order_adapter, stop,
                                          utc_now=lambda: cycle_fixtures.utc(self.now_ms), monotonic=clock.monotonic)
        place.assert_not_called()
        sdk_place.assert_not_called()
        cancel.assert_not_called()
        self.assert_no_send()
        return result, stop

    def test_attempted_restart_scheduler_exhausts_original_budget_without_resend(self):
        original = self.crash_attempt_before_send()
        self.restart()
        result, stop = self.recover_scheduler()
        self.assertIs(result.exit_reason, SchedulerExit.HALTED)
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(stop.waits, [1.0, 2.0])
        self.assertEqual(self.assert_original(original).remaining_read_attempts, 0)
        self.assertIs(result.checkpoint.snapshot.reason, RuntimeReason.RECOVERY_EXHAUSTED)

    def test_unknown_restart_scheduler_uses_retained_budget_not_fresh_budget(self):
        self.bootstrap()
        self.session.errors["place_order"] = TimeoutError("Synthetic ambiguous send")
        self.advance("110")
        initial = self.run_cycle()
        original = self.action(initial)
        self.assertEqual(original.remaining_read_attempts, 2)
        self.restart()
        result, stop = self.recover_scheduler()
        self.assertIs(result.exit_reason, SchedulerExit.HALTED)
        self.assertEqual(result.cycle_count, 2)
        self.assertEqual(stop.waits, [1.0])
        self.assertEqual(self.assert_original(original).remaining_read_attempts, 0)

    def test_graceful_scheduler_shutdown_then_new_process_observes_pending_only(self):
        result = self.entry(status=OrderStatus.OPEN)
        original = self.action(result)
        clock = scheduler_fixtures.FakeClock(self.now_ms)
        stop = scheduler_fixtures.FakeStop(clock)
        stop.set()
        shutdown = run_hourly_scheduler(self.store, self.market, self.broker, self.order_adapter, stop,
                                        utc_now=lambda: cycle_fixtures.utc(self.now_ms), monotonic=clock.monotonic)
        self.assertEqual(shutdown.cycle_count, 0)
        self.assertIs(shutdown.checkpoint.snapshot.stopped_from, RuntimeState.ORDER_PENDING)
        self.restart()
        self.assertIsNone(self.store.get_checkpoint().shutdown_at_ms)
        self.assertIs(self.recover_cycle().checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assert_original(original)


class RestartBoundaryTests(unittest.TestCase):
    def test_exact_minimal_public_api(self):
        parameters = inspect.signature(prepare_process_restart).parameters
        self.assertEqual(list(parameters), ["store"])
        self.assertIs(parameters["store"].default, inspect.Parameter.empty)
        self.assertIs(inspect.signature(prepare_process_restart).return_annotation, RuntimeCheckpoint)
        self.assertTrue(issubclass(RestartRecoveryError, RuntimeError))
        self.assertEqual({name for name, value in vars(module).items()
                          if (inspect.isclass(value) or inspect.isfunction(value))
                          and value.__module__ == module.__name__}, {"RestartRecoveryError", "prepare_process_restart"})

    def test_invalid_store_input_has_fixed_safe_error(self):
        for value in (None, {}, "synthetic-private-input", object(), True):
            with self.subTest(kind=type(value).__name__), self.assertRaises(RestartRecoveryError) as caught:
                prepare_process_restart(value)
            self.assertNotIn("synthetic-private", str(caught.exception))

    def test_source_imports_only_dataclasses_state_and_store(self):
        tree = ast.parse(inspect.getsource(module))
        self.assertEqual({node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)},
                         {"dataclasses", "state", "store"})
        self.assertFalse(any(isinstance(node, ast.Import) for node in ast.walk(tree)))

    def test_source_uses_only_public_checkpoint_operations_without_loop_or_io(self):
        tree = ast.parse(inspect.getsource(module))
        store_calls = []
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.For, ast.While, ast.AsyncFunctionDef, ast.Await, ast.With, ast.Try))
            if isinstance(node, ast.Attribute):
                self.assertFalse(node.attr.startswith("_"))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertIsInstance(node.func.value, ast.Name)
                self.assertEqual(node.func.value.id, "store")
                store_calls.append(node.func.attr)
        self.assertCountEqual(store_calls, ["get_checkpoint", "save_checkpoint"])
        self.assertNotIn("PROCESS_RESTARTED", inspect.getsource(module))

    def test_frozen_runtime_sources_match_approved_baseline(self):
        # Literal frozen SHA256 values; only reconciliation includes the
        # owner-approved read-failure correction. Not runtime constants.
        expected = {
            "state": "014b92aca145d61a57df230d3c3747025768090d2b96cdeaa97a96e5ad2675bc",
            "store": "cd64f38fe3c695617bd8bf90ba82d80fa20ceaca28727eecc76bd0b7c95929d2",
            "locking": "b10c5a8ac5e4ed4b8a7616b656602319c4e238eb0d2404fc2d31e6d636048273",
            "reconciliation": "2c9386a5f4e3670144722e53202f869c8b7ce6e67ce963342a45bbf6f9ef0bb9",
            "planner": "e97b0f9c709e909c56f132cfd5a718a3fbb8a488debb0c71823415adb0605686",
            "cycle": "1bb6df969546392c75bc9d7091d6cf8c7fa9ca102042171b5ede3ccf52b90db3",
            "scheduler": "f588124296a4442ab0c969ae55202d991ee1e003d500a5aa3f373f03d074608d",
            "__init__": "8843b5105846f5386e9ac799f06b8446688043482618cbb8d3fc5a6655f40b60",
        }
        directory = Path(module.__file__).parent
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((directory / (name + ".py")).read_bytes()).hexdigest(), digest)


if __name__ == "__main__":
    unittest.main()
