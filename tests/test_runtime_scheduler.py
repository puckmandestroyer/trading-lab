"""Offline clock/event control, durable shutdown and frozen-cycle integration."""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import inspect
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock, patch

import requests

from trading_lab.runtime.cycle import CycleError, CycleOutcome, SingleCycleResult
from trading_lab.runtime.scheduler import SchedulerError, SchedulerExit, SchedulerResult, run_hourly_scheduler
import trading_lab.runtime.scheduler as module
from trading_lab.runtime.state import (
    PositionEvidence, RuntimeEvent, RuntimeEventType, RuntimeReason, RuntimeState,
    RuntimeStateSnapshot, transition_runtime_state,
)
from trading_lab.runtime.store import ActionPhase, RuntimeStoreError
from tests.test_runtime_store import StoreCase, HOUR, fill
from tests.test_runtime_cycle import CycleCase, utc


class FakeClock:
    def __init__(self, ms=12 * HOUR + 37 * 60_000):
        self.ms, self.elapsed = ms, 0.0

    def utc(self):
        return utc(self.ms)

    def monotonic(self):
        return self.elapsed

    def advance(self, milliseconds):
        self.ms += milliseconds
        self.elapsed += milliseconds / 1000


class FakeStop:
    """Scripted event; exhausted scripts request stop, never use real sleep."""

    def __init__(self, clock):
        self.clock, self.flag, self.waits, self.steps = clock, False, [], []

    def is_set(self):
        return self.flag

    def set(self):
        self.flag = True

    def wait(self, seconds):
        self.waits.append(seconds)
        if self.steps:
            return self.steps.pop(0)(seconds)
        self.set()
        return True

    def elapsed_wait(self, seconds):
        self.clock.advance(round(seconds * 1000))
        return False


class SchedulerCase(StoreCase):
    def setUp(self):
        super().setUp()
        self.clock = FakeClock()
        self.stop = FakeStop(self.clock)
        self.market, self.broker, self.adapter = Mock(spec=[]), Mock(spec=[]), Mock(spec=[])
        self.effects, self.times, self.active = [], [], False
        self.enterContext(patch.object(requests.Session, "send", side_effect=AssertionError("No broker network")))
        self.enterContext(patch("socket.create_connection", side_effect=AssertionError("No broker network")))
        self.enterContext(patch("time.sleep", side_effect=AssertionError("Only event waiting")))

    def result(self, outcome=CycleOutcome.NOOP, reason=None):
        return SingleCycleResult(self.store.get_checkpoint(), outcome, reason=reason)

    def fake_cycle(self, *args, **kwargs):
        self.assertFalse(self.active, "Cycles must never overlap")
        self.assertFalse(self.store._connection.in_transaction)
        self.active = True
        self.times.append(self.clock.ms)
        try:
            effect = self.effects.pop(0) if self.effects else lambda: self.result()
            return effect()
        finally:
            self.active = False

    def run_scheduler(self, **kwargs):
        with patch.object(module, "run_single_cycle", side_effect=self.fake_cycle) as cycle:
            self.cycle = cycle
            return run_hourly_scheduler(self.store, self.market, self.broker, self.adapter, self.stop,
                                        utc_now=kwargs.get("utc_now", self.clock.utc),
                                        monotonic=kwargs.get("monotonic", self.clock.monotonic))

    def transient(self, outcome=CycleOutcome.WAIT, reason=RuntimeReason.EVIDENCE_MISSING):
        return lambda: self.result(outcome, reason)

    def state(self, state):
        if state == RuntimeState.ORDER_PENDING:
            self.prepare()
        elif state == RuntimeState.LONG:
            self.settle(self.acknowledge(), fill())
        elif state == RuntimeState.FLAT:
            self.flat()
        elif state == RuntimeState.UNCERTAIN:
            self.attempt()
            cp = self.store.get_checkpoint()
            action = replace(self.store.list_actions()[0], phase=ActionPhase.UNKNOWN_OUTCOME,
                             safe_reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN)
            snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.UNCERTAINTY_DETECTED,
                                                                          reason=RuntimeReason.ACTION_OUTCOME_UNKNOWN))
            self.store.record_observation(action, replace(cp, sequence=cp.sequence + 1, snapshot=snapshot),
                                          expected_sequence=cp.sequence)
        elif state == RuntimeState.HALTED:
            cp = self.store.get_checkpoint()
            snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.FATAL_INCONSISTENCY,
                                                                          reason=RuntimeReason.OWNERSHIP_CONFLICT))
            self.store.save_checkpoint(replace(cp, sequence=cp.sequence + 1, snapshot=snapshot, halted_at_ms=self.clock.ms),
                                       expected_sequence=cp.sequence)


