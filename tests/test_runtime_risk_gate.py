"""Offline Decision 020 authorization, provenance and crash-boundary regressions."""

import ast
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal as D
import inspect
import hashlib
import sqlite3
from textwrap import dedent
import unittest
from unittest.mock import patch

from trading_lab.risk.runtime_risk import RiskActionKind, RiskReason, RiskVerdict
import trading_lab.runtime.cycle as cycle
import trading_lab.runtime.risk_gate as gate
import trading_lab.runtime.store as persistence
from trading_lab.runtime.planner import CanonicalDecision, DecisionMode, PlanKind, plan_action
from trading_lab.runtime.reconciliation import reconcile_startup
from trading_lab.runtime.recovery import prepare_process_restart
from trading_lab.runtime.state import (
    PositionEvidence, RuntimeEvent, RuntimeEventType, RuntimeReason, RuntimeState,
    transition_runtime_state,
)
from trading_lab.runtime.store import (
    ActionPhase, DecisionDisposition, JournalActionKind, RiskValuationMode,
    RuntimeStore, RuntimeStoreConflictError, RuntimeStoreError,
)
from tests.test_runtime_cycle import CycleCase, OrderStatus, utc
from tests.test_runtime_scheduler import SchedulerCase
from tests.test_runtime_store import HOUR, risk_configuration


class RiskGateCase(CycleCase):
    def raw_cycle(self):
        # Bypass ONLY the legacy fixture's explicit permissive activation hook.
        return cycle.run_single_cycle(self.store, self.market, self.broker, self.order_adapter,
                                      utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0)

    def activate(self, **changes):
        self.assertIs(self.raw_cycle().outcome, cycle.CycleOutcome.BOOTSTRAP)
        self.store.initialize_risk_journal(risk_configuration(**changes),
            candle_open_ms=self.store.get_checkpoint().last_processed_candle_ms)

    def step(self, price):
        self.advance(price)
        return self.raw_cycle()

    def count_block(self):
        self.activate(max_entries_per_utc_day=1)
        self.assertIs(self.step("110").outcome, cycle.CycleOutcome.OBSERVED)
        self.assertIs(self.step("80").outcome, cycle.CycleOutcome.OBSERVED)
        return self.step("110")

    def realized_loss(self):
        self.activate()
        self.step("110")
        self.broker.fee, self.broker.fee_currency = D(150), "USDT"
        self.step("80")
        self.broker.fee = D(0)

    def all_rows(self):
        return {name: tuple(tuple(row) for row in self.store._connection.execute(
                    "SELECT * FROM " + name + " ORDER BY rowid")) for name in persistence._SCHEMA}

    def planner_inputs(self, price="110"):
        self.advance(price)
        reconcile_startup(self.store, self.broker, utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0)
        cp = self.store.get_checkpoint()
        records, decisions = cycle._strategy_decisions(self.prefix(), self.config)
        decision = decisions[-1]
        plan = plan_action(self.config, cp, decision, evaluated_at_ms=self.now_ms,
                           mode=DecisionMode.LIVE, action_history=self.store.list_actions())
        proposed = cycle._proposed(cp, plan.events, self.now_ms,
                                   last_processed_candle_ms=decision.candle_open_ms)
        return records[-1], plan.decision, proposed, dict(expected_sequence=cp.sequence,
            evaluated_at_ms=self.now_ms, proposed_action=plan.action)

    def assert_refused(self, result, reason, verdict=RiskVerdict.BLOCK):
        self.assertIs(result.outcome, cycle.CycleOutcome.RISK_BLOCKED if verdict is RiskVerdict.BLOCK
                      else cycle.CycleOutcome.RISK_TRIPPED)
        self.assertIs(result.risk_verdict, verdict)
        self.assertIs(result.risk_reason, reason)
        snapshot = result.checkpoint.snapshot
        self.assertIs(snapshot.state, RuntimeState.FLAT)
        self.assertIs(snapshot.position_evidence, PositionEvidence.CONFIRMED)
        self.assertEqual(snapshot.owned_base_quantity, 0)
        self.assertEqual(snapshot.desired_position, 1)
        self.assertIsNone(snapshot.pending_action)
        decision = self.store.get_decision(result.checkpoint.last_processed_candle_ms)
        self.assertEqual((decision.signal, decision.desired_position, decision.disposition, decision.action_id),
                         ("LONG_ENTRY", 1, DecisionDisposition.WAIT, None))
        row = self.store.get_risk_verdict(decision.candle_open_ms)
        self.assertEqual((row.proposal_kind, row.authorized_amount, row.action_id),
                         (RiskActionKind.ENTRY, self.config.buy_quote_budget, None))
        self.assertFalse(any(action.candle_open_ms == decision.candle_open_ms for action in self.store.list_actions()))
        self.assertNotIn("cancel_order", [name for name, _ in self.session.calls])


