"""Synthetic ledger tests for elapsed holding time and binary exposure."""

from datetime import datetime, timezone
import unittest
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_lab.analytics.trade_time import (
    calculate_trade_time_breakdown,
    summarize_trade_time_metrics,
)
from trading_lab.backtest.execution import apply_next_open_execution
from trading_lab.backtest.trades import build_trade_ledger


START = pd.Timestamp("2025-01-01", tz="UTC")
END = START + pd.Timedelta(hours=10)
SOURCE_COLUMNS = ["trade_id", "status", "entry_time", "exit_time"]
BREAKDOWN_COLUMNS = SOURCE_COLUMNS + [
    "closed_duration_hours", "observed_time_in_market_hours",
]
SUMMARY_COLUMNS = [
    "closed_trade_count", "open_trade_count",
    "average_closed_duration_hours", "median_closed_duration_hours",
    "minimum_closed_duration_hours", "maximum_closed_duration_hours",
    "total_closed_duration_hours", "open_observed_duration_hours",
    "total_time_in_market_hours", "observation_window_hours", "exposure_ratio",
]
FUNCTIONS = (calculate_trade_time_breakdown, summarize_trade_time_metrics)


def ledger(intervals):
    """Create canonical fields from (status, entry hour, exit hour or None)."""
    return pd.DataFrame({
        "trade_id": pd.Series(range(1, len(intervals) + 1), dtype="int64"),
        "status": pd.Series([row[0] for row in intervals], dtype="object"),
        "entry_time": pd.Series(
            [START + pd.Timedelta(hours=row[1]) for row in intervals],
            dtype="datetime64[ns, UTC]",
        ),
        "exit_time": pd.Series(
            [pd.NaT if row[2] is None else START + pd.Timedelta(hours=row[2])
             for row in intervals], dtype="datetime64[ns, UTC]",
        ),
    })


