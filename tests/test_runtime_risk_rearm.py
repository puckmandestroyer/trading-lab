"""Decision 021 controls: exact pure facts and real temporary SQLite commits.

Low-level fixtures exercise local persistence with explicit synthetic evidence;
integration fixtures additionally run the unchanged strategy/cycle/reconciler.
No credentials, real journals or network resources are used.
"""

import ast
from dataclasses import FrozenInstanceError, fields, replace
from decimal import Decimal as D, Inexact, Rounded, ROUND_UP, localcontext
import hashlib
import inspect
import json
import sqlite3
from textwrap import dedent
import unittest
from unittest.mock import patch

import trading_lab.risk.runtime_risk as risk
import trading_lab.runtime.store as persistence
from trading_lab.runtime.planner import CanonicalDecision, DecisionMode, plan_action
from trading_lab.runtime.reconciliation import reconcile_startup
from trading_lab.runtime.recovery import prepare_process_restart
from trading_lab.runtime.state import (
    PositionEvidence, RuntimeEvent, RuntimeEventType, RuntimeEvidence,
    RuntimeReason, RuntimeState, RuntimeStateSnapshot, transition_runtime_state,
)
from trading_lab.runtime.store import (
    ActionPhase, DecisionDisposition, JournalActionKind, RiskValuationMode,
    RuntimeStore, RuntimeStoreConflictError, RuntimeStoreError,
)
from tests import test_runtime_risk as pure_fixtures
from tests import test_runtime_store as store_fixtures
from tests import test_runtime_risk_circuit_breakers as breaker_fixtures
from tests import test_runtime_integration_regression as integration_fixtures
from tests.test_runtime_cycle import utc

HOUR, DAY = risk.HOUR_MS, risk.DAY_MS


class PureRearmTests(unittest.TestCase):
    def setUp(self):
        self.config = pure_fixtures.config()
        self.book = risk.RiskBook(D(800), D(1))
        self.mark = D(100)
        self.previous = risk.RiskState(0, HOUR, D(900), D(1100), 0, D(1000),
                                      D(-100), 2, risk.RiskReason.DAILY_LOSS_LIMIT, HOUR, False)

    def rearm(self, **changes):
        arguments = dict(config=self.config, previous=self.previous, book=self.book,
                         mark_price=self.mark, valued_at_ms=HOUR)
        return risk.rearm_risk_state(**{**arguments, **changes})

    def test_daily_loss_rearms_at_same_boundary_with_count_carried(self):
        child = self.rearm()
        self.assertEqual(child, risk.RiskState(HOUR, HOUR, D(900), D(900), 0, D(900), D(0), 2))

    def test_drawdown_rearms(self):
        child = self.rearm(previous=replace(self.previous, trip_reason=risk.RiskReason.MAX_DRAWDOWN))
        self.assertIsNone(child.trip_reason)
        self.assertEqual(child.entries_this_utc_day, 2)

    def test_untripped_parent_rejects(self):
        with self.assertRaises(risk.RuntimeRiskError):
            self.rearm(previous=replace(self.previous, trip_reason=None, tripped_at_ms=None))

    def test_pending_notification_rejects(self):
        with self.assertRaises(risk.RuntimeRiskError):
            self.rearm(previous=replace(self.previous, trip_pending_report=True))

    def test_changed_time_rejects(self):
        for value in (0, 2 * HOUR, True, 1.0, HOUR + 1, 2**63):
            with self.subTest(time=value), self.assertRaises(risk.RuntimeRiskError):
                self.rearm(valued_at_ms=value)

    def test_changed_mark_rejects_exactly_without_tolerance(self):
        with self.assertRaises(risk.RuntimeRiskError):
            self.rearm(mark_price=D("100.000000000000000000000000001"))

    def test_changed_book_rejects(self):
        with self.assertRaises(risk.RuntimeRiskError):
            self.rearm(book=risk.RiskBook(D("800.00000000000000000001"), D(1)))

    def test_exact_record_types_and_corrupt_bypassed_records_reject(self):
        for name in ("config", "previous", "book"):
            with self.subTest(record=name), self.assertRaises(risk.RuntimeRiskError):
                self.rearm(**{name: object()})
        broken = object.__new__(risk.RiskState)
        with self.assertRaises(risk.RuntimeRiskError):
            self.rearm(previous=broken)
        broken = replace(self.previous)
        object.__setattr__(broken, "trip_reason", risk.RiskReason.ENTRY_COUNT_LIMIT)
        with self.assertRaises(risk.RuntimeRiskError):
            self.rearm(previous=broken)

    def test_invalid_mark_is_sanitized(self):
        for value in (D(0), D(-1), D("NaN"), D("Infinity"), True, 100, "PRIVATE_MARK"):
            with self.subTest(kind=type(value)), self.assertRaises(risk.RuntimeRiskError) as caught:
                self.rearm(mark_price=value)
            self.assertNotIn("PRIVATE_MARK", str(caught.exception))

    def test_initialization_and_rearm_are_semantically_distinct(self):
        initialized = risk.initialize_risk_state(self.config, self.book, self.mark, HOUR)
        with patch.object(risk, "initialize_risk_state", side_effect=AssertionError("No initialization shortcut")):
            child = self.rearm()
        self.assertEqual(initialized.entries_this_utc_day, 0)
        self.assertEqual(child.entries_this_utc_day, 2)

    def test_inputs_stay_immutable_and_parent_latch_survives(self):
        before = replace(self.config), replace(self.previous), replace(self.book)
        child = self.rearm()
        self.assertEqual((self.config, self.previous, self.book), before)
        self.assertIsNot(child, self.previous)
        self.assertIs(self.previous.trip_reason, risk.RiskReason.DAILY_LOSS_LIMIT)
        with self.assertRaises(FrozenInstanceError):
            child.entries_this_utc_day = 0

    def test_hostile_global_decimal_context_cannot_change_result(self):
        expected = self.rearm()
        with localcontext() as context:
            context.prec, context.Emax, context.Emin, context.rounding = 1, 1, -1, ROUND_UP
            context.traps[Inexact] = context.traps[Rounded] = True
            self.assertEqual(self.rearm(), expected)

    def test_partial_day_baseline_uses_boundary_day_not_an_operator_clock(self):
        previous = replace(self.previous, valued_at_ms=DAY + HOUR,
                           utc_day_start_ms=DAY, tripped_at_ms=DAY)
        child = self.rearm(previous=previous, valued_at_ms=DAY + HOUR)
        self.assertEqual((child.utc_day_start_ms, child.utc_day_start_risk_equity,
                          child.daily_pnl, child.entries_this_utc_day), (DAY, D(900), D(0), 2))


