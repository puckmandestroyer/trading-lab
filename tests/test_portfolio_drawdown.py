"""Synthetic decision 007 checks and integration with the unchanged equity layer."""

from datetime import datetime, timezone
from fractions import Fraction
import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.analytics.portfolio_drawdown import (
    calculate_gross_portfolio_drawdown,
    calculate_net_portfolio_drawdown,
    summarize_gross_portfolio_drawdown,
    summarize_net_portfolio_drawdown,
)
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results


START = pd.Timestamp("2025-01-01", tz="UTC")
HOUR = pd.Timedelta(hours=1)
PATH_COLUMNS = [
    "observation", "valuation_time", "equity", "running_peak", "drawdown", "drawdown_amount",
]
SUMMARY_COLUMNS = [
    "max_portfolio_drawdown", "max_portfolio_drawdown_amount", "peak_observation",
    "trough_observation", "peak_valuation_time", "trough_valuation_time", "peak_equity", "trough_equity",
]
CALCULATORS = [calculate_gross_portfolio_drawdown, calculate_net_portfolio_drawdown]
SUMMARIZERS = [summarize_gross_portfolio_drawdown, summarize_net_portfolio_drawdown]
FUNCTIONS = CALCULATORS + SUMMARIZERS


def equity_source(values, times=None):
    """Make only the three required fields; no candles or trades are implied."""
    if times is None:
        times = pd.date_range(START, periods=len(values), freq="h")
    return pd.DataFrame({
        "observation": pd.Series(range(len(values)), dtype="int64"),
        "valuation_time": times,
        "equity": values,
    })


def integration_sources(final_close=90):
    """Real Stage 4 accounting → Stage 5.11 equity, with CLOSED then final OPEN."""
    candles = pd.DataFrame({
        "timestamp": pd.date_range(START, periods=4, freq="h"),
        "close": [110, 90, 120, final_close],
    })
    trades = pd.DataFrame({
        "trade_id": [1, 2],
        "entry_time": [START, START + 3 * HOUR],
        "entry_price": [100, 100],
        "exit_time": pd.Series([START + 2 * HOUR, pd.NaT], dtype="datetime64[ns, UTC]"),
        "exit_price": [120, np.nan],
        "status": ["CLOSED", "OPEN"],
    })
    gross = calculate_trade_results(trades, 1_000)
    net = calculate_trade_results_with_costs(trades, 1_000, fee_rate=.01, slippage_rate=.02)
    return (
        calculate_gross_mark_to_market_equity(candles, gross, HOUR, 1_000),
        calculate_net_mark_to_market_equity(candles, net, HOUR, 1_000),
        trades,
    )


