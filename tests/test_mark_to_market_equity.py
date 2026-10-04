"""Synthetic decision 006 checks, including actual Stage 4 accounting outputs."""

from datetime import datetime, timedelta
import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results


START = pd.Timestamp("2025-01-01", tz="UTC")
HOUR = pd.Timedelta(hours=1)
COLUMNS = [
    "observation", "candle_timestamp", "valuation_time", "mark_price", "position",
    "active_trade_id", "cash", "quantity", "position_value", "unrealized_pnl", "equity",
]
FINANCIAL = ["mark_price", "cash", "quantity", "position_value", "unrealized_pnl", "equity"]


def candles(closes):
    return pd.DataFrame({
        "timestamp": pd.date_range(START, periods=len(closes), freq="h"),
        "close": closes,
    })


def ledger(specifications):
    """Each tuple is (entry hour, exit hour or None, entry price, exit price)."""
    rows = []
    for number, (entry, exit_hour, entry_price, exit_price) in enumerate(specifications, start=1):
        rows.append((number, START + entry * HOUR, entry_price,
                     pd.NaT if exit_hour is None else START + exit_hour * HOUR,
                     np.nan if exit_hour is None else exit_price,
                     "OPEN" if exit_hour is None else "CLOSED"))
    trades = pd.DataFrame(rows, columns=[
        "trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status",
    ])
    for column in ("entry_time", "exit_time"):
        trades[column] = pd.Series(trades[column].tolist(), dtype="datetime64[ns, UTC]")
    return trades


def sources(specifications, capital=1_000.0):
    trades = ledger(specifications)
    return (
        (calculate_gross_mark_to_market_equity,
         calculate_trade_results(trades, capital), "capital_after", "entry_price"),
        (calculate_net_mark_to_market_equity,
         calculate_trade_results_with_costs(trades, capital, fee_rate=.01, slippage_rate=.02),
         "net_capital_after", "effective_entry_price"),
    )