class LocalRearmCase(store_fixtures.RiskPersistenceCase):
    """A small legacy owned book, then the real atomic LIVE risk boundary."""

    def rows(self):
        return {name: tuple(tuple(row) for row in self.store._connection.execute(
            "SELECT * FROM " + name + " ORDER BY rowid")) for name in persistence._SCHEMA}

    def refresh(self, at):
        current = self.store.get_checkpoint()
        cp = replace(current, sequence=current.sequence + 1,
                     last_reconciled_at_ms=at, observed_at_ms=at)
        self.store.save_checkpoint(cp, expected_sequence=current.sequence)

    def live(self, close="80", *, signal="HOLD", desired=None):
        current = self.store.get_checkpoint()
        at = current.last_processed_candle_ms + HOUR
        self.now_ms = at + HOUR + 1000
        self.refresh(self.now_ms)
        current = self.store.get_checkpoint()
        price = D(close)
        candle = replace(store_fixtures.candle(at), open=price, high=price, low=price, close=price)
        decision = CanonicalDecision(candle.symbol, candle.timeframe, at, candle.input_fingerprint,
            signal, current.snapshot.desired_position if desired is None else desired, at + HOUR)
        plan = plan_action(self.config, current, decision, evaluated_at_ms=self.now_ms,
                           mode=DecisionMode.LIVE, action_history=self.store.list_actions())
        snapshot = current.snapshot
        for event in plan.events:
            snapshot = transition_runtime_state(snapshot, event)
        cp = replace(current, sequence=current.sequence + 1, snapshot=snapshot, last_processed_candle_ms=at)
        self.store.commit_live_risk_decision(candle, plan.decision, cp, expected_sequence=current.sequence,
                                            evaluated_at_ms=self.now_ms, proposed_action=plan.action)
        return self.store.get_latest_risk_valuation(), plan.action

    def tripped_long(self, *, drawdown=False):
        cfg = store_fixtures.risk_configuration(max_daily_loss_fraction=D(1) if drawdown else D("0.01"),
                                                max_drawdown_fraction=D("0.01") if drawdown else D(1))
        self.long_activation(close="100", cfg=cfg)
        row, _ = self.live()
        self.assertIsNotNone(row.trip_reason)
        self.assertFalse(row.trip_pending_report)
        return row

    def finish(self, action, *, quantity="1", price="80", fee="0", currency=None, executed_at=None):
        cp = self.store.get_checkpoint()
        self.store.start_attempt(action.logical_action_id, replace(cp, sequence=cp.sequence + 1), expected_sequence=cp.sequence)
        action = self.store.get_action(action.logical_action_id)
        cp = self.store.get_checkpoint()
        fill = replace(store_fixtures.fill("new-fill-" + action.logical_action_id[:8]),
            action_id=action.logical_action_id, broker_order_id="order-" + action.logical_action_id[:8],
            order_link_id=action.order_link_id, side=action.side, executed_quantity=D(quantity),
            execution_price=D(price), execution_fee=D(fee), fee_currency=currency,
            executed_at_ms=self.now_ms if executed_at is None else executed_at, observed_at_ms=self.now_ms)
        book = persistence._risk_book(self.store.get_risk_configuration().configuration,
                                      (*self.store.list_fills(), fill))
        event = RuntimeEvent(RuntimeEventType.RECONCILED_FLAT if book.owned_base_quantity == 0
                             else RuntimeEventType.RECONCILED_LONG,
                             evidence=RuntimeEvidence(book.owned_base_quantity,
                                                      terminal_action_id=action.logical_action_id))
        done = replace(action, phase=ActionPhase.TERMINAL_CONFIRMED, broker_order_id=fill.broker_order_id,
                       order_status="FILLED", observed_at_ms=self.now_ms, terminal_at_ms=self.now_ms)
        cp = replace(cp, sequence=cp.sequence + 1, snapshot=transition_runtime_state(cp.snapshot, event))
        self.store.record_observation(done, cp, expected_sequence=cp.sequence - 1, fills=(fill,))

    def tripped_flat(self):
        self.tripped_long()
        _, action = self.live(signal="LONG_EXIT", desired=0)
        self.finish(action)
        row, _ = self.live(desired=0)
        self.assertEqual(row.book, risk.RiskBook(D(980), D(0)))
        return row

    def rearm(self, **changes):
        args = dict(expected_epoch_id=self.store.get_current_risk_epoch().epoch_id, operator_at_ms=self.now_ms)
        return self.store.rearm_risk_epoch(**{**args, **changes})

    def refuse(self, **changes):
        before = self.rows()
        with self.assertRaises(RuntimeStoreError):
            self.rearm(**changes)
        self.assertEqual(self.rows(), before)

    def halt(self, **changes):
        cp = self.store.get_checkpoint()
        snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(
            RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.INCONSISTENT_EVIDENCE))
        halted = replace(cp, sequence=cp.sequence + 1, snapshot=snapshot, halted_at_ms=self.now_ms, **changes)
        self.store.save_checkpoint(halted, expected_sequence=cp.sequence)
        return halted

    def control_halt(self, **changes):
        args = dict(expected_sequence=self.store.get_checkpoint().sequence, operator_at_ms=self.now_ms + 1)
        return self.store.rearm_runtime_halt(**{**args, **changes})