class PortfolioDrawdownTests(unittest.TestCase):
    def assert_invalid(self, source, message):
        """All wrappers share the same required contract and error behavior."""
        for function in FUNCTIONS:
            with self.subTest(function=function.__name__):
                with self.assertRaisesRegex(ValueError, message):
                    function(source)

    def test_exact_path_schema_order_range_index_and_length(self):
        source = equity_source([1_000, 900, 1_200])
        source.index = [8, 8, -4]
        for function in CALCULATORS:
            path = function(source)
            self.assertEqual(path.columns.tolist(), PATH_COLUMNS)
            pd.testing.assert_index_equal(path.index, pd.RangeIndex(3))
            self.assertEqual(len(path), len(source))
            self.assertEqual(path.observation.tolist(), [0, 1, 2])

    def test_exact_path_dtypes(self):
        for function in CALCULATORS:
            path = function(equity_source([1_000, 900]))
            self.assertEqual(str(path.observation.dtype), "int64")
            self.assertEqual(str(path.valuation_time.dtype), "datetime64[ns, UTC]")
            for column in ["equity", "running_peak", "drawdown", "drawdown_amount"]:
                self.assertEqual(str(path[column].dtype), "float64")

    def test_exact_summary_schema_order_and_index(self):
        for function, label in zip(SUMMARIZERS, ["GROSS", "NET"]):
            summary = function(equity_source([1_000, 900]))
            self.assertEqual(summary.columns.tolist(), SUMMARY_COLUMNS)
            self.assertEqual(summary.index.tolist(), [label])
            self.assertEqual(summary.shape, (1, 8))

    def test_exact_summary_dtypes(self):
        for function in SUMMARIZERS:
            summary = function(equity_source([1_000, 900]))
            for column in ["max_portfolio_drawdown", "max_portfolio_drawdown_amount", "peak_equity", "trough_equity"]:
                self.assertEqual(str(summary[column].dtype), "float64")
            for column in ["peak_observation", "trough_observation"]:
                self.assertEqual(str(summary[column].dtype), "int64")
            for column in ["peak_valuation_time", "trough_valuation_time"]:
                self.assertEqual(str(summary[column].dtype), "datetime64[ns, UTC]")

    def test_initial_only_path(self):
        for function in CALCULATORS:
            path = function(equity_source([1_000]))
            self.assertEqual(len(path), 1)
            self.assertEqual(path.iloc[0].tolist(), [0, START, 1_000, 1_000, 0, 0])

    def test_initial_only_summary(self):
        for function in SUMMARIZERS:
            summary = function(equity_source([1_000]))
            self.assertEqual(summary.iloc[0].tolist(), [0, 0, 0, 0, START, START, 1_000, 1_000])

    def test_initial_observation_is_retained_without_synthetic_point(self):
        source = equity_source([725, 600, 800])
        for function in CALCULATORS:
            path = function(source)
            self.assertEqual(len(path), 3)
            self.assertEqual(path.equity.tolist(), source.equity.tolist())
            self.assertEqual(path.iloc[0].tolist(), [0, START, 725, 725, 0, 0])

    def test_worked_example_path(self):
        for function in CALCULATORS:
            path = function(equity_source([1_000, 1_100, 900, 1_200, 1_000]))
            self.assertEqual(path.running_peak.tolist(), [1_000, 1_100, 1_100, 1_200, 1_200])
            np.testing.assert_allclose(path.drawdown, [0, 0, 900 / 1_100 - 1, 0, 1_000 / 1_200 - 1])
            self.assertEqual(path.drawdown_amount.tolist(), [0, 0, -200, 0, -200])

    def test_worked_example_summary(self):
        for function in SUMMARIZERS:
            row = function(equity_source([1_000, 1_100, 900, 1_200, 1_000])).iloc[0]
            self.assertEqual(row.max_portfolio_drawdown, 900 / 1_100 - 1)
            self.assertEqual(row.max_portfolio_drawdown_amount, -200)
            self.assertEqual((row.peak_observation, row.trough_observation), (1, 2))
            self.assertEqual((row.peak_equity, row.trough_equity), (1_100, 900))
            self.assertEqual((row.peak_valuation_time, row.trough_valuation_time), (START + HOUR, START + 2 * HOUR))

    def test_flat_path_summary_selects_initial_point(self):
        for function in SUMMARIZERS:
            row = function(equity_source([1_000, 1_000, 1_000])).iloc[0]
            self.assertEqual(row.tolist(), [0, 0, 0, 0, START, START, 1_000, 1_000])

    def test_increasing_path_summary_selects_initial_point(self):
        for function in SUMMARIZERS:
            row = function(equity_source([1_000, 1_100, 1_200])).iloc[0]
            self.assertEqual(row.tolist(), [0, 0, 0, 0, START, START, 1_000, 1_000])

    def test_first_close_loss_uses_initial_reference(self):
        for function in CALCULATORS:
            path = function(equity_source([1_000, 900]))
            self.assertEqual(path.running_peak.tolist(), [1_000, 1_000])
            self.assertEqual(path.drawdown.iloc[1], 900 / 1_000 - 1)
            self.assertEqual(path.drawdown_amount.iloc[1], -100)

    def test_zero_later_equity_is_full_loss(self):
        for calculate, summarize in zip(CALCULATORS, SUMMARIZERS):
            source = equity_source([1_000, 0, 0])
            path = calculate(source)
            self.assertEqual(path.drawdown.tolist(), [0, -1, -1])
            self.assertEqual(path.drawdown_amount.tolist(), [0, -1_000, -1_000])
            self.assertEqual(summarize(source).trough_observation.iloc[0], 1)

    def test_recovery_to_old_peak_does_not_erase_historical_drawdown(self):
        source = equity_source([1_000, 800, 1_000])
        for calculate, summarize in zip(CALCULATORS, SUMMARIZERS):
            self.assertEqual(calculate(source).drawdown.iloc[-1], 0)
            self.assertEqual(summarize(source).max_portfolio_drawdown.iloc[0], 800 / 1_000 - 1)

    def test_new_high_updates_running_peak(self):
        for function in CALCULATORS:
            path = function(equity_source([1_000, 800, 1_200, 1_080]))
            self.assertEqual(path.running_peak.tolist(), [1_000, 1_000, 1_200, 1_200])
            self.assertEqual(path.drawdown.iloc[2], 0)
            self.assertEqual(path.drawdown.iloc[3], 1_080 / 1_200 - 1)

    def test_earliest_repeated_minimum_trough_wins(self):
        for function in SUMMARIZERS:
            row = function(equity_source([100, 80, 100, 80])).iloc[0]
            self.assertEqual((row.peak_observation, row.trough_observation), (0, 1))
            self.assertEqual(row.trough_valuation_time, START + HOUR)

    def test_latest_repeated_equal_peak_before_trough_wins(self):
        for function in SUMMARIZERS:
            row = function(equity_source([100, 120, 120, 100, 120])).iloc[0]
            self.assertEqual((row.peak_observation, row.trough_observation), (2, 3))
            self.assertEqual(row.peak_valuation_time, START + 2 * HOUR)

    def test_minimum_trough_comparison_is_exact_not_rounded_or_tolerant(self):
        for function in SUMMARIZERS:
            row = function(equity_source([1_000, 900, 1_000, np.nextafter(900.0, 0)])).iloc[0]
            self.assertEqual(row.trough_observation, 3)

    def test_associated_peak_comparison_is_exact_not_tolerant(self):
        for function in SUMMARIZERS:
            row = function(equity_source([100, 120, np.nextafter(120.0, 0), 100])).iloc[0]
            self.assertEqual(row.peak_observation, 1)

    def test_summary_amount_belongs_to_percentage_trough(self):
        # -20% / -200 at row 1 is worse proportionally than -15% / -300 at row 3.
        source = equity_source([1_000, 800, 2_000, 1_700])
        for calculate, summarize in zip(CALCULATORS, SUMMARIZERS):
            path = calculate(source)
            row = summarize(source).iloc[0]
            self.assertEqual(path.drawdown_amount.min(), -300)
            self.assertEqual(row.trough_observation, 1)
            self.assertEqual(row.max_portfolio_drawdown_amount, -200)
            self.assertEqual(row.trough_equity, 800)

    def test_gross_and_net_wrappers_share_math_with_explicit_labels(self):
        source = equity_source([100, 120, 90])
        pd.testing.assert_frame_equal(CALCULATORS[0](source), CALCULATORS[1](source))
        gross, net = [function(source) for function in SUMMARIZERS]
        self.assertEqual(gross.index.tolist(), ["GROSS"])
        self.assertEqual(net.index.tolist(), ["NET"])
        pd.testing.assert_frame_equal(gross.reset_index(drop=True), net.reset_index(drop=True))

    def test_independent_gross_and_net_inputs_are_authoritative(self):
        gross = calculate_gross_portfolio_drawdown(equity_source([1_000, 1_200, 900]))
        net = calculate_net_portfolio_drawdown(equity_source([1_000, 1_050, 850]))
        self.assertEqual(gross.running_peak.iloc[-1], 1_200)
        self.assertEqual(net.running_peak.iloc[-1], 1_050)
        self.assertEqual(net.drawdown.iloc[-1], 850 / 1_050 - 1)

    def test_appending_future_observations_preserves_causal_prefix(self):
        complete = equity_source([1_000, 800, 1_200, 600, 5_000])
        for function in CALCULATORS:
            for size in [1, 2, 3, 4]:
                prefix = function(complete.iloc[:size])
                pd.testing.assert_frame_equal(prefix, function(complete).iloc[:size])

    def test_dataframe_is_required(self):
        for value in [None, [], {}, pd.Series([1_000])]:
            self.assert_invalid(value, "DataFrame")

    def test_duplicate_column_names_are_rejected(self):
        source = equity_source([1_000, 900])
        for name in ["equity", "unused"]:
            duplicate = source.copy()
            duplicate["unused"] = None
            duplicate = pd.concat([duplicate, duplicate[[name]]], axis=1)
            self.assert_invalid(duplicate, "unique")

    def test_required_columns_are_checked_even_on_empty_input(self):
        for size in [0, 2]:
            source = equity_source([1_000] * size)
            for column in ["observation", "valuation_time", "equity"]:
                self.assert_invalid(source.drop(columns=column), "missing required columns")

    def test_empty_input_with_valid_schema_is_rejected(self):
        self.assert_invalid(equity_source([]), "initial observation")

    def test_bool_observations_are_rejected(self):
        for value in [False, True, np.bool_(False)]:
            source = equity_source([1_000, 900])
            source["observation"] = pd.Series([value, 1], dtype=object)
            self.assert_invalid(source, "observation")

    def test_non_integer_observation_types_are_rejected(self):
        for value in [0.0, np.float64(0), "0", None, pd.NA, np.nan, 0j]:
            source = equity_source([1_000, 900])
            source["observation"] = pd.Series([value, 1], dtype=object)
            self.assert_invalid(source, "observation")

    def test_noncanonical_observations_are_not_reordered_or_repaired(self):
        for values in [[1, 2, 3], [-1, 0, 1], [0, 0, 1], [0, 2, 3], [0, 2, 1], [0, 1, 2**64]]:
            source = equity_source([1_000] * 3)
            source["observation"] = pd.Series(values, dtype=object)
            original = source.copy(deep=True)
            self.assert_invalid(source, "observation")
            pd.testing.assert_frame_equal(source, original)

    def test_existing_datetime_scalar_types_are_accepted(self):
        times = pd.Series([datetime(2025, 1, 1), np.datetime64("2025-01-02"), pd.Timestamp("2025-01-03")], dtype=object)
        for function in CALCULATORS:
            path = function(equity_source([1_000] * 3, times))
            self.assertEqual(str(path.valuation_time.dtype), "datetime64[ns]")
            self.assertEqual(path.valuation_time.iloc[-1], pd.Timestamp("2025-01-03"))

    def test_invalid_or_missing_valuation_time_types_are_rejected(self):
        for value in ["2025-01-01", 1_735_689_600, 1.0, False, None, pd.NaT, pd.NA, np.datetime64("NaT")]:
            source = equity_source([1_000, 900])
            source["valuation_time"] = pd.Series([value, START + HOUR], dtype=object)
            self.assert_invalid(source, "valuation_time")

    def test_unsafe_valuation_timestamps_are_rejected(self):
        source = equity_source([1_000])
        source["valuation_time"] = pd.Series([datetime(3000, 1, 1)], dtype=object)
        self.assert_invalid(source, "representable")

    def test_duplicate_or_reversed_valuation_times_are_rejected(self):
        for times in [[START, START], [START + HOUR, START]]:
            self.assert_invalid(equity_source([1_000, 900], times), "strictly increasing")

    def test_mixed_naive_and_aware_times_are_rejected(self):
        times = pd.Series([datetime(2025, 1, 1), START + HOUR], dtype=object)
        self.assert_invalid(equity_source([1_000, 900], times), "timezone")

    def test_incompatible_timezone_zones_are_rejected(self):
        times = pd.Series([START, (START + HOUR).tz_convert("Asia/Seoul")], dtype=object)
        self.assert_invalid(equity_source([1_000, 900], times), "timezone")

    def test_incompatible_timezone_implementations_are_rejected(self):
        times = pd.Series([
            datetime(2025, 1, 1, tzinfo=timezone.utc),
            datetime(2025, 1, 2, tzinfo=ZoneInfo("UTC")),
        ], dtype=object)
        self.assert_invalid(equity_source([1_000, 900], times), "timezone")

    def test_naive_clock_is_preserved_in_paths_and_summaries(self):
        times = pd.date_range("2025-01-01", periods=2, freq="h")
        source = equity_source([1_000, 900], times)
        for calculate, summarize in zip(CALCULATORS, SUMMARIZERS):
            self.assertEqual(str(calculate(source).valuation_time.dtype), "datetime64[ns]")
            self.assertEqual(str(summarize(source).peak_valuation_time.dtype), "datetime64[ns]")
            self.assertEqual(str(summarize(source).trough_valuation_time.dtype), "datetime64[ns]")

    def test_coherent_aware_clock_is_preserved(self):
        zone = ZoneInfo("Asia/Seoul")
        times = pd.date_range("2025-01-01", periods=2, freq="h", tz=zone)
        source = equity_source([1_000, 900], times)
        for calculate, summarize in zip(CALCULATORS, SUMMARIZERS):
            path, summary = calculate(source), summarize(source)
            self.assertEqual(path.valuation_time.dtype, source.valuation_time.dtype)
            self.assertEqual(summary.trough_valuation_time.dtype, source.valuation_time.dtype)
            self.assertEqual(summary.trough_valuation_time.iloc[0], times[1])

    def test_same_zone_spring_dst_change_is_valid(self):
        times = pd.date_range("2025-03-09 01:00", periods=3, freq="h", tz=ZoneInfo("America/New_York"))
        self.assertEqual([stamp.hour for stamp in times], [1, 3, 4])
        for function in CALCULATORS:
            path = function(equity_source([1_000, 900, 950], times))
            self.assertEqual(path.valuation_time.tolist(), times.tolist())

    def test_same_zone_fall_dst_repeated_wall_clock_is_valid(self):
        # The two 01:00 labels have different offsets and increasing actual time.
        for zone in ["America/New_York", ZoneInfo("America/New_York")]:
            times = pd.date_range("2025-11-02 00:00", periods=4, freq="h", tz=zone)
            self.assertEqual([stamp.hour for stamp in times], [0, 1, 1, 2])
            for function in CALCULATORS:
                path = function(equity_source([1_000, 900, 800, 950], times))
                self.assertEqual(path.valuation_time.dtype, times.dtype)
                self.assertEqual(path.valuation_time.tolist(), times.tolist())

    def test_unequal_time_spacing_is_valid_without_candle_interval(self):
        times = [START, START + HOUR, START + pd.Timedelta(days=3)]
        for function in CALCULATORS:
            path = function(equity_source([1_000, 900, 950], times))
            self.assertEqual(path.valuation_time.tolist(), times)

    def test_bool_equity_is_rejected_at_any_observation(self):
        for value in [True, False, np.bool_(True)]:
            for position in [0, 1]:
                source = equity_source([1_000, 900])
                source["equity"] = source.equity.astype(object)
                source.at[position, "equity"] = value
                self.assert_invalid(source, "equity")

    def test_invalid_equity_values_are_rejected_at_any_observation(self):
        for value in [None, pd.NA, np.nan, np.inf, -np.inf, "1000", 1_000 + 0j]:
            for position in [0, 1]:
                source = equity_source([1_000, 900])
                source["equity"] = source.equity.astype(object)
                source.at[position, "equity"] = value
                self.assert_invalid(source, "equity")

    def test_negative_later_equity_is_rejected(self):
        self.assert_invalid(equity_source([1_000, -1]), "non-negative")

    def test_initial_zero_or_negative_equity_is_rejected(self):
        for value in [0, -1]:
            self.assert_invalid(equity_source([value, 100]), "strictly positive")

    def test_unsafe_float64_equity_conversion_is_rejected(self):
        for value in [10**400, Fraction(1, 10**400), Fraction(-1, 10**400)]:
            source = equity_source([1_000, 900])
            source["equity"] = pd.Series([1_000, value], dtype=object)
            self.assert_invalid(source, "representable")

    def test_extreme_valid_float64_equity_calculates_finite_fields(self):
        source = equity_source([np.finfo(np.float64).tiny, np.finfo(np.float64).max, 0])
        for function in CALCULATORS:
            path = function(source)
            self.assertTrue(np.isfinite(path[["equity", "running_peak", "drawdown", "drawdown_amount"]]).all().all())
            self.assertEqual(path.drawdown.iloc[-1], -1)

    def test_optional_columns_are_ignored_even_when_malformed(self):
        source = equity_source([1_000, 900])
        extras = source.copy()
        for column in ["status", "position", "quantity", "fee", "close", "signal", "running_peak", "drawdown"]:
            extras[column] = "irrelevant"
        # Even a NET-intended path cannot be identified by extra columns.
        extras["source"] = "NET"
        extras = extras[list(reversed(extras.columns))]
        for function in FUNCTIONS:
            pd.testing.assert_frame_equal(function(extras), function(source))

    def test_duplicate_nondefault_index_is_preserved_and_not_used_as_ordinal(self):
        source = equity_source([1_000, 900, 1_200])
        source.index = pd.Index(["last", "first", "first"], name="original")
        original = source.copy(deep=True)
        for function in FUNCTIONS:
            function(source)
            pd.testing.assert_frame_equal(source, original)

    def test_full_input_values_dtypes_columns_and_order_are_preserved(self):
        source = equity_source([1_000, 900, 1_200])
        source["observation"] = source.observation.astype("UInt32")
        source["equity"] = source.equity.astype(object)
        source["unused"] = pd.Series([1, pd.NA, 3], dtype="Int64")
        source = source[["unused", "equity", "valuation_time", "observation"]]
        source.index = pd.Index([9, 9, 5], name="original")
        original = source.copy(deep=True)
        for function in FUNCTIONS:
            function(source)
            pd.testing.assert_frame_equal(source, original)

    def test_output_mutation_cannot_change_input(self):
        source = equity_source([1_000, 900])
        original = source.copy(deep=True)
        for function in FUNCTIONS:
            output = function(source)
            for column in output.columns:
                output.loc[output.index[0], column] = output[column].iloc[-1]
            # Assign different valid amounts/times to exercise independence.
            output.iloc[0, 0] = 7
            pd.testing.assert_frame_equal(source, original)

    def test_input_mutation_cannot_change_previously_returned_output(self):
        for function in FUNCTIONS:
            source = equity_source([1_000, 900])
            output = function(source)
            original_output = output.copy(deep=True)
            source.at[0, "equity"] = 2_000
            source.at[0, "valuation_time"] = START - HOUR
            pd.testing.assert_frame_equal(output, original_output)

    def test_real_stage_511_equity_paths_integrate_without_rebuilding(self):
        gross_equity, net_equity, _ = integration_sources()
        self.assertEqual(gross_equity.equity.tolist(), [1_000, 1_100, 900, 1_200, 1_080])
        self.assertFalse(gross_equity.equity.equals(net_equity.equity))
        for equity, calculate, summarize in zip([gross_equity, net_equity], CALCULATORS, SUMMARIZERS):
            original = equity.copy(deep=True)
            path, summary = calculate(equity), summarize(equity)
            self.assertEqual(len(path), 5)
            pd.testing.assert_frame_equal(path[["observation", "valuation_time", "equity"]], equity[["observation", "valuation_time", "equity"]])
            self.assertEqual(summary.trough_observation.iloc[0], 2)
            self.assertEqual(summary.trough_equity.iloc[0], equity.equity.iloc[2])
            pd.testing.assert_frame_equal(equity, original)

    def test_final_open_mark_is_naturally_included_and_can_be_selected_trough(self):
        gross_equity, net_equity, trades = integration_sources(final_close=50)
        original_trades = trades.copy(deep=True)
        self.assertEqual(trades.status.iloc[-1], "OPEN")
        self.assertTrue(pd.isna(trades.exit_time.iloc[-1]))
        for equity, calculate, summarize in zip([gross_equity, net_equity], CALCULATORS, SUMMARIZERS):
            path, summary = calculate(equity), summarize(equity)
            self.assertEqual(equity.position.iloc[-1], 1)
            self.assertEqual(path.equity.iloc[-1], equity.equity.iloc[-1])
            self.assertEqual(path.valuation_time.iloc[-1], START + 4 * HOUR)
            self.assertEqual(summary.trough_observation.iloc[0], 4)
            self.assertEqual(summary.trough_equity.iloc[0], path.equity.iloc[-1])
        pd.testing.assert_frame_equal(trades, original_trades)


if __name__ == "__main__":
    unittest.main()
