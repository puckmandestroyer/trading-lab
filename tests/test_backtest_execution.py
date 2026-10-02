"""Synthetic acceptance tests for decision 002; no market downloads or PnL."""

import unittest

import pandas as pd

from trading_lab.backtest.execution import apply_next_open_execution


def candles(signals, opens=None):
    """Small, explicit hourly inputs; each row labels a candle's opening."""
    if opens is None:
        opens = [100 + number for number in range(len(signals))]
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=len(signals), freq="h", tz="UTC"),
        "open": opens,
        "signal": signals,
    })


class BacktestExecutionTests(unittest.TestCase):
    def test_a_entry_fills_next_open_and_state_is_delayed(self):
        data = candles(["HOLD", "LONG_ENTRY", "HOLD"], [100, 101, 103])
        result = apply_next_open_execution(data)
        self.assertEqual(result.loc[1, "execution_time"], data.loc[2, "timestamp"])
        self.assertEqual(result.loc[1, "execution_price"], 103)
        self.assertEqual(result["executed_position"].tolist(), [0, 0, 1])
        self.assertTrue(pd.isna(result.loc[2, "execution_time"]))  # Its own HOLD has no fill.

    def test_b_exit_fills_next_open_and_state_is_delayed(self):
        data = candles(["HOLD", "LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"], [100, 101, 103, 105, 104])
        result = apply_next_open_execution(data)
        self.assertEqual(result.loc[3, "execution_time"], data.loc[4, "timestamp"])
        self.assertEqual(result.loc[3, "execution_price"], 104)
        self.assertEqual(result["executed_position"].tolist(), [0, 0, 1, 1, 0])

    def test_c_hold_has_no_fill_and_preserves_flat_or_long_state(self):
        data = candles(["HOLD", "LONG_ENTRY", "HOLD", "HOLD"])
        result = apply_next_open_execution(data)
        hold_rows = data.signal == "HOLD"
        self.assertTrue(result.loc[hold_rows, "execution_time"].isna().all())
        self.assertTrue(result.loc[hold_rows, "execution_price"].isna().all())
        self.assertEqual(result.executed_position.tolist(), [0, 0, 1, 1])

    def test_d_final_entry_is_preserved_but_cannot_execute(self):
        data = candles(["HOLD", "LONG_ENTRY"])
        result = apply_next_open_execution(data)
        self.assertEqual(result.signal.tolist(), data.signal.tolist())
        self.assertTrue(result.execution_time.isna().all())
        self.assertTrue(result.execution_price.isna().all())
        self.assertEqual(result.executed_position.tolist(), [0, 0])

    def test_d_final_exit_does_not_force_close_a_long_state(self):
        result = apply_next_open_execution(candles(["LONG_ENTRY", "HOLD", "LONG_EXIT"]))
        self.assertEqual(result.executed_position.tolist(), [0, 1, 1])
        self.assertEqual(result.loc[2, "signal"], "LONG_EXIT")
        self.assertTrue(pd.isna(result.loc[2, "execution_time"]))
        self.assertTrue(pd.isna(result.loc[2, "execution_price"]))

    def test_final_row_can_receive_prior_entry_but_its_own_exit_cannot_fill(self):
        result = apply_next_open_execution(candles(["LONG_ENTRY", "LONG_EXIT"]))
        self.assertEqual(result.executed_position.tolist(), [0, 1])
        self.assertTrue(pd.notna(result.loc[0, "execution_time"]))
        self.assertTrue(pd.isna(result.loc[1, "execution_time"]))
        self.assertTrue(pd.isna(result.loc[1, "execution_price"]))

    def test_e_next_candle_non_open_fields_and_later_data_do_not_change_fill(self):
        data = candles(["LONG_ENTRY", "HOLD", "HOLD", "HOLD"])
        data["high"] = [110, 111, 112, 113]
        data["low"] = [90, 91, 92, 93]
        data["close"] = [105, 106, 107, 108]
        data["volume"] = [1, 2, 3, 4]
        original = apply_next_open_execution(data)
        changed = data.copy()
        changed.loc[1, ["high", "low", "close", "volume"]] = [999, 1, 500, 800]
        changed.loc[2:, "open"] = [500, 600]
        changed.loc[2:, "signal"] = ["LONG_EXIT", "HOLD"]
        updated = apply_next_open_execution(changed)
        pd.testing.assert_frame_equal(original.iloc[:2], updated.iloc[:2])
        prefix = apply_next_open_execution(data.iloc[:2])
        pd.testing.assert_frame_equal(original.iloc[:2], prefix)
        self.assertEqual(updated.loc[0, "execution_price"], data.loc[1, "open"])

    def test_f_fifty_warmup_hold_rows_have_no_execution(self):
        data = candles(["HOLD"] * 50 + ["LONG_ENTRY", "HOLD"])
        result = apply_next_open_execution(data)
        self.assertTrue(result.iloc[:50].execution_time.isna().all())
        self.assertTrue(result.iloc[:50].execution_price.isna().all())
        self.assertTrue(result.iloc[:51].executed_position.eq(0).all())
        self.assertEqual(result.loc[51, "executed_position"], 1)

    def test_g_sequence_starts_flat_and_never_contains_shorts(self):
        data = candles(["LONG_ENTRY", "HOLD", "LONG_EXIT", "LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"])
        result = apply_next_open_execution(data)
        self.assertEqual(result.executed_position.tolist(), [0, 1, 1, 0, 1, 1, 0])
        self.assertTrue(result.executed_position.isin([0, 1]).all())

    def test_g_entry_while_long_is_rejected_even_on_final_candle(self):
        for signals in (["LONG_ENTRY", "LONG_ENTRY"], ["LONG_ENTRY", "HOLD", "LONG_ENTRY", "HOLD"]):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(ValueError, "LONG_ENTRY.*already long"):
                    apply_next_open_execution(candles(signals))

    def test_g_exit_while_flat_is_rejected_even_on_final_candle(self):
        for signals in (["LONG_EXIT"], ["HOLD", "LONG_EXIT"], ["LONG_ENTRY", "LONG_EXIT", "LONG_EXIT", "HOLD"]):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(ValueError, "LONG_EXIT.*currently flat"):
                    apply_next_open_execution(candles(signals))

    def test_invalid_or_missing_signal_is_rejected(self):
        for signal in ("BUY", "long_entry", "", None, pd.NA):
            with self.subTest(signal=signal):
                with self.assertRaisesRegex(ValueError, "Invalid signal"):
                    apply_next_open_execution(candles(["HOLD", signal]))

    def test_duplicate_timestamps_are_rejected(self):
        data = candles(["HOLD", "LONG_ENTRY", "HOLD"])
        data.loc[1, "timestamp"] = data.loc[0, "timestamp"]
        with self.assertRaisesRegex(ValueError, "unique"):
            apply_next_open_execution(data)

    def test_non_chronological_timestamps_are_rejected(self):
        data = candles(["HOLD"] * 3).iloc[::-1]
        with self.assertRaisesRegex(ValueError, "chronological"):
            apply_next_open_execution(data)

    def test_hourly_gaps_and_wrong_spacing_are_rejected(self):
        for frequency in ("2h", "30min"):
            with self.subTest(frequency=frequency):
                data = candles(["LONG_ENTRY", "HOLD", "HOLD"])
                data["timestamp"] = pd.date_range("2025-01-01", periods=3, freq=frequency, tz="UTC")
                with self.assertRaisesRegex(ValueError, "one-hour spacing"):
                    apply_next_open_execution(data)

    def test_invalid_execution_open_is_rejected(self):
        for price in (0, -1, float("nan"), float("inf"), -float("inf"), "101", True, 1 + 2j, pd.NA):
            with self.subTest(price=price):
                data = candles(["LONG_ENTRY", "HOLD"], [100, price])
                with self.assertRaisesRegex(ValueError, "Execution OPEN"):
                    apply_next_open_execution(data)

    def test_unused_open_is_left_for_upstream_market_validation(self):
        data = candles(["HOLD", "LONG_ENTRY", "HOLD", "HOLD"], [None, None, 103, None])
        result = apply_next_open_execution(data)
        self.assertEqual(result.loc[1, "execution_price"], 103)

    def test_missing_required_columns_are_rejected(self):
        for column in ("timestamp", "open", "signal"):
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "Missing required columns"):
                    apply_next_open_execution(candles(["HOLD"]).drop(columns=column))

    def test_non_datetime_and_missing_timestamps_are_rejected(self):
        data = candles(["HOLD", "HOLD"])
        with self.assertRaisesRegex(ValueError, "pandas datetime"):
            apply_next_open_execution(data.assign(timestamp=["2025-01-01", "2025-01-02"]))
        data.loc[1, "timestamp"] = pd.NaT
        with self.assertRaisesRegex(ValueError, "must not be missing"):
            apply_next_open_execution(data)

    def test_pure_function_preserves_input_optional_columns_and_index(self):
        data = candles(["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"])
        data.index = [10, 20, 30, 40]
        data["desired_position"] = [1, 1, 0, 0]
        data["signal_time"] = data.timestamp + pd.Timedelta(hours=1)
        original = data.copy(deep=True)
        result = apply_next_open_execution(data)
        pd.testing.assert_frame_equal(data, original)
        self.assertEqual(result.index.tolist(), [10, 20, 30, 40])
        self.assertEqual(result.columns.tolist(), [
            "timestamp", "open", "signal", "execution_time", "execution_price", "executed_position"
        ])
        self.assertEqual(result.executed_position.tolist(), [0, 1, 1, 0])
        result.loc[10, "signal"] = "HOLD"
        pd.testing.assert_frame_equal(data, original)

    def test_empty_and_single_hold_inputs_return_typed_results(self):
        for signals in ([], ["HOLD"]):
            with self.subTest(signals=signals):
                result = apply_next_open_execution(candles(signals))
                self.assertEqual(len(result), len(signals))
                self.assertEqual(str(result.execution_time.dtype), "datetime64[ns, UTC]")
                self.assertEqual(str(result.execution_price.dtype), "float64")
                self.assertEqual(str(result.executed_position.dtype), "int64")
                self.assertTrue(result.execution_time.isna().all())

    def test_naive_datetime_input_preserves_timezone_semantics(self):
        data = candles(["LONG_ENTRY", "HOLD"])
        data["timestamp"] = data.timestamp.dt.tz_localize(None)
        result = apply_next_open_execution(data)
        self.assertEqual(result.loc[0, "execution_time"], data.loc[1, "timestamp"])
        self.assertEqual(str(result.execution_time.dtype), "datetime64[ns]")

    def test_duplicate_columns_and_non_dataframe_input_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
            apply_next_open_execution(None)
        data = candles(["HOLD"])
        duplicated = pd.concat([data, data[["open"]]], axis=1)
        with self.assertRaisesRegex(ValueError, "column names must be unique"):
            apply_next_open_execution(duplicated)


if __name__ == "__main__":
    unittest.main()
