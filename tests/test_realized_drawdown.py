"""Synthetic capital paths test decision 004 without a market-data file."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.analytics.drawdown import (
    calculate_gross_realized_drawdown,
    calculate_net_realized_drawdown,
    summarize_gross_realized_drawdown,
    summarize_net_realized_drawdown,
)
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.costs import calculate_trade_results_with_costs


PATH_COLUMNS = [
    "observation", "closed_trade_number", "capital", "running_peak", "drawdown", "drawdown_amount",
]
SUMMARY_COLUMNS = ["max_realized_drawdown", "max_realized_drawdown_amount"]
SOURCES = [
    (calculate_gross_realized_drawdown, summarize_gross_realized_drawdown, "GROSS", "capital_after"),
    (calculate_net_realized_drawdown, summarize_net_realized_drawdown, "NET", "net_capital_after"),
]


def accounting(capitals, *, net=False, include_open=False):
    """Minimal canonical source schema; capital_before is context only."""
    column = "net_capital_after" if net else "capital_after"
    frame = pd.DataFrame({
        "status": ["CLOSED"] * len(capitals),
        "capital_before": pd.Series([10_000.0] * len(capitals), dtype="float64"),
        column: pd.Series(capitals, dtype="float64"),
    })
    if include_open:
        frame.loc[len(frame)] = ["OPEN", 123_456.0, np.nan]
    return frame


def ledger(prices):
    """Small chronological ledger for integration with actual Stage 4 helpers."""
    start = pd.Timestamp("2025-01-01", tz="UTC")
    rows = [{
        "trade_id": number + 1,
        "entry_time": start + pd.Timedelta(hours=2 * number),
        "entry_price": entry,
        "exit_time": pd.NaT if exit_price is None else start + pd.Timedelta(hours=2 * number + 1),
        "exit_price": np.nan if exit_price is None else exit_price,
        "status": "OPEN" if exit_price is None else "CLOSED",
    } for number, (entry, exit_price) in enumerate(prices)]
    result = pd.DataFrame(rows)
    result["exit_time"] = pd.to_datetime(result["exit_time"], utc=True)
    return result


class RealizedDrawdownTests(unittest.TestCase):
    def sources(self, capitals, include_open=False):
        for path_function, summary_function, label, column in SOURCES:
            frame = accounting(capitals, net=label == "NET", include_open=include_open)
            yield path_function, summary_function, label, column, frame

    def test_worked_example_path_and_summary(self):
        for path_function, summary_function, label, _, frame in self.sources([11_000, 9_900, 12_000, 9_000]):
            with self.subTest(source=label):
                path = path_function(frame)
                np.testing.assert_allclose(path.capital, [10_000, 11_000, 9_900, 12_000, 9_000])
                np.testing.assert_allclose(path.running_peak, [10_000, 11_000, 11_000, 12_000, 12_000])
                np.testing.assert_allclose(path.drawdown, [0, 0, -.1, 0, -.25], atol=1e-15)
                np.testing.assert_allclose(path.drawdown_amount, [0, 0, -1_100, 0, -3_000])
                np.testing.assert_allclose(summary_function(frame).loc[label], [-.25, -3_000])

    def test_exact_path_columns_range_index_and_dtypes(self):
        for function, _, _, _, frame in self.sources([11_000, 9_000]):
            path = function(frame)
            self.assertEqual(path.columns.tolist(), PATH_COLUMNS)
            pd.testing.assert_index_equal(path.index, pd.RangeIndex(3))
            np.testing.assert_array_equal(path.observation, [0, 1, 2])
            np.testing.assert_array_equal(path.closed_trade_number, [0, 1, 2])
            for column in PATH_COLUMNS[:2]:
                self.assertEqual(str(path[column].dtype), "int64")
            for column in PATH_COLUMNS[2:]:
                self.assertEqual(str(path[column].dtype), "float64")

    def test_exact_summary_columns_index_and_dtypes(self):
        for _, function, label, _, frame in self.sources([9_000]):
            summary = function(frame)
            self.assertEqual(summary.columns.tolist(), SUMMARY_COLUMNS)
            self.assertEqual(summary.index.tolist(), [label])
            self.assertEqual(summary.shape, (1, 2))
            self.assertTrue(all(str(dtype) == "float64" for dtype in summary.dtypes))

    def test_first_trade_loss_includes_initial_observation(self):
        for path_function, summary_function, label, _, frame in self.sources([8_000]):
            path = path_function(frame)
            np.testing.assert_allclose(path.capital, [10_000, 8_000])
            np.testing.assert_allclose(path.running_peak, [10_000, 10_000])
            np.testing.assert_allclose(path.drawdown, [0, -.2], atol=1e-15)
            np.testing.assert_allclose(summary_function(frame).loc[label], [-.2, -2_000])

    def test_explicit_initial_capital_is_not_inferred_from_context(self):
        for path_function, summary_function, label, _, frame in self.sources([400]):
            frame["capital_before"] = 99_999.0
            path = path_function(frame, initial_capital=500.0)
            np.testing.assert_allclose(path.capital, [500, 400])
            np.testing.assert_allclose(summary_function(frame, initial_capital=500.0).loc[label], [-.2, -100])

    def test_zero_closed_has_one_initial_point_and_zero_summary(self):
        for path_function, summary_function, label, _, frame in self.sources([]):
            path = path_function(frame)
            self.assertEqual(path.shape, (1, 6))
            np.testing.assert_allclose(path.iloc[0], [0, 0, 10_000, 10_000, 0, 0])
            np.testing.assert_allclose(summary_function(frame).loc[label], [0, 0])
            self.assertFalse(path.isna().any().any())
            self.assertEqual(str(path.observation.dtype), "int64")
            self.assertEqual(str(path.drawdown.dtype), "float64")

    def test_open_only_equals_empty_path_and_summary(self):
        for path_function, summary_function, label, _, frame in self.sources([], include_open=True):
            empty = accounting([], net=label == "NET")
            pd.testing.assert_frame_equal(path_function(frame), path_function(empty))
            pd.testing.assert_frame_equal(summary_function(frame), summary_function(empty))

    def test_final_open_removal_leaves_path_and_summary_identical(self):
        for path_function, summary_function, _, _, frame in self.sources([11_000, 9_000], include_open=True):
            frame["entry_fee"] = [10, 9, 9_999]
            frame["entry_notional"] = [9_990, 8_991, 123_000]
            frame["quantity"] = [1, 2, 999]
            pd.testing.assert_frame_equal(path_function(frame), path_function(frame.iloc[:-1]))
            pd.testing.assert_frame_equal(summary_function(frame), summary_function(frame.iloc[:-1]))
            self.assertEqual(len(path_function(frame)), 3)

    def test_only_increasing_capital_has_zero_drawdown(self):
        for path_function, summary_function, label, _, frame in self.sources([11_000, 12_000, 13_000]):
            path = path_function(frame)
            self.assertTrue(path.drawdown.eq(0).all())
            self.assertTrue(path.drawdown_amount.eq(0).all())
            np.testing.assert_allclose(summary_function(frame).loc[label], [0, 0])

    def test_exactly_flat_capital_has_zero_drawdown(self):
        for path_function, summary_function, label, _, frame in self.sources([10_000, 10_000]):
            self.assertTrue(path_function(frame).drawdown.eq(0).all())
            np.testing.assert_allclose(summary_function(frame).loc[label], [0, 0])

    def test_repeated_new_peaks_have_zero_drawdown(self):
        for path_function, _, _, _, frame in self.sources([11_000, 11_000, 12_000, 12_000]):
            path = path_function(frame)
            np.testing.assert_allclose(path.running_peak, [10_000, 11_000, 11_000, 12_000, 12_000])
            self.assertTrue(path.drawdown.eq(0).all())

    def test_recovery_to_previous_peak_retains_historical_decline(self):
        for path_function, summary_function, label, _, frame in self.sources([8_000, 10_000]):
            path = path_function(frame)
            np.testing.assert_allclose(path.drawdown, [0, -.2, 0], atol=1e-15)
            np.testing.assert_allclose(summary_function(frame).loc[label], [-.2, -2_000])

    def test_zero_post_trade_capital_is_valid_full_decline(self):
        for path_function, summary_function, label, _, frame in self.sources([12_000, 0]):
            path = path_function(frame)
            self.assertEqual(path.drawdown.iloc[-1], -1.0)
            self.assertEqual(path.drawdown_amount.iloc[-1], -12_000)
            np.testing.assert_allclose(summary_function(frame).loc[label], [-1, -12_000])

    def test_tied_percentage_minimum_uses_earliest_amount(self):
        for path_function, summary_function, label, _, frame in self.sources([7_500, 20_000, 15_000]):
            path = path_function(frame)
            self.assertEqual(path.drawdown.iloc[1], path.drawdown.iloc[3])
            self.assertEqual(path.drawdown.iloc[1], -.25)
            np.testing.assert_allclose(summary_function(frame).loc[label], [-.25, -2_500])
            self.assertEqual(path.drawdown_amount.min(), -5_000)

    def test_percentage_and_currency_worst_points_can_differ(self):
        for path_function, summary_function, label, _, frame in self.sources([6_000, 20_000, 13_000]):
            path = path_function(frame)
            self.assertEqual(path.drawdown.idxmin(), 1)
            self.assertEqual(path.drawdown_amount.idxmin(), 3)
            np.testing.assert_allclose(summary_function(frame).loc[label], [-.4, -4_000])

    def test_peaks_and_drawdowns_use_unrounded_capital(self):
        higher = np.nextafter(10_000.0, np.inf)
        for path_function, summary_function, label, _, frame in self.sources([higher, 10_000]):
            path = path_function(frame)
            self.assertEqual(path.running_peak.iloc[-1], higher)
            self.assertLess(path.drawdown.iloc[-1], 0)
            self.assertLess(summary_function(frame).loc[label, "max_realized_drawdown"], 0)

    def test_summary_matches_earliest_minimum_path_observation(self):
        for path_function, summary_function, label, _, frame in self.sources([10_100, 9_300, 11_000, 8_800, 11_000]):
            path = path_function(frame)
            trough = path.loc[path.drawdown.idxmin()]
            np.testing.assert_allclose(summary_function(frame).loc[label], [trough.drawdown, trough.drawdown_amount])
            self.assertTrue(path.drawdown.between(-1, 0).all())
            self.assertTrue(path.drawdown_amount.le(0).all())

    def test_negative_closed_capital_rejected(self):
        for path_function, summary_function, _, column, frame in self.sources([-1]):
            for function in (path_function, summary_function):
                with self.assertRaisesRegex(ValueError, column):
                    function(frame)

    def test_nonfinite_closed_capital_rejected(self):
        for value in (np.nan, np.inf, -np.inf):
            for path_function, summary_function, _, column, frame in self.sources([value]):
                for function in (path_function, summary_function):
                    with self.subTest(value=value, function=function.__name__):
                        with self.assertRaisesRegex(ValueError, column):
                            function(frame)

    def test_missing_closed_capital_rejected(self):
        for value in (None, pd.NA):
            for path_function, summary_function, _, column, frame in self.sources([10_000]):
                frame[column] = pd.Series([value], dtype="object")
                for function in (path_function, summary_function):
                    with self.assertRaisesRegex(ValueError, column):
                        function(frame)

    def test_string_bool_complex_and_unrepresentable_closed_capital_rejected(self):
        for value in ("10000", True, False, np.bool_(True), np.bool_(False), 1 + 0j, 10 ** 400):
            for path_function, summary_function, _, column, frame in self.sources([10_000]):
                frame[column] = pd.Series([value], dtype="object")
                for function in (path_function, summary_function):
                    with self.subTest(value=str(value)[:25], function=function.__name__):
                        with self.assertRaisesRegex(ValueError, column):
                            function(frame)

    def test_invalid_initial_capital_rejected_even_without_closed_trades(self):
        invalid = (0, -1, np.nan, np.inf, -np.inf, None, pd.NA, "10000", True, np.bool_(True), 1 + 0j, 10 ** 400)
        for value in invalid:
            for path_function, summary_function, _, _, frame in self.sources([], include_open=True):
                for function in (path_function, summary_function):
                    with self.subTest(value=str(value)[:25], function=function.__name__):
                        with self.assertRaisesRegex(ValueError, "initial_capital"):
                            function(frame, initial_capital=value)

    def test_finite_real_numpy_capital_and_initial_capital_accepted(self):
        for path_function, summary_function, label, column, frame in self.sources([80, 120]):
            frame[column] = pd.Series([np.int64(80), np.float32(120)], dtype="object")
            path = path_function(frame, initial_capital=np.float64(100))
            np.testing.assert_allclose(path.capital, [100, 80, 120])
            np.testing.assert_allclose(summary_function(frame, initial_capital=np.float64(100)).loc[label], [-.2, -20])

    def test_invalid_status_rejected_without_repair(self):
        for value in ("closed", "UNKNOWN", None, pd.NA, np.nan, True, 1):
            for path_function, summary_function, _, _, frame in self.sources([10_000]):
                frame["status"] = pd.Series([value], dtype="object")
                original = frame.copy(deep=True)
                for function in (path_function, summary_function):
                    with self.assertRaisesRegex(ValueError, "CLOSED or OPEN"):
                        function(frame)
                    pd.testing.assert_frame_equal(frame, original)

    def test_non_dataframe_rejected(self):
        for path_function, summary_function, _, _ in SOURCES:
            for function in (path_function, summary_function):
                for value in (None, [], {}, pd.Series([10_000])):
                    with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
                        function(value)

    def test_all_required_columns_checked_for_nonempty_and_empty_input(self):
        for capitals in ([10_000], []):
            for path_function, summary_function, _, _, frame in self.sources(capitals):
                for column in frame.columns:
                    for function in (path_function, summary_function):
                        with self.assertRaisesRegex(ValueError, "missing required columns"):
                            function(frame.drop(columns=column))

    def test_duplicate_columns_rejected(self):
        for path_function, summary_function, _, _, frame in self.sources([10_000]):
            duplicate = pd.concat([frame, frame[["status"]]], axis=1)
            for function in (path_function, summary_function):
                with self.assertRaisesRegex(ValueError, "column names must be unique"):
                    function(duplicate)

    def test_optional_columns_do_not_reconstruct_capital_or_guess_source(self):
        for path_function, summary_function, label, _, frame in self.sources([9_000, 11_000]):
            path, summary = path_function(frame), summary_function(frame)
            frame["gross_pnl"] = [999_999, -999_999]
            frame["net_pnl"] = [-999_999, 999_999]
            frame["entry_fee"] = 999_999
            frame["quantity"] = np.nan
            frame["note"] = "irrelevant"
            other_column = "net_capital_after" if label == "GROSS" else "capital_after"
            frame[other_column] = [1, 999_999]
            pd.testing.assert_frame_equal(path_function(frame), path)
            pd.testing.assert_frame_equal(summary_function(frame), summary)

    def test_all_four_functions_preserve_input_and_returns_are_independent(self):
        for path_function, summary_function, _, _, frame in self.sources([11_000, 9_000], include_open=True):
            frame.index = pd.Index([30, 10, 30], name="source_row")
            frame["note"] = "preserve me"
            frame = frame[frame.columns[::-1]]
            original = frame.copy(deep=True)
            path = path_function(frame)
            summary = summary_function(frame)
            path.loc[0, "capital"] = 999
            summary.iloc[0, 0] = 999
            pd.testing.assert_frame_equal(frame, original)

    def test_existing_order_and_duplicate_nonstandard_index_preserved(self):
        for path_function, summary_function, _, _, frame in self.sources([9_000, 12_000, 8_000, 11_000]):
            frame.index = pd.Index([20, 10, 20, 5], name="unordered")
            original = frame.copy(deep=True)
            path = path_function(frame)
            np.testing.assert_allclose(path.capital, [10_000, 9_000, 12_000, 8_000, 11_000])
            np.testing.assert_allclose(path.running_peak, [10_000, 10_000, 12_000, 12_000, 12_000])
            pd.testing.assert_index_equal(path.index, pd.RangeIndex(5))
            summary_function(frame)
            pd.testing.assert_frame_equal(frame, original)

    def test_actual_wrong_stage4_source_rejected_by_paths_and_summaries(self):
        trades = ledger([(100, 110)])
        gross = calculate_trade_results(trades)
        net = calculate_trade_results_with_costs(trades, fee_rate=.001)
        for function in (calculate_gross_realized_drawdown, summarize_gross_realized_drawdown):
            with self.assertRaisesRegex(ValueError, "GROSS.*capital_after"):
                function(net)
        for function in (calculate_net_realized_drawdown, summarize_net_realized_drawdown):
            with self.assertRaisesRegex(ValueError, "NET.*net_capital_after"):
                function(gross)

    def test_actual_stage4_outputs_integrate_and_gross_net_paths_differ(self):
        trades = ledger([(100, 110), (100, 90), (50_000, None)])
        gross = calculate_trade_results(trades)
        net = calculate_trade_results_with_costs(trades, fee_rate=.001, slippage_rate=.0005)
        gross_path = calculate_gross_realized_drawdown(gross)
        net_path = calculate_net_realized_drawdown(net)
        np.testing.assert_allclose(gross_path.capital, [10_000, 11_000, 9_900])
        np.testing.assert_allclose(summarize_gross_realized_drawdown(gross).loc["GROSS"], [-.1, -1_100])
        np.testing.assert_allclose(net_path.capital.iloc[1:], net.net_capital_after.iloc[:2])
        self.assertFalse(gross_path.capital.equals(net_path.capital))
        self.assertLess(summarize_net_realized_drawdown(net).loc["NET", "max_realized_drawdown"], -.1)
        for path_function, summary_function, label, results in (
            (calculate_gross_realized_drawdown, summarize_gross_realized_drawdown, "GROSS", gross),
            (calculate_net_realized_drawdown, summarize_net_realized_drawdown, "NET", net),
        ):
            self.assertEqual(len(path_function(results)), 3)
            pd.testing.assert_frame_equal(path_function(results), path_function(results.iloc[:-1]))
            pd.testing.assert_frame_equal(summary_function(results), summary_function(results.iloc[:-1]))


if __name__ == "__main__":
    unittest.main()