class ActivationAndPolicyTests(RiskGateCase):
    def test_empty_journal_live_entry_has_no_commit_frontier_or_send(self):
        self.raw_cycle()
        before = self.store.get_checkpoint().last_processed_candle_ms
        self.advance("110")
        with patch.object(self.store, "initialize_risk_journal") as initialize, \
             patch.object(self.store, "commit_live_risk_decision") as commit:
            result = self.raw_cycle()
        self.assertIs(result.outcome, cycle.CycleOutcome.RISK_NOT_READY)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(result.checkpoint.last_processed_candle_ms, before)
        self.assertIsNone(self.store.get_decision(50 * HOUR))
        self.assertEqual((self.store.list_risk_valuations(), self.store.list_risk_verdicts(), self.store.list_actions()), ((), (), ()))
        self.assertIsNone(result.risk_verdict)
        initialize.assert_not_called()
        commit.assert_not_called()
        self.assert_no_send()

    def test_empty_journal_live_hold_does_not_consume_candle(self):
        self.raw_cycle()
        result = self.step("100")
        self.assertIs(result.outcome, cycle.CycleOutcome.RISK_NOT_READY)
        self.assertEqual(result.processed_candle_count, 0)
        self.assertEqual(result.checkpoint.last_processed_candle_ms, 49 * HOUR)
        self.assertIsNone(self.store.get_candle(50 * HOUR))
        self.assertEqual(self.store.list_actions(), ())
        self.assert_no_send()

    def test_empty_journal_legacy_long_has_no_exit_bypass(self):
        # Establish a legitimate pre-integration holding with the test's old
        # Stage 10 writes, not a fabricated wallet position or risk approval.
        self.raw_cycle()
        record, decision, cp, kwargs = self.planner_inputs()
        # This fixture explicitly represents a pre-risk journal (no cutoffs).
        current = self.store.get_checkpoint()
        legacy = replace(current, sequence=current.sequence + 1, bootstrap_until_ms=None)
        self.store._update("checkpoint", persistence._checkpoint_values(legacy), "singleton", 1)
        cp = replace(cp, sequence=legacy.sequence + 1, bootstrap_until_ms=None)
        self.store.commit_decision(record, decision, cp, expected_sequence=legacy.sequence,
                                   action=kwargs["proposed_action"])
        action = kwargs["proposed_action"]
        self.store.start_attempt(action.logical_action_id, replace(cp, sequence=cp.sequence + 1), expected_sequence=cp.sequence)
        self.broker.publish(dict(qty="10.1234567", side="Buy", orderLinkId=action.order_link_id), "order-1")
        reconcile_startup(self.store, self.broker, utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0)
        result = self.step("80")
        self.assertIs(result.outcome, cycle.CycleOutcome.RISK_NOT_READY)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertIsNone(self.store.get_decision(51 * HOUR))
        self.assertEqual(self.order_adapter.calls, [])

    def test_historical_bootstrap_and_replay_need_no_risk_journal(self):
        self.assertIs(self.raw_cycle().outcome, cycle.CycleOutcome.BOOTSTRAP)
        self.advance("110", "110")
        self.assertIs(self.raw_cycle().outcome, cycle.CycleOutcome.REPLAY_ONLY)
        self.assertIsNone(self.store.get_current_risk_epoch())
        self.assertEqual(self.store.get_checkpoint().last_processed_candle_ms, 51 * HOUR)
        self.assert_no_send()

    def test_healthy_entry_commits_matching_allow_and_prepared_before_preflight(self):
        self.activate()
        metadata = self.session.get_instruments_info
        def checked(**kwargs):
            action = self.store.get_action(self.pending_id())
            verdict = self.store.get_risk_verdict(action.candle_open_ms)
            self.assertIs(action.phase, ActionPhase.PREPARED)
            self.assertEqual((verdict.verdict, verdict.action_id), (RiskVerdict.ALLOW, action.logical_action_id))
            self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
            self.assertFalse(self.store._connection.in_transaction)
            return metadata(**kwargs)
        with patch.object(self.session, "get_instruments_info", side_effect=checked):
            result = self.step("110")
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.reopen()
        self.assertEqual(len(self.store.list_risk_verdicts()), 1)

    def test_genuine_daily_entry_count_block_is_atomic_and_has_no_new_action(self):
        result = self.count_block()
        self.assert_refused(result, RiskReason.ENTRY_COUNT_LIMIT)
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.assertEqual(len(self.store.list_actions()), 2)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)

    def test_new_realized_loss_entry_trips_without_pending_or_halt(self):
        self.realized_loss()
        result = self.step("110")
        self.assert_refused(result, RiskReason.DAILY_LOSS_LIMIT, RiskVerdict.TRIP)
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.assertFalse(self.store.get_latest_risk_valuation().trip_pending_report)

    def test_existing_latch_blocks_genuine_entry_without_broker_mutation(self):
        self.realized_loss()
        trip = self.step("80")
        self.assertIs(trip.outcome, cycle.CycleOutcome.RISK_TRIPPED)
        result = self.step("130")
        self.assert_refused(result, RiskReason.RISK_LATCH_ACTIVE)
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.assertEqual(self.store.get_latest_risk_valuation().tripped_at_ms, 53 * HOUR)

    def test_new_hold_drawdown_trip_preserves_long_and_never_sells(self):
        self.activate(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.0001"))
        self.step("110")
        self.step("110")
        result = self.step("105")
        self.assertIs(result.outcome, cycle.CycleOutcome.RISK_TRIPPED)
        self.assertIs(result.risk_reason, RiskReason.MAX_DRAWDOWN)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.05"))
        self.assertIsNone(self.store.get_risk_verdict(52 * HOUR).proposal_kind)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_tripped_exact_owned_exit_allows_without_clearing_latch(self):
        self.activate(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.0001"))
        self.step("110")
        self.step("110")
        self.step("105")
        previous = self.store.get_latest_risk_valuation()
        result = self.step("80")
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        verdict = self.store.get_risk_verdict(53 * HOUR)
        self.assertEqual((verdict.proposal_kind, verdict.authorized_amount), (RiskActionKind.EXIT, D("0.05")))
        latest = self.store.get_latest_risk_valuation()
        self.assertEqual((latest.trip_reason, latest.tripped_at_ms), (previous.trip_reason, previous.tripped_at_ms))
        self.assertEqual(len(self.order_adapter.calls), 2)

    def test_new_trip_on_exact_exit_allows_and_consumes_notification(self):
        self.activate(max_daily_loss_fraction=D("0.0001"))
        self.step("110")
        result = self.step("80")
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        row = self.store.get_latest_risk_valuation()
        self.assertIs(row.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        self.assertFalse(row.trip_pending_report)
        self.assertEqual(len(self.order_adapter.calls), 2)

    def test_healthy_live_noop_gets_accounting_only_allow(self):
        self.activate()
        result = self.step("100")
        self.assertIs(result.outcome, cycle.CycleOutcome.NOOP)
        verdict = self.store.list_risk_verdicts()[0]
        self.assertEqual((verdict.verdict, verdict.proposal_kind, verdict.authorized_amount, verdict.action_id),
                         (RiskVerdict.ALLOW, None, None, None))
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 0)
        self.assert_no_send()

    def test_pending_ack_allows_accounting_but_no_second_authorization(self):
        self.activate()
        self.broker.status = OrderStatus.OPEN
        first = self.step("110")
        result = self.step("80")
        self.assertIs(result.outcome, cycle.CycleOutcome.WAIT)
        self.assertEqual(result.logical_action_id, first.logical_action_id)
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, 0)
        self.assertIsNone(self.store.get_risk_verdict(51 * HOUR).proposal_kind)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)

    def test_partial_fill_preserves_full_lifecycle_and_consumed_count(self):
        self.activate()
        self.broker.status = OrderStatus.PARTIALLY_FILLED
        self.step("110")
        result = self.step("110")
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.02"))
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(self.store.get_latest_risk_valuation().owned_base_quantity, D("0.02"))
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_preflight_abandonment_never_refunds_entry_after_restart(self):
        self.activate()
        self.session.errors["get_instruments_info"] = TimeoutError("Synthetic preflight")
        result = self.step("110")
        self.assertIs(result.outcome, cycle.CycleOutcome.ABANDONED_UNSENT)
        rows = self.store.list_risk_verdicts()
        prepare_process_restart(self.store)
        self.reopen()
        self.assertEqual(self.store.list_risk_verdicts(), rows)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertEqual(self.store.list_actions()[0].attempt_count, 0)
        self.assert_no_send()

    def test_broker_rejection_keeps_consumed_entry_and_halt(self):
        self.activate()
        self.session.raw_ack = {"retCode": 10001}
        result = self.step("110")
        self.assertIs(result.outcome, cycle.CycleOutcome.HALTED)
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.REJECTED)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_ambiguous_placement_keeps_count_and_original_id_without_resend(self):
        self.activate()
        self.session.errors["place_order"] = TimeoutError("Synthetic transport ambiguity")
        result = self.step("110")
        action_id = result.logical_action_id
        self.reopen()
        prepare_process_restart(self.store)
        self.raw_cycle()
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertEqual(self.store.list_actions()[0].logical_action_id, action_id)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_abandoned_entry_still_blocks_next_genuine_entry_at_count_cap(self):
        self.activate(max_entries_per_utc_day=1)
        self.session.errors["get_instruments_info"] = TimeoutError("Synthetic preflight")
        self.step("110")
        self.session.errors.clear()
        self.step("80")
        result = self.step("110")
        self.assert_refused(result, RiskReason.ENTRY_COUNT_LIMIT)
        self.assertEqual(len(self.store.list_actions()), 1)
        self.assert_no_send()

    def test_pending_post_boundary_fill_is_not_applied_retroactively(self):
        self.activate()
        self.broker.status = OrderStatus.OPEN
        self.step("110")
        self.advance("110")
        params = next(params for name, params in self.session.calls if name == "place_order")
        self.broker.status = OrderStatus.PARTIALLY_FILLED
        self.broker.publish(params, "order-1")
        result = self.raw_cycle()
        self.assertEqual(result.checkpoint.snapshot.owned_base_quantity, D("0.02"))
        self.assertEqual(self.store.get_latest_risk_valuation().owned_base_quantity, 0)
        self.assertIsNone(self.store.list_risk_verdicts()[-1].proposal_kind)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_final_timing_refusal_keeps_consumed_allow_without_attempt(self):
        self.activate()
        metadata = self.session.get_instruments_info
        def delayed(**kwargs):
            response = metadata(**kwargs)
            self.now_ms += self.config.decision_max_age_ms
            return response
        with patch.object(self.session, "get_instruments_info", side_effect=delayed), \
             patch.object(self.store, "start_attempt", wraps=self.store.start_attempt) as attempt:
            result = self.step("110")
        self.assertIs(result.outcome, cycle.CycleOutcome.ABANDONED_UNSENT)
        attempt.assert_not_called()
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertIs(self.store.list_risk_verdicts()[0].verdict, RiskVerdict.ALLOW)
        self.assert_no_send()

    def test_unconfirmed_attempt_commit_stops_and_keeps_consumed_allow(self):
        self.activate()
        start = self.store.start_attempt
        def lost(*args, **kwargs):
            start(*args, **kwargs)
            raise RuntimeStoreError("Synthetic lost attempt return")
        with patch.object(self.store, "start_attempt", side_effect=lost), \
             patch.object(self.store, "abandon_prepared") as abandon, \
             patch.object(self.store, "record_observation") as observe, self.assertRaises(RuntimeStoreError):
            self.step("110")
        abandon.assert_not_called()
        observe.assert_not_called()
        self.assert_no_send()
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.ATTEMPT_STARTED)