class RiskRearmGuardTests(LocalRearmCase):
    def test_safe_long_preserves_all_other_rows_and_exact_book(self):
        parent = self.tripped_long()
        before = self.rows()
        child = self.rearm()
        after = self.rows()
        for table in before.keys() - {"risk_epochs", "risk_valuations"}:
            self.assertEqual(after[table], before[table], table)
        self.assertEqual(after["risk_epochs"][:-1], before["risk_epochs"])
        self.assertEqual(after["risk_valuations"][:-1], before["risk_valuations"])
        self.assertEqual((child.book, child.mark_price, child.valued_at_ms,
                          child.fill_evidence_count, child.fill_evidence_digest),
                         (parent.book, parent.mark_price, parent.valued_at_ms,
                          parent.fill_evidence_count, parent.fill_evidence_digest))
        self.assertEqual((child.risk_equity, child.peak_risk_equity, child.utc_day_start_risk_equity,
                          child.daily_pnl), (D(980), D(980), D(980), D(0)))
        self.assertIsNone(child.trip_reason)

    def test_safe_flat_rearms_without_cash_credit(self):
        parent = self.tripped_flat()
        child = self.rearm()
        self.assertEqual(child.book, parent.book)
        self.assertEqual(child.virtual_quote_cash, D(980))
        self.assertIsNone(child.trip_reason)

    def test_drawdown_parent_is_supported(self):
        parent = self.tripped_long(drawdown=True)
        self.assertIs(parent.trip_reason, risk.RiskReason.MAX_DRAWDOWN)
        self.assertIsNone(self.rearm().trip_reason)

    def test_empty_journal_rejects(self):
        before = self.rows()
        with self.assertRaises(RuntimeStoreError):
            self.store.rearm_risk_epoch(expected_epoch_id="a" * 64, operator_at_ms=HOUR)
        self.assertEqual(self.rows(), before)

    def test_untripped_initial_epoch_rejects(self):
        self.activate()
        self.now_ms = HOUR + 1000
        self.refresh(self.now_ms)
        self.refuse()

    def test_stale_expected_epoch_and_malformed_inputs_reject(self):
        self.tripped_long()
        for epoch in ("a" * 64, None, "PRIVATE\n", True):
            with self.subTest(epoch=epoch):
                self.refuse(expected_epoch_id=epoch)
        for at in (True, -1, 1.0, 2**63, None):
            with self.subTest(at=at):
                self.refuse(operator_at_ms=at)

    def test_unsafe_runtime_states_reject_unchanged(self):
        self.tripped_long()
        cp = self.store.get_checkpoint()
        for state in (RuntimeState.STARTING, RuntimeState.SYNCHRONIZING, RuntimeState.UNCERTAIN,
                      RuntimeState.HALTED, RuntimeState.STOPPING):
            reason = RuntimeReason.EVIDENCE_MISSING if state in (RuntimeState.UNCERTAIN, RuntimeState.HALTED) else None
            snapshot = replace(cp.snapshot, state=state, position_evidence=PositionEvidence.LAST_KNOWN,
                               reason=reason, stopped_from=RuntimeState.LONG if state is RuntimeState.STOPPING else None)
            altered = replace(cp, snapshot=snapshot, halted_at_ms=self.now_ms if state is RuntimeState.HALTED else None,
                              shutdown_at_ms=self.now_ms if state is RuntimeState.STOPPING else None)
            self.store._update("checkpoint", persistence._checkpoint_values(altered), "singleton", 1)
            with self.subTest(state=state):
                self.refuse()

    def test_pending_placement_and_cancellation_both_reject(self):
        self.tripped_long()
        _, action = self.live(signal="LONG_EXIT", desired=0)
        self.refuse()
        cp = self.store.get_checkpoint()
        self.store.start_attempt(action.logical_action_id, replace(cp, sequence=cp.sequence + 1), expected_sequence=cp.sequence)
        attempted = self.store.get_action(action.logical_action_id)
        cp = self.store.get_checkpoint()
        ack = replace(attempted, phase=ActionPhase.ACKNOWLEDGED, broker_order_id="exit-order",
                      submitted_amount=D(1), acknowledgement_broker_ms=self.now_ms, acknowledgement_observed_ms=self.now_ms)
        self.store.record_observation(ack, replace(cp, sequence=cp.sequence + 1), expected_sequence=cp.sequence)
        cancel = persistence.ActionRecord("e" * 64, JournalActionKind.CANCEL, self.config.symbol,
            action.reconciliation_deadline_ms, 5, 3, control_id="cancel-test",
            parent_action_id=action.logical_action_id, target_broker_order_id="exit-order")
        cp = self.store.get_checkpoint()
        self.store.prepare_cancellation(cancel, replace(cp, sequence=cp.sequence + 1), expected_sequence=cp.sequence)
        self.refuse()
        self.assertIs(self.store.get_action(cancel.logical_action_id).phase, ActionPhase.PREPARED)

    def test_long_zero_or_missing_intent_rejects(self):
        self.tripped_long()
        cp = self.store.get_checkpoint()
        # Deliberately inconsistent durable intent also proves full validation.
        for desired in (0, None):
            altered = replace(cp, snapshot=replace(cp.snapshot, desired_position=desired))
            self.store._update("checkpoint", persistence._checkpoint_values(altered), "singleton", 1)
            with self.subTest(desired=desired):
                self.refuse()

    def test_flat_desired_long_refused_entry_cannot_rearm(self):
        self.tripped_flat()
        self.live("110", signal="LONG_ENTRY", desired=1)
        self.assertEqual(self.store.get_checkpoint().snapshot.desired_position, 1)
        self.refuse()

    def test_missing_stale_or_future_reconciliation_rejects(self):
        self.tripped_long()
        cp = self.store.get_checkpoint()
        for name in ("last_reconciled_at_ms", "observed_at_ms"):
            for time in (None, self.now_ms - self.config.observation_max_age_ms - 1, self.now_ms + 1):
                self.store._update("checkpoint", persistence._checkpoint_values(replace(cp, **{name: time})), "singleton", 1)
                with self.subTest(field=name, time=time):
                    self.refuse()

    def test_stale_or_future_mark_rejects_with_fresh_reconciliation(self):
        row = self.tripped_long()
        for at in (row.valued_at_ms - 1, row.valued_at_ms + self.config.decision_max_age_ms + 1):
            cp = self.store.get_checkpoint()
            self.store._update("checkpoint", persistence._checkpoint_values(replace(cp,
                last_reconciled_at_ms=at, observed_at_ms=at)), "singleton", 1)
            with self.subTest(at=at):
                self.refuse(operator_at_ms=at)

    def test_exact_freshness_limits_accept(self):
        row = self.tripped_long()
        at = row.valued_at_ms + self.config.decision_max_age_ms
        cp = self.store.get_checkpoint()
        self.store._update("checkpoint", persistence._checkpoint_values(replace(cp,
            last_reconciled_at_ms=at - self.config.observation_max_age_ms,
            observed_at_ms=at - self.config.observation_max_age_ms)), "singleton", 1)
        self.assertIsNone(self.rearm(operator_at_ms=at).trip_reason)

    def test_lagging_risk_frontier_rejects(self):
        self.tripped_long()
        # A historical candle can commit before its risk catch-up. Preserve the
        # still-fresh observation/mark to isolate the frontier requirement.
        self.commit_candle(3 * HOUR, "80")
        before = self.rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError, "frontiers"):
            self.rearm()
        self.assertEqual(self.rows(), before)

    def test_coherent_long_desired_zero_after_unsent_exit_rejects(self):
        self.tripped_long()
        _, action = self.live(signal="LONG_EXIT", desired=0)
        cp = self.store.get_checkpoint()
        snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.RECONCILED_LONG,
            evidence=RuntimeEvidence(D(1), terminal_action_id=action.logical_action_id)))
        self.store.abandon_prepared(action.logical_action_id, replace(cp, sequence=cp.sequence + 1, snapshot=snapshot),
                                   expected_sequence=cp.sequence, terminal_at_ms=self.now_ms)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.LONG)
        before = self.rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError, "aligned strategy intent"):
            self.rearm()
        self.assertEqual(self.rows(), before)

    def test_pending_replay_trip_notification_rejects(self):
        self.long_activation(close="100", cfg=store_fixtures.risk_configuration(max_daily_loss_fraction=D("0.01")))
        self.commit_candle(2 * HOUR, "80")
        self.store.append_risk_replay_valuation(candle_open_ms=2 * HOUR)
        self.now_ms = 3 * HOUR + 1000
        self.refresh(self.now_ms)
        self.assertTrue(self.store.get_latest_risk_valuation().trip_pending_report)
        self.refuse()

    def test_changed_book_even_at_same_equity_rejects_at_store_boundary(self):
        row = self.tripped_long()
        # The pure validator can value this coincidentally equal combination;
        # the store must still compare it with the reconstructed owned book.
        self.store._connection.execute("UPDATE risk_valuations SET virtual_quote_cash='920', owned_base_quantity='0.75' WHERE valued_at_ms=?",
                                       (row.valued_at_ms,))
        self.assertEqual(self.store.get_latest_risk_valuation().risk_equity, row.risk_equity)
        self.refuse()

    def test_changed_mark_is_not_accepted_as_operator_evidence(self):
        row = self.tripped_long()
        self.store._connection.execute("UPDATE risk_valuations SET mark_price='100', virtual_quote_cash='880' WHERE valued_at_ms=?",
                                       (row.valued_at_ms,))
        self.refuse()

    def test_confirmed_quantity_must_match_accepted_book(self):
        self.tripped_long()
        cp = self.store.get_checkpoint()
        self.store._update("checkpoint", persistence._checkpoint_values(replace(cp,
            snapshot=replace(cp.snapshot, owned_base_quantity=D(2)))), "singleton", 1)
        self.refuse()

    def test_configuration_or_state_cannot_be_supplied_to_control(self):
        self.tripped_long()
        before = self.rows()
        for name in ("configuration", "book", "mark_price", "state", "epoch_id", "trip_reason"):
            with self.subTest(field=name), self.assertRaises(TypeError):
                self.rearm(**{name: None})
        self.assertEqual(self.rows(), before)

    def test_repeated_old_or_current_epoch_control_cannot_create_third(self):
        self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        self.rearm()
        self.refuse(expected_epoch_id=parent.epoch_id)
        self.refuse()
        self.assertEqual(self.store.get_current_risk_epoch().epoch_sequence, 2)


