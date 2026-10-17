"""Display-only ordering, confirmed cycles and bounded visualization math."""

from dataclasses import replace
from decimal import Decimal as D, localcontext
import unittest

from trading_lab.dashboard import *
from tests import test_dashboard_model as f

T, AT = f.T, f.AT


def cycle(*, pnl=None):
    opening = f.event_fixture(T.POSITION_OPEN_CONFIRMED, sequence=1, occurred=AT+1)
    details = {} if pnl is None else {"realized_trade_pnl_quote": pnl}
    closing = f.event_fixture(T.POSITION_CLOSE_CONFIRMED, sequence=2, occurred=AT+2, details=details)
    return opening, closing


class DashboardAnalyticsTests(unittest.TestCase):
    def model(self, events=(), **changes):
        return build_dashboard_model(f.health_fixture(), events, now_ms=AT, **changes)

    def test_deterministic_newest_order_observed_occurred_id(self):
        events = tuple(f.event_fixture(sequence=n, observed=AT+n//2, occurred=AT+n%2) for n in range(5))
        expected = tuple(sorted(events, key=lambda event: (event.observed_at_ms, event.occurred_at_ms, event.event_id), reverse=True))
        self.assertEqual(self.model(events).events, expected)
        self.assertEqual(self.model(tuple(reversed(events))).events, expected)

    def test_missing_occurrence_orders_explicitly_before_known_at_same_observation(self):
        known = f.event_fixture(sequence=1, occurred=AT)
        unknown = f.event_fixture(sequence=2, occurred=None)
        self.assertEqual(self.model((unknown, known)).events, (known, unknown))

    def test_duplicates_latest_observation_wins_without_source_mutation(self):
        original = f.event_fixture()
        later = replace(original, observed_at_ms=AT+1, run_id="1"*32)
        source = (later, original, later)
        self.assertEqual(self.model(source).events, (later,))
        self.assertEqual(source, (later, original, later))
        self.assertEqual(self.model(source).notices, ())

    def test_duplicate_time_tie_is_independent_of_input_order(self):
        first = f.event_fixture()
        second = replace(first, run_id="1"*32)
        a, b = self.model((first, second)), self.model((second, first))
        self.assertEqual(a.events, b.events)
        self.assertEqual(a.events, (max((first, second), key=lambda event: event.to_json()),))

    def test_default_recent_250_unique_and_hard_maximum(self):
        events = tuple(f.event_fixture(sequence=n, observed=AT+n) for n in range(1001))
        default = self.model(events)
        self.assertEqual(len(default.events), 250)
        self.assertEqual(default.events[0].observed_at_ms, AT+1000)
        self.assertIn(DashboardNotice.HISTORY_LIMITED, default.notices)
        self.assertEqual(len(self.model(events, limit=1000).events), 1000)

    def test_filters_preserve_order_and_warning_error_visibility(self):
        events = (f.event_fixture(), f.event_fixture(T.RUNTIME_HALTED), f.event_fixture(T.RUNTIME_UNCERTAIN))
        model = self.model(events)
        self.assertEqual(filter_events(model), model.events)
        self.assertEqual(len(filter_events(model, severities=("ERROR", "CRITICAL"))), 2)
        self.assertEqual(filter_events(model, event_types=("PROCESS_STARTED",)), (events[0],))

    def test_exact_percentage_rounded_only_for_display(self):
        with localcontext() as context:
            context.prec = 3
            self.assertEqual(display_percentage(D(1), D(3)), D("33.333333"))
            self.assertEqual(display_percentage(D("123456789.123456789"), D("1000000000")), D("12.345679"))
            self.assertEqual(context.prec, 3)
        self.assertEqual(display_percentage(D(0), D(1000)), D("0.000000"))
        self.assertIsNone(display_percentage(None, D(1000)))

    def test_invalid_display_ratios_rejected_without_epsilon(self):
        for values in ((D(1), D(0)), (D(-1), D(1)), (D("NaN"), D(1)), (1.0, D(1)), (D(1), True)):
            with self.subTest(values=values), self.assertRaises(DashboardError):
                display_percentage(*values)

    def test_chart_float_is_final_boundary_and_does_not_change_exact_data(self):
        points = ((AT, D("0.12345678901234567890123456789")), (AT+1, D(0)))
        rows = chart_rows(points)
        self.assertIs(type(rows[0]["Value"]), float)
        self.assertEqual(points[0][1], D("0.12345678901234567890123456789"))
        self.assertEqual(rows[1]["Value"], 0.0)
        for amount in (D("1E-400"), D("1E400"), D("NaN")):
            with self.assertRaises(DashboardError):
                chart_rows(((AT, amount),))

    def test_no_history_series_synthesized_from_health(self):
        model = self.model()
        self.assertEqual(history_series(model, "risk_equity"), ())
        self.assertEqual(history_series(model, "owned_base_quantity"), ())
        with self.assertRaises(DashboardError):
            history_series(model, "external_price")

    def test_series_only_exact_recorded_fields_and_times(self):
        events = (f.event_fixture(T.RISK_BLOCKED, details={"valued_at_ms": AT,
                    "risk_equity": D("999.123456789"), "daily_pnl": D("-0.876543211")}),
                  f.event_fixture(T.POSITION_OPEN_CONFIRMED))
        model = self.model(events)
        self.assertEqual(history_series(model, "risk_equity"), ((AT, D("999.123456789")),))
        self.assertEqual(history_series(model, "daily_pnl"), ((AT, D("-0.876543211")),))
        self.assertEqual(history_series(model, "owned_base_quantity"), ((AT, D("0.1")),))

    def test_closed_cycle_with_missing_pnl_stays_unavailable(self):
        model = self.model(cycle())
        self.assertEqual(len(model.trades), 1)
        self.assertIsNone(model.trades[0].realized_pnl_quote)
        self.assertEqual(format_value(model.trades[0].realized_pnl_quote), "Unavailable")
        self.assertEqual(model.trades[0].executions, ())

    def test_closed_cycle_uses_only_explicit_exact_pnl(self):
        for pnl in (D("1.12345678901234567890123456789"), D(0), D("-0.5")):
            with self.subTest(pnl=pnl):
                self.assertEqual(self.model(cycle(pnl=pnl)).trades[0].realized_pnl_quote, pnl)

    def test_ack_and_executions_alone_do_not_create_trade(self):
        events = (f.event_fixture(T.ACTION_PREPARED), f.event_fixture(T.ACTION_ACKNOWLEDGED),
                  f.event_fixture(T.OWNED_EXECUTION_DISCOVERED))
        model = build_dashboard_model(f.health_fixture(state="LONG"), events, now_ms=AT)
        self.assertEqual(model.trades, ())
        self.assertTrue(model.trade_history_incomplete)

    def test_current_long_does_not_manufacture_open_transition(self):
        model = build_dashboard_model(f.health_fixture(state="LONG"), now_ms=AT)
        self.assertEqual(model.trades, ())
        self.assertEqual(model.events, ())
        self.assertTrue(model.trade_history_incomplete)

    def test_process_only_history_is_incomplete_even_for_flat_snapshot(self):
        model = self.model((f.event_fixture(),))
        self.assertEqual(model.health.owned_base_quantity, D(0))
        self.assertEqual(model.trades, ())
        self.assertTrue(model.trade_history_incomplete)

    def test_old_closed_cycle_does_not_prove_current_open_history(self):
        model = build_dashboard_model(f.health_fixture(state="LONG"), cycle(), now_ms=AT)
        self.assertEqual(len(model.trades), 1)
        self.assertTrue(model.trade_history_incomplete)

    def test_orphan_close_and_quantity_gap_not_fabricated(self):
        opening, closing = cycle()
        for events in ((closing,), (opening, f.event_fixture(T.POSITION_CLOSE_CONFIRMED, sequence=2,
                                                    details={"previous_owned_base_quantity": D("0.2")}))):
            model = self.model(events)
            self.assertEqual(model.trades, ())
            self.assertTrue(model.trade_history_incomplete)

    def test_durable_checkpoint_order_survives_reversed_observation_order(self):
        opening, closing = cycle()
        opening = replace(opening, observed_at_ms=AT+100)
        model = self.model((closing, opening))
        self.assertEqual(len(model.trades), 1)
        self.assertEqual(model.events[0], opening)

    def test_conflicting_same_checkpoint_and_reversed_trade_time_are_incomplete(self):
        opening, closing = cycle()
        for bad in (f.event_fixture(T.POSITION_CLOSE_CONFIRMED, sequence=1),
                    replace(closing, occurred_at_ms=AT)):
            model = self.model((opening, bad))
            self.assertEqual(model.trades, ())
            self.assertTrue(model.trade_history_incomplete)

    def test_partial_inventory_transitions_and_exact_referenced_fees(self):
        opening = f.event_fixture(T.POSITION_OPEN_CONFIRMED, sequence=1,
                                 details={"contributing_execution_ids": ("buy1",)})
        growth = f.event_fixture(T.POSITION_QUANTITY_CHANGED, sequence=2,
            details={"previous_owned_base_quantity": D("0.1"), "owned_base_quantity": D("0.2"),
                     "contributing_execution_ids": ("buy2",)})
        reduction = f.event_fixture(T.POSITION_QUANTITY_CHANGED, sequence=3,
            details={"previous_owned_base_quantity": D("0.2"), "owned_base_quantity": D("0.05"),
                     "contributing_execution_ids": ("sell1",)})
        closing = f.event_fixture(T.POSITION_CLOSE_CONFIRMED, sequence=4,
            details={"previous_owned_base_quantity": D("0.05"), "contributing_execution_ids": ("sell2",)})
        fills = tuple(f.event_fixture(T.OWNED_EXECUTION_DISCOVERED, details={"broker_execution_id": name,
            "side": side, "execution_fee": D("-0.00000123456789"), "fee_currency": "USDT"})
            for name, side in (("buy1", "BUY"), ("buy2", "BUY"), ("sell1", "SELL"), ("sell2", "SELL")))
        model = self.model((opening, growth, reduction, closing) + fills)
        trade, = model.trades
        self.assertEqual(trade.initial_owned_quantity, D("0.1"))
        self.assertEqual(trade.pre_close_owned_quantity, D("0.05"))
        self.assertEqual(trade.entry_execution_ids, ("buy1", "buy2"))
        self.assertEqual(trade.exit_execution_ids, ("sell1", "sell2"))
        self.assertEqual(len(trade.executions), 4)
        self.assertTrue(all(execution.fee == D("-0.00000123456789") for execution in trade.executions))

    def test_risk_and_runtime_rearms_are_history_not_state_mutations(self):
        health = f.health_fixture(trip=True)
        before = health.to_json()
        events = tuple(f.event_fixture(kind) for kind in
            (T.RISK_TRIPPED, T.RISK_REARMED, T.RUNTIME_HALTED, T.RUNTIME_REARMED))
        model = build_dashboard_model(health, events, now_ms=AT)
        self.assertEqual(health.to_json(), before)
        self.assertEqual(model.health.risk_epoch_sequence, 1)
        self.assertEqual({event.event_type for event in model.events}, {event.event_type for event in events})

    def test_closing_entry_fill_references_do_not_mix_with_exit_contributions(self):
        opening, _ = cycle()
        closing = f.event_fixture(T.POSITION_CLOSE_CONFIRMED, sequence=2, occurred=AT+2,
            details={"entry_fills": ((("broker_execution_id", "buy1"),),),
                     "contributing_execution_ids": ("sell1",)})
        trade, = self.model((opening, closing)).trades
        self.assertEqual(trade.entry_execution_ids, ("buy1",))
        self.assertEqual(trade.exit_execution_ids, ("sell1",))
        self.assertEqual(trade.executions, ())  # A reference does not invent absent fee/price records.