class TradeTimeTests(unittest.TestCase):
    def assert_rejected(self, trades, start=START, end=END, message=None):
        for function in FUNCTIONS:
            with self.subTest(function=function.__name__):
                if message is None:
                    with self.assertRaises(ValueError):
                        function(trades, start, end)
                else:
                    with self.assertRaisesRegex(ValueError, message):
                        function(trades, start, end)

    def assert_summary_dtypes(self, summary):
        self.assertEqual(summary.index.tolist(), ["TIME"])
        self.assertEqual(summary.columns.tolist(), SUMMARY_COLUMNS)
        self.assertEqual(summary.dtypes.astype(str).tolist(), ["int64"] * 2 + ["float64"] * 9)

    def assert_undefined_closed_statistics(self, summary):
        self.assertTrue(summary.loc["TIME", SUMMARY_COLUMNS[2:6]].isna().all())
        self.assertEqual(summary.loc["TIME", "total_closed_duration_hours"], 0.0)

    def test_exact_schemas_and_dtypes(self):
        trades = ledger([("CLOSED", 1, 4), ("OPEN", 7, None)])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        self.assertEqual(breakdown.columns.tolist(), BREAKDOWN_COLUMNS)
        pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)
        self.assertEqual(breakdown.dtypes.astype(str).tolist()[-2:], ["float64", "float64"])
        self.assert_summary_dtypes(summarize_trade_time_metrics(trades, START, END))

    def test_decision_005_worked_example(self):
        trades = ledger([("CLOSED", 1, 4), ("OPEN", 7, None)])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        self.assertEqual(breakdown.loc[0, "closed_duration_hours"], 3.0)
        self.assertTrue(np.isnan(breakdown.loc[1, "closed_duration_hours"]))
        self.assertEqual(breakdown.observed_time_in_market_hours.tolist(), [3.0, 3.0])
        summary = summarize_trade_time_metrics(trades, START, END)
        self.assertEqual(summary.loc["TIME"].tolist(), [1, 1, 3, 3, 3, 3, 3, 3, 6, 10, 0.6])

    def test_fractional_elapsed_duration_is_not_a_candle_count(self):
        trades = ledger([("CLOSED", 1.25, 2.75)])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        self.assertEqual(breakdown.closed_duration_hours.iloc[0], 1.5)
        self.assertEqual(breakdown.observed_time_in_market_hours.iloc[0], 1.5)
        self.assertEqual(summarize_trade_time_metrics(trades, START, END).loc["TIME", "exposure_ratio"], 0.15)

    def test_empty_ledger_retains_schema_dtypes_and_positive_window(self):
        trades = ledger([])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        self.assertTrue(breakdown.empty)
        self.assertEqual(breakdown.columns.tolist(), BREAKDOWN_COLUMNS)
        self.assertEqual(breakdown.dtypes.astype(str).tolist()[-2:], ["float64", "float64"])
        pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)
        summary = summarize_trade_time_metrics(trades, START, END)
        self.assert_summary_dtypes(summary)
        self.assert_undefined_closed_statistics(summary)
        self.assertEqual(summary.loc["TIME", SUMMARY_COLUMNS[:2]].tolist(), [0, 0])
        self.assertEqual(summary.loc["TIME", SUMMARY_COLUMNS[6:]].tolist(), [0, 0, 0, 10, 0])

    def test_open_only_has_exposure_but_no_completed_duration(self):
        trades = ledger([("OPEN", 7, None)])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        self.assertTrue(breakdown.closed_duration_hours.isna().all())
        self.assertTrue(breakdown.exit_time.isna().all())
        self.assertEqual(breakdown.observed_time_in_market_hours.iloc[0], 3.0)
        summary = summarize_trade_time_metrics(trades, START, END)
        self.assert_undefined_closed_statistics(summary)
        self.assertEqual(summary.loc["TIME", SUMMARY_COLUMNS[:2]].tolist(), [0, 1])
        self.assertEqual(summary.loc["TIME", SUMMARY_COLUMNS[6:]].tolist(), [0, 3, 3, 10, 0.3])

    def test_open_at_window_start_has_full_exposure(self):
        summary = summarize_trade_time_metrics(ledger([("OPEN", 0, None)]), START, END)
        self.assert_undefined_closed_statistics(summary)
        self.assertEqual(summary.loc["TIME", "total_time_in_market_hours"], 10.0)
        self.assertEqual(summary.loc["TIME", "exposure_ratio"], 1.0)

    def test_multiple_closed_trades_and_no_open(self):
        trades = ledger([("CLOSED", 0, 1), ("CLOSED", 2, 4), ("CLOSED", 5, 8), ("CLOSED", 9, 13)])
        summary = summarize_trade_time_metrics(trades, START, START + pd.Timedelta(hours=20))
        self.assertEqual(summary.loc["TIME"].tolist(), [4, 0, 2.5, 2.5, 1, 4, 10, 0, 10, 20, 0.5])

    def test_touching_half_open_intervals_are_allowed(self):
        trades = ledger([("CLOSED", 0, 4), ("CLOSED", 4, 7), ("OPEN", 7, None)])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        self.assertEqual(breakdown.observed_time_in_market_hours.tolist(), [4, 3, 3])
        self.assertEqual(summarize_trade_time_metrics(trades, START, END).loc["TIME", "exposure_ratio"], 1.0)

    def test_sub_microsecond_intervals_remain_positive_and_full_exposure_is_exact(self):
        end = START + pd.Timedelta(nanoseconds=3)
        trades = ledger([("CLOSED", 0, 1), ("OPEN", 1, None)])
        trades.loc[0, "exit_time"] = START + pd.Timedelta(nanoseconds=1)
        trades.loc[1, "entry_time"] = trades.loc[0, "exit_time"]
        breakdown = calculate_trade_time_breakdown(trades, START, end)
        self.assertGreater(breakdown.closed_duration_hours.iloc[0], 0)
        self.assertAlmostEqual(breakdown.closed_duration_hours.iloc[0], 1 / 3_600_000_000_000, places=25)
        self.assertEqual(summarize_trade_time_metrics(trades, START, end).loc["TIME", "exposure_ratio"], 1.0)

    def test_summary_agrees_with_breakdown_semantics(self):
        trades = ledger([("CLOSED", 1, 2.5), ("CLOSED", 3, 6), ("OPEN", 8, None)])
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        closed = breakdown.loc[breakdown.status.eq("CLOSED"), "closed_duration_hours"]
        summary = summarize_trade_time_metrics(trades, START, END).loc["TIME"]
        self.assertEqual(summary.average_closed_duration_hours, closed.mean())
        self.assertEqual(summary.median_closed_duration_hours, closed.median())
        self.assertEqual(summary.minimum_closed_duration_hours, closed.min())
        self.assertEqual(summary.maximum_closed_duration_hours, closed.max())
        self.assertEqual(summary.total_closed_duration_hours, closed.sum())
        self.assertEqual(summary.total_time_in_market_hours, breakdown.observed_time_in_market_hours.sum())
        self.assertEqual(summary.total_time_in_market_hours,
                         summary.total_closed_duration_hours + summary.open_observed_duration_hours)
        self.assertEqual(summary.exposure_ratio, summary.total_time_in_market_hours / 10)
        self.assertGreater(summary.exposure_ratio, 0)
        self.assertLessEqual(summary.exposure_ratio, 1)

    def test_required_columns_are_required_even_when_empty(self):
        for trades in (ledger([]), ledger([("CLOSED", 1, 4)])):
            for column in SOURCE_COLUMNS:
                with self.subTest(empty=trades.empty, column=column):
                    self.assert_rejected(trades.drop(columns=column), message="Missing required ledger columns")

    def test_duplicate_columns_are_rejected(self):
        for trades in (ledger([]), ledger([("CLOSED", 1, 4)])):
            duplicated = pd.concat([trades, trades[["status"]]], axis=1)
            self.assert_rejected(duplicated, message="unique")

    def test_non_dataframe_is_rejected(self):
        for value in (None, [], {}, np.array([]), pd.Series(dtype="object")):
            self.assert_rejected(value, message="DataFrame")

    def test_invalid_statuses_are_rejected_without_repair(self):
        for status in ("closed", "open", "UNKNOWN", "", None, pd.NA, np.nan, True, 1):
            with self.subTest(status=status):
                trades = ledger([("CLOSED", 1, 4)])
                trades["status"] = pd.Series([status], dtype="object")
                self.assert_rejected(trades, message="CLOSED or OPEN")

    def test_multiple_open_trades_are_rejected(self):
        self.assert_rejected(ledger([("OPEN", 1, None), ("OPEN", 7, None)]), message="At most one OPEN")

    def test_nonfinal_open_is_rejected(self):
        for intervals in (
            [("OPEN", 1, None), ("CLOSED", 7, 9)],
            [("CLOSED", 1, 3), ("OPEN", 4, None), ("CLOSED", 7, 9)],
        ):
            self.assert_rejected(ledger(intervals), message="final ledger row")

    def test_out_of_order_entries_are_rejected_without_sorting(self):
        trades = ledger([("CLOSED", 7, 9), ("CLOSED", 1, 3)])
        original = trades.copy(deep=True)
        self.assert_rejected(trades, message="chronological and non-overlapping")
        pd.testing.assert_frame_equal(trades, original)

    def test_closed_overlap_is_rejected_even_below_full_exposure(self):
        self.assert_rejected(ledger([("CLOSED", 1, 4), ("CLOSED", 3, 5)]), message="non-overlapping")

    def test_open_overlap_is_rejected(self):
        self.assert_rejected(ledger([("CLOSED", 1, 4), ("OPEN", 3, None)]), message="non-overlapping")

    def test_entry_at_start_and_closed_exit_at_end_are_valid(self):
        trades = ledger([("CLOSED", 0, 10)])
        self.assertEqual(calculate_trade_time_breakdown(trades, START, END).closed_duration_hours.iloc[0], 10)
        self.assertEqual(summarize_trade_time_metrics(trades, START, END).loc["TIME", "exposure_ratio"], 1.0)

    def test_invalid_window_timestamp_objects_are_rejected_even_when_empty(self):
        for value in ("2025-01-01", 0, 1.5, True, None, pd.NaT, pd.NA, np.datetime64("NaT"), []):
            with self.subTest(value=value):
                self.assert_rejected(ledger([]), start=value)
                self.assert_rejected(ledger([]), end=value)

    def test_nonpositive_or_unsafe_window_elapsed_is_rejected(self):
        self.assert_rejected(ledger([]), end=START)
        self.assert_rejected(ledger([]), end=START - pd.Timedelta(hours=1))
        self.assert_rejected(ledger([]), start=pd.Timestamp.min, end=pd.Timestamp.max)

    def test_window_timezone_mismatch_is_rejected(self):
        for end in (END.tz_localize(None), END.tz_convert("Europe/London")):
            self.assert_rejected(ledger([]), end=end, message="same timezone")

    def test_entries_outside_window_are_rejected_without_clipping(self):
        for status in ("CLOSED", "OPEN"):
            for hour in (-1, 10, 11):
                with self.subTest(status=status, hour=hour):
                    self.assert_rejected(ledger([(status, hour, None if status == "OPEN" else hour + 1)]))

    def test_closed_exit_must_be_strictly_after_entry(self):
        for hour in (0, 1):
            self.assert_rejected(ledger([("CLOSED", 1, hour)]), message="positive elapsed duration")

    def test_closed_exit_cannot_exceed_window_end(self):
        self.assert_rejected(ledger([("CLOSED", 1, 11)]), message="must not exceed")

    def test_open_exit_must_be_missing(self):
        for value in (END, "NaT", "", 0, False, [], [None]):
            with self.subTest(value=value):
                trades = ledger([("OPEN", 7, None)])
                trades["exit_time"] = pd.Series([value], dtype="object")
                self.assert_rejected(trades, message="OPEN exit_time must be missing")

    def test_open_missing_exit_representation_is_preserved(self):
        for value in (None, pd.NA, pd.NaT, np.nan, np.datetime64("NaT")):
            with self.subTest(value=value):
                trades = ledger([("OPEN", 7, None)])
                trades["exit_time"] = pd.Series([value], dtype="object")
                original = trades.copy(deep=True)
                breakdown = calculate_trade_time_breakdown(trades, START, END)
                pd.testing.assert_series_equal(breakdown.exit_time, trades.exit_time)
                self.assertIs(breakdown.exit_time.iloc[0], trades.exit_time.iloc[0])
                self.assertTrue(breakdown.closed_duration_hours.isna().all())
                summarize_trade_time_metrics(trades, START, END)
                pd.testing.assert_frame_equal(trades, original)

    def test_entry_strings_numbers_and_missing_values_are_rejected(self):
        for value in (str(START), 1, 1.0, True, None, pd.NaT, pd.NA, np.datetime64("NaT"), []):
            with self.subTest(value=value):
                trades = ledger([("CLOSED", 1, 4)])
                trades["entry_time"] = pd.Series([value], dtype="object")
                self.assert_rejected(trades)

    def test_closed_exit_strings_numbers_and_missing_values_are_rejected(self):
        for value in (str(END), 1, True, None, pd.NaT, pd.NA, np.datetime64("NaT"), [END]):
            with self.subTest(value=value):
                trades = ledger([("CLOSED", 1, 4)])
                trades["exit_time"] = pd.Series([value], dtype="object")
                self.assert_rejected(trades)

    def test_aware_naive_ledger_mixtures_are_rejected(self):
        for column in ("entry_time", "exit_time"):
            trades = ledger([("CLOSED", 1, 4)])
            trades[column] = trades[column].dt.tz_localize(None)
            self.assert_rejected(trades, message="same timezone")
        self.assert_rejected(ledger([("CLOSED", 1, 4)]),
                             start=START.tz_localize(None), end=END.tz_localize(None))

    def test_different_aware_zones_are_rejected_without_conversion(self):
        for column in ("entry_time", "exit_time"):
            trades = ledger([("CLOSED", 1, 4)])
            trades[column] = trades[column].dt.tz_convert("Europe/Berlin")
            self.assert_rejected(trades, message="same timezone")

    def test_consistently_naive_inputs_are_accepted_and_stay_naive(self):
        trades = ledger([("CLOSED", 1, 4), ("OPEN", 7, None)])
        for column in ("entry_time", "exit_time"):
            trades[column] = trades[column].dt.tz_localize(None)
        start, end = START.tz_localize(None), END.tz_localize(None)
        breakdown = calculate_trade_time_breakdown(trades, start, end)
        pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)
        self.assertEqual(summarize_trade_time_metrics(trades, start, end).loc["TIME", "exposure_ratio"], 0.6)

    def test_consistently_same_zone_aware_inputs_are_accepted(self):
        zone = ZoneInfo("Asia/Seoul")
        trades = ledger([("CLOSED", 1, 4), ("OPEN", 7, None)])
        for column in ("entry_time", "exit_time"):
            trades[column] = trades[column].dt.tz_convert(zone)
        start, end = START.tz_convert(zone), END.tz_convert(zone)
        breakdown = calculate_trade_time_breakdown(trades, start, end)
        pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)
        self.assertEqual(summarize_trade_time_metrics(trades, start, end).loc["TIME", "exposure_ratio"], 0.6)

    def test_datetime_and_numpy_datetime_scalars_are_accepted(self):
        for start, end, entry, exit_time in (
            (datetime(2025, 1, 1), datetime(2025, 1, 1, 10),
             datetime(2025, 1, 1, 1), datetime(2025, 1, 1, 4)),
            (datetime(2025, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, 10, tzinfo=timezone.utc),
             datetime(2025, 1, 1, 1, tzinfo=timezone.utc), datetime(2025, 1, 1, 4, tzinfo=timezone.utc)),
            (np.datetime64("2025-01-01T00:00"), np.datetime64("2025-01-01T10:00"),
             np.datetime64("2025-01-01T01:00"), np.datetime64("2025-01-01T04:00")),
        ):
            with self.subTest(start=start):
                trades = pd.DataFrame({
                    "trade_id": [1], "status": ["CLOSED"],
                    "entry_time": pd.Series([entry], dtype="object"),
                    "exit_time": pd.Series([exit_time], dtype="object"),
                })
                breakdown = calculate_trade_time_breakdown(trades, start, end)
                pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)
                self.assertEqual(breakdown.closed_duration_hours.iloc[0], 3.0)
                self.assertEqual(summarize_trade_time_metrics(trades, start, end).loc["TIME", "exposure_ratio"], 0.3)

    def test_dst_transition_uses_elapsed_time_not_wall_clock_labels(self):
        for zone in ("America/New_York", ZoneInfo("America/New_York")):
            with self.subTest(zone=zone):
                start = pd.Timestamp("2025-03-09 00:00", tz=zone)
                end = pd.Timestamp("2025-03-09 05:00", tz=zone)
                trades = pd.DataFrame({
                    "trade_id": [1], "status": ["CLOSED"],
                    "entry_time": [pd.Timestamp("2025-03-09 01:30", tz=zone)],
                    "exit_time": [pd.Timestamp("2025-03-09 03:30", tz=zone)],
                })
                breakdown = calculate_trade_time_breakdown(trades, start, end)
                self.assertEqual(breakdown.closed_duration_hours.iloc[0], 1.0)
                summary = summarize_trade_time_metrics(trades, start, end).loc["TIME"]
                self.assertEqual(summary.observation_window_hours, 4.0)
                self.assertEqual(summary.exposure_ratio, 0.25)
                pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)

    def test_differing_timezone_implementations_are_rejected(self):
        # The contract requires matching timezone implementations as well as zones.
        end = END.tz_convert(ZoneInfo("UTC"))
        self.assert_rejected(ledger([]), end=end, message="same timezone")

    def test_duplicate_nonstandard_index_and_identifier_dtype_are_preserved(self):
        trades = ledger([("CLOSED", 1, 2), ("CLOSED", 3, 4), ("OPEN", 7, None)])
        trades["trade_id"] = pd.Series(["third", "first", "second"], dtype="string")
        trades["status"] = trades.status.astype("category")
        trades.index = pd.Index(["z", "a", "z"], name="source_row")
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        pd.testing.assert_frame_equal(breakdown[SOURCE_COLUMNS], trades)
        self.assertEqual(breakdown.observed_time_in_market_hours.tolist(), [1, 1, 3])
        self.assertEqual(summarize_trade_time_metrics(trades, START, END).loc["TIME", "exposure_ratio"], 0.5)

    def test_both_functions_preserve_input_and_breakdown_is_independent(self):
        trades = ledger([("CLOSED", 1, 4), ("OPEN", 7, None)])
        trades = trades[["exit_time", "entry_time", "status", "trade_id"]]
        trades.index = [9, 2]
        trades["notes"] = "untouched"
        original = trades.copy(deep=True)
        breakdown = calculate_trade_time_breakdown(trades, START, END)
        summarize_trade_time_metrics(trades, START, END)
        pd.testing.assert_frame_equal(trades, original)
        self.assertIsNot(breakdown, trades)
        breakdown.loc[9, "entry_time"] = END
        breakdown.loc[2, "exit_time"] = END
        breakdown.loc[9, "trade_id"] = 999
        pd.testing.assert_frame_equal(trades, original)

    def test_optional_price_accounting_and_signal_fields_are_irrelevant(self):
        trades = ledger([("CLOSED", 1, 4), ("OPEN", 7, None)])
        expected_breakdown = calculate_trade_time_breakdown(trades, START, END)
        expected_summary = summarize_trade_time_metrics(trades, START, END)
        for column in ("entry_price", "exit_price", "gross_pnl", "net_pnl", "quantity", "fees",
                       "capital_after", "signal_time", "desired_position", "executed_position", "notes"):
            trades[column] = ["irrelevant malformed value", None]
        pd.testing.assert_frame_equal(calculate_trade_time_breakdown(trades, START, END), expected_breakdown)
        pd.testing.assert_frame_equal(summarize_trade_time_metrics(trades, START, END), expected_summary)

    def test_actual_stage_4_ledger_uses_recorded_fills_without_accounting(self):
        candles = pd.DataFrame({
            "timestamp": pd.date_range(START, periods=8, freq="h"),
            "open": [100.0] * 8,
            "signal": ["HOLD", "LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD", "LONG_ENTRY", "HOLD", "HOLD"],
        })
        executed = apply_next_open_execution(candles)
        trades = build_trade_ledger(executed)
        original = trades.copy(deep=True)
        end = candles.timestamp.iloc[-1] + pd.Timedelta(hours=1)
        breakdown = calculate_trade_time_breakdown(trades, START, end)
        self.assertEqual(trades.entry_time.tolist(), [START + pd.Timedelta(hours=2), START + pd.Timedelta(hours=6)])
        self.assertEqual(trades.exit_time.iloc[0], START + pd.Timedelta(hours=4))
        self.assertEqual(breakdown.closed_duration_hours.iloc[0], 2.0)
        self.assertTrue(np.isnan(breakdown.closed_duration_hours.iloc[1]))
        self.assertEqual(breakdown.observed_time_in_market_hours.tolist(), [2.0, 2.0])
        summary = summarize_trade_time_metrics(trades, START, end)
        self.assertEqual(summary.loc["TIME"].tolist(), [1, 1, 2, 2, 2, 2, 2, 2, 4, 8, 0.5])
        pd.testing.assert_frame_equal(trades, original)
        self.assertTrue(pd.isna(breakdown.exit_time.iloc[-1]))


if __name__ == "__main__":
    unittest.main()
