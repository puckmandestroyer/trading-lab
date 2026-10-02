"""Synthetic composition tests; strategy and execution mechanics stay in their layers."""

import unittest
from unittest.mock import patch

import pandas as pd

from trading_lab.backtest.execution import apply_next_open_execution
from trading_lab.backtest.pipeline import run_ema_execution_pipeline
from trading_lab.strategies.ema_trend import generate_ema_signals


def candles(closes):
    """Different OPEN and CLOSE prices expose accidental same-close fills."""
    return pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=len(closes), freq="h", tz="UTC"),
        "open": pd.Series([200 + row for row in range(len(closes))], dtype="float64"),
        "close": pd.Series(closes, dtype="float64"),
    })


class BacktestPipelineTests(unittest.TestCase):
    def example(self):
        # With spans 2/3: row 50 bearish while flat, 51 entry, 52 exit,
        # 53 HOLD, 54 entry, 55 HOLD. Warm-up remains 50 candles.
        return candles([100] * 50 + [90, 110, 80, 80, 120, 120])

    def test_a_row_count_schema_and_custom_ema_names(self):
        data = self.example()
        for fast, slow in ((20, 50), (2, 3)):
            with self.subTest(fast=fast, slow=slow):
                result = run_ema_execution_pipeline(data, fast, slow)
                self.assertEqual(len(result), len(data))
                self.assertEqual(result.columns.tolist(), [
                    "timestamp", "open", "close", f"ema_{fast}", f"ema_{slow}",
                    "warmup_complete", "bullish_cross", "bearish_cross", "signal",
                    "desired_position", "signal_time", "execution_time",
                    "execution_price", "executed_position",
                ])

    def test_b_input_and_optional_context_are_not_modified(self):
        data = self.example()
        data["volume"] = 123
        data["signal"] = "existing unrelated input"
        original = data.copy(deep=True)
        result = run_ema_execution_pipeline(data, 2, 3)
        pd.testing.assert_frame_equal(data, original)
        self.assertNotIn("volume", result.columns)
        result.loc[0, "open"] = 999
        result.loc[0, "close"] = 999
        pd.testing.assert_frame_equal(data, original)

    def test_c_strategy_columns_equal_direct_component_output(self):
        data = self.example()
        strategy = generate_ema_signals(data, 2, 3)
        combined = run_ema_execution_pipeline(data, 2, 3)
        pd.testing.assert_frame_equal(combined[strategy.columns], strategy)

    def test_d_execution_columns_equal_direct_component_output(self):
        data = self.example()
        strategy = generate_ema_signals(data, 2, 3)
        execution_input = data[["timestamp", "open"]].copy()
        execution_input["signal"] = strategy.signal
        execution = apply_next_open_execution(execution_input)
        combined = run_ema_execution_pipeline(data, 2, 3)
        pd.testing.assert_frame_equal(combined[execution.columns], execution)

    def test_e_indexes_and_timestamps_are_preserved_without_resetting(self):
        data = self.example()
        # Labels do not describe chronological order; timestamps do.
        data.index = pd.Index(range(500, 500 - len(data), -1), name="candle_id")
        result = run_ema_execution_pipeline(data, 2, 3)
        pd.testing.assert_index_equal(result.index, data.index)
        pd.testing.assert_series_equal(result.timestamp, data.timestamp)
        pd.testing.assert_series_equal(result.open, data.open)
        pd.testing.assert_series_equal(result.close, data.close)

    def test_f_entry_changes_intent_now_and_execution_at_next_open(self):
        data = self.example()
        result = run_ema_execution_pipeline(data, 2, 3)
        self.assertEqual(result.loc[51, "signal"], "LONG_ENTRY")
        self.assertEqual(result.loc[51, "desired_position"], 1)
        self.assertEqual(result.loc[51, "executed_position"], 0)
        self.assertEqual(result.loc[51, "execution_time"], data.loc[52, "timestamp"])
        self.assertEqual(result.loc[51, "signal_time"], data.loc[52, "timestamp"])
        self.assertEqual(result.loc[51, "execution_price"], data.loc[52, "open"])
        self.assertNotEqual(result.loc[51, "execution_price"], data.loc[51, "close"])
        self.assertEqual(result.loc[52, "executed_position"], 1)

    def test_g_exit_changes_intent_now_and_execution_at_next_open(self):
        data = self.example()
        result = run_ema_execution_pipeline(data, 2, 3)
        self.assertEqual(result.loc[52, "signal"], "LONG_EXIT")
        self.assertEqual(result.loc[52, "desired_position"], 0)
        self.assertEqual(result.loc[52, "executed_position"], 1)
        self.assertEqual(result.loc[52, "execution_time"], data.loc[53, "timestamp"])
        self.assertEqual(result.loc[52, "execution_price"], data.loc[53, "open"])
        self.assertEqual(result.loc[53, "executed_position"], 0)

    def test_h_default_fifty_candle_warmup_has_no_intent_or_fills(self):
        result = run_ema_execution_pipeline(self.example())
        warmup = result.iloc[:50]
        self.assertTrue(warmup.signal.eq("HOLD").all())
        self.assertTrue(warmup.desired_position.eq(0).all())
        self.assertTrue(warmup.executed_position.eq(0).all())
        self.assertTrue(warmup.execution_time.isna().all())
        self.assertTrue(warmup.execution_price.isna().all())
        self.assertFalse(warmup.warmup_complete.any())

    def test_i_final_entry_and_exit_preserve_intent_without_fake_fill(self):
        data = self.example()
        for length, signal, desired, executed in (
            (52, "LONG_ENTRY", 1, 0), (53, "LONG_EXIT", 0, 1),
        ):
            with self.subTest(signal=signal):
                result = run_ema_execution_pipeline(data.iloc[:length], 2, 3)
                last = result.iloc[-1]
                self.assertEqual(last.signal, signal)
                self.assertEqual(last.desired_position, desired)
                self.assertEqual(last.executed_position, executed)
                self.assertTrue(pd.isna(last.execution_time))
                self.assertTrue(pd.isna(last.execution_price))

    def test_j_appending_next_candle_changes_only_final_signal_fill_metadata(self):
        data = self.example()
        full = run_ema_execution_pipeline(data, 2, 3)
        for length in (50, 52, 53, 54, 55):
            with self.subTest(length=length):
                prefix = run_ema_execution_pipeline(data.iloc[:length], 2, 3)
                # Every earlier row is identical. Strategy and state during
                # the former final candle stay identical as well.
                pd.testing.assert_frame_equal(prefix.iloc[:-1], full.iloc[:length - 1])
                stable_columns = prefix.columns.drop(["execution_time", "execution_price"])
                pd.testing.assert_frame_equal(prefix[stable_columns], full.iloc[:length][stable_columns])
                if prefix.signal.iloc[-1] == "HOLD":
                    pd.testing.assert_frame_equal(prefix, full.iloc[:length])
                else:
                    # A newly supplied N+1 legitimately makes final N executable.
                    self.assertTrue(pd.isna(prefix.execution_time.iloc[-1]))
                    self.assertTrue(pd.isna(prefix.execution_price.iloc[-1]))
                    self.assertEqual(full.execution_time.iloc[length - 1], data.timestamp.iloc[length])
                    self.assertEqual(full.execution_price.iloc[length - 1], data.open.iloc[length])

    def test_alignment_rejects_component_row_count_changes(self):
        data = self.example()
        with patch("trading_lab.backtest.pipeline.generate_ema_signals", wraps=generate_ema_signals) as strategy_call:
            strategy_call.return_value = generate_ema_signals(data, 2, 3).iloc[:-1]
            with self.assertRaisesRegex(ValueError, "Strategy.*row count"):
                run_ema_execution_pipeline(data, 2, 3)
        with patch("trading_lab.backtest.pipeline.apply_next_open_execution") as execution_call:
            execution_call.side_effect = lambda rows: apply_next_open_execution(rows).iloc[:-1]
            with self.assertRaisesRegex(ValueError, "Execution.*row count"):
                run_ema_execution_pipeline(data, 2, 3)

    def test_alignment_rejects_component_index_changes(self):
        data = self.example()
        for target, layer in (("generate_ema_signals", "Strategy"), ("apply_next_open_execution", "Execution")):
            with self.subTest(layer=layer):
                with patch("trading_lab.backtest.pipeline." + target) as component:
                    direct = generate_ema_signals if layer == "Strategy" else apply_next_open_execution
                    def changed_index(rows, *parameters):
                        result = direct(rows, *parameters)
                        result.index = result.index + 1000
                        return result
                    component.side_effect = changed_index
                    with self.assertRaisesRegex(ValueError, layer + ".*index"):
                        run_ema_execution_pipeline(data, 2, 3)

    def test_alignment_rejects_changed_timestamps_even_with_same_index(self):
        data = self.example()
        for target, layer in (("generate_ema_signals", "Strategy"), ("apply_next_open_execution", "Execution")):
            with self.subTest(layer=layer):
                with patch("trading_lab.backtest.pipeline." + target) as component:
                    direct = generate_ema_signals if layer == "Strategy" else apply_next_open_execution
                    def changed_timestamp(rows, *parameters):
                        result = direct(rows, *parameters)
                        result["timestamp"] += pd.Timedelta(hours=1)
                        return result
                    component.side_effect = changed_timestamp
                    with self.assertRaisesRegex(ValueError, layer + ".*timestamps differ"):
                        run_ema_execution_pipeline(data, 2, 3)

    def test_alignment_rejects_reordered_component_rows(self):
        data = self.example()
        with patch("trading_lab.backtest.pipeline.generate_ema_signals") as component:
            component.return_value = generate_ema_signals(data, 2, 3).iloc[::-1]
            with self.assertRaisesRegex(ValueError, "Strategy.*alignment"):
                run_ema_execution_pipeline(data, 2, 3)

    def test_execution_invalid_strategy_sequence_is_not_repaired(self):
        data = self.example()
        invalid = generate_ema_signals(data, 2, 3)
        invalid.loc[0, "signal"] = "LONG_EXIT"
        with patch("trading_lab.backtest.pipeline.generate_ema_signals", return_value=invalid):
            with self.assertRaisesRegex(ValueError, "LONG_EXIT.*currently flat"):
                run_ema_execution_pipeline(data, 2, 3)

    def test_execution_output_cannot_silently_change_strategy_signals(self):
        def changed_signal(rows):
            result = apply_next_open_execution(rows)
            result.loc[0, "signal"] = "LONG_ENTRY"
            return result
        with patch("trading_lab.backtest.pipeline.apply_next_open_execution", side_effect=changed_signal):
            with self.assertRaisesRegex(ValueError, "changed strategy signals"):
                run_ema_execution_pipeline(self.example(), 2, 3)

    def test_pipeline_requires_only_unique_timestamp_open_close_columns(self):
        data = self.example()
        with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
            run_ema_execution_pipeline(None)
        for column in ("timestamp", "open", "close"):
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "Missing required columns"):
                    run_ema_execution_pipeline(data.drop(columns=column))
        with self.assertRaisesRegex(ValueError, "column names must be unique"):
            run_ema_execution_pipeline(pd.concat([data, data[["open"]]], axis=1))

    def test_component_validation_errors_propagate(self):
        data = self.example()
        with self.assertRaisesRegex(ValueError, "fast_span"):
            run_ema_execution_pipeline(data, fast_span=0)
        bad_spacing = data.copy()
        bad_spacing["timestamp"] = pd.date_range("2025-01-01", periods=len(data), freq="2h", tz="UTC")
        with self.assertRaisesRegex(ValueError, "one-hour spacing"):
            run_ema_execution_pipeline(bad_spacing, 2, 3)
        bad_open = data.copy()
        bad_open.loc[52, "open"] = 0
        with self.assertRaisesRegex(ValueError, "Execution OPEN"):
            run_ema_execution_pipeline(bad_open, 2, 3)

    def test_empty_and_single_hold_inputs_return_aligned_results(self):
        for closes in ([], [100]):
            with self.subTest(length=len(closes)):
                data = candles(closes)
                result = run_ema_execution_pipeline(data)
                self.assertEqual(len(result), len(data))
                pd.testing.assert_index_equal(result.index, data.index)
                pd.testing.assert_series_equal(result.timestamp, data.timestamp)
                self.assertTrue(result.execution_time.isna().all())
                self.assertTrue(result.executed_position.eq(0).all())


if __name__ == "__main__":
    unittest.main()