class HourlyWakeTests(SchedulerCase):
    def test_startup_is_immediate_and_reserves_next_absolute_hour(self):
        result = self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000])
        self.assertEqual(self.stop.waits, [23 * 60.0])
        self.assertEqual((result.cycle_count, result.wake_count), (1, 0))

    def test_exact_boundary_executes_one_scheduled_batch(self):
        self.stop.steps = [self.stop.elapsed_wait]
        result = self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000, 13 * HOUR])
        self.assertEqual(self.stop.waits, [1380.0, 3600.0])
        self.assertEqual((result.cycle_count, result.wake_count), (2, 1))

    def test_starting_at_exact_hour_targets_following_hour(self):
        self.clock.ms = 12 * HOUR
        self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR])
        self.assertEqual(self.stop.waits, [3600.0])

    def test_crossed_startup_boundary_is_due_without_sleep(self):
        self.clock.ms = 13 * HOUR - 100

        def crossing():
            self.clock.advance(1100)
            self.assertEqual(self.stop.waits, [])
            return self.result()

        self.effects = [crossing]
        result = self.run_scheduler()
        self.assertEqual(self.times, [13 * HOUR - 100, 13 * HOUR + 1000])
        self.assertEqual(self.stop.waits, [3599.0])
        self.assertEqual(result.wake_count, 1)

    def test_multiple_missed_startup_hours_get_one_catch_up_batch(self):
        def long_cycle():
            self.clock.advance(4 * HOUR)
            return self.result()

        self.effects = [long_cycle]
        result = self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000, 16 * HOUR + 37 * 60_000])
        self.assertEqual(result.wake_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])

    def test_long_scheduled_batch_jumps_directly_to_first_future_hour(self):
        def long_cycle():
            self.clock.advance(4 * HOUR + 5000)
            return self.result()

        self.effects = [lambda: self.result(), long_cycle]
        self.stop.steps = [self.stop.elapsed_wait]
        result = self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000, 13 * HOUR])
        self.assertEqual(result.wake_count, 1)
        self.assertEqual(self.stop.waits, [1380.0, 3595.0])

    def test_cycle_latency_does_not_shift_hourly_grid(self):
        def latency():
            self.clock.advance(5000)
            return self.result()

        self.effects = [latency, latency, latency]
        self.stop.steps = [self.stop.elapsed_wait, self.stop.elapsed_wait]
        result = self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000, 13 * HOUR, 14 * HOUR])
        self.assertEqual(self.stop.waits, [1375.0, 3595.0, 3595.0])
        self.assertEqual(result.wake_count, 2)

    def test_spurious_boundary_wake_waits_remaining_utc_time(self):
        def early(seconds):
            self.clock.advance(1000)
            return False

        self.stop.steps = [early, self.stop.elapsed_wait]
        self.run_scheduler()
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000, 13 * HOUR])
        self.assertEqual(self.stop.waits, [1380.0, 1379.0, 3600.0])

    def test_midnight_uses_elapsed_utc_grid(self):
        self.clock.ms = 24 * HOUR - 1000
        self.stop.steps = [self.stop.elapsed_wait]
        self.run_scheduler()
        self.assertEqual(self.times, [24 * HOUR - 1000, 24 * HOUR])
        self.assertEqual(self.stop.waits, [1.0, 3600.0])