class FillBoundaryRearmTests(LocalRearmCase):
    def late_fill(self, offset):
        self.tripped_flat()
        # Explicit legacy journal fixture: an owned pre-existing action is
        # still pending while historical HOLD/desired=0 advances the mark.
        # No risk approval or broker send is fabricated by the rearm control.
        current = self.store.get_checkpoint()
        at = current.last_processed_candle_ms + HOUR
        self.now_ms = at + HOUR + 1000
        self.refresh(self.now_ms)
        current = self.store.get_checkpoint()
        candle = replace(store_fixtures.candle(at), open=D(80), high=D(80), low=D(80), close=D(80))
        canonical = CanonicalDecision(candle.symbol, candle.timeframe, at, candle.input_fingerprint,
                                      "LONG_ENTRY", 1, at + HOUR)
        plan = plan_action(self.config, current, canonical, evaluated_at_ms=self.now_ms,
                           mode=DecisionMode.LIVE, action_history=self.store.list_actions())
        cp = replace(current, sequence=current.sequence + 1, last_processed_candle_ms=at,
                     snapshot=transition_runtime_state(current.snapshot, plan.events[0]))
        self.store.commit_decision(candle, plan.decision, cp, expected_sequence=current.sequence, action=plan.action)
        self.store.append_risk_replay_valuation(candle_open_ms=at)
        at += HOUR
        current = self.store.get_checkpoint()
        candle = replace(candle, candle_open_ms=at)
        decision = replace(store_fixtures.decision(at), desired_position=0)
        cp = replace(current, sequence=current.sequence + 1, last_processed_candle_ms=at,
                     snapshot=replace(current.snapshot, desired_position=0))
        self.store.commit_decision(candle, decision, cp, expected_sequence=current.sequence)
        self.store.append_risk_replay_valuation(candle_open_ms=at)
        before_fill = self.store.get_latest_risk_valuation()
        self.now_ms = before_fill.valued_at_ms + 1000
        self.finish(plan.action, fee="1", currency="BTC", executed_at=before_fill.valued_at_ms + offset)
        self.refresh(self.now_ms)
        self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, before_fill.owned_base_quantity)
        self.assertEqual(self.store.get_checkpoint().snapshot.desired_position, 0)
        self.assertEqual(self.store.get_latest_risk_valuation(), before_fill)
        return before_fill

    def test_post_boundary_economics_reject_even_when_final_quantity_matches(self):
        parent = self.late_fill(1)
        self.assertTrue(any(fill.executed_at_ms > parent.valued_at_ms for fill in self.store.list_fills()))
        self.assertEqual(parent.owned_base_quantity, D(0))
        before = self.rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError, "boundary precedes retained owned executions"):
            self.rearm()
        self.assertEqual(self.rows(), before)

    def test_equal_boundary_late_evidence_rejects(self):
        self.late_fill(0)
        before = self.rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError, "Predecessor owned-fill evidence changed"):
            self.rearm()
        self.assertEqual(self.rows(), before)

    def test_older_late_evidence_rejects_without_rewriting_history(self):
        self.late_fill(-1)
        self.refuse()