class MarkToMarketEquityTests(unittest.TestCase):
    def test_exact_schema_order_range_index_and_dtypes(self):
        for function, results, _, _ in sources([(0, 1, 100, 110), (2, None, 100, None)]):
            path = function(candles([105, 95, 115]), results, HOUR, 1_000)
            self.assertEqual(path.columns.tolist(), COLUMNS)
            pd.testing.assert_index_equal(path.index, pd.RangeIndex(4))
            for column in ("observation", "position"):
                self.assertEqual(str(path[column].dtype), "int64")
            self.assertEqual(str(path.active_trade_id.dtype), "Int64")
            for column in FINANCIAL:
                self.assertEqual(str(path[column].dtype), "float64")
            for column in ("candle_timestamp", "valuation_time"):
                self.assertEqual(str(path[column].dtype), "datetime64[ns, UTC]")

    def test_n_candles_produce_n_plus_one_rows_including_single_candle(self):
        for function, results, _, _ in sources([]):
            for size in (1, 2, 7):
                path = function(candles([100] * size), results, HOUR, 1_000)
                self.assertEqual(len(path), size + 1)
                self.assertEqual(path.observation.tolist(), list(range(size + 1)))
                self.assertEqual(path.valuation_time.iloc[-1], START + size * HOUR)

    def test_exact_initial_row_precedes_first_open_entry(self):
        for function, results, _, _ in sources([(0, None, 100, None)]):
            path = function(candles([90]), results, HOUR, 1_000)
            first = path.iloc[0]
            self.assertEqual(first.observation, 0)
            self.assertTrue(pd.isna(first.candle_timestamp))
            self.assertEqual(first.valuation_time, START)
            self.assertTrue(pd.isna(first.mark_price))
            self.assertEqual(first.position, 0)
            self.assertTrue(pd.isna(first.active_trade_id))
            self.assertEqual(first.cash, 1_000)
            self.assertEqual(first.equity, 1_000)
            self.assertEqual(first[["quantity", "position_value", "unrealized_pnl"]].tolist(), [0, 0, 0])
            self.assertLess(path.equity.iloc[1], first.equity)

    def test_zero_trades_keep_flat_equity_and_record_each_mark(self):
        for function, results, _, _ in sources([]):
            path = function(candles([90, 110, 80]), results, HOUR, 1_000)
            self.assertEqual(path.equity.tolist(), [1_000] * 4)
            self.assertEqual(path.cash.tolist(), [1_000] * 4)
            self.assertTrue((path[["position", "quantity", "position_value", "unrealized_pnl"]] == 0).all().all())
            self.assertTrue(path.active_trade_id.isna().all())
            self.assertEqual(path.mark_price.iloc[1:].tolist(), [90, 110, 80])

    def test_decision_006_worked_gross_example(self):
        function, results, _, _ = sources([(0, 2, 100, 120)])[0]
        path = function(candles([110, 90, 999]), results, HOUR, 1_000)
        self.assertEqual(path.equity.tolist(), [1_000, 1_100, 900, 1_200])
        self.assertEqual(path.unrealized_pnl.tolist(), [0, 100, -100, 0])
        self.assertEqual(path.position.tolist(), [0, 1, 1, 0])
        # The 02:00 CLOSE observation is still long before the 02:00 OPEN exit.
        self.assertEqual(path.valuation_time.iloc[2], results.exit_time.iloc[0])
        self.assertEqual(path.cash.iloc[-1], results.capital_after.iloc[0])

    def test_gross_open_is_marked_from_entry_through_final_close(self):
        function, results, _, _ = sources([(1, None, 100, None)])[0]
        path = function(candles([999, 110, 90, 120]), results, HOUR, 1_000)
        self.assertEqual(path.equity.tolist(), [1_000, 1_000, 1_100, 900, 1_200])
        self.assertEqual(path.unrealized_pnl.tolist(), [0, 0, 100, -100, 200])
        self.assertEqual(path.cash.tolist(), [1_000, 1_000, 0, 0, 0])

    def test_net_entry_fee_is_paid_once_and_not_in_price_pnl(self):
        function, results, _, _ = sources([(0, None, 100, None)])[1]
        entry = results.iloc[0]
        path = function(candles([entry.effective_entry_price]), results, HOUR, 1_000)
        self.assertEqual(path.unrealized_pnl.iloc[-1], 0)
        self.assertAlmostEqual(path.equity.iloc[-1], 1_000 - entry.entry_fee)
        self.assertEqual(path.cash.iloc[-1], 0)
        self.assertEqual(path.quantity.iloc[-1], entry.quantity)

    def test_net_unrealized_pnl_uses_effective_entry_basis(self):
        function, results, _, _ = sources([(0, None, 100, None)])[1]
        path = function(candles([100]), results, HOUR, 1_000)
        row = results.iloc[0]
        self.assertAlmostEqual(path.unrealized_pnl.iloc[-1], row.quantity * (100 - row.effective_entry_price))
        self.assertLess(path.unrealized_pnl.iloc[-1], 0)
        self.assertAlmostEqual(path.equity.iloc[-1], 1_000 - row.entry_fee + path.unrealized_pnl.iloc[-1])

    def test_open_mark_charges_no_hypothetical_exit_costs(self):
        trades = ledger([(0, None, 100, None)])
        results = calculate_trade_results_with_costs(trades, 1_000, fee_rate=.2, slippage_rate=.1)
        path = calculate_net_mark_to_market_equity(candles([100, 120]), results, HOUR, 1_000)
        self.assertEqual(path.equity.iloc[-1], results.quantity.iloc[0] * 120)
        self.assertTrue(results[["exit_time", "exit_fee", "net_pnl", "net_capital_after"]].isna().all().all())
        results["exit_fee"] = 999_999
        results["effective_exit_price"] = 1
        pd.testing.assert_frame_equal(
            path, calculate_net_mark_to_market_equity(candles([100, 120]), results, HOUR, 1_000))

    def test_actual_gross_exit_uses_canonical_capital_not_optional_exit_price(self):
        function, results, after, _ = sources([(0, 1, 100, 120)])[0]
        results["exit_price"] = 999_999
        results["gross_pnl"] = -999_999
        path = function(candles([110, 1, 999]), results, HOUR, 1_000)
        self.assertEqual(path.cash.iloc[2:].tolist(), [results[after].iloc[0]] * 2)
        self.assertEqual(path.equity.iloc[2:].tolist(), [1_200] * 2)

    def test_actual_net_exit_uses_canonical_capital_without_charging_costs_again(self):
        function, results, after, _ = sources([(0, 1, 100, 120)])[1]
        results["exit_fee"] = 999_999
        results["effective_exit_price"] = 1
        path = function(candles([110, 1, 999]), results, HOUR, 1_000)
        self.assertEqual(path.equity.iloc[2:].tolist(), [results[after].iloc[0]] * 2)
        self.assertTrue((path[["position", "quantity", "position_value", "unrealized_pnl"]].iloc[2:] == 0).all().all())
        self.assertTrue(path.active_trade_id.iloc[2:].isna().all())

    def test_multiple_closed_exits_reconcile_and_next_entries_reuse_compounded_quantity(self):
        specs = [(0, 1, 100, 110), (2, 3, 200, 180), (4, None, 50, None)]
        for function, results, after, _ in sources(specs):
            path = function(candles([105, 999, 190, 999, 55]), results, HOUR, 1_000)
            for trade in results.iloc[:2].itertuples():
                observed = path.loc[path.candle_timestamp == trade.exit_time].iloc[0]
                self.assertEqual(observed.equity, getattr(trade, after))
                self.assertEqual(observed.position, 0)
            self.assertEqual(path.quantity.iloc[-1], results.quantity.iloc[-1])

    def test_final_open_is_marked_without_fabricated_realized_results(self):
        for function, results, after, _ in sources([(0, 1, 100, 110), (2, None, 200, None)]):
            before = results.copy(deep=True)
            path = function(candles([105, 999, 210, 220]), results, HOUR, 1_000)
            last = path.iloc[-1]
            self.assertEqual(last.position, 1)
            self.assertEqual(last.active_trade_id, 2)
            self.assertEqual(last.equity, results.quantity.iloc[-1] * 220)
            self.assertEqual(last.position_value, last.equity)
            self.assertTrue(pd.isna(results[after].iloc[-1]))
            self.assertTrue(pd.isna(results.exit_time.iloc[-1]))
            pd.testing.assert_frame_equal(results, before)

    def test_entry_on_final_open_receives_one_close_mark(self):
        for function, results, _, _ in sources([(2, None, 100, None)]):
            path = function(candles([80, 90, 110]), results, HOUR, 1_000)
            self.assertEqual(path.position.tolist(), [0, 0, 0, 1])
            self.assertEqual(path.equity.iloc[-1], results.quantity.iloc[0] * 110)

    def test_exit_on_final_open_leaves_realized_cash(self):
        for function, results, after, _ in sources([(0, 2, 100, 120)]):
            path = function(candles([110, 90, 999]), results, HOUR, 1_000)
            self.assertEqual(path.position.iloc[-1], 0)
            self.assertEqual(path.equity.iloc[-1], results[after].iloc[0])
            self.assertEqual(path.cash.iloc[-1], path.equity.iloc[-1])

    def test_shared_open_exit_precedes_replacement_entry(self):
        for function, results, after, basis in sources([(0, 1, 100, 110), (1, None, 200, None)]):
            path = function(candles([90, 210]), results, HOUR, 1_000)
            self.assertEqual(path.active_trade_id.iloc[1:].tolist(), [1, 2])
            self.assertEqual(path.quantity.iloc[-1], results.quantity.iloc[1])
            self.assertEqual(path.cash.iloc[-1], 0)
            self.assertEqual(path.equity.iloc[-1], results.quantity.iloc[1] * 210)
            self.assertNotEqual(path.equity.iloc[-1], results[after].iloc[0])
            self.assertAlmostEqual(path.unrealized_pnl.iloc[-1], results.quantity.iloc[1] * (210 - results[basis].iloc[1]))

    def test_future_exit_does_not_affect_earlier_marks(self):
        market = candles([110, 90, 105, 999])
        closed_sources = sources([(0, 3, 100, 120)])
        open_sources = sources([(0, None, 100, None)])
        for closed_source, open_source in zip(closed_sources, open_sources):
            function, closed, after, _ = closed_source
            path = function(market, closed, HOUR, 1_000)
            open_path = function(market, open_source[1], HOUR, 1_000)
            pd.testing.assert_frame_equal(path.iloc[:4], open_path.iloc[:4])
            closed[after] = closed[after] + 500
            other = function(market, closed, HOUR, 1_000)
            pd.testing.assert_frame_equal(path.iloc[:4], other.iloc[:4])
            self.assertEqual(other.equity.iloc[-1], closed[after].iloc[0])

    def test_appending_future_candles_preserves_shared_prefix(self):
        for function, results, _, _ in sources([(0, None, 100, None)]):
            short = function(candles([110, 90]), results, HOUR, 1_000)
            longer = function(candles([110, 90, 999]), results, HOUR, 1_000)
            pd.testing.assert_frame_equal(short, longer.iloc[:3])

    def test_wrong_accounting_sources_fail_even_when_empty(self):
        for specs in ([], [(0, None, 100, None)]):
            gross, net = sources(specs)
            for function, wrong, label, column in (
                (gross[0], net[1], "GROSS", "capital_after"),
                (net[0], gross[1], "NET", "net_capital_after"),
            ):
                with self.assertRaisesRegex(ValueError, label + ".*" + column):
                    function(candles([100]), wrong, HOUR, 1_000)

    def test_candle_dataframe_required_schema_unique_columns_and_nonempty(self):
        function, results, _, _ = sources([])[0]
        market = candles([100])
        malformed = [None, [], market.iloc[:0], market.drop(columns="timestamp"),
                     market.drop(columns="close"), pd.concat([market, market[["close"]]], axis=1)]
        for data in malformed:
            with self.subTest(data=str(data)[:80]), self.assertRaises(ValueError):
                function(data, results, HOUR, 1_000)

    def test_accounting_required_schema_checked_for_empty_and_nonempty_sources(self):
        for specs in ([], [(0, None, 100, None)]):
            for function, results, after, basis in sources(specs):
                required = ["trade_id", "status", "entry_time", "exit_time", "capital_before", "quantity", basis, after]
                if after == "net_capital_after":
                    required.append("entry_fee")
                expected = function(candles([100]), results, HOUR, 1_000)
                pd.testing.assert_frame_equal(expected, function(candles([100]), results[required], HOUR, 1_000))
                for column in required:
                    with self.subTest(column=column), self.assertRaises(ValueError):
                        function(candles([100]), results.drop(columns=column), HOUR, 1_000)
                for bad in (None, [], pd.concat([results, results[["status"]]], axis=1)):
                    with self.assertRaises(ValueError):
                        function(candles([100]), bad, HOUR, 1_000)

    def test_invalid_close_values_are_rejected_without_parsing(self):
        function, results, _, _ = sources([])[0]
        for value in (0, -1, np.inf, -np.inf, np.nan, None, pd.NA, True, np.bool_(True), "100", 1j, 10 ** 400):
            market = candles([100]).assign(close=pd.Series([value], dtype="object"))
            with self.subTest(value=str(value)[:30]), self.assertRaisesRegex(ValueError, "close"):
                function(market, results, HOUR, 1_000)

    def test_invalid_out_of_order_duplicate_and_gapped_candle_times(self):
        function, results, _, _ = sources([])[0]
        for times in ([START, START], [START + HOUR, START], [START, START + 2 * HOUR],
                      [START, pd.NaT], ["2025-01-01", "2025-01-02"], [0, 1]):
            with self.subTest(times=times), self.assertRaises(ValueError):
                function(candles([100, 100]).assign(timestamp=times), results, HOUR, 1_000)

    def test_invalid_interval_types_and_nonpositive_or_calendar_durations(self):
        function, results, _, _ = sources([])[0]
        for value in (None, True, np.bool_(True), "1h", 3600, 0, 1j, pd.NaT,
                      pd.Timedelta(0), -HOUR, np.timedelta64("NaT"),
                      np.timedelta64(1, "M"), np.timedelta64(1, "Y"),
                      pd.DateOffset(hours=1), pd.offsets.MonthBegin()):
            with self.subTest(value=str(value)), self.assertRaisesRegex(ValueError, "candle_interval"):
                function(candles([100]), results, value, 1_000)

    def test_explicit_fixed_duration_types_and_nonhourly_candles(self):
        function, results, _, _ = sources([])[0]
        expected = function(candles([100, 110]), results, HOUR, 1_000)
        for interval in (timedelta(hours=1), np.timedelta64(1, "h")):
            pd.testing.assert_frame_equal(expected, function(candles([100, 110]), results, interval, 1_000))
        market = candles([100, 110]).assign(timestamp=pd.date_range(START, periods=2, freq="30min"))
        path = function(market, results, pd.Timedelta(minutes=30), 1_000)
        self.assertEqual(path.valuation_time.iloc[-1], START + HOUR)

    def test_invalid_initial_capital_rejected_even_without_trades(self):
        for function, results, _, _ in sources([]):
            for value in (0, -1, np.inf, np.nan, None, True, np.bool_(True), "1000", 1j, 10 ** 400):
                with self.subTest(value=str(value)[:30]), self.assertRaisesRegex(ValueError, "initial_capital"):
                    function(candles([100]), results, HOUR, value)

    def test_entry_and_closed_exit_must_match_supplied_opens_inside_window(self):
        for function, results, _, _ in sources([(0, 1, 100, 110)]):
            for column in ("entry_time", "exit_time"):
                for value in (START - HOUR, START + HOUR / 2, START + 3 * HOUR, "2025-01-01", 0, pd.NaT):
                    bad = results.copy()
                    bad[column] = pd.Series([value], dtype="object")
                    with self.subTest(column=column, value=value), self.assertRaisesRegex(ValueError, column):
                        function(candles([100, 110, 120]), bad, HOUR, 1_000)

    def test_open_exit_and_capital_after_must_remain_missing(self):
        for function, results, after, _ in sources([(0, None, 100, None)]):
            for column, value in (("exit_time", START + HOUR), (after, 1_000), (after, "NaN")):
                bad = results.copy()
                bad[column] = pd.Series([value], dtype="object")
                with self.subTest(column=column), self.assertRaisesRegex(ValueError, "OPEN"):
                    function(candles([100, 110]), bad, HOUR, 1_000)

    def test_closed_exit_must_follow_entry(self):
        for function, results, _, _ in sources([(1, 2, 100, 110)]):
            for hour in (0, 1):
                bad = results.assign(exit_time=START + hour * HOUR)
                with self.assertRaisesRegex(ValueError, "strictly after"):
                    function(candles([100, 110, 120]), bad, HOUR, 1_000)

    def test_overlap_and_out_of_order_entries_are_not_repaired(self):
        for function, results, _, _ in sources([(0, 2, 100, 110), (3, None, 100, None)]):
            for hour, message in ((1, "overlap"), (0, "chronological")):
                bad = results.copy()
                bad.loc[1, "entry_time"] = START + hour * HOUR
                with self.assertRaisesRegex(ValueError, message):
                    function(candles([100] * 4), bad, HOUR, 1_000)

    def test_statuses_multiple_open_and_nonfinal_open(self):
        for function, results, _, _ in sources([(0, 1, 100, 110), (2, None, 100, None)]):
            for statuses in (["OPEN", "OPEN"], ["OPEN", "CLOSED"], ["BUY", "OPEN"], [None, "OPEN"]):
                with self.subTest(statuses=statuses), self.assertRaises(ValueError):
                    function(candles([100] * 3), results.assign(status=statuses), HOUR, 1_000)

    def test_positive_quantity_basis_and_capital_before_are_required(self):
        for function, results, _, basis in sources([(0, None, 100, None)]):
            for column in ("quantity", basis, "capital_before"):
                for value in (0, -1, np.inf, np.nan, None, True, np.bool_(True), "1", 1j, 10 ** 400):
                    bad = results.copy()
                    bad[column] = pd.Series([value], dtype="object")
                    with self.subTest(column=column, value=str(value)[:30]), self.assertRaisesRegex(ValueError, column):
                        function(candles([100]), bad, HOUR, 1_000)

    def test_closed_capital_and_net_entry_fees_must_be_finite_nonnegative(self):
        for function, results, after, _ in sources([(0, 1, 100, 110)]):
            columns = [after] + (["entry_fee"] if "entry_fee" in results else [])
            for column in columns:
                for value in (-1, np.inf, np.nan, None, True, "1", 1j, 10 ** 400):
                    bad = results.copy()
                    bad[column] = pd.Series([value], dtype="object")
                    with self.subTest(column=column, value=str(value)[:30]), self.assertRaisesRegex(ValueError, column):
                        function(candles([100, 110]), bad, HOUR, 1_000)

    def test_canonical_integer_ids_are_required(self):
        for function, results, _, _ in sources([(0, None, 100, None)]):
            for value in (0, 2, 1.0, "1", True, np.bool_(True), None):
                with self.subTest(value=value), self.assertRaisesRegex(ValueError, "trade_id"):
                    function(candles([100]), results.assign(trade_id=pd.Series([value], dtype="object")), HOUR, 1_000)

    def test_initial_and_compounded_capital_and_all_in_allocation_reconcile(self):
        for function, results, _, basis in sources([(0, 1, 100, 110), (2, None, 100, None)]):
            with self.assertRaisesRegex(ValueError, "capital_before"):
                function(candles([100] * 3), results, HOUR, 2_000)
            for column in ("capital_before", "quantity", basis) + (("entry_fee",) if "entry_fee" in results else ()):
                bad = results.copy()
                bad.loc[1, column] += 10
                with self.subTest(column=column), self.assertRaisesRegex(ValueError, "reconcile"):
                    function(candles([100] * 3), bad, HOUR, 1_000)

    def test_floating_tolerance_checks_do_not_repair_or_resize_canonical_amounts(self):
        function, results, _, _ = sources([(0, None, 100, None)])[0]
        results["capital_before"] = 1_000 * (1 + 5e-13)
        path = function(candles([110]), results, HOUR, 1_000)
        self.assertEqual(path.quantity.iloc[-1], results.quantity.iloc[0])
        self.assertEqual(path.equity.iloc[-1], 1_100)
        results["capital_before"] = 1_001
        with self.assertRaisesRegex(ValueError, "reconcile"):
            function(candles([110]), results, HOUR, 1_000)

    def test_zero_canonical_exit_cash_is_valid_while_flat(self):
        for function, results, after, _ in sources([(0, 1, 100, 110)]):
            results[after] = 0.0
            path = function(candles([100, 110]), results, HOUR, 1_000)
            self.assertEqual(path.equity.iloc[-1], 0)
            self.assertEqual(path.position.iloc[-1], 0)

    def test_naive_timestamps_are_accepted_and_preserved(self):
        market = candles([100, 110])
        market["timestamp"] = market.timestamp.dt.tz_localize(None)
        for function, results, _, _ in sources([(0, 1, 100, 110)]):
            for column in ("entry_time", "exit_time"):
                results[column] = results[column].dt.tz_localize(None)
            path = function(market, results, HOUR, 1_000)
            self.assertEqual(str(path.valuation_time.dtype), "datetime64[ns]")
            self.assertEqual(str(path.candle_timestamp.dtype), "datetime64[ns]")

    def test_coherent_same_zone_aware_timestamps_preserve_zone(self):
        zone = ZoneInfo("Asia/Seoul")
        market = candles([100, 110])
        market["timestamp"] = market.timestamp.dt.tz_convert(zone)
        for function, results, _, _ in sources([(0, 1, 100, 110)]):
            for column in ("entry_time", "exit_time"):
                results[column] = results[column].dt.tz_convert(zone)
            path = function(market, results, HOUR, 1_000)
            self.assertEqual(path.valuation_time.dt.tz, zone)
            self.assertEqual(path.valuation_time.iloc[0], market.timestamp.iloc[0])

    def test_mixed_naive_aware_and_incompatible_timezones_are_rejected(self):
        for function, results, _, _ in sources([(0, 1, 100, 110)]):
            for column in ("entry_time", "exit_time"):
                for times in (results[column].dt.tz_localize(None),
                              results[column].dt.tz_convert("Europe/Berlin"),
                              results[column].dt.tz_convert(ZoneInfo("UTC"))):
                    bad = results.copy()
                    bad[column] = times
                    with self.assertRaisesRegex(ValueError, "timezone"):
                        function(candles([100, 110]), bad, HOUR, 1_000)
            market = candles([100, 110]).assign(timestamp=[START, (START + HOUR).tz_localize(None)])
            with self.assertRaisesRegex(ValueError, "timezone"):
                function(market, results, HOUR, 1_000)

    def test_dst_spacing_and_valuation_use_actual_elapsed_time(self):
        zone = ZoneInfo("America/New_York")
        local_start = pd.Timestamp("2025-03-09 00:00", tz=zone)
        market = candles([100] * 4).assign(timestamp=pd.date_range(local_start, periods=4, freq="h"))
        for function, results, _, _ in sources([(1, None, 100, None)]):
            results["entry_time"] = pd.Series([local_start + HOUR])
            path = function(market, results, HOUR, 1_000)
            self.assertEqual(path.valuation_time.iloc[-1] - path.valuation_time.iloc[0], 4 * HOUR)
            self.assertEqual(path.valuation_time.dt.tz, zone)
            self.assertEqual(path.position.tolist(), [0, 0, 1, 1, 1])

    def test_existing_datetime_scalars_are_accepted_without_string_parsing(self):
        function, results, _, _ = sources([(0, 1, 100, 110)])[0]
        for column in ("entry_time", "exit_time"):
            results[column] = results[column].dt.tz_localize(None)
        for times in ([datetime(2025, 1, 1), datetime(2025, 1, 1, 1)],
                      [np.datetime64("2025-01-01T00:00"), np.datetime64("2025-01-01T01:00")]):
            market = candles([100, 110]).assign(timestamp=pd.Series(times, dtype="object"))
            self.assertEqual(function(market, results, HOUR, 1_000).equity.iloc[-1], 1_100)

    def test_inputs_indexes_dtypes_and_values_are_preserved_outputs_independent(self):
        for function, results, _, _ in sources([(0, 1, 100, 110), (2, None, 100, None)]):
            market = candles([105, 999, 120])
            market.index = pd.Index([30, 10, 30], name="market_row")
            results.index = pd.Index([8, 8], name="accounting_row")
            market = market.assign(note="keep me")[["note", "close", "timestamp"]]
            results = results[results.columns[::-1]]
            original_market, original_results = market.copy(deep=True), results.copy(deep=True)
            path = function(market, results, HOUR, 1_000)
            path.loc[1, "quantity"] = 999
            path.loc[1, "candle_timestamp"] = START + 100 * HOUR
            pd.testing.assert_frame_equal(market, original_market)
            pd.testing.assert_frame_equal(results, original_results)

    def test_optional_market_and_accounting_columns_are_ignored(self):
        for function, results, after, _ in sources([(0, 1, 100, 110)]):
            market = candles([105, 999])
            expected = function(market, results, HOUR, 1_000)
            market = market.assign(high=-1, low="bad", open=999, signal="BUY")
            results = results.assign(gross_pnl="bad", net_pnl="bad", exit_price=-1, note="irrelevant")
            other_after = "net_capital_after" if after == "capital_after" else "capital_after"
            results[other_after] = "bad"
            pd.testing.assert_frame_equal(expected, function(market, results, HOUR, 1_000))

    def test_actual_accounting_paths_are_independent_and_obey_equity_identities(self):
        market = candles([105, 110, 95, 90, 55])
        specs = [(0, 1, 100, 110), (2, 3, 100, 90), (4, None, 50, None)]
        paths = []
        for function, results, _, basis in sources(specs):
            path = function(market, results, HOUR, 1_000)
            np.testing.assert_allclose(path.equity, path.cash + path.position_value)
            for trade in results.itertuples():
                entry_row = path.loc[path.candle_timestamp == trade.entry_time].iloc[0]
                self.assertEqual(entry_row.quantity, trade.quantity)
                self.assertAlmostEqual(entry_row.unrealized_pnl, trade.quantity * (entry_row.mark_price - getattr(trade, basis)))
            paths.append(path)
        self.assertLess(paths[1].equity.iloc[-1], paths[0].equity.iloc[-1])
        self.assertFalse(paths[0].quantity.equals(paths[1].quantity))
        pd.testing.assert_series_equal(paths[0].mark_price, paths[1].mark_price)

    def test_zero_cost_net_equity_equals_gross_equity(self):
        trades = ledger([(0, 1, 100, 110), (2, None, 50, None)])
        market = candles([105, 110, 55, 45])
        gross = calculate_gross_mark_to_market_equity(market, calculate_trade_results(trades, 1_000), HOUR, 1_000)
        net = calculate_net_mark_to_market_equity(market, calculate_trade_results_with_costs(trades, 1_000), HOUR, 1_000)
        pd.testing.assert_frame_equal(gross, net)

    def test_calculated_value_overflow_underflow_and_unsafe_window_end_rejected(self):
        for capital, entry_price, close in ((1e308, 1, 2), (1, 1e308, 1e-308)):
            results = calculate_trade_results(ledger([(0, None, entry_price, None)]), capital)
            with self.assertRaisesRegex(ValueError, "Calculated"):
                calculate_gross_mark_to_market_equity(candles([close]), results, HOUR, capital)
        function, results, _, _ = sources([])[0]
        market = candles([100]).assign(timestamp=[pd.Timestamp.max])
        with self.assertRaisesRegex(ValueError, "valuation"):
            function(market, results, HOUR, 1_000)


if __name__ == "__main__":
    unittest.main()