class RetryTests(SchedulerCase):
    def test_startup_safe_sequence_uses_one_second_then_two_second_backoff(self):
        self.effects = [self.transient(), self.transient(CycleOutcome.RECONCILE), lambda: self.result()]
        self.stop.steps = [self.stop.elapsed_wait, self.stop.elapsed_wait]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(self.stop.waits, [1.0, 2.0, 1377.0])
        self.assertEqual(result.wake_count, 0)
        self.assertIs(result.last_cycle.outcome, CycleOutcome.NOOP)

    def test_three_transient_attempts_end_batch_without_attempt_four(self):
        self.effects = [self.transient()] * 3
        self.stop.steps = [self.stop.elapsed_wait, self.stop.elapsed_wait]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(self.stop.waits, [1.0, 2.0, 1377.0])

    def test_scheduled_wake_gets_its_own_bounded_batch(self):
        self.effects = [lambda: self.result(), self.transient(), self.transient(), self.transient()]
        self.stop.steps = [self.stop.elapsed_wait] * 3
        result = self.run_scheduler()
        self.assertEqual((result.cycle_count, result.wake_count), (4, 1))
        self.assertEqual(self.stop.waits, [1380.0, 1.0, 2.0, 3597.0])

    def test_existing_uncertain_read_outcome_unknown_allows_bounded_retry(self):
        self.state(RuntimeState.UNCERTAIN)
        self.effects = [self.transient(CycleOutcome.RECONCILE, RuntimeReason.ACTION_OUTCOME_UNKNOWN)] * 3
        self.stop.steps = [self.stop.elapsed_wait] * 2
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(self.stop.waits[:2], [1.0, 2.0])
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.UNCERTAIN)

    def test_no_new_data_with_transient_reason_can_retry(self):
        self.effects = [self.transient(CycleOutcome.NO_NEW_DATA), lambda: self.result()]
        self.stop.steps = [self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1.0, 1379.0])

    def test_pending_wait_without_transient_reason_never_polls(self):
        self.state(RuntimeState.ORDER_PENDING)
        self.effects = [lambda: self.result(CycleOutcome.WAIT)]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])

    def test_no_new_data_without_reason_is_not_retried(self):
        self.effects = [lambda: self.result(CycleOutcome.NO_NEW_DATA)]
        self.assertEqual(self.run_scheduler().cycle_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])

    def test_observed_uncertainty_does_not_extend_post_send_reconciliation(self):
        self.state(RuntimeState.UNCERTAIN)
        self.effects = [lambda: self.result(CycleOutcome.OBSERVED, RuntimeReason.ACTION_OUTCOME_UNKNOWN)]
        self.assertEqual(self.run_scheduler().cycle_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])

    def test_abandoned_unsent_is_never_immediately_retried(self):
        self.effects = [lambda: self.result(CycleOutcome.ABANDONED_UNSENT, RuntimeReason.EVIDENCE_MISSING)]
        self.assertEqual(self.run_scheduler().cycle_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])

    def assert_not_retried(self, outcome, reason):
        self.effects = [lambda: self.result(outcome, reason)]
        self.assertEqual(self.run_scheduler().cycle_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])

    def test_bootstrap_never_retries_even_with_transient_reason(self):
        self.assert_not_retried(CycleOutcome.BOOTSTRAP, RuntimeReason.EVIDENCE_MISSING)

    def test_replay_only_never_retries_even_with_transient_reason(self):
        self.assert_not_retried(CycleOutcome.REPLAY_ONLY, RuntimeReason.EVIDENCE_MISSING)

    def test_noop_never_retries_even_with_transient_reason(self):
        self.assert_not_retried(CycleOutcome.NOOP, RuntimeReason.EVIDENCE_MISSING)

    def test_configuration_reason_never_retries(self):
        self.assert_not_retried(CycleOutcome.RECONCILE, RuntimeReason.INVALID_CONFIGURATION)

    def test_ownership_conflict_never_retries(self):
        self.assert_not_retried(CycleOutcome.RECONCILE, RuntimeReason.OWNERSHIP_CONFLICT)

    def test_integrity_reason_never_retries(self):
        self.assert_not_retried(CycleOutcome.RECONCILE, RuntimeReason.INCONSISTENT_EVIDENCE)

    def test_exhausted_recovery_never_retries(self):
        self.assert_not_retried(CycleOutcome.RECONCILE, RuntimeReason.RECOVERY_EXHAUSTED)

    def test_elapsed_budget_blocks_backoff_that_would_exceed_it(self):
        def slow():
            self.clock.advance(self.config.reconciliation_timeout_ms - 500)
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [slow]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 1)
        self.assertEqual(self.stop.waits, [780.5])

    def test_elapsed_budget_is_not_reset_between_attempts(self):
        def slow():
            self.clock.advance(self.config.reconciliation_timeout_ms - 2500)
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [slow, self.transient()]
        self.stop.steps = [self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1.0, 781.5])

    def test_wait_overshoot_exhausts_elapsed_budget_before_retry(self):
        def overshoot(seconds):
            self.clock.advance(self.config.reconciliation_timeout_ms + 1)
            return False

        self.effects = [self.transient()]
        self.stop.steps = [overshoot]
        self.assertEqual(self.run_scheduler().cycle_count, 1)
        self.assertEqual(self.stop.waits, [1.0, 779.999])

    def test_scheduled_decision_age_ends_retries(self):
        def stale():
            self.clock.advance(self.config.decision_max_age_ms + 1)
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [lambda: self.result(), stale]
        self.stop.steps = [self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1380.0, 3539.999])

    def test_decision_age_includes_upcoming_backoff(self):
        def nearly_stale():
            self.clock.advance(self.config.decision_max_age_ms - 500)
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [lambda: self.result(), nearly_stale]
        self.stop.steps = [self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1380.0, 3540.5])

    def test_scheduled_retry_at_exact_decision_age_limit_is_allowed(self):
        def delayed():
            self.clock.advance(self.config.decision_max_age_ms - 1000)
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [lambda: self.result(), delayed, lambda: self.result()]
        self.stop.steps = [self.stop.elapsed_wait] * 2
        self.assertEqual(self.run_scheduler().cycle_count, 3)
        self.assertEqual(self.times[-1], 13 * HOUR + self.config.decision_max_age_ms)
        self.assertEqual(self.stop.waits, [1380.0, 1.0, 3540.0])

    def test_scheduled_backoff_overshoot_checks_decision_age_before_retry(self):
        def overshoot(seconds):
            self.clock.advance(self.config.decision_max_age_ms + 1)
            return False

        self.effects = [lambda: self.result(), self.transient()]
        self.stop.steps = [self.stop.elapsed_wait, overshoot]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1380.0, 1.0, 3539.999])

    def test_retry_may_start_at_exact_elapsed_budget_but_not_beyond(self):
        def delayed():
            self.clock.advance(self.config.reconciliation_timeout_ms - 1000)
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [delayed, lambda: self.result()]
        self.stop.steps = [self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1.0, 780.0])

    def test_spurious_backoff_wake_cannot_retry_before_delay(self):
        def early(seconds):
            self.clock.advance(250)
            return False

        self.effects = [self.transient(), lambda: self.result()]
        self.stop.steps = [early, self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.times, [12 * HOUR + 37 * 60_000, 12 * HOUR + 37 * 60_000 + 1000])
        self.assertEqual(self.stop.waits, [1.0, 0.75, 1379.0])


