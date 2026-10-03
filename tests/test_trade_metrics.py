"""Synthetic accounting summaries test decision 003 without a market-data file."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.analytics.trade_metrics import (
    BREAKEVEN_TOLERANCE,
    summarize_gross_trade_performance,
    summarize_net_trade_performance,
)
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.costs import calculate_trade_results_with_costs


METRIC_COLUMNS = [
    "closed_trade_count", "winning_trade_count", "losing_trade_count", "breakeven_trade_count",
    "win_rate", "loss_rate", "breakeven_rate", "average_trade_return", "median_trade_return",
    "average_win_return", "average_loss_return", "best_trade_return", "worst_trade_return",
    "total_realized_pnl", "expectancy_pnl", "profit_factor",
]
SOURCES = [
    (summarize_gross_trade_performance, "GROSS", "trade_return", "gross_pnl", "capital_after"),
    (summarize_net_trade_performance, "NET", "net_trade_return", "net_pnl", "net_capital_after"),
]


def accounting(returns, pnl, *, net=False, include_open=False):
    """Explicit source outcomes; capital is context, not recalculated analytics."""
    return_column = "net_trade_return" if net else "trade_return"
    pnl_column = "net_pnl" if net else "gross_pnl"
    after_column = "net_capital_after" if net else "capital_after"
    frame = pd.DataFrame({
        "status": ["CLOSED"] * len(returns),
        return_column: pd.Series(returns, dtype="float64"),
        pnl_column: pd.Series(pnl, dtype="float64"),
        "capital_before": pd.Series([10_000.0] * len(returns), dtype="float64"),
        after_column: pd.Series([10_000.0 + value for value in pnl], dtype="float64"),
    })
    if include_open:
        frame.loc[len(frame)] = ["OPEN", np.nan, np.nan, 12_345.0, np.nan]
    return frame


def ledger(prices):
    """Small six-column ledger for integration with actual Stage 4 helpers."""
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


class TradeMetricTests(unittest.TestCase):
    def summaries(self, returns, pnl, include_open=False):
        for function, label, _, _, _ in SOURCES:
            frame = accounting(returns, pnl, net=label == "NET", include_open=include_open)
            yield function, label, frame, function(frame)

    def test_mixed_population_all_sixteen_metrics(self):
        expected = [5, 2, 2, 1, .4, .4, .2, .03, 0, .15, -.075, .2, -.1, 240, 48, 500 / 260]
        for _, label, _, summary in self.summaries([.1, -.05, 0, .2, -.1], [100, -60, 0, 400, -200]):
            with self.subTest(source=label):
                np.testing.assert_allclose(summary.loc[label], expected, rtol=1e-12, atol=1e-12)

    def test_exact_schema_index_and_column_dtypes(self):
        for _, label, _, summary in self.summaries([.1], [100]):
            self.assertEqual(summary.columns.tolist(), METRIC_COLUMNS)
            self.assertEqual(summary.index.tolist(), [label])
            self.assertEqual(summary.shape, (1, 16))
            for column in METRIC_COLUMNS[:4]:
                self.assertTrue(pd.api.types.is_integer_dtype(summary[column]))
            for column in METRIC_COLUMNS[4:]:
                self.assertEqual(str(summary[column].dtype), "float64")

    def test_positive_tolerance_boundary_is_breakeven(self):
        self.assertEqual(BREAKEVEN_TOLERANCE, 1e-12)
        for _, label, _, summary in self.summaries([1e-12], [.01]):
            self.assertEqual(summary.loc[label, "breakeven_trade_count"], 1)

    def test_negative_tolerance_boundary_is_breakeven(self):
        for _, label, _, summary in self.summaries([-1e-12], [-.01]):
            self.assertEqual(summary.loc[label, "breakeven_trade_count"], 1)

    def test_next_float_above_tolerance_is_win(self):
        for _, label, _, summary in self.summaries([np.nextafter(1e-12, np.inf)], [.01]):
            self.assertEqual(summary.loc[label, "winning_trade_count"], 1)

    def test_next_float_below_negative_tolerance_is_loss(self):
        for _, label, _, summary in self.summaries([np.nextafter(-1e-12, -np.inf)], [-.01]):
            self.assertEqual(summary.loc[label, "losing_trade_count"], 1)

    def test_display_rounding_does_not_affect_classification(self):
        self.assertEqual(round(2e-12, 6), 0.0)
        for _, label, _, summary in self.summaries([2e-12, -2e-12], [.01, -.01]):
            self.assertEqual(summary.loc[label, "winning_trade_count"], 1)
            self.assertEqual(summary.loc[label, "losing_trade_count"], 1)
            self.assertEqual(summary.loc[label, "breakeven_trade_count"], 0)

    def test_empty_population_counts_total_and_nan_statistics(self):
        for _, label, _, summary in self.summaries([], []):
            self.assertTrue(summary.loc[label, METRIC_COLUMNS[:4]].eq(0).all())
            self.assertEqual(summary.loc[label, "total_realized_pnl"], 0.0)
            undefined = [column for column in METRIC_COLUMNS[4:] if column != "total_realized_pnl"]
            self.assertTrue(summary.loc[label, undefined].isna().all())
            for column in METRIC_COLUMNS[:4]:
                self.assertTrue(pd.api.types.is_integer_dtype(summary[column]))

    def test_open_only_equals_empty_summary(self):
        for function, label, _, summary in self.summaries([], [], include_open=True):
            pd.testing.assert_frame_equal(summary, function(accounting([], [], net=label == "NET")))

    def test_valid_final_open_row_does_not_change_closed_statistics(self):
        for function, label, frame, summary in self.summaries([.1, -.2], [100, -150]):
            with_open = accounting([.1, -.2], [100, -150], net=label == "NET", include_open=True)
            with_open["entry_fee"] = [10, 10, 999]
            with_open["quantity"] = [1, 2, 9_999]
            pd.testing.assert_frame_equal(summary, function(with_open))

    def test_all_wins_have_nan_average_loss_and_infinite_profit_factor(self):
        for _, label, _, summary in self.summaries([.1, .3], [100, 600]):
            self.assertEqual(summary.loc[label, "win_rate"], 1.0)
            self.assertTrue(np.isnan(summary.loc[label, "average_loss_return"]))
            self.assertEqual(summary.loc[label, "profit_factor"], np.inf)
            self.assertEqual(summary.loc[label, "worst_trade_return"], .1)

    def test_all_losses_have_nan_average_win_and_zero_profit_factor(self):
        for _, label, _, summary in self.summaries([-.1, -.3], [-100, -600]):
            self.assertEqual(summary.loc[label, "loss_rate"], 1.0)
            self.assertTrue(np.isnan(summary.loc[label, "average_win_return"]))
            self.assertEqual(summary.loc[label, "profit_factor"], 0.0)
            self.assertEqual(summary.loc[label, "best_trade_return"], -.1)

    def test_all_breakevens_keep_raw_return_statistics(self):
        for _, label, _, summary in self.summaries([0, 5e-13, -1e-12], [0, .01, -.02]):
            row = summary.loc[label]
            self.assertEqual(row.winning_trade_count, 0)
            self.assertEqual(row.losing_trade_count, 0)
            self.assertEqual(row.breakeven_trade_count, 3)
            self.assertEqual(row.breakeven_rate, 1)
            self.assertTrue(np.isnan(row.profit_factor))
            self.assertTrue(np.isnan(row.average_win_return))
            self.assertTrue(np.isnan(row.average_loss_return))
            self.assertAlmostEqual(row.average_trade_return, -5e-13 / 3, delta=1e-27)
            self.assertEqual(row.median_trade_return, 0)
            self.assertEqual(row.best_trade_return, 5e-13)
            self.assertEqual(row.worst_trade_return, -1e-12)

    def test_breakeven_residual_pnl_enters_totals_but_not_profit_factor(self):
        for _, label, _, summary in self.summaries([.1, -.1, 5e-13, -5e-13], [100, -50, .01, -.02]):
            row = summary.loc[label]
            self.assertAlmostEqual(row.total_realized_pnl, 49.99)
            self.assertAlmostEqual(row.expectancy_pnl, 49.99 / 4)
            self.assertEqual(row.profit_factor, 2.0)
            self.assertAlmostEqual(row.average_win_return, .1)
            self.assertAlmostEqual(row.average_loss_return, -.1)

    def test_single_closed_win(self):
        for _, label, _, summary in self.summaries([.25], [123]):
            row = summary.loc[label]
            self.assertEqual(row.winning_trade_count, 1)
            self.assertTrue(row[["average_trade_return", "median_trade_return", "average_win_return", "best_trade_return", "worst_trade_return"]].eq(.25).all())
            self.assertEqual(row.total_realized_pnl, 123)
            self.assertEqual(row.expectancy_pnl, 123)
            self.assertEqual(row.profit_factor, np.inf)

    def test_single_closed_loss(self):
        for _, label, _, summary in self.summaries([-.25], [-123]):
            row = summary.loc[label]
            self.assertEqual(row.losing_trade_count, 1)
            self.assertTrue(row[["average_trade_return", "median_trade_return", "average_loss_return", "best_trade_return", "worst_trade_return"]].eq(-.25).all())
            self.assertEqual(row.expectancy_pnl, -123)
            self.assertEqual(row.profit_factor, 0)

    def test_single_closed_breakeven_with_residual(self):
        for _, label, _, summary in self.summaries([5e-13], [.01]):
            row = summary.loc[label]
            self.assertEqual(row.breakeven_trade_count, 1)
            self.assertTrue(row[["average_trade_return", "median_trade_return", "best_trade_return", "worst_trade_return"]].eq(5e-13).all())
            self.assertEqual(row.total_realized_pnl, .01)
            self.assertEqual(row.expectancy_pnl, .01)
            self.assertTrue(np.isnan(row.profit_factor))

    def test_actual_accounting_gross_win_can_be_net_loss(self):
        trades = ledger([(100, 100.1)])
        gross = summarize_gross_trade_performance(calculate_trade_results(trades))
        net = summarize_net_trade_performance(calculate_trade_results_with_costs(trades, fee_rate=.001))
        self.assertEqual(gross.loc["GROSS", "winning_trade_count"], 1)
        self.assertEqual(net.loc["NET", "losing_trade_count"], 1)

    def test_expectancy_identity(self):
        for _, label, _, summary in self.summaries([.1, -.1, 0], [300, -100, .01]):
            row = summary.loc[label]
            self.assertAlmostEqual(row.expectancy_pnl, row.total_realized_pnl / row.closed_trade_count)

    def test_rates_sum_to_one_as_decimal_fractions(self):
        for _, label, _, summary in self.summaries([.1, -.1, 0], [100, -100, 0]):
            row = summary.loc[label]
            self.assertAlmostEqual(row.win_rate + row.loss_rate + row.breakeven_rate, 1.0)
            self.assertAlmostEqual(row.win_rate, 1 / 3)

    def test_count_identity(self):
        for _, label, _, summary in self.summaries([.1, -.1, 0, 1e-12], [100, -100, 0, .01]):
            row = summary.loc[label]
            self.assertEqual(row.closed_trade_count, row.winning_trade_count + row.losing_trade_count + row.breakeven_trade_count)

    def test_wrong_actual_accounting_source_rejected(self):
        trades = ledger([(100, 110)])
        gross = calculate_trade_results(trades)
        net = calculate_trade_results_with_costs(trades, fee_rate=.001)
        with self.assertRaisesRegex(ValueError, "GROSS.*trade_return.*capital_after"):
            summarize_gross_trade_performance(net)
        with self.assertRaisesRegex(ValueError, "NET.*net_trade_return.*net_pnl.*net_capital_after"):
            summarize_net_trade_performance(gross)

    def test_actual_stage4_outputs_integrate_without_btc_csv(self):
        trades = ledger([(100, 110), (200, 180), (50_000, None)])
        gross_results = calculate_trade_results(trades)
        net_results = calculate_trade_results_with_costs(trades, fee_rate=.001, slippage_rate=.0005)
        for function, label, results in [
            (summarize_gross_trade_performance, "GROSS", gross_results),
            (summarize_net_trade_performance, "NET", net_results),
        ]:
            summary = function(results)
            self.assertEqual(summary.loc[label, "closed_trade_count"], 2)
            pd.testing.assert_frame_equal(summary, function(results.iloc[:-1]))
        self.assertAlmostEqual(summarize_gross_trade_performance(gross_results).loc["GROSS", "total_realized_pnl"], -100)

    def test_non_dataframe_input_rejected(self):
        for function, _, _, _, _ in SOURCES:
            for value in (None, [], {}, pd.Series([.1])):
                with self.subTest(value=type(value).__name__):
                    with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
                        function(value)

    def test_every_required_column_is_checked_even_for_empty_input(self):
        for function, label, _, _, _ in SOURCES:
            for empty in (False, True):
                frame = accounting([] if empty else [.1], [] if empty else [100], net=label == "NET")
                for column in frame.columns:
                    with self.subTest(source=label, empty=empty, column=column):
                        with self.assertRaisesRegex(ValueError, "missing required columns"):
                            function(frame.drop(columns=column))

    def test_duplicate_columns_rejected(self):
        for function, label, frame, _ in self.summaries([.1], [100]):
            with self.assertRaisesRegex(ValueError, "column names must be unique"):
                function(pd.concat([frame, frame[["status"]]], axis=1))

    def test_invalid_status_rejected_without_changing_input(self):
        for function, label, frame, _ in self.summaries([.1], [100]):
            for value in ("closed", "UNKNOWN", None, pd.NA, np.nan, True, 1):
                with self.subTest(source=label, value=str(value)):
                    invalid = frame.assign(status=pd.Series([value], dtype="object"))
                    original = invalid.copy(deep=True)
                    with self.assertRaisesRegex(ValueError, "CLOSED or OPEN"):
                        function(invalid)
                    pd.testing.assert_frame_equal(invalid, original)

    def test_nonfinite_closed_returns_rejected(self):
        for function, label, return_column, _, _ in SOURCES:
            for value in (np.nan, np.inf, -np.inf):
                frame = accounting([.1], [100], net=label == "NET")
                frame[return_column] = value
                with self.assertRaisesRegex(ValueError, return_column):
                    function(frame)

    def test_nonfinite_closed_pnl_rejected(self):
        for function, label, _, pnl_column, _ in SOURCES:
            for value in (np.nan, np.inf, -np.inf):
                frame = accounting([.1], [100], net=label == "NET")
                frame[pnl_column] = value
                with self.assertRaisesRegex(ValueError, pnl_column):
                    function(frame)

    def test_strings_bools_complex_and_missing_closed_values_rejected(self):
        for function, label, return_column, pnl_column, _ in SOURCES:
            for column in (return_column, pnl_column):
                for value in ("0.1", True, False, np.bool_(True), 1 + 0j, None, pd.NA, 10 ** 400):
                    with self.subTest(source=label, column=column, value=str(value)[:25]):
                        frame = accounting([.1], [100], net=label == "NET")
                        frame[column] = frame[column].astype("object")
                        frame.loc[0, column] = value
                        with self.assertRaisesRegex(ValueError, column):
                            function(frame)

    def test_input_rows_values_index_dtypes_and_columns_preserved(self):
        for function, label, frame, _ in self.summaries([.1, -.1, 0], [100, -200, 0]):
            frame.index = pd.Index([30, 10, 20], name="source_row")
            frame["note"] = "keep me"
            original = frame.copy(deep=True)
            summary = function(frame)
            pd.testing.assert_frame_equal(frame, original)
            summary.loc[label, "total_realized_pnl"] = 999
            pd.testing.assert_frame_equal(frame, original)

    def test_optional_columns_ignored_including_other_source_fields(self):
        for function, label, frame, summary in self.summaries([.1, -.1], [100, -50]):
            frame["note"] = "irrelevant"
            frame["entry_fee"] = 999
            frame["quantity"] = np.nan
            other_return = "net_trade_return" if label == "GROSS" else "trade_return"
            other_pnl = "net_pnl" if label == "GROSS" else "gross_pnl"
            frame[other_return] = -.9
            frame[other_pnl] = -99_999
            pd.testing.assert_frame_equal(function(frame), summary)

    def test_finite_real_object_values_and_numpy_scalars_accepted(self):
        for function, label, return_column, pnl_column, _ in SOURCES:
            frame = accounting([.1, -.2], [100, -200], net=label == "NET")
            frame[return_column] = pd.Series([np.float64(.1), np.float32(-.2)], dtype="object")
            frame[pnl_column] = pd.Series([np.int64(100), -200], dtype="object")
            summary = function(frame)
            self.assertEqual(summary.loc[label, "closed_trade_count"], 2)
            self.assertEqual(summary.loc[label, "profit_factor"], .5)

    def test_unsorted_duplicate_input_index_is_not_repaired(self):
        for function, label, frame, summary in self.summaries([.1, -.1, 0], [100, -50, 0]):
            frame.index = [2, 1, 2]
            original = frame.copy(deep=True)
            pd.testing.assert_frame_equal(function(frame), summary)
            pd.testing.assert_frame_equal(frame, original)

    def test_even_population_median_uses_two_middle_returns(self):
        for _, label, _, summary in self.summaries([.4, -.1, .2, .1], [400, -100, 200, 100]):
            self.assertAlmostEqual(summary.loc[label, "median_trade_return"], .15)


if __name__ == "__main__":
    unittest.main()
