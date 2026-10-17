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


class DashboardPerformanceAnalyticsTests(unittest.TestCase):
    def model(self, equity="1125.25", events=(), capital="1000", **changes):
        return build_dashboard_model(f.performance_health(equity, capital, **changes), events, now_ms=AT)

    def test_positive_current_performance_exact_decimal(self):
        performance = self.model().performance
        self.assertEqual(performance.net_pnl_quote, D("125.25"))
        self.assertEqual(performance.return_percent, D("12.525"))
        self.assertIs(type(performance.return_percent), D)

    def test_negative_current_performance_exact_decimal(self):
        performance = self.model("900").performance
        self.assertEqual(performance.net_pnl_quote, D("-100"))
        self.assertEqual(performance.return_percent, D("-10"))

    def test_genuine_zero_performance_is_not_unavailable(self):
        performance = self.model("1000").performance
        self.assertEqual(performance.net_pnl_quote, D(0))
        self.assertEqual(performance.return_percent, D(0))

    def test_high_precision_capital_equity_history_and_text_without_float_loss(self):
        capital = "1000000000000000000000000000000"
        equity = "1125250000000000000000000000000.1234567890123456789"
        health = f.performance_health(equity, capital)
        event = f.risk_observation(equity, digest=health.risk_configuration_digest)
        with localcontext() as context:
            context.prec = 200
            expected_pnl = D(equity)-D(capital)
            expected_return = expected_pnl*100/D(capital)
        with localcontext() as context:
            context.prec = 3
            model = build_dashboard_model(health, (event,), now_ms=AT)
            self.assertEqual(model.performance.net_pnl_quote, expected_pnl)
            self.assertEqual(model.performance.return_percent, expected_return)
            self.assertEqual(performance_series(model), ((3_600_000, expected_return),))
            self.assertEqual(context.prec, 3)
        self.assertEqual(format_value(model.performance.net_pnl_quote),
            "125250000000000000000000000000.1234567890123456789")
        self.assertEqual(format_percent(expected_return, detailed=True),
            "+12.52500000000000000000000000001234567890123456789%")

    def test_known_retained_returns_exact_without_interpolation(self):
        digest = f.health_fixture().risk_configuration_digest
        events = tuple(f.risk_observation(value, n, digest=digest) for n, value in enumerate(("1000", "1025", "980", "1100")))
        model = self.model(events=tuple(reversed(events)))
        self.assertEqual(performance_series(model), tuple((3_600_000*(n+1), D(value))
            for n, value in enumerate(("0", "2.5", "-2", "10"))))
        self.assertFalse(model.performance.history_incomplete)

    def test_incompatible_digest_excluded_and_history_explicitly_incomplete(self):
        digest = f.health_fixture().risk_configuration_digest
        events = (f.risk_observation("1000", 0, digest=digest),
                  f.risk_observation("1500", 1, digest="e"*64), f.risk_observation("1025", 2, digest=digest))
        model = self.model(events=events)
        self.assertEqual(performance_series(model), ((3_600_000, D(0)), (10_800_000, D("2.5"))))
        self.assertTrue(model.performance.history_incomplete)

    def test_missing_digest_excluded_not_assumed_compatible(self):
        model = self.model(events=(f.risk_observation("1100"),))
        self.assertEqual(performance_series(model), ())
        self.assertTrue(model.performance.history_incomplete)

    def test_snapshot_twenty_percent_never_becomes_history(self):
        model = self.model("1200")
        self.assertEqual(model.performance.return_percent, D(20))
        self.assertEqual(performance_series(model), ())
        self.assertTrue(model.performance.history_incomplete)

    def test_single_retained_observation_stays_single(self):
        event = f.risk_observation("1025", digest=f.health_fixture().risk_configuration_digest)
        model = self.model("1200", events=(event,))
        self.assertEqual(performance_series(model), ((3_600_000, D("2.5")),))
        self.assertTrue(model.performance.history_incomplete)

    def test_tripped_observation_is_retained_and_duplicate_is_not_a_second_point(self):
        event = f.risk_observation("900", kind=T.RISK_TRIPPED, digest=f.health_fixture().risk_configuration_digest)
        model = self.model(events=(event, event))
        self.assertEqual(performance_series(model), ((3_600_000, D(-10)),))

    def test_same_configuration_child_epoch_rearm_does_not_reset_history(self):
        digest = f.health_fixture().risk_configuration_digest
        events = (f.risk_observation("1000", 0, digest=digest),
            f.event_fixture(T.RISK_REARMED), f.risk_observation("1100", 2, digest=digest,
                risk_epoch_id="b"*64, risk_epoch_sequence=2))
        model = self.model(events=events, risk_epoch_id="b"*64, risk_epoch_sequence=2)
        self.assertEqual(performance_series(model), ((3_600_000, D(0)), (10_800_000, D(10))))
        self.assertFalse(model.performance.history_incomplete)

    def test_inactive_risk_does_not_normalize_old_events(self):
        event = f.risk_observation("1100", digest=f.health_fixture().risk_configuration_digest)
        model = build_dashboard_model(f.health_fixture(active=False), (event,), now_ms=AT)
        self.assertEqual(performance_series(model), ())

    def test_history_still_uses_bounded_deduped_events(self):
        digest = f.health_fixture().risk_configuration_digest
        events = tuple(f.risk_observation("1100", n, digest=digest) for n in range(3))
        model = build_dashboard_model(f.performance_health(), events, now_ms=AT, limit=2)
        self.assertEqual(tuple(time for time, _ in performance_series(model)), (7_200_000, 10_800_000))
        self.assertTrue(model.performance.history_incomplete)

    def test_current_performance_does_not_sum_realized_trade_pnl(self):
        model = self.model(events=cycle(pnl=D("999")))
        self.assertEqual(model.performance.net_pnl_quote, D("125.25"))
        self.assertEqual(model.trades[0].realized_pnl_quote, D("999"))

    def test_performance_does_not_modify_input_records(self):
        health = f.performance_health()
        event = f.risk_observation("1100", digest=health.risk_configuration_digest)
        before = health.to_json(), event.to_json()
        model = build_dashboard_model(health, (event,), now_ms=AT)
        performance_series(model)
        self.assertEqual((health.to_json(), event.to_json()), before)


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