class ExceptionTests(SchedulerCase):
    def assert_cycle_exception(self, error):
        def fail():
            self.stop.set()  # Even a concurrent stop cannot license cleanup writes.
            raise error

        self.effects = [fail]
        with patch.object(self.store, "save_checkpoint") as save, \
             patch.object(self.store, "close") as close, patch.object(self.lock, "release") as release, \
             self.assertRaises(type(error)) as caught:
            self.run_scheduler()
        self.assertIs(caught.exception, error)
        self.cycle.assert_called_once()
        save.assert_not_called()
        close.assert_not_called()
        release.assert_not_called()
        self.assertEqual(self.stop.waits, [])

    def test_store_exception_propagates_without_retry_or_shutdown_write(self):
        self.assert_cycle_exception(RuntimeStoreError("Synthetic indeterminate commit"))

    def test_cycle_exception_propagates_without_retry_or_shutdown_write(self):
        self.assert_cycle_exception(CycleError("Synthetic cycle error"))

    def test_unexpected_exception_propagates_unchanged(self):
        self.assert_cycle_exception(LookupError("Synthetic unexpected error"))

    def test_exception_on_retry_stops_before_next_wait_or_shutdown(self):
        error = RuntimeStoreError("Synthetic retry fault")
        self.effects = [self.transient(), lambda: (_ for _ in ()).throw(error)]
        self.stop.steps = [self.stop.elapsed_wait]
        with patch.object(self.store, "save_checkpoint") as save, self.assertRaises(RuntimeStoreError) as caught:
            self.run_scheduler()
        self.assertIs(caught.exception, error)
        self.assertEqual(self.cycle.call_count, 2)
        self.assertEqual(self.stop.waits, [1.0])
        save.assert_not_called()