class HaltRearmTests(LocalRearmCase):
    def test_exact_frozen_transition_preserves_every_other_fact_and_risk(self):
        self.tripped_long()
        halted = self.halt()
        before = self.rows()
        with patch.object(persistence, "transition_runtime_state", wraps=transition_runtime_state) as transition:
            cp = self.control_halt()
        transition.assert_called_once_with(halted.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED))
        self.assertEqual(cp, replace(halted, sequence=halted.sequence + 1,
            snapshot=transition_runtime_state(halted.snapshot, RuntimeEvent(RuntimeEventType.OPERATOR_REARMED)),
            halted_at_ms=None, rearmed_at_ms=self.now_ms + 1))
        self.assertIs(cp.snapshot.state, RuntimeState.SYNCHRONIZING)
        self.assertIs(cp.snapshot.position_evidence, PositionEvidence.LAST_KNOWN)
        for table in before.keys() - {"checkpoint"}:
            self.assertEqual(self.rows()[table], before[table])
        self.assertIsNotNone(self.store.get_latest_risk_valuation().trip_reason)

    def test_halt_unknown_exposure_remains_unknown(self):
        self.now_ms = HOUR
        self.halt()
        cp = self.control_halt()
        self.assertIsNone(cp.snapshot.owned_base_quantity)
        self.assertIs(cp.snapshot.position_evidence, PositionEvidence.UNKNOWN)

    def test_stale_sequence_rejects_without_changes(self):
        self.tripped_long()
        cp = self.halt()
        before = self.rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.control_halt(expected_sequence=cp.sequence - 1)
        self.assertEqual(self.rows(), before)

    def test_invalid_or_non_later_operator_times_reject(self):
        self.tripped_long()
        self.halt()
        before = self.rows()
        for at in (True, -1, 2**63, 1.2, None, self.now_ms, self.now_ms - 1):
            with self.subTest(at=at), self.assertRaises(RuntimeStoreError):
                self.control_halt(operator_at_ms=at)
            self.assertEqual(self.rows(), before)

    def test_prior_rearm_metadata_must_remain_monotonic(self):
        self.tripped_long()
        self.halt(rearmed_at_ms=self.now_ms + 10)
        before = self.rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.control_halt(operator_at_ms=self.now_ms + 1)
        self.assertEqual(self.rows(), before)

    def test_other_states_and_stopping_from_halt_reject(self):
        self.tripped_long()
        cp = self.halt()
        for state in RuntimeState:
            if state is RuntimeState.HALTED or state is RuntimeState.ORDER_PENDING:
                continue
            if state is RuntimeState.FLAT:
                snapshot = RuntimeStateSnapshot(state, D(0), PositionEvidence.CONFIRMED, 1)
            else:
                snapshot = replace(cp.snapshot, state=state,
                    position_evidence=PositionEvidence.CONFIRMED if state is RuntimeState.LONG else PositionEvidence.LAST_KNOWN,
                    reason=cp.snapshot.reason if state in (RuntimeState.UNCERTAIN, RuntimeState.STOPPING) else None,
                    stopped_from=RuntimeState.HALTED if state is RuntimeState.STOPPING else None)
            altered = replace(cp, snapshot=snapshot, halted_at_ms=cp.halted_at_ms if state is RuntimeState.STOPPING else None,
                              shutdown_at_ms=self.now_ms if state is RuntimeState.STOPPING else None)
            self.store._update("checkpoint", persistence._checkpoint_values(altered), "singleton", 1)
            before = self.rows()
            with self.subTest(state=state), self.assertRaises(RuntimeStoreError):
                self.control_halt()
            self.assertEqual(self.rows(), before)

    def test_pending_order_cannot_rearm_until_halted_and_retains_budgets(self):
        self.tripped_long()
        _, action = self.live(signal="LONG_EXIT", desired=0)
        before = self.rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.control_halt()
        self.assertEqual(self.rows(), before)
        self.halt()
        cp = self.control_halt()
        self.assertEqual(cp.snapshot.pending_action.logical_action_id, action.logical_action_id)
        self.assertEqual(self.store.get_action(action.logical_action_id), action)

    def test_repeated_halt_control_is_not_idempotent_success(self):
        self.tripped_long()
        self.halt()
        self.control_halt()
        before = self.rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.control_halt()
        self.assertEqual(self.rows(), before)

    def test_old_fresh_looking_observations_cannot_replace_post_halt_reconciliation(self):
        self.tripped_long()
        self.halt()
        cp = self.control_halt()
        snapshot = transition_runtime_state(cp.snapshot, RuntimeEvent(RuntimeEventType.RECONCILED_LONG,
                                                                       evidence=RuntimeEvidence(D(1))))
        # Synthetic caller confirmation with OLD timestamps, deliberately not
        # a real reconcile_startup call: rearm must independently reject it.
        self.store.save_checkpoint(replace(cp, sequence=cp.sequence + 1, snapshot=snapshot), expected_sequence=cp.sequence)
        self.refuse(operator_at_ms=self.now_ms + 1)


