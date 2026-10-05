"""Synthetic Decision 010 intent validation; no market files or executions."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.backtest.strategy_validation import validate_strategy_output
from trading_lab.strategies.ema_trend import generate_ema_signals


def frames(signals, positions, timestamps=None, index=None):
    """Build canonical output and timestamp-only candles for small examples."""
    if timestamps is None:
        timestamps = pd.date_range("2025-01-01", periods=len(signals), freq="h", tz="UTC")
    candles = pd.DataFrame({"timestamp": timestamps}, index=index)
    output = candles.copy(deep=True)
    output["signal_time"] = candles["timestamp"] + pd.Timedelta(hours=1)
    output["signal"] = pd.Series(signals, index=candles.index, dtype="object")
    output["desired_position"] = pd.Series(positions, index=candles.index, dtype="int64")
    return candles, output


class StrategyValidationTests(unittest.TestCase):
    def assert_valid(self, candles, output):
        result = validate_strategy_output(candles, output)
        pd.testing.assert_frame_equal(result, output)
        self.assertIsNot(result, output)
        return result

    def test_all_hold_remains_flat(self):
        self.assert_valid(*frames(["HOLD"] * 3, [0] * 3))

    def test_entry_then_hold_remains_long(self):
        self.assert_valid(*frames(["LONG_ENTRY", "HOLD", "HOLD"], [1, 1, 1]))

    def test_exit_then_hold_remains_flat(self):
        self.assert_valid(*frames(["LONG_ENTRY", "LONG_EXIT", "HOLD"], [1, 0, 0]))

    def test_entry_exit_alternation(self):
        self.assert_valid(*frames(["LONG_ENTRY", "LONG_EXIT"] * 2, [1, 0] * 2))

    def test_final_entry_is_valid_intent_without_execution_fields(self):
        result = self.assert_valid(*frames(["HOLD", "HOLD", "LONG_ENTRY"], [0, 0, 1]))
        self.assertEqual(result.columns.tolist(), [
            "timestamp", "signal_time", "signal", "desired_position",
        ])

    def test_final_exit_after_long_is_valid(self):
        self.assert_valid(*frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0]))

    def test_single_hold_is_valid(self):
        self.assert_valid(*frames(["HOLD"], [0]))

    def test_single_final_entry_is_valid(self):
        self.assert_valid(*frames(["LONG_ENTRY"], [1]))

    def test_empty_typed_frames_are_valid(self):
        for timezone in (None, "UTC"):
            with self.subTest(timezone=timezone):
                timestamps = pd.date_range("2025-01-01", periods=0, freq="h", tz=timezone)
                result = self.assert_valid(*frames([], [], timestamps=timestamps))
                self.assertTrue(result.empty)

    def test_non_range_index_is_preserved(self):
        index = pd.Index([30, 10, 20], name="candle_id")
        result = self.assert_valid(*frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0], index=index))
        pd.testing.assert_index_equal(result.index, index)

    def test_duplicate_index_labels_are_valid_when_aligned(self):
        index = pd.Index([5, 5, 2], name="candle_id")
        self.assert_valid(*frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0], index=index))

    def test_naive_datetimes_remain_naive(self):
        timestamps = pd.date_range("2025-01-01", periods=2, freq="h")
        result = self.assert_valid(*frames(["LONG_ENTRY", "HOLD"], [1, 1], timestamps=timestamps))
        self.assertIsNone(result.timestamp.dt.tz)
        self.assertIsNone(result.signal_time.dt.tz)

    def test_dst_signal_time_is_one_elapsed_hour(self):
        for start in ("2025-03-09 01:00", "2025-11-02 00:00"):
            with self.subTest(start=start):
                timestamps = pd.date_range(start, periods=4, freq="h", tz="America/New_York")
                result = self.assert_valid(*frames(["HOLD"] * 4, [0] * 4, timestamps=timestamps))
                self.assertTrue((result.signal_time - result.timestamp).eq(pd.Timedelta(hours=1)).all())
                if start.startswith("2025-03"):
                    self.assertEqual(result.timestamp.iloc[0].hour, 1)
                    self.assertEqual(result.signal_time.iloc[0].hour, 3)
                else:
                    # Both clocks read 01:00, but their UTC offsets differ.
                    self.assertEqual(result.timestamp.iloc[1].hour, 1)
                    self.assertEqual(result.signal_time.iloc[1].hour, 1)
                    self.assertNotEqual(
                        result.timestamp.iloc[1].utcoffset(), result.signal_time.iloc[1].utcoffset()
                    )

    def test_candle_spacing_is_not_validated_or_used_for_availability(self):
        start = pd.Timestamp("2025-01-01", tz="UTC")
        timestamps = pd.DatetimeIndex([start, start + pd.Timedelta(hours=3), start + pd.Timedelta(minutes=450)])
        self.assert_valid(*frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0], timestamps=timestamps))

    def test_extra_diagnostics_are_preserved_and_ignored(self):
        candles, output = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0])
        output["ema_20"] = [np.nan, np.inf, -999.0]
        output["ema_50"] = "unrelated diagnostic"
        output["bullish_cross"] = [None, "anything", False]
        output["breakout_level"] = [10.0, 20.0, 30.0]
        output["z_score"] = [0.0, -1.0, 2.0]
        output["open"] = "not a market price"
        self.assert_valid(candles, output)
        changed = output.copy(deep=True)
        for column in ("ema_20", "ema_50", "bullish_cross", "breakout_level", "z_score", "open"):
            changed[column] = "different ignored value"
        self.assert_valid(candles, changed)

    def test_inputs_columns_indexes_and_dtypes_are_preserved(self):
        candles, output = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0])
        candles["close"] = "not validated here"
        output["diagnostic"] = pd.Series([1, None, 3], dtype="Int64")
        output["category"] = pd.Categorical(["a", "b", "a"])
        output = output[["category", "signal", "timestamp", "diagnostic", "desired_position", "signal_time"]]
        candles_before = candles.copy(deep=True)
        output_before = output.copy(deep=True)
        self.assert_valid(candles, output)
        pd.testing.assert_frame_equal(candles, candles_before)
        pd.testing.assert_frame_equal(output, output_before)

    def test_returned_scalar_columns_are_independent(self):
        candles, output = frames(["LONG_ENTRY", "HOLD"], [1, 1])
        output["diagnostic"] = [10.0, 20.0]
        candles_before = candles.copy(deep=True)
        output_before = output.copy(deep=True)
        result = self.assert_valid(candles, output)
        result.loc[0, "desired_position"] = 99
        result.loc[0, "signal"] = "changed"
        result.loc[0, "timestamp"] += pd.Timedelta(days=1)
        result.loc[0, "diagnostic"] = -1.0
        pd.testing.assert_frame_equal(candles, candles_before)
        pd.testing.assert_frame_equal(output, output_before)

    def test_python_and_numpy_integer_scalars_are_accepted_without_coercion(self):
        candles, output = frames(["HOLD", "LONG_ENTRY", "HOLD", "LONG_EXIT"], [0, 1, 1, 0])
        output["desired_position"] = pd.Series([0, np.int64(1), np.uint8(1), np.int32(0)], dtype="object")
        self.assert_valid(candles, output)

    def test_existing_ema_output_is_accepted(self):
        candles, _ = frames(["HOLD"] * 55, [0] * 55)
        candles["close"] = [100.0] * 50 + [90.0, 110.0, 80.0, 80.0, 120.0]
        for fast, slow in ((20, 50), (2, 3)):
            with self.subTest(fast=fast, slow=slow):
                output = generate_ema_signals(candles, fast, slow)
                self.assert_valid(candles, output)
                if fast == 2:
                    self.assertEqual(output.signal.iloc[-1], "LONG_ENTRY")

    def test_non_dataframe_inputs_are_rejected(self):
        candles, output = frames(["HOLD"], [0])
        for name in ("candles", "strategy_output"):
            for value in (None, [], {}, pd.Series([1])):
                with self.subTest(name=name, value=type(value).__name__):
                    args = (value, output) if name == "candles" else (candles, value)
                    with self.assertRaisesRegex(ValueError, name + ".*pandas DataFrame"):
                        validate_strategy_output(*args)

    def test_duplicate_column_names_are_rejected(self):
        candles, output = frames(["HOLD"], [0])
        for name, frame in (("candles", candles), ("strategy_output", output)):
            for column in ("timestamp", "diagnostic"):
                with self.subTest(name=name, column=column):
                    expanded = frame.assign(diagnostic=123)
                    duplicate = pd.concat([expanded, expanded[[column]]], axis=1)
                    args = (duplicate, output) if name == "candles" else (candles, duplicate)
                    with self.assertRaisesRegex(ValueError, name + ".*column names.*unique"):
                        validate_strategy_output(*args)

    def test_missing_candle_timestamp_is_rejected(self):
        candles, output = frames(["HOLD"], [0])
        with self.assertRaisesRegex(ValueError, "candles.*missing.*timestamp"):
            validate_strategy_output(candles.drop(columns="timestamp"), output)

    def test_missing_canonical_columns_are_rejected(self):
        candles, output = frames(["HOLD"], [0])
        for column in ("timestamp", "signal_time", "signal", "desired_position"):
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "strategy_output.*missing.*" + column):
                    validate_strategy_output(candles, output.drop(columns=column))

    def test_missing_or_extra_strategy_rows_are_rejected(self):
        candles, output = frames(["HOLD"] * 2, [0] * 2)
        for malformed in (output.iloc[:1], pd.concat([output, output.iloc[:1]])):
            with self.subTest(rows=len(malformed)):
                with self.assertRaisesRegex(ValueError, "alignment.*row count"):
                    validate_strategy_output(candles, malformed)

    def test_changed_index_is_rejected(self):
        candles, output = frames(["HOLD"] * 2, [0] * 2)
        output.index = [100, 200]
        with self.assertRaisesRegex(ValueError, "alignment.*index"):
            validate_strategy_output(candles, output)

    def test_changed_timestamp_is_rejected(self):
        candles, output = frames(["HOLD"] * 2, [0] * 2)
        output["timestamp"] += pd.Timedelta(minutes=1)
        with self.assertRaisesRegex(ValueError, "alignment.*timestamps"):
            validate_strategy_output(candles, output)

    def test_reordered_rows_are_not_repaired(self):
        candles, output = frames(["HOLD"] * 3, [0] * 3)
        for reordered in (output.iloc[::-1], output.iloc[::-1].reset_index(drop=True)):
            with self.subTest(index=reordered.index.tolist()):
                with self.assertRaisesRegex(ValueError, "alignment"):
                    validate_strategy_output(candles, reordered)

    def test_duplicate_candle_timestamps_are_rejected(self):
        timestamps = pd.DatetimeIndex([pd.Timestamp("2025-01-01")] * 2)
        candles, output = frames(["HOLD"] * 2, [0] * 2, timestamps=timestamps)
        with self.assertRaisesRegex(ValueError, "timestamps.*unique"):
            validate_strategy_output(candles, output)

    def test_non_chronological_timestamps_are_rejected(self):
        timestamps = pd.date_range("2025-01-01", periods=2, freq="h")[::-1]
        candles, output = frames(["HOLD"] * 2, [0] * 2, timestamps=timestamps)
        with self.assertRaisesRegex(ValueError, "timestamps.*chronological"):
            validate_strategy_output(candles, output)

    def test_missing_timestamps_are_rejected(self):
        for name in ("candles", "strategy_output"):
            with self.subTest(name=name):
                candles, output = frames(["HOLD"] * 2, [0] * 2)
                frame = candles if name == "candles" else output
                frame.loc[1, "timestamp"] = pd.NaT
                with self.assertRaisesRegex(ValueError, name + " timestamp.*missing"):
                    validate_strategy_output(candles, output)

    def test_non_datetime_timestamps_are_rejected_even_when_empty(self):
        for size in (0, 1):
            for name in ("candles", "strategy_output"):
                for value in ("2025-01-01", pd.Timestamp("2025-01-01"), 123):
                    with self.subTest(size=size, name=name, value=value):
                        candles, output = frames(["HOLD"] * size, [0] * size)
                        frame = candles if name == "candles" else output
                        frame["timestamp"] = pd.Series([value] * size, dtype="object")
                        with self.assertRaisesRegex(ValueError, name + " timestamp.*pandas datetime"):
                            validate_strategy_output(candles, output)

    def test_timestamp_timezone_representation_must_match(self):
        candles, output = frames(["HOLD"] * 2, [0] * 2)
        output["timestamp"] = output.timestamp.dt.tz_convert("America/New_York")
        with self.assertRaisesRegex(ValueError, "alignment.*timestamps"):
            validate_strategy_output(candles, output)

    def test_missing_signal_times_are_rejected_on_every_row(self):
        for row in range(3):
            with self.subTest(row=row):
                candles, output = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0])
                output.loc[row, "signal_time"] = pd.NaT
                with self.assertRaisesRegex(ValueError, "signal_time.*missing"):
                    validate_strategy_output(candles, output)

    def test_non_datetime_signal_time_is_rejected_even_when_empty(self):
        for size in (0, 1):
            for value in ("2025-01-01 01:00", pd.Timestamp("2025-01-01 01:00"), 123):
                with self.subTest(size=size, value=value):
                    candles, output = frames(["HOLD"] * size, [0] * size)
                    output["signal_time"] = pd.Series([value] * size, dtype="object")
                    with self.assertRaisesRegex(ValueError, "signal_time.*pandas datetime"):
                        validate_strategy_output(candles, output)

    def test_incorrect_signal_time_is_rejected_on_hold_event_and_final_rows(self):
        for row in range(3):
            for offset in (-60, 30, 60):
                with self.subTest(row=row, offset_minutes=offset):
                    candles, output = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0])
                    output.loc[row, "signal_time"] += pd.Timedelta(minutes=offset)
                    with self.assertRaisesRegex(ValueError, "signal_time.*one elapsed hour"):
                        validate_strategy_output(candles, output)

    def test_signal_time_timezone_representation_must_match(self):
        for timezone in (None, "America/New_York"):
            with self.subTest(timezone=timezone):
                candles, output = frames(["HOLD"], [0])
                output["signal_time"] = output.signal_time.dt.tz_convert(timezone)
                with self.assertRaisesRegex(ValueError, "signal_time.*datetime/timezone"):
                    validate_strategy_output(candles, output)

    def test_signal_time_overflow_raises_value_error(self):
        candles = pd.DataFrame({"timestamp": [pd.Timestamp.max]})
        output = candles.assign(signal_time=candles.timestamp, signal="HOLD", desired_position=0)
        with self.assertRaisesRegex(ValueError, "signal_time.*represent"):
            validate_strategy_output(candles, output)

    def test_invalid_or_missing_signals_are_rejected_without_coercion(self):
        invalid = ("BUY", "SELL", "long_entry", "hold", " HOLD", "HOLD ", "", None, pd.NA,
                   np.nan, 0, True, object(), [], {}, np.array(["HOLD"]))
        for value in invalid:
            with self.subTest(value=repr(value)):
                candles, output = frames(["HOLD"], [0])
                output["signal"] = pd.Series([value], dtype="object")
                with self.assertRaisesRegex(ValueError, "Invalid signal at row 0"):
                    validate_strategy_output(candles, output)

    def test_exit_while_flat_is_rejected_including_final_row(self):
        for signals, positions, row in ((["LONG_EXIT"], [0], 0),
                                       (["LONG_ENTRY", "LONG_EXIT", "LONG_EXIT"], [1, 0, 0], 2)):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(ValueError, f"LONG_EXIT at row {row}.*currently FLAT"):
                    validate_strategy_output(*frames(signals, positions))

    def test_entry_while_long_is_rejected_including_final_row(self):
        with self.assertRaisesRegex(ValueError, "LONG_ENTRY at row 2.*already LONG"):
            validate_strategy_output(*frames(["LONG_ENTRY", "HOLD", "LONG_ENTRY"], [1, 1, 1]))

    def test_hold_cannot_change_flat_or_long_state(self):
        for signals, positions, row, expected in ((["HOLD"], [1], 0, 0),
                                                 (["LONG_ENTRY", "HOLD"], [1, 0], 1, 1)):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(ValueError, f"HOLD at row {row}.*desired_position {expected}"):
                    validate_strategy_output(*frames(signals, positions))

    def test_entry_desired_position_disagreement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "LONG_ENTRY at row 1.*desired_position 1"):
            validate_strategy_output(*frames(["HOLD", "LONG_ENTRY"], [0, 0]))

    def test_exit_desired_position_disagreement_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "LONG_EXIT at row 1.*desired_position 0"):
            validate_strategy_output(*frames(["LONG_ENTRY", "LONG_EXIT"], [1, 1]))

    def test_desired_position_outside_zero_one_is_rejected(self):
        for value in (-1, 2, np.int64(10)):
            with self.subTest(value=value):
                candles, output = frames(["HOLD"], [0])
                output["desired_position"] = pd.Series([value], dtype="object")
                with self.assertRaisesRegex(ValueError, "desired_position at row 0.*integer 0 or 1"):
                    validate_strategy_output(candles, output)

    def test_boolean_desired_positions_are_rejected(self):
        for value in (True, False, np.bool_(True), np.bool_(False)):
            with self.subTest(value=repr(value), scalar_type=type(value).__name__):
                candles, output = frames(["HOLD"], [0])
                output["desired_position"] = pd.Series([value], dtype="object")
                with self.assertRaisesRegex(ValueError, "desired_position at row 0.*integer 0 or 1"):
                    validate_strategy_output(candles, output)

    def test_float_desired_positions_are_rejected(self):
        for value in (0.0, 1.0, np.float64(0.0), np.float32(1.0)):
            with self.subTest(value=repr(value), scalar_type=type(value).__name__):
                candles, output = frames(["HOLD"], [0])
                output["desired_position"] = pd.Series([value], dtype="object")
                with self.assertRaisesRegex(ValueError, "desired_position at row 0.*integer 0 or 1"):
                    validate_strategy_output(candles, output)

    def test_other_malformed_desired_positions_are_rejected(self):
        for value in ("0", "1", None, pd.NA, np.nan, 0j, 1 + 0j, object(), [], {}, np.array([0])):
            with self.subTest(value=repr(value)):
                candles, output = frames(["HOLD"], [0])
                output["desired_position"] = pd.Series([value], dtype="object")
                with self.assertRaisesRegex(ValueError, "desired_position at row 0.*integer 0 or 1"):
                    validate_strategy_output(candles, output)

    def test_rejected_inputs_are_preserved(self):
        candles, output = frames(["LONG_ENTRY", "HOLD"], [1, 0])
        output["diagnostic"] = [10.0, 20.0]
        candles_before = candles.copy(deep=True)
        output_before = output.copy(deep=True)
        with self.assertRaisesRegex(ValueError, "HOLD at row 1"):
            validate_strategy_output(candles, output)
        pd.testing.assert_frame_equal(candles, candles_before)
        pd.testing.assert_frame_equal(output, output_before)


if __name__ == "__main__":
    unittest.main()