class ShutdownTests(SchedulerCase):
    def assert_shutdown_state(self, state):
        self.state(state)
        before = self.store.get_checkpoint()
        self.stop.set()
        with patch.object(self.store, "save_checkpoint", wraps=self.store.save_checkpoint) as save:
            result = self.run_scheduler()
        save.assert_called_once()
        self.cycle.assert_not_called()
        expected = replace(before, sequence=before.sequence + 1,
                           snapshot=transition_runtime_state(before.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED)),
                           shutdown_at_ms=self.clock.ms)
        self.assertEqual(result.checkpoint, expected)
        self.assertEqual(self.store.get_checkpoint(), expected)
        self.assertIs(result.exit_reason, SchedulerExit.STOP_REQUESTED)
        self.assertEqual((result.cycle_count, result.wake_count, result.last_cycle), (0, 0, None))
        self.assertEqual(result.checkpoint.snapshot.pending_action, before.snapshot.pending_action)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, before.snapshot.owned_base_quantity)
        self.assertEqual(result.checkpoint.snapshot.reason, before.snapshot.reason)
        self.assertEqual(result.checkpoint.snapshot.desired_position, before.snapshot.desired_position)
        self.assertIs(result.checkpoint.snapshot.position_evidence,
                      PositionEvidence.UNKNOWN if before.snapshot.owned_base_quantity is None else PositionEvidence.LAST_KNOWN)
        self.assertEqual(result.checkpoint.halted_at_ms, before.halted_at_ms)
        self.assertIs(result.checkpoint.snapshot.stopped_from, state)
        self.assertEqual(save.call_args.kwargs, {"expected_sequence": before.sequence})

    def test_stop_before_starting_cycle_preserves_unknown_quantity(self):
        self.assert_shutdown_state(RuntimeState.STARTING)

    def test_shutdown_preserves_flat(self):
        self.assert_shutdown_state(RuntimeState.FLAT)

    def test_shutdown_preserves_long_exact_quantity(self):
        self.assert_shutdown_state(RuntimeState.LONG)

    def test_shutdown_preserves_pending_logical_action(self):
        self.assert_shutdown_state(RuntimeState.ORDER_PENDING)

    def test_shutdown_preserves_uncertain_reason_and_action(self):
        self.assert_shutdown_state(RuntimeState.UNCERTAIN)

    def test_shutdown_preserves_halt_reason_time_and_latch(self):
        self.assert_shutdown_state(RuntimeState.HALTED)

    def test_already_stopping_exits_without_cycle_clock_wait_or_write(self):
        cp = self.store.get_checkpoint()
        proposed = replace(cp, sequence=cp.sequence + 1,
                           snapshot=transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED)),
                           shutdown_at_ms=self.clock.ms)
        self.store.save_checkpoint(proposed, expected_sequence=cp.sequence)
        with patch.object(self.store, "save_checkpoint") as save:
            result = self.run_scheduler(utc_now=Mock(side_effect=AssertionError("No clock needed")))
        self.cycle.assert_not_called()
        save.assert_not_called()
        self.assertIs(result.exit_reason, SchedulerExit.STOPPING)
        self.assertEqual(result.checkpoint, proposed)
        self.assertEqual(self.stop.waits, [])

    def test_stop_already_stopping_does_not_repeat_transition(self):
        self.stop.set()
        first = self.run_scheduler()
        with patch.object(self.store, "save_checkpoint") as save:
            second = self.run_scheduler()
        save.assert_not_called()
        self.assertEqual(second.checkpoint, first.checkpoint)
        self.assertIs(second.exit_reason, SchedulerExit.STOP_REQUESTED)

    def test_stop_during_boundary_wait_prevents_next_cycle(self):
        self.stop.steps = [lambda seconds: (self.clock.advance(1000), self.stop.set(), True)[-1]]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 1)
        self.assertEqual(result.checkpoint.shutdown_at_ms, 12 * HOUR + 37 * 60_000 + 1000)

    def test_stop_during_first_backoff_prevents_retry(self):
        self.effects = [self.transient()]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 1)
        self.assertEqual(self.stop.waits, [1.0])

    def test_stop_during_second_backoff_prevents_third_attempt(self):
        self.effects = [self.transient()] * 2
        self.stop.steps = [self.stop.elapsed_wait]
        self.assertEqual(self.run_scheduler().cycle_count, 2)
        self.assertEqual(self.stop.waits, [1.0, 2.0])

    def test_stop_during_normally_returning_cycle_saves_before_any_wait(self):
        def finish_with_stop():
            self.stop.set()
            return self.result(CycleOutcome.WAIT, RuntimeReason.EVIDENCE_MISSING)

        self.effects = [finish_with_stop]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 1)
        self.assertEqual(self.stop.waits, [])
        self.assertIs(result.exit_reason, SchedulerExit.STOP_REQUESTED)

    def test_halted_cycle_exits_without_stop_write_or_rearm(self):
        def halt():
            self.state(RuntimeState.HALTED)
            return self.result(CycleOutcome.HALTED)

        self.effects = [halt]
        result = self.run_scheduler()
        self.assertEqual(result.cycle_count, 1)
        self.assertIs(result.exit_reason, SchedulerExit.HALTED)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIsNone(result.checkpoint.shutdown_at_ms)
        self.assertEqual(self.stop.waits, [])

    def test_stopping_cycle_exits_without_second_transition(self):
        def stop():
            cp = self.store.get_checkpoint()
            snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.SHUTDOWN_REQUESTED))
            self.store.save_checkpoint(replace(cp, sequence=cp.sequence + 1, snapshot=snapshot, shutdown_at_ms=self.clock.ms),
                                       expected_sequence=cp.sequence)
            return self.result(CycleOutcome.STOPPING)

        self.effects = [stop]
        result = self.run_scheduler()
        self.assertIs(result.exit_reason, SchedulerExit.STOPPING)
        self.assertEqual(result.checkpoint.sequence, 1)
        self.assertEqual(self.stop.waits, [])

    def test_reported_halt_also_stops_scheduling_without_shutdown(self):
        self.effects = [lambda: self.result(CycleOutcome.HALTED)]
        with patch.object(self.store, "save_checkpoint") as save:
            result = self.run_scheduler()
        self.assertIs(result.exit_reason, SchedulerExit.HALTED)
        self.cycle.assert_called_once()
        save.assert_not_called()
        self.assertEqual(self.stop.waits, [])

    def test_reported_stopping_also_exits_without_another_transition(self):
        self.effects = [lambda: self.result(CycleOutcome.STOPPING)]
        with patch.object(self.store, "save_checkpoint") as save:
            result = self.run_scheduler()
        self.assertIs(result.exit_reason, SchedulerExit.STOPPING)
        self.cycle.assert_called_once()
        save.assert_not_called()
        self.assertEqual(self.stop.waits, [])

    def test_shutdown_commit_failure_propagates_without_cycle_or_cleanup(self):
        self.stop.set()
        error = RuntimeStoreError("Synthetic shutdown failure")
        with patch.object(self.store, "save_checkpoint", side_effect=error) as save, self.assertRaises(RuntimeStoreError) as caught:
            self.run_scheduler()
        self.assertIs(caught.exception, error)
        save.assert_called_once()
        self.cycle.assert_not_called()