class EpochHistoryTests(LocalRearmCase):
    def replace_child(self, **changes):
        child = self.store.get_current_risk_epoch()
        row = self.store.get_latest_risk_valuation()
        values = {field.name: getattr(child, field.name) for field in fields(child) if field.name != "epoch_id"}
        values.update(changes)
        altered = persistence.RiskEpochRecord(persistence._canonical_hash(values), **values)
        # Corruption fixture only: keep FK/hash integrity while independently
        # violating the reviewed lineage contract, so validation must detect it.
        with self.store._transaction(validate=False):
            self.store._connection.execute("PRAGMA defer_foreign_keys=ON")
            self.store._update("risk_epochs", persistence._encode(altered), "epoch_id", child.epoch_id)
            altered_row = replace(row, epoch_id=altered.epoch_id,
                                  risk_configuration_digest=altered.risk_configuration_digest)
            self.store._update("risk_valuations", persistence._encode(altered_row), "epoch_id", child.epoch_id)

    def test_deterministic_identity_and_shared_boundary_reads(self):
        parent_row = self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        parent_history = self.store.list_risk_valuations(parent.epoch_id)
        child_row = self.rearm()
        child = self.store.get_current_risk_epoch()
        payload = dict(epoch_sequence=2, risk_configuration_digest=parent.risk_configuration_digest,
                       started_at_ms=parent_row.valued_at_ms, parent_epoch_id=parent.epoch_id)
        expected_id = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
        self.assertEqual(child.epoch_id, expected_id)
        self.assertEqual(self.store.list_risk_valuations()[-2:], (parent_row, child_row))
        self.assertEqual(self.store.list_risk_valuations(parent.epoch_id), parent_history)
        self.assertEqual(self.store.list_risk_valuations(child.epoch_id), (child_row,))
        self.assertEqual(self.store.get_latest_risk_valuation(), child_row)
        self.assertEqual(self.store.list_risk_verdicts(child.epoch_id), ())
        self.assertEqual(self.store.get_risk_verdict(parent_row.candle_open_ms).epoch_id, parent.epoch_id)

    def test_multiple_children_current_authority_and_lexical_inversion(self):
        self.tripped_long()
        seen_inversion = False
        for sequence, close in enumerate(("60", "40", "20"), 2):
            parent = self.store.get_current_risk_epoch()
            row = self.rearm()
            child = self.store.get_current_risk_epoch()
            seen_inversion |= child.epoch_id < parent.epoch_id
            self.assertEqual(child.epoch_sequence, sequence)
            self.assertEqual(child.parent_epoch_id, parent.epoch_id)
            self.assertEqual(self.store.get_latest_risk_valuation(), row)
            self.assertEqual(self.store.list_risk_valuations()[-1], row)
            self.live(close)
        self.assertTrue(seen_inversion, "Fixture must exercise reversed lexical hash order.")
        self.reopen()
        self.assertEqual(self.store.get_current_risk_epoch().epoch_sequence, 4)

    def test_next_live_uses_child_and_closed_parent_never_changes(self):
        self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        old = self.store.list_risk_valuations(parent.epoch_id), self.store.list_risk_verdicts(parent.epoch_id)
        activation = self.rearm()
        row, action = self.live()
        self.assertIsNone(action)
        self.assertEqual(row.epoch_id, activation.epoch_id)
        self.assertEqual(row.valued_at_ms, activation.valued_at_ms + HOUR)
        self.assertEqual((self.store.list_risk_valuations(parent.epoch_id), self.store.list_risk_verdicts(parent.epoch_id)), old)

    def test_replay_append_targets_only_current_child(self):
        self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        old = self.store.list_risk_valuations(parent.epoch_id)
        child = self.rearm()
        self.commit_candle(3 * HOUR, "80")
        self.assertTrue(self.store.append_risk_replay_valuation(candle_open_ms=3 * HOUR))
        self.assertFalse(self.store.append_risk_replay_valuation(candle_open_ms=3 * HOUR))
        self.assertEqual(self.store.get_latest_risk_valuation().epoch_id, child.epoch_id)
        self.assertEqual(self.store.list_risk_valuations(parent.epoch_id), old)

    def test_old_shared_candle_cannot_be_appended_or_reauthorized(self):
        row = self.tripped_long()
        self.rearm()
        before = self.rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.append_risk_replay_valuation(candle_open_ms=row.candle_open_ms)
        cp = self.store.get_checkpoint()
        with self.assertRaisesRegex(RuntimeStoreConflictError, "Conflicting immutable LIVE replay"):
            self.store.commit_live_risk_decision(self.store.get_candle(row.candle_open_ms),
                self.store.get_decision(row.candle_open_ms), replace(cp, sequence=cp.sequence + 1),
                expected_sequence=cp.sequence, evaluated_at_ms=self.now_ms)
        self.assertEqual(self.rows(), before)

    def test_corrupt_child_count_rejects_filtered_reads_and_reopen(self):
        self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        child = self.rearm()
        self.store._connection.execute("UPDATE risk_valuations SET entries_this_utc_day=1 WHERE epoch_id=?", (child.epoch_id,))
        with self.assertRaises(RuntimeStoreError):
            self.store.list_risk_valuations(parent.epoch_id)
        self.store.close()
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config)

    def test_orphan_child_or_missing_activation_rejects(self):
        self.tripped_long()
        child = self.rearm()
        self.store._connection.execute("DELETE FROM risk_valuations WHERE epoch_id=?", (child.epoch_id,))
        with self.assertRaises(RuntimeStoreError):
            self.store.get_current_risk_epoch()

    def test_parent_cannot_acquire_a_later_valuation(self):
        self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        self.rearm()
        row, _ = self.live()
        forged = replace(row, epoch_id=parent.epoch_id, peak_risk_equity=D(1000),
                         utc_day_start_risk_equity=D(1000), daily_pnl=D(-20),
                         trip_reason=risk.RiskReason.DAILY_LOSS_LIMIT, tripped_at_ms=3 * HOUR)
        self.store._insert("risk_valuations", persistence._encode(forged))
        with self.assertRaises(RuntimeStoreError):
            self.store.get_current_risk_epoch()

    def test_child_sequence_gap_is_rejected_even_with_valid_hash_and_foreign_keys(self):
        self.tripped_long()
        self.rearm()
        self.replace_child(epoch_sequence=3)
        with self.assertRaisesRegex(RuntimeStoreError, "lineage"):
            self.store.get_current_risk_epoch()

    def test_child_different_started_boundary_rejects(self):
        self.tripped_long()
        child = self.rearm()
        self.replace_child(started_at_ms=child.valued_at_ms + HOUR)
        with self.assertRaisesRegex(RuntimeStoreError, "lineage"):
            self.store.list_risk_valuations()

    def test_child_cannot_switch_configuration_even_with_matching_currencies_and_budget(self):
        self.tripped_long()
        self.rearm()
        cfg = replace(self.store.get_risk_configuration().configuration, max_entry_notional_quote=D(201))
        record = persistence._risk_configuration_record(cfg)
        # Insert and rewrite together; an unbound config must not fail first.
        with self.store._transaction(validate=False):
            self.store._insert("risk_configurations", persistence._encode(record))
            # Read the existing known-valid child directly, before validating
            # the intentionally incomplete configuration change.
            child = self.store._one("risk_epochs", "epoch_sequence=2")
            row = self.store._one("risk_valuations", "epoch_id=?", (child.epoch_id,))
            values = dict(epoch_sequence=2, started_at_ms=child.started_at_ms,
                          parent_epoch_id=child.parent_epoch_id, risk_configuration_digest=record.risk_configuration_digest)
            altered = persistence.RiskEpochRecord(persistence._canonical_hash(values), **values)
            self.store._connection.execute("PRAGMA defer_foreign_keys=ON")
            self.store._update("risk_epochs", persistence._encode(altered), "epoch_id", child.epoch_id)
            self.store._update("risk_valuations", persistence._encode(replace(row, epoch_id=altered.epoch_id,
                risk_configuration_digest=record.risk_configuration_digest)), "epoch_id", child.epoch_id)
        with self.assertRaisesRegex(RuntimeStoreError, "lineage"):
            self.store.get_risk_configuration()

    def test_child_cannot_reset_book_even_if_equity_coincidentally_matches(self):
        self.tripped_long()
        child = self.rearm()
        self.store._connection.execute("UPDATE risk_valuations SET virtual_quote_cash='980', owned_base_quantity='0' WHERE epoch_id=?", (child.epoch_id,))
        with self.assertRaisesRegex(RuntimeStoreError, "parent book/mark/evidence"):
            self.store.get_latest_risk_valuation()

    def test_branch_to_earlier_parent_rejects(self):
        self.tripped_long()
        parent = self.store.get_current_risk_epoch()
        self.rearm()
        row = self.store.get_latest_risk_valuation()
        values = dict(epoch_sequence=3, started_at_ms=row.valued_at_ms,
                      parent_epoch_id=parent.epoch_id, risk_configuration_digest=parent.risk_configuration_digest)
        branch = persistence.RiskEpochRecord(persistence._canonical_hash(values), **values)
        self.store._insert("risk_epochs", persistence._encode(branch))
        self.store._insert("risk_valuations", persistence._encode(replace(row, epoch_id=branch.epoch_id)))
        with self.assertRaisesRegex(RuntimeStoreError, "lineage"):
            self.store.list_risk_verdicts(parent.epoch_id)

    def test_child_of_untripped_parent_rejects_without_initialization_shortcut(self):
        initial = self.activate(close="100")
        parent = self.store.get_current_risk_epoch()
        child = persistence._initial_risk_epoch(self.store.get_risk_configuration(), initial.valued_at_ms, parent=parent)
        self.store._insert("risk_epochs", persistence._encode(child))
        self.store._insert("risk_valuations", persistence._encode(replace(initial, epoch_id=child.epoch_id)))
        with self.assertRaises(RuntimeStoreError):
            self.store.get_latest_risk_valuation()


