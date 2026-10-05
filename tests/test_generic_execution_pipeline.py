"""Synthetic tests for generic intent/execution composition; no BTC or PnL."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_lab.backtest.execution import apply_next_open_execution
from trading_lab.backtest.pipeline import run_execution_pipeline
from trading_lab.backtest.strategy_validation import validate_strategy_output


EXECUTION_COLUMNS = [
    "timestamp", "open", "signal", "execution_time", "execution_price", "executed_position",
]


def frames(signals, positions, opens=None, index=None, timestamps=None):
    """Explicit intent and timestamp/OPEN-only candles; no strategy generation."""
    if timestamps is None:
        timestamps = pd.date_range("2025-01-01", periods=len(signals), freq="h", tz="UTC")
    candles = pd.DataFrame({"timestamp": timestamps}, index=index)
    if opens is None:
        opens = pd.Series(range(100, 100 + len(signals)), index=candles.index, dtype="float64")
    candles["open"] = pd.Series(opens, index=candles.index)
    strategy = candles[["timestamp"]].copy(deep=True)
    strategy["signal_time"] = strategy.timestamp + pd.Timedelta(hours=1)
    strategy["signal"] = pd.Series(signals, index=candles.index, dtype="object")
    strategy["desired_position"] = pd.Series(positions, index=candles.index, dtype="int64")
    return candles, strategy


class GenericExecutionPipelineTests(unittest.TestCase):
    def assert_direct_parity(self, candles, strategy):
        generic = run_execution_pipeline(candles, strategy)
        direct_input = candles.copy(deep=True)
        direct_input["signal"] = strategy["signal"]
        direct = apply_next_open_execution(direct_input)
        pd.testing.assert_frame_equal(generic, direct)
        self.assertEqual(generic.columns.tolist(), EXECUTION_COLUMNS)
        return generic

    def test_all_hold_stays_flat_without_fills(self):
        result = run_execution_pipeline(*frames(["HOLD"] * 3, [0] * 3))
        self.assertEqual(result.executed_position.tolist(), [0, 0, 0])
        self.assertTrue(result.execution_time.isna().all())
        self.assertTrue(result.execution_price.isna().all())

    def test_entry_fills_next_market_open_with_delayed_state(self):
        candles, strategy = frames(["HOLD", "LONG_ENTRY", "HOLD"], [0, 1, 1], [100, 101, 103])
        candles["close"] = [900, 901, 903]
        result = run_execution_pipeline(candles, strategy)
        self.assertEqual(result.loc[1, "execution_time"], candles.loc[2, "timestamp"])
        self.assertEqual(result.loc[1, "execution_price"], 103)
        self.assertNotEqual(result.loc[1, "execution_price"], candles.loc[1, "close"])
        self.assertEqual(result.executed_position.tolist(), [0, 0, 1])

    def test_entry_and_exit_fill_at_their_next_opens(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"], [1, 1, 0, 0])
        result = run_execution_pipeline(candles, strategy)
        for signal_row, fill_row in ((0, 1), (2, 3)):
            self.assertEqual(result.loc[signal_row, "execution_time"], candles.loc[fill_row, "timestamp"])
            self.assertEqual(result.loc[signal_row, "execution_price"], candles.loc[fill_row, "open"])
        self.assertEqual(result.executed_position.tolist(), [0, 1, 1, 0])

    def test_hold_while_long_preserves_executed_state(self):
        result = run_execution_pipeline(*frames(["LONG_ENTRY", "HOLD", "HOLD"], [1, 1, 1]))
        self.assertEqual(result.executed_position.tolist(), [0, 1, 1])
        self.assertTrue(result.iloc[1:].execution_time.isna().all())
        self.assertTrue(result.iloc[1:].execution_price.isna().all())

    def test_final_entry_has_no_fill_or_executed_state_change(self):
        result = run_execution_pipeline(*frames(["HOLD", "LONG_ENTRY"], [0, 1]))
        self.assertEqual(result.signal.tolist(), ["HOLD", "LONG_ENTRY"])
        self.assertEqual(result.executed_position.tolist(), [0, 0])
        self.assertTrue(result.execution_time.isna().all())
        self.assertTrue(result.execution_price.isna().all())

    def test_final_exit_does_not_force_close(self):
        result = run_execution_pipeline(*frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0]))
        self.assertEqual(result.executed_position.tolist(), [0, 1, 1])
        self.assertEqual(result.signal.iloc[-1], "LONG_EXIT")
        self.assertTrue(pd.isna(result.execution_time.iloc[-1]))
        self.assertTrue(pd.isna(result.execution_price.iloc[-1]))

    def test_single_final_entry_is_valid_without_a_fill(self):
        result = run_execution_pipeline(*frames(["LONG_ENTRY"], [1]))
        self.assertEqual(result.executed_position.tolist(), [0])
        self.assertTrue(result.execution_time.isna().all())
        self.assertTrue(result.execution_price.isna().all())

    def test_non_range_index_is_preserved(self):
        index = pd.Index([30, 10, 20, 5], name="candle_id")
        result = self.assert_direct_parity(*frames(
            ["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"], [1, 1, 0, 0], index=index
        ))
        pd.testing.assert_index_equal(result.index, index)

    def test_aligned_duplicate_index_labels_are_preserved(self):
        index = pd.Index([5, 5, 2], name="candle_id")
        result = self.assert_direct_parity(*frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0], index=index))
        pd.testing.assert_index_equal(result.index, index)

    def test_empty_typed_input_has_exact_execution_schema_and_dtypes(self):
        result = self.assert_direct_parity(*frames([], []))
        self.assertTrue(result.empty)
        self.assertEqual(str(result.timestamp.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(result.open.dtype), "float64")
        self.assertEqual(str(result.signal.dtype), "object")
        self.assertEqual(str(result.execution_time.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(result.execution_price.dtype), "float64")
        self.assertEqual(str(result.executed_position.dtype), "int64")

    def test_naive_and_timezone_aware_clocks_retain_direct_helper_parity(self):
        for timezone in (None, "America/New_York"):
            with self.subTest(timezone=timezone):
                timestamps = pd.date_range("2025-03-09 01:00", periods=3, freq="h", tz=timezone)
                candles, strategy = frames(["LONG_ENTRY", "HOLD", "HOLD"], [1, 1, 1], timestamps=timestamps)
                result = self.assert_direct_parity(candles, strategy)
                self.assertEqual(result.execution_time.iloc[0], timestamps[1])
                self.assertEqual(result.execution_time.dtype, candles.timestamp.dtype)

    def test_strategy_diagnostics_are_ignored_and_not_returned(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"], [1, 1, 0, 0])
        baseline = run_execution_pipeline(candles, strategy)
        strategy["ema_20"] = [np.nan, np.inf, -100.0, 0.0]
        strategy["ema_50"] = "ignored"
        strategy["breakout_level"] = "anything"
        strategy["z_score"] = pd.NA
        result = run_execution_pipeline(candles, strategy)
        pd.testing.assert_frame_equal(result, baseline)
        self.assertEqual(result.columns.tolist(), EXECUTION_COLUMNS)

    def test_colliding_strategy_open_and_execution_diagnostics_cannot_override_market(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1], [100, 103])
        strategy["open"] = [999999, 999999]
        strategy["execution_price"] = -1.0
        strategy["execution_time"] = "fake time"
        strategy["executed_position"] = 99
        result = self.assert_direct_parity(candles, strategy)
        pd.testing.assert_series_equal(result.open, candles.open)
        self.assertEqual(result.execution_price.iloc[0], 103)
        self.assertEqual(result.executed_position.tolist(), [0, 1])

    def test_preexisting_candle_signal_is_overridden_only_in_local_input(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1])
        candles["signal"] = "unrelated existing signal"
        original = candles.copy(deep=True)
        result = run_execution_pipeline(candles, strategy)
        pd.testing.assert_series_equal(result.signal, strategy.signal)
        self.assertEqual(result.executed_position.tolist(), [0, 1])
        pd.testing.assert_frame_equal(candles, original)

    def test_validator_then_execution_are_delegated_on_a_local_copy(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1])
        strategy["diagnostic"] = "never copied to execution input"
        calls = []

        def validate(market, intent):
            calls.append("validate")
            self.assertIs(market, candles)
            self.assertIs(intent, strategy)
            return validate_strategy_output(market, intent)

        def execute(execution_input):
            calls.append("execute")
            self.assertIsNot(execution_input, candles)
            expected = candles.copy(deep=True)
            expected["signal"] = strategy["signal"]
            pd.testing.assert_frame_equal(execution_input, expected)
            return apply_next_open_execution(execution_input)

        with patch("trading_lab.backtest.pipeline.validate_strategy_output", side_effect=validate) as validator:
            with patch("trading_lab.backtest.pipeline.apply_next_open_execution", side_effect=execute) as executor:
                run_execution_pipeline(candles, strategy)
                validator.assert_called_once()
                executor.assert_called_once()
        self.assertEqual(calls, ["validate", "execute"])

    def test_invalid_intent_is_rejected_before_execution(self):
        cases = ("signal_time", "float", "bool", "hold_state", "exit_flat", "timestamp", "index")
        for case in cases:
            with self.subTest(case=case):
                candles, strategy = frames(["HOLD", "HOLD"], [0, 0])
                if case == "signal_time":
                    strategy["signal_time"] += pd.Timedelta(minutes=1)
                elif case in ("float", "bool"):
                    value = 0.0 if case == "float" else False
                    strategy["desired_position"] = pd.Series([value, value], dtype="object")
                elif case == "hold_state":
                    strategy.loc[0, "desired_position"] = 1
                elif case == "exit_flat":
                    strategy.loc[0, "signal"] = "LONG_EXIT"
                elif case == "timestamp":
                    strategy["timestamp"] += pd.Timedelta(minutes=1)
                else:
                    strategy.index = [10, 20]
                candles_before = candles.copy(deep=True)
                strategy_before = strategy.copy(deep=True)
                with patch("trading_lab.backtest.pipeline.apply_next_open_execution") as executor:
                    with self.assertRaises(ValueError):
                        run_execution_pipeline(candles, strategy)
                    executor.assert_not_called()
                pd.testing.assert_frame_equal(candles, candles_before)
                pd.testing.assert_frame_equal(strategy, strategy_before)

    def test_hourly_continuity_validation_is_delegated_to_execution(self):
        timestamps = pd.date_range("2025-01-01", periods=2, freq="2h", tz="UTC")
        candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1], timestamps=timestamps)
        with patch("trading_lab.backtest.pipeline.apply_next_open_execution", wraps=apply_next_open_execution) as executor:
            with self.assertRaisesRegex(ValueError, "one-hour spacing"):
                run_execution_pipeline(candles, strategy)
            executor.assert_called_once()

    def test_invalid_fill_open_validation_is_delegated_to_execution(self):
        for price in (0, "bad price"):
            with self.subTest(price=price):
                candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1])
                candles["open"] = pd.Series([100, price], dtype="object")
                with patch("trading_lab.backtest.pipeline.apply_next_open_execution", wraps=apply_next_open_execution) as executor:
                    with self.assertRaisesRegex(ValueError, "Execution OPEN"):
                        run_execution_pipeline(candles, strategy)
                    executor.assert_called_once()

    def test_missing_open_is_rejected_by_execution_not_replaced_by_a_diagnostic(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1])
        candles = candles.drop(columns="open")
        strategy["open"] = 999999
        with patch("trading_lab.backtest.pipeline.apply_next_open_execution", wraps=apply_next_open_execution) as executor:
            with self.assertRaisesRegex(ValueError, "Missing required columns.*open"):
                run_execution_pipeline(candles, strategy)
            executor.assert_called_once()

    def test_unused_market_open_values_are_not_validated_by_the_pipeline(self):
        candles, strategy = frames(["HOLD", "LONG_ENTRY", "HOLD"], [0, 1, 1])
        candles["open"] = pd.Series([None, None, 103.0], dtype="object")
        result = self.assert_direct_parity(candles, strategy)
        self.assertEqual(result.execution_price.iloc[1], 103.0)

    def test_direct_helper_parity_includes_schema_index_and_dtypes(self):
        for signals, positions in ((["HOLD"] * 3, [0] * 3),
                                   (["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"], [1, 1, 0, 0]),
                                   (["LONG_ENTRY", "LONG_EXIT"], [1, 0])):
            with self.subTest(signals=signals):
                self.assert_direct_parity(*frames(signals, positions))

    def test_inputs_are_preserved_and_returned_scalar_columns_are_independent(self):
        index = pd.Index([30, 10, 20, 5], name="candle_id")
        candles, strategy = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"], [1, 1, 0, 0], index=index)
        candles["context"] = pd.Categorical(["a", "b", "a", "b"])
        strategy["diagnostic"] = pd.Series([1, None, 3, 4], index=index, dtype="Int64")
        candles_before = candles.copy(deep=True)
        strategy_before = strategy.copy(deep=True)
        result = run_execution_pipeline(candles, strategy)
        pd.testing.assert_frame_equal(candles, candles_before)
        pd.testing.assert_frame_equal(strategy, strategy_before)
        result.loc[30, "open"] = -999
        result.loc[30, "signal"] = "changed"
        result.loc[30, "timestamp"] += pd.Timedelta(days=1)
        result.loc[30, "execution_price"] = -1.0
        pd.testing.assert_frame_equal(candles, candles_before)
        pd.testing.assert_frame_equal(strategy, strategy_before)

    def test_appending_next_candle_only_populates_former_final_event_metadata(self):
        signals = ["HOLD", "LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD", "LONG_ENTRY", "HOLD"]
        candles, strategy = frames(signals, [0, 1, 1, 0, 0, 1, 1])
        original_strategy = strategy.copy(deep=True)
        full = run_execution_pipeline(candles, strategy)
        for length in (2, 4, 6):
            with self.subTest(length=length):
                prefix_intent = strategy.iloc[:length].copy(deep=True)
                intent_before = prefix_intent.copy(deep=True)
                prefix = run_execution_pipeline(candles.iloc[:length], prefix_intent)
                pd.testing.assert_frame_equal(prefix.iloc[:-1], full.iloc[:length - 1])
                stable_columns = prefix.columns.drop(["execution_time", "execution_price"])
                pd.testing.assert_frame_equal(prefix[stable_columns], full.iloc[:length][stable_columns])
                self.assertTrue(pd.isna(prefix.execution_time.iloc[-1]))
                self.assertTrue(pd.isna(prefix.execution_price.iloc[-1]))
                self.assertEqual(full.execution_time.iloc[length - 1], candles.timestamp.iloc[length])
                self.assertEqual(full.execution_price.iloc[length - 1], candles.open.iloc[length])
                pd.testing.assert_frame_equal(prefix_intent, intent_before)
        pd.testing.assert_frame_equal(strategy, original_strategy)

    def test_execution_output_alignment_and_signal_open_changes_are_rejected(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD"], [1, 1])
        cases = (("row_count", "Execution.*row count"), ("index", "Execution.*index"),
                 ("timestamp", "Execution.*timestamps"), ("signal", "changed strategy signals"),
                 ("open", "changed market OPEN"))
        for case, message in cases:
            with self.subTest(case=case):
                def changed_execution(rows):
                    result = apply_next_open_execution(rows)
                    if case == "row_count":
                        return result.iloc[:-1]
                    if case == "index":
                        result.index = result.index + 100
                    elif case == "timestamp":
                        result["timestamp"] += pd.Timedelta(minutes=1)
                    elif case == "signal":
                        result.loc[0, "signal"] = "HOLD"
                    else:
                        result.loc[0, "open"] = 999999
                    return result

                with patch("trading_lab.backtest.pipeline.apply_next_open_execution", side_effect=changed_execution):
                    with self.assertRaisesRegex(ValueError, message):
                        run_execution_pipeline(candles, strategy)

    def test_generic_pipeline_does_not_generate_ema_signals(self):
        with patch("trading_lab.backtest.pipeline.generate_ema_signals", side_effect=AssertionError("Unexpected EMA generation")) as ema:
            run_execution_pipeline(*frames(["LONG_ENTRY", "HOLD"], [1, 1]))
            ema.assert_not_called()


if __name__ == "__main__":
    unittest.main()