class ClockAndInputTests(SchedulerCase):
    def test_utc_clock_uses_integer_microsecond_floor(self):
        self.assertEqual(module._milliseconds(utc(HOUR) + timedelta(microseconds=999)), HOUR)
        self.assertEqual(module._milliseconds(utc(0)), 0)

    def test_invalid_utc_clock_fails_before_first_cycle_or_write(self):
        for value in (None, 1.0, datetime(2026, 1, 1), utc(-1),
                      datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=9)))):
            with self.subTest(type=type(value).__name__), patch.object(self.store, "save_checkpoint") as save, \
                 self.assertRaises(SchedulerError):
                self.run_scheduler(utc_now=lambda: value)
            self.cycle.assert_not_called()
            save.assert_not_called()

    def test_utc_regression_during_wait_stops_without_new_cycle_or_write(self):
        def regress(seconds):
            self.clock.ms -= 1
            return False

        self.stop.steps = [regress]
        with patch.object(self.store, "save_checkpoint") as save, self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()
        save.assert_not_called()
        self.assertTrue(all(seconds > 0 for seconds in self.stop.waits))

    def test_invalid_monotonic_values_fail_before_cycle(self):
        for value in (True, None, "1", float("nan"), float("inf"), -float("inf"), complex(1), 10**400):
            with self.subTest(type=type(value).__name__), self.assertRaises(SchedulerError):
                self.run_scheduler(monotonic=lambda: value)
            self.cycle.assert_not_called()

    def test_monotonic_regression_in_retry_accounting_stops_without_write(self):
        def regress(seconds):
            self.clock.elapsed -= 1
            return False

        self.effects = [self.transient()]
        self.stop.steps = [regress]
        with patch.object(self.store, "save_checkpoint") as save, self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()
        save.assert_not_called()

    def test_monotonic_regression_after_cycle_prevents_another_invocation(self):
        def regress():
            self.clock.elapsed -= 1
            return self.result()

        self.effects = [regress]
        with patch.object(self.store, "save_checkpoint") as save, self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()
        save.assert_not_called()

    def test_bad_stop_interface_fails_closed(self):
        for stop in (None, object(), Mock(spec=["is_set"]), Mock(spec=["wait"]),
                     type("BadStop", (), {"is_set": False, "wait": lambda self, seconds: False})()):
            with self.subTest(type=type(stop).__name__), patch.object(module, "run_single_cycle") as cycle, self.assertRaises(SchedulerError):
                run_hourly_scheduler(self.store, self.market, self.broker, self.adapter, stop,
                                     utc_now=self.clock.utc, monotonic=self.clock.monotonic)
            cycle.assert_not_called()

    def test_nonboolean_stop_state_is_rejected(self):
        with patch.object(self.stop, "is_set", return_value=1), self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_not_called()

    def test_nonboolean_wait_result_is_rejected_without_write(self):
        with patch.object(self.stop, "wait", return_value=1), patch.object(self.store, "save_checkpoint") as save, \
             self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()
        save.assert_not_called()

    def test_stop_interface_errors_have_fixed_safe_diagnostics(self):
        with patch.object(self.stop, "is_set", side_effect=ValueError("synthetic-private-stop")), self.assertRaises(SchedulerError) as caught:
            self.run_scheduler()
        self.assertNotIn("synthetic-private", str(caught.exception))

    def test_wait_interface_error_stops_without_write_and_hides_private_text(self):
        with patch.object(self.stop, "wait", side_effect=ValueError("synthetic-private-wait")), \
             patch.object(self.store, "save_checkpoint") as save, self.assertRaises(SchedulerError) as caught:
            self.run_scheduler()
        self.assertNotIn("synthetic-private", str(caught.exception))
        self.cycle.assert_called_once()
        save.assert_not_called()

    def test_invalid_monotonic_after_cycle_stops_before_wait_or_shutdown(self):
        def invalid():
            self.clock.elapsed = float("nan")
            return self.result()

        self.effects = [invalid]
        with patch.object(self.store, "save_checkpoint") as save, self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()
        save.assert_not_called()
        self.assertEqual(self.stop.waits, [])

    def test_clock_exceptions_have_fixed_safe_diagnostics(self):
        with self.assertRaises(SchedulerError) as caught:
            self.run_scheduler(utc_now=Mock(side_effect=ValueError("synthetic-private-clock")))
        self.assertNotIn("synthetic-private", str(caught.exception))
        self.cycle.assert_not_called()

    def test_standard_threading_event_is_structurally_compatible(self):
        event = threading.Event()
        event.set()
        with patch.object(module, "run_single_cycle") as cycle:
            result = run_hourly_scheduler(self.store, self.market, self.broker, self.adapter, event,
                                          utc_now=self.clock.utc, monotonic=self.clock.monotonic)
        cycle.assert_not_called()
        self.assertIs(result.exit_reason, SchedulerExit.STOP_REQUESTED)

    def test_malformed_cycle_control_result_stops_without_retry_or_shutdown(self):
        self.effects = [lambda: {"outcome": "WAIT"}]
        with patch.object(self.store, "save_checkpoint") as save, self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()
        save.assert_not_called()

    def test_cycle_result_must_match_durable_checkpoint(self):
        self.effects = [lambda: replace(self.result(), checkpoint=replace(self.store.get_checkpoint(), sequence=99))]
        with self.assertRaises(SchedulerError):
            self.run_scheduler()
        self.cycle.assert_called_once()