class RearmFaultTests(LocalRearmCase):
    def fault(self, method, *, boundary, lost=False, rollback=False):
        self.tripped_long()
        if method == "halt":
            self.halt()
        before = self.rows()
        operation = self.control_halt if method == "halt" else self.rearm
        connection = self.store._connection

        class FaultConnection:
            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, sql, *values):
                if (boundary == "update" and sql.startswith("UPDATE checkpoint")
                        or boundary == "epoch" and sql.startswith("INSERT INTO risk_epochs")
                        or boundary == "activation" and sql.startswith("INSERT INTO risk_valuations")
                        or rollback and sql == "ROLLBACK"):
                    raise sqlite3.OperationalError("Synthetic control fault")
                return connection.execute(sql, *values)

        def commit():
            if lost:
                connection.execute("COMMIT")
            raise sqlite3.OperationalError("Synthetic commit fault")

        with patch.object(self.store, "_connection", FaultConnection()):
            if boundary == "commit":
                with patch.object(self.store, "_commit", side_effect=commit), self.assertRaises(RuntimeStoreError):
                    operation()
            else:
                with self.assertRaises(RuntimeStoreError):
                    operation()
            if lost or rollback:
                self.assertIsNone(self.store._connection)
        self.reopen()
        if not lost:
            self.assertEqual(self.rows(), before)
        elif method == "halt":
            self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.SYNCHRONIZING)
            for table in before.keys() - {"checkpoint"}:
                self.assertEqual(self.rows()[table], before[table])
        else:
            self.assertEqual(self.store.get_current_risk_epoch().epoch_sequence, 2)
            self.assertIsNone(self.store.get_latest_risk_valuation().trip_reason)
            self.refuse()

    def test_halt_during_checkpoint_update_rolls_back(self):
        self.fault("halt", boundary="update")

    def test_halt_before_checkpoint_update_rolls_back(self):
        self.tripped_long()
        self.halt()
        before = self.rows()
        with patch.object(self.store, "_save_checkpoint", side_effect=RuntimeStoreError("Synthetic CAS")), self.assertRaises(RuntimeStoreError):
            self.control_halt()
        self.assertEqual(self.rows(), before)

    def test_halt_before_commit_rolls_back(self):
        self.fault("halt", boundary="commit")

    def test_halt_lost_commit_return_requires_reopen(self):
        self.fault("halt", boundary="commit", lost=True)

    def test_halt_rollback_uncertainty_requires_reopen(self):
        self.fault("halt", boundary="update", rollback=True)

    def test_child_epoch_insert_fault_rolls_back(self):
        self.fault("risk", boundary="epoch")

    def test_child_activation_insert_fault_rolls_back_both_rows(self):
        self.fault("risk", boundary="activation")

    def test_child_before_commit_rolls_back_both_rows(self):
        self.fault("risk", boundary="commit")

    def test_child_lost_commit_return_requires_reopen_without_third_epoch(self):
        self.fault("risk", boundary="commit", lost=True)

    def test_child_rollback_uncertainty_requires_reopen(self):
        self.fault("risk", boundary="activation", rollback=True)

    def test_child_post_insert_validation_fault_rolls_back(self):
        self.tripped_long()
        before = self.rows()
        validate = self.store._validate_risk_history

        def fail():
            validate()
            if self.store._connection.execute("SELECT count(*) FROM risk_epochs").fetchone()[0] == 2:
                raise RuntimeStoreError("Synthetic child validation fault")

        with patch.object(self.store, "_validate_risk_history", side_effect=fail), self.assertRaises(RuntimeStoreError):
            self.rearm()
        self.assertEqual(self.rows(), before)


