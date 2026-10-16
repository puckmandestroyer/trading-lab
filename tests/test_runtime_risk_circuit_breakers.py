"""Stage 11.5: exact breaker behavior through frozen offline runtime boundaries.

All fills, clocks and accounts come from the existing Stage 11.4 fake broker.
No policy calculation is replaced: the real cycle, planner, store and pure risk
engine run together against temporary SQLite journals.
"""

from dataclasses import replace
from decimal import Decimal as D
import unittest
from unittest.mock import patch

from trading_lab.data.closed_candles import MarketDataIntegrityError
from trading_lab.exchange.account_state import CurrencyBalance
from trading_lab.risk.runtime_risk import RiskActionKind, RiskBook, RiskReason, RiskVerdict
from trading_lab.runtime.cycle import CycleOutcome
from trading_lab.runtime.recovery import prepare_process_restart
from trading_lab.runtime.state import PositionEvidence, RuntimeReason, RuntimeState
from trading_lab.runtime.store import (
    ActionPhase, RiskValuationMode, RuntimeStore,
    RuntimeStoreError,
)
from tests import test_runtime_risk_gate as fixtures
from tests.test_runtime_cycle import OrderStatus
from tests.test_runtime_store import HOUR


class BreakerCase(fixtures.RiskGateCase):
    def owned_long(self, **changes):
        self.activate(max_daily_loss_fraction=changes.pop("max_daily_loss_fraction", D("0.0001")),
                      max_drawdown_fraction=changes.pop("max_drawdown_fraction", D(1)), **changes)
        self.assertIs(self.step("110").outcome, CycleOutcome.OBSERVED)
        self.assertIs(self.step("110").outcome, CycleOutcome.NOOP)
        row = self.store.get_latest_risk_valuation()
        self.assertEqual(row.book, RiskBook(D(995), D("0.05")))
        self.assertEqual(row.risk_equity, D("1000.5"))
        return row

    def assert_trip(self, result, reason):
        row = self.store.get_latest_risk_valuation()
        verdict = self.store.get_risk_verdict(row.candle_open_ms)
        self.assertEqual((result.outcome, result.risk_verdict, result.risk_reason),
                         (CycleOutcome.RISK_TRIPPED, RiskVerdict.TRIP, reason))
        self.assertEqual((verdict.verdict, verdict.reason), (RiskVerdict.TRIP, reason))
        self.assertIsNone(verdict.proposal_kind)
        self.assertIsNone(verdict.action_id)
        self.assertIs(row.mode, RiskValuationMode.LIVE)
        self.assertIs(row.trip_reason, reason)
        self.assertEqual(row.tripped_at_ms, row.valued_at_ms)
        self.assertFalse(row.trip_pending_report)
        self.assertIsNot(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertEqual(len(self.order_adapter.calls), 1)  # Only the original strategy ENTRY.
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))
        return row

    def restart_and_reconcile(self):
        history = self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        epoch = self.store.get_current_risk_epoch()
        prepare_process_restart(self.store)
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.STARTING)
        self.reopen()
        result = self.raw_cycle()  # Same market prefix: observations only, no new decision.
        self.assertIs(result.outcome, CycleOutcome.NO_NEW_DATA)
        self.assertIs(result.checkpoint.snapshot.position_evidence, PositionEvidence.CONFIRMED)
        self.assertEqual((self.store.list_risk_valuations(), self.store.list_risk_verdicts()), history)
        self.assertEqual(self.store.get_current_risk_epoch(), epoch)
        return result

    def exit_then_block_new_entry(self):
        # Let unchanged EMA produce its own EXIT. A bounded decline is needed
        # after a large profitable peak; no synthetic signal or risk SELL.
        for _ in range(20):
            result = self.step("1")
            verdict = self.store.list_risk_verdicts()[-1]
            if verdict.proposal_kind is RiskActionKind.EXIT:
                break
            self.assertIsNone(verdict.proposal_kind)
            self.assertEqual(len(self.order_adapter.calls), 1)
        else:
            self.fail("Synthetic EMA path did not produce an EXIT within its explicit bound.")
        self.assertIs(verdict.verdict, RiskVerdict.ALLOW)
        self.assertEqual(verdict.authorized_amount, D("0.05"))
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.FLAT)
        self.assertEqual(len(self.order_adapter.calls), 2)
        blocked = self.step("1000")
        self.assert_refused(blocked, RiskReason.RISK_LATCH_ACTIVE)
        self.assertEqual(len(self.order_adapter.calls), 2)
        return blocked