class PublicAndStructuralTests(SchedulerCase):
    def test_frozen_runtime_sources_and_package_match_published_baseline(self):
        # Literal SHA256 values from published 728bf6d, not runtime constants.
        expected = {
            "cycle": "d1a8b92b042d10402ef5bdc80b58edc62415a5a69cef7c99a27174311d890bc4",
            "state": "014b92aca145d61a57df230d3c3747025768090d2b96cdeaa97a96e5ad2675bc",
            "store": "e71ac3cf7dd7c607b78e3fc30e6c43c7320c27d83ca5c1389cac4259790a26b5",
            "locking": "b10c5a8ac5e4ed4b8a7616b656602319c4e238eb0d2404fc2d31e6d636048273",
            "reconciliation": "14c9e1a8e60ba7f35eb4d33f63b2f8a517068dbb6f1d87a04bdeab6f349178d0",
            "planner": "e97b0f9c709e909c56f132cfd5a718a3fbb8a488debb0c71823415adb0605686",
            "__init__": "8843b5105846f5386e9ac799f06b8446688043482618cbb8d3fc5a6655f40b60",
        }
        directory = Path(module.__file__).parent
        for name, digest in expected.items():
            self.assertEqual(hashlib.sha256((directory / (name + ".py")).read_bytes()).hexdigest(), digest)

    def test_exact_public_api_and_no_test_only_bounds(self):
        parameters = inspect.signature(run_hourly_scheduler).parameters
        self.assertEqual(list(parameters), ["store", "market_reader", "broker", "order_adapter", "stop_signal", "utc_now", "monotonic"])
        self.assertIs(parameters["utc_now"].kind, inspect.Parameter.KEYWORD_ONLY)
        self.assertIs(parameters["utc_now"].default, inspect.Parameter.empty)
        self.assertTrue(issubclass(SchedulerError, RuntimeError))
        self.assertEqual([exit.value for exit in SchedulerExit], ["STOP_REQUESTED", "HALTED", "STOPPING"])

    def test_result_is_frozen_slotted_and_only_normalized_control_fields(self):
        result = self.run_scheduler()
        self.assertIs(type(result), SchedulerResult)
        self.assertFalse(hasattr(result, "__dict__"))
        self.assertEqual({field.name for field in fields(result)}, {"checkpoint", "exit_reason", "cycle_count", "wake_count", "last_cycle"})
        with self.assertRaises(FrozenInstanceError):
            result.cycle_count = 999

    def test_exact_resources_and_clocks_forwarded_to_every_serialized_cycle(self):
        utc_now, monotonic = self.clock.utc, self.clock.monotonic
        self.effects = [self.transient(), self.transient(), lambda: self.result()]
        self.stop.steps = [self.stop.elapsed_wait] * 2
        self.run_scheduler(utc_now=utc_now, monotonic=monotonic)
        for call in self.cycle.call_args_list:
            self.assertEqual(call.args, (self.store, self.market, self.broker, self.adapter))
            self.assertIs(call.kwargs["utc_now"], utc_now)
            self.assertIs(call.kwargs["monotonic"], monotonic)
        self.assertFalse(self.active)

    def test_waits_and_shutdown_do_not_close_or_release_resources(self):
        with patch.object(self.store, "close") as close, patch.object(self.lock, "release") as release:
            self.run_scheduler()
        close.assert_not_called()
        release.assert_not_called()
        self.assertEqual(self.market.mock_calls, [])
        self.assertEqual(self.broker.mock_calls, [])
        self.assertEqual(self.adapter.mock_calls, [])

    def test_ast_excludes_concurrency_direct_io_actions_and_recovery(self):
        tree = ast.parse(inspect.getsource(module))
        imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
        imports.update(alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names)
        self.assertEqual(imports, {"collections.abc", "dataclasses", "datetime", "enum", "math", "numbers", "time",
                                   "exchange.account_state", "exchange.bybit_demo_orders", "cycle", "state", "store"})
        allowed_attributes = {"get_configuration", "get_checkpoint", "save_checkpoint", "is_set", "wait", "utcoffset", "isfinite"}
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, (ast.AsyncFunctionDef, ast.Await, ast.TryStar))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                self.assertIn(node.func.attr, allowed_attributes)
            if isinstance(node, ast.Attribute):
                self.assertFalse(node.attr.startswith("_"))
                self.assertNotIn(node.attr, {"now", "timestamp", "environ", "sleep", "ActionPhase", "ActionRecord",
                                             "get_order", "get_executions", "cancel_order", "place_market_order", "list_actions", "list_fills"})
            if isinstance(node, ast.Try):
                self.assertEqual(node.finalbody, [])
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                self.assertFalse(any(isinstance(child, ast.Call) and isinstance(child.func, ast.Name)
                                     and child.func.id == "run_single_cycle" for child in ast.walk(node)))