class IntegratedRearmTests(breaker_fixtures.BreakerCase):
    def trip(self):
        self.owned_long()
        return self.assert_trip(self.step("98"), risk.RiskReason.DAILY_LOSS_LIMIT)

    def rearm(self):
        return self.store.rearm_risk_epoch(expected_epoch_id=self.store.get_current_risk_epoch().epoch_id,
                                           operator_at_ms=self.now_ms)

    def test_long_count_and_exact_economics_carry_then_hold_buys_nothing(self):
        parent = self.trip()
        config = self.store.get_risk_configuration()
        calls = list(self.session.calls)
        cp = self.store.get_checkpoint()
        child = self.rearm()
        self.assertEqual((child.book, child.entries_this_utc_day), (parent.book, 1))
        self.assertEqual(self.store.get_risk_configuration(), config)
        self.assertEqual(self.store.get_checkpoint(), cp)
        self.assertEqual(self.session.calls, calls)
        self.step("110")
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.store.get_latest_risk_valuation().epoch_id, child.epoch_id)

    def test_child_next_genuine_entry_counts_parent_authorization_once(self):
        self.trip()
        self.rearm()
        # Hold the accepted rearm mark until EMA naturally exits. A further
        # price decline would correctly retrip the child's tight daily limit.
        for _ in range(20):
            self.step("98")
            if self.store.get_checkpoint().snapshot.state is RuntimeState.FLAT:
                break
        else:
            self.fail("Synthetic EMA path did not produce its bounded EXIT.")
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.FLAT)
        result = self.step("110")
        self.assertIs(result.risk_verdict, risk.RiskVerdict.ALLOW)
        self.assertEqual(self.store.list_risk_verdicts()[-1].proposal_kind, risk.RiskActionKind.ENTRY)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 2)
        self.assertEqual(len(self.order_adapter.calls), 3)
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 2)

    def test_child_cannot_zero_carried_same_day_authorization_count(self):
        self.trip()
        child = self.rearm()
        self.assertEqual(child.entries_this_utc_day, 1)
        self.store._connection.execute("UPDATE risk_valuations SET entries_this_utc_day=0 WHERE epoch_id=?", (child.epoch_id,))
        with self.assertRaises(RuntimeStoreError):
            self.store.get_latest_risk_valuation()

    def test_restart_before_rearm_retains_parent_trip_then_after_retains_child(self):
        self.trip()
        self.restart_and_reconcile()
        parent = self.store.get_current_risk_epoch()
        self.assertEqual(parent.epoch_sequence, 1)
        self.assertIsNotNone(self.store.get_latest_risk_valuation().trip_reason)
        child = self.rearm()
        self.restart_and_reconcile()
        self.assertEqual(self.store.get_current_risk_epoch().epoch_id, child.epoch_id)
        self.assertEqual(self.store.get_latest_risk_valuation(), child)
        self.step("110")
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_both_latches_require_halt_rearm_then_real_frozen_reconciliation(self):
        parent = self.trip()
        cp = self.store.get_checkpoint()
        halted = replace(cp, sequence=cp.sequence + 1, halted_at_ms=self.now_ms,
            snapshot=transition_runtime_state(cp.snapshot, RuntimeEvent(
                RuntimeEventType.FATAL_INCONSISTENCY, reason=RuntimeReason.INCONSISTENT_EVIDENCE)))
        self.store.save_checkpoint(halted, expected_sequence=cp.sequence)
        with self.assertRaises(RuntimeStoreError):
            self.rearm()
        self.now_ms += 1
        calls = list(self.trace)
        self.store.rearm_runtime_halt(expected_sequence=halted.sequence, operator_at_ms=self.now_ms)
        self.assertEqual(self.trace, calls)
        self.assertEqual(self.store.get_latest_risk_valuation(), parent)
        with self.assertRaises(RuntimeStoreError):
            self.rearm()
        reconcile_startup(self.store, self.broker, utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.LONG)
        self.assertIsNone(self.rearm().trip_reason)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_price_recovery_does_not_rearm_automatically(self):
        self.trip()
        epoch = self.store.get_current_risk_epoch()
        self.step("1000")
        self.assertEqual(self.store.get_current_risk_epoch(), epoch)
        self.assertIsNotNone(self.store.get_latest_risk_valuation().trip_reason)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_midnight_retains_trip_and_explicit_rearm_carries_rollover_zero(self):
        self.prices, self.now_ms = ["100"] * 67, 67 * HOUR + 1000
        self.trip()
        epoch = self.store.get_current_risk_epoch()
        while self.store.get_latest_risk_valuation().valued_at_ms < 72 * HOUR:
            self.step("110")
        row = self.store.get_latest_risk_valuation()
        self.assertEqual(self.store.get_current_risk_epoch(), epoch)
        self.assertIsNotNone(row.trip_reason)
        self.assertEqual(row.entries_this_utc_day, 0)
        self.assertEqual(self.rearm().entries_this_utc_day, 0)

    def test_refused_entry_cannot_become_delayed_hold_buy_after_rearm(self):
        self.realized_loss()
        self.step("110")  # TRIP on a genuine fresh ENTRY, FLAT/desired=1.
        before = self.store.list_risk_valuations()
        with self.assertRaises(RuntimeStoreConflictError):
            self.rearm()
        self.assertEqual(self.store.list_risk_valuations(), before)
        self.step("110")  # Same-epoch refused HOLD, no delayed BUY.
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.step("1")  # Genuine LONG_EXIT aligns FLAT/desired=0; no exposure.
        self.assertEqual(self.store.get_checkpoint().snapshot.desired_position, 0)
        child = self.rearm()
        self.step("1")
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.assertEqual(self.store.get_latest_risk_valuation().epoch_id, child.epoch_id)
        self.assertIsNone(self.store.list_risk_verdicts(child.epoch_id)[-1].proposal_kind)


class GoldenRearmPreservationTests(integration_fixtures.IntegrationCase):
    def test_unused_controls_preserve_exact_golden_and_one_epoch(self):
        self.golden()  # Frozen exact IDs, quantities, fees and restart assertions.
        self.assertEqual(self.store.get_current_risk_epoch().epoch_sequence, 1)
        self.assertEqual(len({row.epoch_id for row in self.store.list_risk_valuations()}), 1)
        self.assertEqual((len(self.logical_history()), len(self.sends), len(self.store.list_fills()), len(self.cancels)),
                         (54, 2, 2, 0))


class RearmStructuralTests(unittest.TestCase):
    def test_controls_and_pure_helper_have_no_external_capability(self):
        forbidden = {"exchange", "pybit", "requests", "socket", "place_order", "cancel_order",
                     "get_account_state", "environ", "getenv", "sleep", "now", "initialize_risk_state"}
        for function in (risk.rearm_risk_state, RuntimeStore.rearm_runtime_halt, RuntimeStore.rearm_risk_epoch):
            tree = ast.parse(dedent(inspect.getsource(function)))
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            self.assertFalse(names & forbidden)
        tree = ast.parse(inspect.getsource(risk))
        self.assertEqual({node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)},
                         {"dataclasses", "decimal", "enum"})

    def test_exact_new_signatures_and_no_other_control_capabilities(self):
        self.assertEqual(list(inspect.signature(risk.rearm_risk_state).parameters),
                         ["config", "previous", "book", "mark_price", "valued_at_ms"])
        self.assertIn("rearm_risk_state", risk.__all__)
        self.assertEqual(list(inspect.signature(RuntimeStore.rearm_runtime_halt).parameters),
                         ["self", "expected_sequence", "operator_at_ms"])
        self.assertEqual(list(inspect.signature(RuntimeStore.rearm_risk_epoch).parameters),
                         ["self", "expected_epoch_id", "operator_at_ms"])
        self.assertEqual((persistence.SCHEMA_VERSION, persistence.RUNTIME_CONTRACT_VERSION), (2, 1))
        public = {name for name in vars(RuntimeStore) if not name.startswith("_")}
        self.assertEqual({name for name in public if "rearm" in name}, {"rearm_runtime_halt", "rearm_risk_epoch"})
        self.assertFalse(public & {"pause_risk", "manual_trip", "kill_switch", "clear_trip", "force_flat",
                                   "liquidate", "cancel_all", "edit_risk_config", "transaction"})


if __name__ == "__main__":
    unittest.main()