class DailyLossIntegrationTests(BreakerCase):
    def test_exact_daily_threshold_is_durable_trip_without_liquidation(self):
        self.owned_long()
        row = self.assert_trip(self.step("98"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual((row.risk_equity, row.daily_pnl), (D("999.9"), D("-0.1")))
        cfg = self.store.get_risk_configuration().configuration
        self.assertEqual(row.daily_pnl, -(cfg.risk_capital_quote * cfg.max_daily_loss_fraction))
        self.assertEqual(row.owned_base_quantity, D("0.05"))
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation(), row)

    def test_one_exact_quantum_above_daily_threshold_is_allowed_accounting(self):
        self.owned_long()
        result = self.step("98.01")
        row = self.store.get_latest_risk_valuation()
        # Hundredth-price fixture quantum * exact 0.05 owned BTC = 0.0005 USDT.
        quantum = D("0.01") * D("0.05")
        self.assertEqual(row.daily_pnl, D("-0.1") + quantum)
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        self.assertIsNone(row.trip_reason)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation(), row)

    def test_one_exact_quantum_beyond_daily_threshold_trips(self):
        self.owned_long()
        row = self.assert_trip(self.step("97.99"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(row.daily_pnl, D("-0.1") - D("0.01") * D("0.05"))

    def test_prior_profit_does_not_enlarge_fixed_capital_loss_allowance(self):
        self.prices, self.now_ms = ["100"] * 69, 69 * HOUR + 1000
        self.owned_long()
        self.step("300")  # Profitable midnight equity becomes the new daily baseline.
        peak = self.store.get_latest_risk_valuation()
        self.assertEqual((peak.risk_equity, peak.peak_risk_equity), (D(1010), D(1010)))
        self.assertEqual(peak.valued_at_ms, 72 * HOUR)
        row = self.assert_trip(self.step("298"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(row.utc_day_start_risk_equity, D(1010))
        self.assertEqual(row.risk_equity, D("1009.9"))
        self.assertEqual(row.daily_pnl, D("-0.1"))
        self.assertEqual(self.store.get_risk_configuration().risk_capital_quote, D(1000))


class DrawdownIntegrationTests(BreakerCase):
    def peak(self):
        self.owned_long(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.001"))
        self.step("300")
        peak = self.store.get_latest_risk_valuation()
        self.assertEqual(peak.peak_risk_equity, D(1010))
        return peak

    def test_new_durable_high_and_exact_drawdown_trip_while_still_profitable(self):
        peak = self.peak()
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation(), peak)
        row = self.assert_trip(self.step("279.8"), RiskReason.MAX_DRAWDOWN)
        self.assertEqual(row.risk_equity, D("1008.99"))
        self.assertGreater(row.risk_equity, D(1000))
        self.assertEqual(peak.peak_risk_equity - row.risk_equity, D(1010) * D("0.001"))

    def test_exact_quantum_before_drawdown_boundary_does_not_trip(self):
        self.peak()
        result = self.step("279.81")
        row = self.store.get_latest_risk_valuation()
        self.assertEqual(row.risk_equity, D("1008.9905"))
        self.assertEqual(row.peak_risk_equity, D(1010))
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        self.assertIsNone(row.trip_reason)

    def test_exact_quantum_beyond_drawdown_boundary_trips(self):
        self.peak()
        row = self.assert_trip(self.step("279.79"), RiskReason.MAX_DRAWDOWN)
        self.assertEqual(row.risk_equity, D("1008.9895"))

    def test_simultaneous_first_breach_keeps_daily_reason_and_original_time(self):
        self.owned_long(max_drawdown_fraction=D("0.0005"))
        row = self.assert_trip(self.step("98"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertGreaterEqual(row.peak_risk_equity - row.risk_equity,
                                row.peak_risk_equity * D("0.0005"))
        self.step("97")
        self.restart_and_reconcile()
        later = self.store.get_latest_risk_valuation()
        self.assertEqual((later.trip_reason, later.tripped_at_ms), (row.trip_reason, row.tripped_at_ms))


class MidnightBreakerTests(BreakerCase):
    def near_midnight(self, **changes):
        # Activation at 21:00, ENTRY at 22:00, HOLD at 23:00, then midnight.
        self.prices, self.now_ms = ["100"] * 69, 69 * HOUR + 1000
        return self.owned_long(**changes)

    def test_midnight_checks_outgoing_loss_then_rolls_without_clearing_trip(self):
        before = self.near_midnight()
        self.assertEqual(before.valued_at_ms, 71 * HOUR)
        self.assertEqual(before.entries_this_utc_day, 1)
        self.assertEqual(before.utc_day_start_risk_equity, D(1000))
        row = self.assert_trip(self.step("98"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(before.utc_day_start_risk_equity - row.risk_equity, D("0.1"))
        self.assertEqual((row.valued_at_ms, row.tripped_at_ms, row.utc_day_start_ms), (72 * HOUR,) * 3)
        self.assertEqual((row.utc_day_start_risk_equity, row.daily_pnl, row.entries_this_utc_day),
                         (D("999.9"), D(0), 0))
        self.step("130")
        self.assertEqual(self.store.get_latest_risk_valuation().tripped_at_ms, 72 * HOUR)

    def test_healthy_midnight_resets_day_and_count_but_preserves_peak_and_epoch(self):
        self.prices, self.now_ms = ["100"] * 69, 69 * HOUR + 1000
        self.activate(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.001"))
        self.step("110")
        self.step("300")
        before, epoch = self.store.get_latest_risk_valuation(), self.store.get_current_risk_epoch()
        result = self.step("280")
        row = self.store.get_latest_risk_valuation()
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        self.assertEqual((before.peak_risk_equity, row.risk_equity), (D(1010), D(1009)))
        self.assertEqual((row.utc_day_start_ms, row.utc_day_start_risk_equity, row.daily_pnl,
                          row.entries_this_utc_day, row.peak_risk_equity),
                         (72 * HOUR, D(1009), D(0), 0, D(1010)))
        self.assertIsNone(row.trip_reason)
        self.assertEqual(self.store.get_current_risk_epoch(), epoch)
        self.reopen()
        self.assertEqual(self.store.get_latest_risk_valuation(), row)
        later = self.assert_trip(self.step("279.8"), RiskReason.MAX_DRAWDOWN)
        self.assertEqual(later.peak_risk_equity, D(1010))
        self.assertEqual(later.daily_pnl, D("-0.01"))

    def test_existing_trip_survives_midnight_and_reset_count_cannot_rearm(self):
        self.prices, self.now_ms = ["100"] * 68, 68 * HOUR + 1000
        self.owned_long()
        tripped = self.assert_trip(self.step("98"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(tripped.valued_at_ms, 71 * HOUR)
        self.step("130")
        row = self.store.get_latest_risk_valuation()
        self.assertEqual((row.daily_pnl, row.entries_this_utc_day), (0, 0))
        self.assertEqual((row.trip_reason, row.tripped_at_ms), (tripped.trip_reason, tripped.tripped_at_ms))
        self.exit_then_block_new_entry()
        self.assertEqual(self.store.get_latest_risk_valuation().entries_this_utc_day, 0)


class RestartBreakerTests(BreakerCase):
    def test_daily_trip_survives_rebound_restart_reconciliation_and_new_entry(self):
        self.owned_long()
        tripped = self.assert_trip(self.step("98"), RiskReason.DAILY_LOSS_LIMIT)
        self.step("130")
        before = self.store.get_latest_risk_valuation()
        self.assertEqual(before.peak_risk_equity, D("1001.5"))
        result = self.restart_and_reconcile()
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.LONG)
        self.assertEqual(self.store.get_latest_risk_valuation(), before)
        self.exit_then_block_new_entry()
        latest = self.store.get_latest_risk_valuation()
        self.assertEqual((latest.trip_reason, latest.tripped_at_ms), (tripped.trip_reason, tripped.tripped_at_ms))

    def test_drawdown_trip_restart_preserves_peak_baseline_and_exact_exit_permission(self):
        self.owned_long(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.001"))
        self.step("300")
        tripped = self.assert_trip(self.step("279.8"), RiskReason.MAX_DRAWDOWN)
        self.restart_and_reconcile()
        self.assertEqual(self.store.get_latest_risk_valuation(), tripped)
        self.exit_then_block_new_entry()
        latest = self.store.get_latest_risk_valuation()
        self.assertEqual((latest.peak_risk_equity, latest.utc_day_start_risk_equity,
                          latest.trip_reason, latest.tripped_at_ms),
                         (D(1010), D(1000), RiskReason.MAX_DRAWDOWN, tripped.tripped_at_ms))


class ReplayBreakerTests(BreakerCase):
    def missed_breach(self, *, drawdown=False):
        self.owned_long(max_daily_loss_fraction=D(1) if drawdown else D("0.0001"),
                        max_drawdown_fraction=D("0.0001") if drawdown else D(1))
        before = self.store.get_latest_risk_valuation()
        self.advance("98", "130")
        self.assertIs(self.raw_cycle().outcome, CycleOutcome.REPLAY_ONLY)
        self.assertEqual(self.store.get_latest_risk_valuation(), before)
        result = self.step("130")  # Real cycle catches up both missing risk hours.
        reason = RiskReason.MAX_DRAWDOWN if drawdown else RiskReason.DAILY_LOSS_LIMIT
        self.assertIs(result.outcome, CycleOutcome.RISK_TRIPPED)
        self.assertIs(result.risk_reason, reason)
        missed, recovered, live = self.store.list_risk_valuations()[-3:]
        self.assertEqual([r.mode for r in (missed, recovered, live)],
                         [RiskValuationMode.REPLAY_ONLY, RiskValuationMode.REPLAY_ONLY, RiskValuationMode.LIVE])
        self.assertGreater(recovered.risk_equity, D(1000))
        for row in (missed, recovered, live):
            self.assertEqual((row.trip_reason, row.tripped_at_ms), (reason, missed.valued_at_ms))
        self.assertTrue(missed.trip_pending_report)
        self.assertTrue(recovered.trip_pending_report)
        self.assertFalse(live.trip_pending_report)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))
        self.exit_then_block_new_entry()

    def test_downtime_daily_breach_is_not_hidden_by_recovered_latest_mark(self):
        self.missed_breach()

    def test_downtime_drawdown_breach_is_not_hidden_by_recovered_latest_mark(self):
        self.missed_breach(drawdown=True)

    def test_restart_after_first_catchup_commit_resumes_next_missing_hour(self):
        self.owned_long()
        previous = self.store.get_latest_risk_valuation()
        self.advance("98", "130", "130")
        self.raw_cycle()
        self.advance("130")
        append = self.store.append_risk_replay_valuation
        def interrupted(**kwargs):
            append(**kwargs)
            raise RuntimeStoreError("Synthetic process death after first replay commit.")
        with patch.object(self.store, "append_risk_replay_valuation", side_effect=interrupted), \
             self.assertRaises(RuntimeStoreError):
            self.raw_cycle()
        partial = self.store.get_latest_risk_valuation()
        self.assertEqual(partial.valued_at_ms, previous.valued_at_ms + HOUR)
        self.assertIs(partial.trip_reason, RiskReason.DAILY_LOSS_LIMIT)
        prepare_process_restart(self.store)
        self.reopen()
        append = self.store.append_risk_replay_valuation
        with patch.object(self.store, "append_risk_replay_valuation", wraps=append) as resumed:
            result = self.raw_cycle()
        self.assertEqual([call.kwargs["candle_open_ms"] for call in resumed.call_args_list],
                         [partial.candle_open_ms + HOUR, partial.candle_open_ms + 2 * HOUR])
        rows = self.store.list_risk_valuations()
        self.assertEqual([row.valued_at_ms for row in rows],
                         list(range(rows[0].valued_at_ms, rows[-1].valued_at_ms + HOUR, HOUR)))
        self.assertIs(result.outcome, CycleOutcome.RISK_TRIPPED)
        self.assertEqual(rows[-1].tripped_at_ms, partial.tripped_at_ms)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))


class PendingLifecycleBreakerTests(BreakerCase):
    def test_open_ack_is_not_inventory_and_blocks_a_second_authorization(self):
        self.activate(max_daily_loss_fraction=D("0.0001"))
        self.broker.status = OrderStatus.OPEN
        entry = self.step("110")
        result = self.step("1")
        row, verdict = self.store.get_latest_risk_valuation(), self.store.list_risk_verdicts()[-1]
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(result.logical_action_id, entry.logical_action_id)
        self.assertEqual(row.book, RiskBook(D(1000), D(0)))
        self.assertEqual((row.risk_equity, row.daily_pnl, row.entries_this_utc_day), (D(1000), D(0), 1))
        self.assertIsNone(row.trip_reason)
        self.assertEqual((verdict.verdict, verdict.proposal_kind), (RiskVerdict.ALLOW, None))
        self.assertEqual(self.store.list_fills(), ())
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertEqual(len(self.store.list_actions()), 1)
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))

    def test_ack_then_partial_fee_trip_preserves_full_unresolved_authorization(self):
        self.activate(max_daily_loss_fraction=D("0.0001"))
        self.broker.status = OrderStatus.OPEN
        entry = self.step("110")
        self.step("110")
        self.assertEqual(self.store.get_latest_risk_valuation().owned_base_quantity, 0)
        params = next(params for name, params in self.session.calls if name == "place_order")
        self.broker.status, self.broker.fee, self.broker.fee_currency = OrderStatus.PARTIALLY_FILLED, D("0.1"), "USDT"
        self.broker.publish(params, "order-1")  # After prior cutoff, before next mark.
        row = self.assert_trip(self.step("100"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(row.book, RiskBook(D("997.9"), D("0.02")))
        self.assertEqual((row.risk_equity, row.entries_this_utc_day), (D("999.9"), 1))
        cp, action = self.store.get_checkpoint(), self.store.get_action(entry.logical_action_id)
        self.assertIs(cp.snapshot.state, RuntimeState.ORDER_PENDING)
        self.assertEqual(cp.snapshot.owned_base_quantity, D("0.02"))
        self.assertEqual(cp.snapshot.pending_action.logical_action_id, entry.logical_action_id)
        self.assertEqual(action.authorized_amount, self.config.buy_quote_budget)
        self.assertIs(action.phase, ActionPhase.ACKNOWLEDGED)
        self.assertEqual(len(self.store.list_actions()), 1)
        self.assertIsNone(self.store.list_risk_verdicts()[-1].proposal_kind)

    def test_partial_mark_drawdown_trips_without_cancelling_or_reducing_pending(self):
        self.activate(max_daily_loss_fraction=D(1), max_drawdown_fraction=D("0.0001"))
        self.broker.status = OrderStatus.PARTIALLY_FILLED
        entry = self.step("110")
        self.step("110")
        row = self.assert_trip(self.step("104"), RiskReason.MAX_DRAWDOWN)
        self.assertEqual((row.book, row.peak_risk_equity, row.risk_equity),
                         (RiskBook(D(998), D("0.02")), D("1000.2"), D("1000.08")))
        self.assertEqual(row.entries_this_utc_day, 1)
        self.assertEqual(self.store.get_checkpoint().snapshot.pending_action.logical_action_id, entry.logical_action_id)
        self.assertEqual(self.store.get_action(entry.logical_action_id).authorized_amount, self.config.buy_quote_budget)
        self.assertEqual(len(self.store.list_actions()), 1)


class ExposureSemanticsTests(BreakerCase):
    def test_position_appreciation_above_entry_cap_never_generates_sell_or_resize(self):
        self.owned_long()
        before = self.store.list_actions()
        result = self.step("11000")
        row = self.store.get_latest_risk_valuation()
        self.assertGreater(row.owned_base_quantity * row.mark_price,
                           self.store.get_risk_configuration().max_position_notional_quote)
        self.assertEqual(row.owned_base_quantity, D("0.05"))
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        self.assertIsNone(row.trip_reason)
        self.assertIsNone(self.store.list_risk_verdicts()[-1].proposal_kind)
        self.assertEqual(self.store.list_actions(), before)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_genuine_flat_entry_uses_matching_budget_within_ordered_caps(self):
        self.activate()
        self.assertIs(self.store.get_checkpoint().snapshot.state, RuntimeState.FLAT)
        self.assertEqual(self.store.get_checkpoint().snapshot.owned_base_quantity, 0)
        result = self.step("110")
        policy = self.store.get_risk_configuration()
        action = self.store.get_action(result.logical_action_id)
        self.assertEqual(action.authorized_amount, self.config.buy_quote_budget)
        self.assertEqual(action.authorized_amount, policy.buy_quote_budget)
        self.assertLessEqual(action.authorized_amount, policy.max_entry_notional_quote)
        self.assertLessEqual(policy.max_entry_notional_quote, policy.max_position_notional_quote)
        self.assertIs(result.risk_verdict, RiskVerdict.ALLOW)
        self.assertIsNone(result.risk_reason)


class WalletAndFeeBreakerTests(BreakerCase):
    def equivalent_wallet_scenarios(self, *, drawdown=False):
        observations = []
        # Independent temporary journals, same owned facts, different wallet totals.
        for huge in (False, True):
            case = fixtures.RiskGateCase("runTest")
            case.setUp()
            try:
                original = case.broker.get_account_state
                def account():
                    state = original()
                    if not huge:
                        return state
                    return replace(state, available_balance=D("1E20"), total_balance=D("1E20"),
                        total_equity=D("1E20"), balances=(
                            CurrencyBalance("BTC", D("1E10"), D("1E10"), D(0), D("1E10")),
                            CurrencyBalance("USDT", D("1E20"), D("1E20"), D(0), D("1E20"))))
                with patch.object(case.broker, "get_account_state", side_effect=account):
                    case.activate(max_daily_loss_fraction=D(1) if drawdown else D("0.0001"),
                                  max_drawdown_fraction=D("0.0005") if drawdown else D(1))
                    case.step("110")
                    case.step("110")
                    result = case.step("98")
                    observations.append((case.store.get_latest_risk_valuation(),
                                         case.store.get_risk_configuration(), result.risk_verdict,
                                         result.risk_reason, result.checkpoint.snapshot.owned_base_quantity))
            finally:
                case.doCleanups()
        self.assertEqual(observations[0], observations[1])
        self.assertEqual(observations[0][0].book, RiskBook(D(995), D("0.05")))
        self.assertEqual(observations[0][0].risk_equity, D("999.9"))
        self.assertEqual(observations[0][1].risk_capital_quote, D(1000))
        self.assertEqual(observations[0][2:], (RiskVerdict.TRIP,
            RiskReason.MAX_DRAWDOWN if drawdown else RiskReason.DAILY_LOSS_LIMIT, D("0.05")))

    def test_large_unrelated_btc_and_usdt_do_not_change_daily_breaker(self):
        self.equivalent_wallet_scenarios()

    def test_large_unrelated_btc_and_usdt_do_not_change_drawdown_breaker(self):
        self.equivalent_wallet_scenarios(drawdown=True)

    def fee_trip_once(self, fee, currency, expected_book):
        self.activate(max_daily_loss_fraction=D("0.0001"))
        self.broker.fee, self.broker.fee_currency = D(fee), currency
        self.step("110")
        row = self.assert_trip(self.step("100"), RiskReason.DAILY_LOSS_LIMIT)
        self.assertEqual(row.book, expected_book)
        self.assertEqual((row.risk_equity, row.daily_pnl, row.fill_evidence_count),
                         (D("999.9"), D("-0.1"), 1))
        fill = self.store.list_fills()[0]
        self.assertEqual((fill.execution_price, fill.execution_fee, fill.fee_currency), (D(100), D(fee), currency))
        self.restart_and_reconcile()
        self.step("100")
        later = self.store.get_latest_risk_valuation()
        self.assertEqual((later.book, later.risk_equity, later.fill_evidence_count),
                         (expected_book, D("999.9"), 1))
        self.assertEqual(later.tripped_at_ms, row.tripped_at_ms)
        self.assertEqual(len(self.store.list_fills()), 1)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_exact_durable_quote_fee_causes_trip_and_is_not_applied_twice(self):
        self.fee_trip_once("0.1", "USDT", RiskBook(D("994.9"), D("0.05")))

    def test_exact_durable_base_fee_causes_trip_and_is_not_applied_twice(self):
        self.fee_trip_once("0.001", "BTC", RiskBook(D(995), D("0.049")))


class FailClosedBreakerTests(BreakerCase):
    def test_unsupported_nonzero_fee_blocks_next_live_authorization(self):
        self.activate()
        self.broker.fee, self.broker.fee_currency = D("0.01"), "BNB"
        self.step("110")
        before = self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        with self.assertRaises(RuntimeStoreError):
            self.step("110")
        self.assertEqual((self.store.list_risk_valuations(), self.store.list_risk_verdicts()), before)
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertIsNone(self.store.get_decision(51 * HOUR))

    def test_corrupt_risk_history_cannot_reach_cycle_allow_or_another_order(self):
        self.owned_long()
        self.store._connection.execute("UPDATE risk_valuations SET daily_pnl='NaN' WHERE mode='LIVE'")
        with patch.object(self.store, "commit_live_risk_decision", wraps=self.store.commit_live_risk_decision) as commit, \
             self.assertRaises(RuntimeStoreError):
            self.step("110")
        commit.assert_not_called()
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_nonpositive_owned_risk_equity_fails_before_another_verdict(self):
        self.activate()
        self.broker.fee, self.broker.fee_currency = D(1000), "USDT"
        self.step("110")
        before = self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        with self.assertRaises(RuntimeStoreError):
            self.step("100")  # Durable fee makes exact equity zero, never ALLOW.
        self.assertEqual((self.store.list_risk_valuations(), self.store.list_risk_verdicts()), before)
        self.assertEqual(len(self.order_adapter.calls), 1)

    def test_operational_integrity_halt_precedes_otherwise_healthy_risk(self):
        self.owned_long()
        self.assertIsNone(self.store.get_latest_risk_valuation().trip_reason)
        before = self.store.list_risk_valuations(), self.store.list_risk_verdicts()
        self.market.error = MarketDataIntegrityError("Synthetic invalid authoritative market history.")
        with patch.object(self.store, "commit_live_risk_decision", wraps=self.store.commit_live_risk_decision) as commit:
            result = self.step("110")
        self.assertEqual((result.outcome, result.reason), (CycleOutcome.HALTED, RuntimeReason.INCONSISTENT_EVIDENCE))
        self.assertIs(result.checkpoint.snapshot.state, RuntimeState.HALTED)
        self.assertIsNone(result.risk_verdict)
        self.assertEqual((self.store.list_risk_valuations(), self.store.list_risk_verdicts()), before)
        commit.assert_not_called()
        self.assertEqual(len(self.order_adapter.calls), 1)
        self.assertFalse(any(name == "cancel_order" for name, _ in self.session.calls))


class StructuralBreakerBoundaryTests(unittest.TestCase):
    def test_public_store_capabilities_have_no_rearm_clear_or_second_epoch_writer(self):
        # Exact published public surface; risk remains epoch-1-only, not a new
        # operator control hidden under another name.
        self.assertEqual({name for name in vars(RuntimeStore) if not name.startswith("_")}, {
            "open", "migrate_v1_to_v2", "durability_settings", "get_configuration", "get_checkpoint",
            "get_candle", "get_decision", "get_action", "get_fill", "list_actions", "list_fills",
            "get_risk_configuration", "get_current_risk_epoch", "get_latest_risk_valuation",
            "list_risk_valuations", "get_risk_verdict", "list_risk_verdicts", "initialize_risk_journal",
            "append_risk_replay_valuation", "commit_live_risk_decision", "save_checkpoint", "commit_decision",
            "prepare_cancellation", "start_attempt", "abandon_prepared", "record_observation", "close",
        })


if __name__ == "__main__":
    unittest.main()