class FrozenCycleIntegrationTests(CycleCase):
    def test_scheduler_runs_real_bootstrap_and_one_future_cycle_offline(self):
        clock = FakeClock(self.now_ms)
        stop = FakeStop(clock)

        def hour(seconds):
            clock.advance(round(seconds * 1000))
            self.now_ms = clock.ms
            self.prices.append("110")
            return False

        stop.steps = [hour]
        with patch.object(module, "run_single_cycle", wraps=module.run_single_cycle) as cycle:
            result = run_hourly_scheduler(self.store, self.market, self.broker, self.order_adapter, stop,
                                          utc_now=lambda: utc(self.now_ms), monotonic=lambda: clock.elapsed)
        self.assertEqual((result.cycle_count, result.wake_count), (2, 1))
        self.assertEqual(cycle.call_count, 2)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(sum(name == "place_order" for name, _ in self.session.calls), 1)
        self.assertIs(result.last_cycle.outcome, CycleOutcome.OBSERVED)
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, Decimal("0.05"))
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))

    def test_real_read_deficiencies_get_three_bounded_cycles_without_actions(self):
        clock = FakeClock(self.now_ms)
        stop = FakeStop(clock)
        self.broker.errors["account"] = TimeoutError("Synthetic read deficiency")

        def backoff(seconds):
            clock.advance(round(seconds * 1000))
            self.now_ms = clock.ms
            return False

        stop.steps = [backoff, backoff]
        result = run_hourly_scheduler(self.store, self.market, self.broker, self.order_adapter, stop,
                                      utc_now=lambda: utc(self.now_ms), monotonic=lambda: clock.elapsed)
        self.assertEqual(result.cycle_count, 3)
        self.assertEqual(stop.waits[:2], [1.0, 2.0])
        self.assertIs(result.checkpoint.snapshot.stopped_from, RuntimeState.UNCERTAIN)
        self.assertEqual(self.market.calls, [])
        self.assert_no_send()


if __name__ == "__main__":
    unittest.main()
