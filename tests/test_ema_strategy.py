"""Synthetic tests for Stage 3.1 EMA behavior; no files, APIs, or execution."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.strategies.ema_trend import generate_ema_signals


def candles(closes):
    """Hourly close-only data: no other OHLCV fields are needed."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=len(closes), freq="h", tz="UTC"),
        "close": pd.Series(closes, dtype="float64"),
    })


class EmaStrategyTests(unittest.TestCase):
    def crossover_example(self):
        # Short spans make events obvious, while preserving the 50-row warm-up.
        # Row 50: bearish while flat. 51: entry. 52: exit. 54: entry.
        return generate_ema_signals(candles([100] * 50 + [90, 110, 80, 80, 120]), 2, 3)

    def test_a_first_fifty_rows_are_initialization_only(self):
        data = candles([100, 110, 90, 120, 80] * 12)
        result = generate_ema_signals(data)
        warmup = result.iloc[:50]
        self.assertTrue(warmup.signal.eq("HOLD").all())
        self.assertTrue(warmup.desired_position.eq(0).all())
        self.assertFalse(warmup[["bullish_cross", "bearish_cross"]].any().any())
        self.assertFalse(warmup.warmup_complete.any())
        self.assertTrue(result.iloc[50:].warmup_complete.all())

    def test_b_bullish_crossover_while_flat_enters(self):
        result = self.crossover_example()
        self.assertTrue(result.loc[51, "bullish_cross"])
        self.assertEqual(result.loc[50, "desired_position"], 0)
        self.assertEqual(result.loc[51, "signal"], "LONG_ENTRY")
        self.assertEqual(result.loc[51, "desired_position"], 1)

    def test_c_bearish_crossover_while_long_exits(self):
        result = self.crossover_example()
        self.assertTrue(result.loc[52, "bearish_cross"])
        self.assertEqual(result.loc[51, "desired_position"], 1)
        self.assertEqual(result.loc[52, "signal"], "LONG_EXIT")
        self.assertEqual(result.loc[52, "desired_position"], 0)

    def test_d_bearish_crossover_while_flat_remains_hold(self):
        result = self.crossover_example()
        self.assertTrue(result.loc[50, "bearish_cross"])
        self.assertEqual(result.loc[50, "signal"], "HOLD")
        self.assertEqual(result.loc[50, "desired_position"], 0)

    def test_e_hold_preserves_previous_desired_state(self):
        result = generate_ema_signals(candles([100] * 50 + [110, 110, 110, 80, 80, 80]), 2, 3)
        previous = result.desired_position.shift(1, fill_value=0)
        holds = result.signal.eq("HOLD")
        pd.testing.assert_series_equal(result.loc[holds, "desired_position"], previous.loc[holds])
        self.assertEqual(set(result.loc[holds, "desired_position"]), {0, 1})

    def test_f_state_is_flat_or_long_and_crossovers_are_exclusive(self):
        result = self.crossover_example()
        self.assertTrue(result.desired_position.isin([0, 1]).all())
        self.assertFalse((result.bullish_cross & result.bearish_cross).any())

    def test_g_valid_events_alternate_and_have_correct_previous_state(self):
        result = self.crossover_example()
        events = result.loc[result.signal.ne("HOLD"), "signal"].tolist()
        self.assertEqual(events, ["LONG_ENTRY", "LONG_EXIT", "LONG_ENTRY"])
        previous = result.desired_position.shift(1, fill_value=0)
        self.assertTrue(previous.loc[result.signal.eq("LONG_ENTRY")].eq(0).all())
        self.assertTrue(previous.loc[result.signal.eq("LONG_EXIT")].eq(1).all())

    def test_h_future_rows_do_not_change_any_prefix_outputs(self):
        data = candles([100] * 50 + [90, 110, 80, 80, 120, 5, 500, 10])
        full = generate_ema_signals(data, 2, 3)
        for prefix_length in (1, 49, 50, 51, 52, 55):
            with self.subTest(prefix_length=prefix_length):
                prefix = generate_ema_signals(data.iloc[:prefix_length], 2, 3)
                pd.testing.assert_frame_equal(prefix, full.iloc[:prefix_length])

    def test_i_input_and_optional_columns_are_unchanged(self):
        data = candles([100, 90, 110, 80])
        data.index = [10, 20, 30, 40]
        data["open"] = [99, 89, 109, 79]
        data["signal"] = "unrelated input"
        original = data.copy(deep=True)
        result = generate_ema_signals(data, 2, 3, 1)
        pd.testing.assert_frame_equal(data, original)
        self.assertEqual(result.index.tolist(), [10, 20, 30, 40])
        self.assertNotIn("open", result.columns)
        result.loc[10, "close"] = 999
        pd.testing.assert_frame_equal(data, original)

    def test_j_missing_columns_are_rejected(self):
        for column in ("timestamp", "close"):
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "Missing required columns"):
                    generate_ema_signals(candles([100]).drop(columns=column))

    def test_j_duplicate_timestamps_are_rejected(self):
        data = candles([100, 110])
        data.loc[1, "timestamp"] = data.loc[0, "timestamp"]
        with self.assertRaisesRegex(ValueError, "unique"):
            generate_ema_signals(data)

    def test_j_non_chronological_timestamps_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "chronological"):
            generate_ema_signals(candles([100, 110]).iloc[::-1])

    def test_j_invalid_close_values_and_types_are_rejected(self):
        for value in (0, -1, np.nan, np.inf, -np.inf, None, pd.NA, "100", True, 1 + 2j):
            with self.subTest(value=value):
                data = candles([100])
                data["close"] = pd.Series([value])
                with self.assertRaisesRegex(ValueError, "finite positive numeric"):
                    generate_ema_signals(data)

    def test_j_invalid_parameter_values_are_rejected(self):
        for name in ("fast_span", "slow_span", "warmup_candles"):
            for value in (0, -1, 1.5, 2.0, "2", True, np.bool_(True), None):
                with self.subTest(name=name, value=value):
                    with self.assertRaisesRegex(ValueError, name + ".*positive integer"):
                        generate_ema_signals(candles([100]), **{name: value})
        for fast, slow in ((20, 20), (50, 20)):
            with self.subTest(fast=fast, slow=slow):
                with self.assertRaisesRegex(ValueError, "less than"):
                    generate_ema_signals(candles([100]), fast, slow)

    def test_j_dataframe_unique_columns_and_datetime_required(self):
        with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
            generate_ema_signals(None)
        data = candles([100, 110])
        with self.assertRaisesRegex(ValueError, "column names must be unique"):
            generate_ema_signals(pd.concat([data, data[["close"]]], axis=1))
        with self.assertRaisesRegex(ValueError, "pandas datetime"):
            generate_ema_signals(data.assign(timestamp=["2025-01-01", "2025-01-02"]))
        data.loc[1, "timestamp"] = pd.NaT
        with self.assertRaisesRegex(ValueError, "must not be missing"):
            generate_ema_signals(data)

    def test_k_signal_time_is_one_hour_after_candle_open(self):
        data = candles([100, 90, 110])
        for naive in (False, True):
            with self.subTest(naive=naive):
                if naive:
                    data["timestamp"] = data.timestamp.dt.tz_localize(None)
                result = generate_ema_signals(data, 2, 3, 1)
                pd.testing.assert_series_equal(
                    result.signal_time, (data.timestamp + pd.Timedelta(hours=1)).rename("signal_time")
                )

    def test_bullish_regime_at_warmup_end_does_not_synthesize_entry(self):
        result = generate_ema_signals(candles(list(range(100, 170))))
        self.assertTrue(result.loc[50, "warmup_complete"])
        self.assertGreater(result.loc[50, "ema_20"], result.loc[50, "ema_50"])
        self.assertFalse(result.bullish_cross.any())
        self.assertTrue(result.signal.eq("HOLD").all())
        self.assertTrue(result.desired_position.eq(0).all())

    def test_default_ema_recursion_is_seeded_by_first_close(self):
        result = generate_ema_signals(candles([100, 110, 90]))
        for span in (20, 50):
            alpha = 2 / (span + 1)
            second = alpha * 110 + (1 - alpha) * 100
            third = alpha * 90 + (1 - alpha) * second
            self.assertEqual(result.loc[0, f"ema_{span}"], 100)
            self.assertAlmostEqual(result.loc[1, f"ema_{span}"], second)
            self.assertAlmostEqual(result.loc[2, f"ema_{span}"], third)

    def test_custom_spans_warmup_and_numpy_integer_parameters(self):
        result = generate_ema_signals(candles([100, 90, 110]), np.int64(2), np.int64(3), np.int64(1))
        self.assertEqual(result.warmup_complete.tolist(), [False, True, True])
        self.assertEqual(result.signal.tolist(), ["HOLD", "HOLD", "LONG_ENTRY"])
        self.assertIn("ema_2", result.columns)
        self.assertIn("ema_3", result.columns)

    def test_empty_short_and_constant_inputs_remain_flat(self):
        for closes in ([], [100], [100] * 49, [100] * 55):
            with self.subTest(length=len(closes)):
                result = generate_ema_signals(candles(closes))
                self.assertEqual(len(result), len(closes))
                self.assertTrue(result.signal.eq("HOLD").all())
                self.assertTrue(result.desired_position.eq(0).all())
                self.assertEqual(str(result.desired_position.dtype), "int64")
                self.assertEqual(result.warmup_complete.dtype, bool)

    def test_output_schema_has_no_execution_or_financial_fields(self):
        result = generate_ema_signals(candles([100]))
        self.assertEqual(result.columns.tolist(), [
            "timestamp", "close", "ema_20", "ema_50", "warmup_complete",
            "bullish_cross", "bearish_cross", "signal", "desired_position", "signal_time",
        ])


if __name__ == "__main__":
    unittest.main()