class ContinuationTests(RiskGateCase):
    def test_blocked_entry_hold_continues_confirmed_flat_without_delayed_buy(self):
        self.count_block()
        result = self.step("110")
        self.assertIs(result.outcome, cycle.CycleOutcome.NOOP)
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(result.checkpoint.snapshot.desired_position, 1)
        verdict = self.store.list_risk_verdicts()[-1]
        self.assertEqual((verdict.verdict, verdict.proposal_kind, verdict.action_id), (RiskVerdict.ALLOW, None, None))
        self.assertEqual(len(self.order_adapter.calls), 2)

    def test_many_hold_continuations_survive_reopen_without_buy(self):
        self.count_block()
        for _ in range(3):
            self.reopen()
            result = self.step("110")
            self.assertIs(result.outcome, cycle.CycleOutcome.NOOP)
        self.assertEqual(len(self.order_adapter.calls), 2)
        self.assertEqual(len(self.store.list_actions()), 2)

    def test_midnight_entry_count_reset_never_resurrects_refused_buy_on_hold(self):
        self.prices, self.now_ms = ["100"] * 68, 68 * HOUR + 1000
        self.count_block()
        result = self.step("110")
        self.assertIs(result.outcome, cycle.CycleOutcome.NOOP)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 0)
        self.assertEqual(len(self.order_adapter.calls), 2)

    def proof_inputs(self):
        self.count_block()
        self.advance("110")
        reconcile_startup(self.store, self.broker, utc_now=lambda: utc(self.now_ms), monotonic=lambda: 1.0)
        cp = self.store.get_checkpoint()
        canonical = cycle._strategy_decisions(self.prefix(), self.config)[1][-1]
        actions = self.store.list_actions()
        plan = plan_action(self.config, cp, canonical, evaluated_at_ms=self.now_ms,
                           mode=DecisionMode.LIVE, action_history=actions)
        self.assertIs(plan.kind, PlanKind.HALT)
        epoch = self.store.get_current_risk_epoch()
        verdicts = {row.candle_open_ms: row for row in self.store.list_risk_verdicts()}
        history = tuple((self.store.get_decision(row.candle_open_ms), row, verdicts.get(row.candle_open_ms))
                        for row in self.store.list_risk_valuations())
        return cp, canonical, plan, dict(evaluated_at_ms=self.now_ms, epoch=epoch, history=history, action_history=actions)

    def test_complete_history_proof_is_deterministic_and_input_preserving(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        before = deepcopy((cp, canonical, plan, kwargs))
        first = gate.continue_refused_intent(self.config, cp, canonical, plan, **kwargs)
        self.assertIs(first.kind, PlanKind.NOOP)
        self.assertIsNone(first.action)
        self.assertEqual(first, gate.continue_refused_intent(self.config, cp, canonical, plan, **kwargs))
        self.assertEqual((cp, canonical, plan, kwargs), before)

    def test_each_missing_malformed_or_discontinuous_link_invalidates_proof(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        history = kwargs["history"]
        variants = [history[1:], history[:-1], history[:1] + history[2:],
                    (*history[:-1], (history[-1][0], history[-1][1], None)),
                    (*history[:-1], (None, history[-1][1], history[-1][2])),
                    (*history[:-1], (history[-1][0], replace(history[-1][1], epoch_id="f" * 64), history[-1][2])),
                    (*history[:-1], (history[-1][0], replace(history[-1][1], risk_configuration_digest="f" * 64), history[-1][2])),
                    (*history[:-1], (history[-1][0], replace(history[-1][1], mode=RiskValuationMode.REPLAY_ONLY), history[-1][2])),
                    (*history[:-1], (replace(history[-1][0], signal="LONG_EXIT", desired_position=0), *history[-1][1:])),
                    (*history[:-1], (replace(history[-1][0], signal="HOLD", desired_position=0), *history[-1][1:]))]
        for altered in variants:
            with self.subTest(history_length=len(altered)):
                self.assertEqual(gate.continue_refused_intent(self.config, cp, canonical, plan,
                    **{**kwargs, "history": altered}), plan)
        malformed = deepcopy(history)
        object.__setattr__(malformed[-1][1], "entries_this_utc_day", True)
        self.assertEqual(gate.continue_refused_intent(self.config, cp, canonical, plan,
                         **{**kwargs, "history": malformed}), plan)

    def test_bound_exhaustion_does_not_use_a_convenient_suffix(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        with patch.object(gate, "_MAX_HISTORY", 2):
            self.assertEqual(gate.continue_refused_intent(self.config, cp, canonical, plan, **kwargs), plan)

    def test_action_at_refusal_origin_invalidates_the_chain(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        origin = kwargs["history"][-1][0].candle_open_ms
        action = replace(kwargs["action_history"][0], candle_open_ms=origin)
        self.assertEqual(gate.continue_refused_intent(self.config, cp, canonical, plan,
                         **{**kwargs, "action_history": (*kwargs["action_history"], action)}), plan)

    def test_expired_hold_mismatch_is_never_overridden(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        self.assertEqual(gate.continue_refused_intent(self.config, cp, canonical, plan,
            **{**kwargs, "evaluated_at_ms": canonical.available_at_ms + self.config.decision_max_age_ms + 1}), plan)

    def test_independent_operational_halt_reconcile_and_wait_remain_unchanged(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        for kind, reason in ((PlanKind.HALT, RuntimeReason.OWNERSHIP_CONFLICT),
                             (PlanKind.RECONCILE, RuntimeReason.EVIDENCE_MISSING),
                             (PlanKind.WAIT, RuntimeReason.EVIDENCE_MISSING)):
            other = cycle.plan_action(self.config, cp, canonical, evaluated_at_ms=self.now_ms,
                                      mode=DecisionMode.LIVE, action_history=self.store.list_actions())
            other = replace(other, kind=kind, reason=reason)
            self.assertEqual(gate.continue_refused_intent(self.config, cp, canonical, other, **kwargs), other)

    def test_stale_reconciliation_and_historical_cutoff_cannot_be_overridden(self):
        cp, canonical, plan, kwargs = self.proof_inputs()
        for changed in (replace(cp, observed_at_ms=0), replace(cp, last_reconciled_at_ms=None),
                        replace(cp, replay_until_ms=canonical.candle_open_ms)):
            self.assertEqual(gate.continue_refused_intent(self.config, changed, canonical, plan, **kwargs), plan)

    def test_store_independently_rejects_caller_forged_continuation(self):
        self.activate()
        # Historical desired LONG alone is deliberately not refusal provenance.
        self.advance("110", "110")
        self.raw_cycle()
        self.store.append_risk_replay_valuation(candle_open_ms=50 * HOUR)
        self.store.append_risk_replay_valuation(candle_open_ms=51 * HOUR)
        record, decision, proposed, kwargs = self.planner_inputs("110")
        self.assertIs(decision.disposition, DecisionDisposition.HALT)
        forged = replace(decision, disposition=DecisionDisposition.NOOP)
        cp = self.store.get_checkpoint()
        proposed = replace(cp, sequence=cp.sequence + 1, last_processed_candle_ms=record.candle_open_ms)
        before = self.all_rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(record, forged, proposed, **kwargs)
        self.assertEqual(self.all_rows(), before)


class ReplayAndEvidenceTests(RiskGateCase):
    def test_exact_live_replay_changes_nothing_and_sends_nothing(self):
        self.activate()
        inputs = self.planner_inputs()
        self.assertTrue(self.store.commit_live_risk_decision(*inputs[:3], **inputs[3]))
        before = self.all_rows()
        self.assertFalse(self.store.commit_live_risk_decision(*inputs[:3], **inputs[3]))
        self.assertEqual(self.all_rows(), before)
        self.assert_no_send()

    def test_conflicting_live_replay_cannot_reauthorize(self):
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        self.store.commit_live_risk_decision(record, decision, cp, **kwargs)
        before = self.all_rows()
        # Keep OHLC valid while deliberately changing accepted raw evidence.
        altered = replace(record, open=D(109), high=D(109), low=D(109), close=D(109))
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(altered, decision, cp, **kwargs)
        self.assertEqual(self.all_rows(), before)

    def test_exact_block_replay_has_no_action_or_second_count(self):
        self.activate(max_entries_per_utc_day=1)
        self.step("110")
        self.step("80")
        args = self.planner_inputs()
        self.store.commit_live_risk_decision(*args[:3], **args[3])
        before = self.all_rows()
        self.assertFalse(self.store.commit_live_risk_decision(*args[:3], **args[3]))
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(len(self.store.list_actions()), 2)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)

    def test_changed_evaluation_time_is_a_conflicting_replay(self):
        self.activate()
        args = self.planner_inputs()
        self.store.commit_live_risk_decision(*args[:3], **args[3])
        before = self.all_rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(*args[:3], **{**args[3], "evaluated_at_ms": self.now_ms + 1})
        self.assertEqual(self.all_rows(), before)

    def test_caller_cannot_replace_owned_quantity_or_checkpoint_fields(self):
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        before = self.all_rows()
        for altered in (replace(cp, observed_at_ms=cp.observed_at_ms + 1),
                        replace(cp, snapshot=replace(cp.snapshot, owned_base_quantity=D("0.01"))),
                        replace(cp, bootstrap_until_ms=decision.candle_open_ms)):
            with self.subTest(sequence=altered.sequence), self.assertRaises(RuntimeStoreConflictError):
                self.store.commit_live_risk_decision(record, decision, altered, **kwargs)
            self.assertEqual(self.all_rows(), before)

    def test_live_gap_and_stale_cas_commit_nothing(self):
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        before = self.all_rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(record, decision, cp,
                **{**kwargs, "expected_sequence": kwargs["expected_sequence"] - 1})
        later = replace(record, candle_open_ms=record.candle_open_ms + HOUR)
        later_decision = replace(decision, candle_open_ms=later.candle_open_ms,
                                 available_at_ms=decision.available_at_ms + HOUR)
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(later, later_decision, cp, **kwargs)
        self.assertEqual(self.all_rows(), before)

    def test_risk_history_count_and_decision_corruption_fail_on_reopen(self):
        self.activate()
        self.step("110")
        self.store.close()
        with sqlite3.connect(self.lock.database_path) as connection:
            connection.execute("UPDATE risk_valuations SET entries_this_utc_day=0 WHERE mode='LIVE'")
        with self.assertRaises(RuntimeStoreError):
            RuntimeStore.open(self.lock, self.config)

    def test_constructed_oversized_planner_amount_is_rejected_not_runtime_block(self):
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        before = self.all_rows()
        altered = replace(kwargs["proposed_action"], authorized_amount=D(300))
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(record, decision, cp, **{**kwargs, "proposed_action": altered})
        self.assertEqual(self.all_rows(), before)

    def test_legacy_commit_cannot_bypass_classified_live_authorization(self):
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        before = self.all_rows()
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_decision(record, decision, cp, expected_sequence=kwargs["expected_sequence"],
                                       action=kwargs["proposed_action"])
        self.assertEqual(self.all_rows(), before)

    def test_late_predecessor_fill_including_exact_boundary_blocks_live(self):
        self.activate()
        self.broker.status = OrderStatus.OPEN
        self.step("110")
        self.step("110")
        previous = self.store.get_latest_risk_valuation()
        observed = self.now_ms
        self.now_ms = previous.valued_at_ms
        params = next(params for name, params in self.session.calls if name == "place_order")
        self.broker.status = OrderStatus.FILLED
        self.broker.publish(params, "order-1")
        self.now_ms = observed
        self.raw_cycle()  # Reconcile the legitimate late report; no new candle.
        before = self.store.list_risk_valuations(), self.store.list_risk_verdicts(), self.store.get_checkpoint().last_processed_candle_ms
        with self.assertRaisesRegex(RuntimeStoreConflictError, "Predecessor"):
            self.step("110")
        self.assertEqual((self.store.list_risk_valuations(), self.store.list_risk_verdicts(),
                          self.store.get_checkpoint().last_processed_candle_ms), before)
        self.assertEqual(self.store.get_latest_risk_valuation(), previous)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_post_boundary_inventory_cannot_be_used_for_closed_boundary_exit(self):
        self.activate()
        self.broker.status = OrderStatus.OPEN
        self.step("110")
        self.advance("80")
        params = next(params for name, params in self.session.calls if name == "place_order")
        self.broker.status = OrderStatus.FILLED
        self.broker.publish(params, "order-1")  # fill is after the current candle's cutoff
        with self.assertRaisesRegex(RuntimeStoreConflictError, "closed-boundary"):
            self.raw_cycle()
        self.assertIsNone(self.store.get_decision(51 * HOUR))
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_historical_catchup_latches_missed_trip_without_historical_send(self):
        self.activate(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.0001"))
        self.step("110")
        self.step("110")
        self.advance("105", "110")
        self.assertIs(self.raw_cycle().outcome, cycle.CycleOutcome.REPLAY_ONLY)
        old = self.store.get_latest_risk_valuation()
        self.reopen()
        result = self.step("110")
        self.assertIs(result.outcome, cycle.CycleOutcome.RISK_TRIPPED)
        rows = self.store.list_risk_valuations()
        self.assertEqual([row.mode for row in rows[-3:]], [RiskValuationMode.REPLAY_ONLY, RiskValuationMode.REPLAY_ONLY, RiskValuationMode.LIVE])
        self.assertEqual(rows[-1].tripped_at_ms, old.valued_at_ms + HOUR)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_failed_replay_stops_before_live_and_restarts_from_missing_hour(self):
        self.activate()
        self.advance("100", "100")
        self.raw_cycle()
        self.advance("110")
        with patch.object(self.store, "append_risk_replay_valuation", side_effect=RuntimeStoreError("Synthetic replay fault")), \
             patch.object(self.store, "commit_live_risk_decision") as live, self.assertRaises(RuntimeStoreError):
            self.raw_cycle()
        live.assert_not_called()
        self.assert_no_send()
        self.reopen()
        self.assertIs(self.raw_cycle().outcome, cycle.CycleOutcome.OBSERVED)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_authorization_day_mismatch_fails_without_relabeling_time(self):
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        before = self.all_rows()
        # A wide valid operational age permits isolating the UTC-day guard.
        # The ordinary short age already fails closed at the planner boundary.
        with self.assertRaises(RuntimeStoreConflictError):
            self.store.commit_live_risk_decision(record, decision, cp,
                **{**kwargs, "evaluated_at_ms": 72 * HOUR})
        self.assertEqual(self.all_rows(), before)


class AtomicRiskCommitTests(RiskGateCase):
    def ready(self):
        self.activate()
        return self.planner_inputs()

    def fail_insert(self, target):
        args = self.ready()
        before = self.all_rows()
        insert = self.store._insert
        def fault(table, values):
            insert(table, values)
            if table == target:
                raise sqlite3.OperationalError("Synthetic insertion failure")
        with patch.object(self.store, "_insert", side_effect=fault), self.assertRaises(RuntimeStoreError):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.reopen()
        self.assertEqual(self.all_rows(), before)
        self.assert_no_send()

    def test_candle_insertion_failure_rolls_back_all_authority(self):
        self.fail_insert("candles")

    def test_action_insertion_failure_rolls_back_all_authority(self):
        self.fail_insert("actions")

    def test_decision_insertion_failure_rolls_back_all_authority(self):
        self.fail_insert("decisions")

    def test_valuation_insertion_failure_rolls_back_all_authority(self):
        self.fail_insert("risk_valuations")

    def test_verdict_insertion_failure_rolls_back_all_authority(self):
        self.fail_insert("risk_verdicts")

    def test_checkpoint_cas_failure_rolls_back_inserted_records(self):
        args = self.ready()
        before = self.all_rows()
        with patch.object(self.store, "_save_checkpoint", side_effect=RuntimeStoreConflictError("Synthetic CAS")), self.assertRaises(RuntimeStoreError):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.reopen()
        self.assertEqual(self.all_rows(), before)

    def test_final_full_validation_failure_rolls_back_all_records(self):
        args = self.ready()
        before = self.all_rows()
        validate = self.store._validate_all
        def fault():
            if self.store._connection.execute("SELECT 1 FROM risk_verdicts").fetchone():
                raise RuntimeStoreError("Synthetic final validation")
            validate()
        with patch.object(self.store, "_validate_all", side_effect=fault), self.assertRaises(RuntimeStoreError):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.reopen()
        self.assertEqual(self.all_rows(), before)

    def test_commit_failure_rolls_back_all_records(self):
        args = self.ready()
        before = self.all_rows()
        with patch.object(self.store, "_commit", side_effect=sqlite3.OperationalError("Synthetic commit")), self.assertRaises(RuntimeStoreError):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.reopen()
        self.assertEqual(self.all_rows(), before)

    def test_lost_commit_return_closes_then_reopens_complete_authorization(self):
        args = self.ready()
        commit = self.store._commit
        def lost():
            commit()
            raise sqlite3.OperationalError("Synthetic lost return")
        with patch.object(self.store, "_commit", side_effect=lost), self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.assertIsNone(self.store._connection)
        self.assert_no_send()
        self.reopen()
        self.assertEqual(len(self.store.list_risk_verdicts()), 1)
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 1)
        self.assertIs(self.store.list_actions()[0].phase, ActionPhase.PREPARED)
        self.assertFalse(self.store.commit_live_risk_decision(*args[:3], **args[3]))

    def test_rollback_failure_requires_reopen_without_partial_authorization(self):
        args = self.ready()
        before = self.all_rows()
        connection = self.store._connection
        class FaultConnection:
            def __getattr__(self, name):
                return getattr(connection, name)

            def execute(self, sql, *values):
                if sql.startswith("INSERT INTO risk_verdicts") or sql == "ROLLBACK":
                    raise sqlite3.OperationalError("Synthetic rollback uncertainty")
                return connection.execute(sql, *values)
        with patch.object(self.store, "_connection", FaultConnection()), self.assertRaisesRegex(RuntimeStoreError, "reopening"):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.reopen()
        self.assertEqual(self.all_rows(), before)
        self.assert_no_send()

    def test_block_verdict_failure_rolls_back_frontier_and_refusal(self):
        self.activate(max_entries_per_utc_day=1)
        self.step("110")
        self.step("80")
        args = self.planner_inputs()
        before = self.all_rows()
        insert = self.store._insert
        def fail(table, values):
            if table == "risk_verdicts":
                raise RuntimeStoreError("Synthetic refusal write failure")
            insert(table, values)
        with patch.object(self.store, "_insert", side_effect=fail), self.assertRaises(RuntimeStoreError):
            self.store.commit_live_risk_decision(*args[:3], **args[3])
        self.reopen()
        self.assertEqual(self.all_rows(), before)
        self.assertEqual(len(self.order_adapter.calls), 2)


class WideAuthorizationDayTests(RiskGateCase):
    def runtime_configuration(self):
        return replace(super().runtime_configuration(), decision_max_age_ms=4 * HOUR,
                       observation_max_age_ms=4 * HOUR)

    def test_operationally_fresh_cross_day_authorization_is_rejected(self):
        self.prices, self.now_ms = ["100"] * 70, 70 * HOUR + 1000
        self.activate()
        record, decision, cp, kwargs = self.planner_inputs()
        self.assertEqual(decision.available_at_ms, 71 * HOUR)
        later_ms = 72 * HOUR
        # Frozen operational planning permits this age, but policy attribution
        # cannot put a prior-day valuation count into the next authorization day.
        original = self.store.get_checkpoint()
        fresh = replace(original, sequence=original.sequence + 1,
                        observed_at_ms=later_ms, last_reconciled_at_ms=later_ms)
        self.store.save_checkpoint(fresh, expected_sequence=original.sequence)
        plan = plan_action(self.config, fresh, CanonicalDecision(decision.symbol, decision.timeframe,
            decision.candle_open_ms, decision.input_fingerprint, decision.signal,
            decision.desired_position, decision.available_at_ms), evaluated_at_ms=later_ms,
            mode=DecisionMode.LIVE, action_history=self.store.list_actions())
        self.assertIs(plan.kind, PlanKind.PLACE_BUY)
        cp = cycle._proposed(fresh, plan.events, later_ms, last_processed_candle_ms=record.candle_open_ms)
        before = self.all_rows()
        with self.assertRaisesRegex(RuntimeStoreConflictError, "UTC days"):
            self.store.commit_live_risk_decision(record, plan.decision, cp, expected_sequence=fresh.sequence,
                evaluated_at_ms=later_ms, proposed_action=plan.action)
        self.assertEqual(self.all_rows(), before)


class RiskSchedulerTests(SchedulerCase):
    def assert_nonretryable(self, outcome):
        self.effects = [lambda: self.result(outcome, RuntimeReason.EVIDENCE_MISSING)]
        self.assertEqual(self.run_scheduler().cycle_count, 1)
        self.assertEqual(self.stop.waits, [1380.0])
        self.assertNotIn(1.0, self.stop.waits)
        self.assertNotIn(2.0, self.stop.waits)

    def test_risk_not_ready_has_no_immediate_retry(self):
        self.assert_nonretryable(cycle.CycleOutcome.RISK_NOT_READY)

    def test_risk_blocked_has_no_immediate_retry(self):
        self.assert_nonretryable(cycle.CycleOutcome.RISK_BLOCKED)

    def test_risk_tripped_has_no_immediate_retry(self):
        self.assert_nonretryable(cycle.CycleOutcome.RISK_TRIPPED)


class StructuralRiskBoundaryTests(unittest.TestCase):
    def test_frozen_post_authorization_send_flow_is_byte_identical(self):
        marker = "        action_id = plan.action.logical_action_id\n"
        tail = inspect.getsource(cycle).split(marker)[1]
        # Exclude only the separately approved post-action reconciliation
        # callback forwarding. Every other send-path byte keeps its old hash.
        approved = ("        final = reconcile_startup(store, broker, utc_now=utc_now, monotonic=monotonic,\n"
                    "                                  reconciliation_observer=reconciliation_observer)\n")
        self.assertEqual(tail.count(approved), 1)
        tail = tail.replace(approved,
            "        final = reconcile_startup(store, broker, utc_now=utc_now, monotonic=monotonic)\n")
        self.assertEqual(hashlib.sha256(tail.encode()).hexdigest(),
                         "373e7474c034079881ccb6b4e9e81eff48f999eefc1522f0c5829f7ff403e6fe")

    def test_gate_and_atomic_store_have_no_network_or_broker_capability(self):
        for source in (inspect.getsource(gate), inspect.getsource(RuntimeStore.commit_live_risk_decision)):
            tree = ast.parse(dedent(source))
            forbidden = {"pybit", "requests", "socket", "exchange", "place_order", "cancel_order", "environ", "getenv"}
            names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
            names |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
            imports = [node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)]
            imports += [alias.name for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names]
            self.assertFalse(names & forbidden)
            self.assertFalse(any(set(name.split(".")) & forbidden for name in imports))

    def test_only_one_new_public_risk_mutation_and_no_rearm(self):
        methods = {name for name in vars(RuntimeStore) if not name.startswith("_")}
        self.assertIn("commit_live_risk_decision", methods)
        self.assertFalse(methods & {"write_live_valuation", "write_verdict", "rearm", "operator_trip", "transaction"})
        self.assertEqual((persistence.SCHEMA_VERSION, persistence.RUNTIME_CONTRACT_VERSION), (2, 1))

    def test_no_proposal_is_not_an_entry_or_an_action(self):
        self.assertIsNone(gate.risk_proposal(None))

    def test_exact_entry_and_exit_amounts_are_preserved_without_coercion(self):
        from tests.test_runtime_store import prepared
        entry = prepared()
        exit_action = replace(entry, kind=JournalActionKind.EXIT, side="SELL", amount_unit="BASE",
                              currency="BTC", authorized_amount=D("0.123456789012345678901"))
        for action in (entry, exit_action):
            before = deepcopy(action)
            proposal = gate.risk_proposal(action)
            self.assertEqual(proposal.kind.value, action.kind.value)
            self.assertEqual(proposal.authorized_amount.as_tuple(), action.authorized_amount.as_tuple())
            self.assertEqual(action, before)

    def test_cancellation_attempted_or_malformed_actions_are_not_proposals(self):
        from tests.test_runtime_store import prepared
        attempted = replace(prepared(), phase=ActionPhase.ATTEMPT_STARTED, attempt_count=1)
        for action in (attempted, {}, True):
            with self.subTest(kind=type(action)), self.assertRaises(RuntimeStoreError):
                gate.risk_proposal(action)


if __name__ == "__main__":
    unittest.main()
