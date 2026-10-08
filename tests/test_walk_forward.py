"""Expanding full windows, fixed settings, and independent cold-start runs."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from types import MappingProxyType
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_lab.data.market_data import load_ohlcv_csv
from trading_lab.robustness import (
    evaluate_expanding_walk_forward,
    evaluate_strategy_segment,
    generate_expanding_walk_forward_windows,
)
from trading_lab.robustness import evaluation, walk_forward
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_ema_generic_regression import (
    END, FEE_RATE, FROZEN_SHA256, HOUR, INITIAL_CAPITAL, RAW_BTC,
    SLIPPAGE_RATE, START,
)
from tests.test_robustness_oos import (
    EMA_KWARGS, SEGMENT_KEYS, assert_segment_equal, candles, event_strategy,
)


WINDOW_COLUMNS = [
    "window_id", "train_start_index", "train_end_index", "test_start_index",
    "test_end_index", "train_rows", "test_rows", "train_start_timestamp",
    "train_last_timestamp", "test_start_timestamp", "test_last_timestamp",
]


def assert_walk_forward_equal(test, actual, expected):
    test.assertEqual(list(actual), ["window_definitions", "unused_tail_rows", "windows"])
    pd.testing.assert_frame_equal(actual["window_definitions"], expected["window_definitions"], check_exact=True)
    test.assertEqual(actual["unused_tail_rows"], expected["unused_tail_rows"])
    test.assertEqual(len(actual["windows"]), len(expected["windows"]))
    for left, right in zip(actual["windows"], expected["windows"]):
        test.assertEqual(left["window_id"], right["window_id"])
        for label in ("train", "test"):
            assert_segment_equal(test, left[label], right[label])


class ExpandingWindowDefinitionTests(unittest.TestCase):
    def setUp(self):
        self.source = candles(range(100, 112))

    def test_one_full_window_exact_schema_and_slice_geometry(self):
        table = generate_expanding_walk_forward_windows(self.source.iloc[:8], 5, 3)
        self.assertEqual(table.columns.tolist(), WINDOW_COLUMNS)
        self.assertEqual(table.iloc[0][WINDOW_COLUMNS[:7]].tolist(), [1, 0, 5, 5, 8, 5, 3])
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(1), exact=True)
        self.assertTrue(table[WINDOW_COLUMNS[:7]].dtypes.eq("int64").all())

    def test_multiple_windows_expand_and_tests_are_fixed_gap_free_nonoverlapping(self):
        table = generate_expanding_walk_forward_windows(self.source, 5, 3)
        self.assertEqual(table[WINDOW_COLUMNS[:7]].values.tolist(), [
            [1, 0, 5, 5, 8, 5, 3], [2, 0, 8, 8, 11, 8, 3],
        ])
        self.assertTrue(table.train_start_index.eq(0).all())
        self.assertTrue(table.train_end_index.eq(table.test_start_index).all())
        self.assertTrue((table.test_end_index - table.test_start_index).eq(3).all())
        self.assertEqual(table.test_start_index.iloc[1], table.test_end_index.iloc[0])
        self.assertEqual(table.train_rows.iloc[1] - table.train_rows.iloc[0], 3)
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(2), exact=True)

    def test_timestamp_metadata_uses_actual_first_and_last_slice_rows(self):
        table = generate_expanding_walk_forward_windows(self.source, 5, 3)
        for row in table.itertuples(index=False):
            self.assertEqual(row.train_start_timestamp, self.source.timestamp.iloc[0])
            self.assertEqual(row.train_last_timestamp, self.source.timestamp.iloc[row.train_end_index - 1])
            self.assertEqual(row.test_start_timestamp, self.source.timestamp.iloc[row.test_start_index])
            self.assertEqual(row.test_last_timestamp, self.source.timestamp.iloc[row.test_end_index - 1])

    def test_partial_final_test_is_excluded(self):
        table = generate_expanding_walk_forward_windows(self.source, 5, 3)
        self.assertEqual(len(table), 2)
        self.assertEqual(table.test_end_index.iloc[-1], 11)
        self.assertFalse(table.test_last_timestamp.eq(self.source.timestamp.iloc[11]).any())

    def test_python_numpy_integral_scalars_are_accepted(self):
        expected = generate_expanding_walk_forward_windows(self.source, 5, 3)
        for train, test in ((5, 3), (np.int64(5), np.int32(3)), (np.uint64(5), np.uint64(3))):
            with self.subTest(train=train, test=test):
                pd.testing.assert_frame_equal(
                    generate_expanding_walk_forward_windows(self.source, train, test), expected, check_exact=True,
                )

    def test_invalid_row_parameters_are_not_coerced(self):
        invalid = (0, -1, True, False, np.bool_(True), np.bool_(False), 5.0,
                   np.float64(3.0), np.nan, np.inf, "3", None, 3 + 0j,
                   [3], np.array(3), np.array([3]), pd.Series([3]))
        for name in ("initial_train_rows", "test_rows"):
            for value in invalid:
                parameters = {"initial_train_rows": 5, "test_rows": 3, name: value}
                with self.subTest(name=name, value=repr(value)), self.assertRaisesRegex(ValueError, name):
                    generate_expanding_walk_forward_windows(self.source, **parameters)

    def test_no_complete_window_is_rejected_including_large_numpy_counts(self):
        for source, train, test in (
            (self.source, 10, 3), (self.source.iloc[:0], 1, 1), (self.source.iloc[:1], 1, 1),
            (self.source, np.uint64(2**64 - 1), np.uint64(3)),
        ):
            with self.subTest(rows=len(source), train=train), self.assertRaisesRegex(ValueError, "complete"):
                generate_expanding_walk_forward_windows(source, train, test)

    def test_non_dataframe_and_missing_timestamp_rejected(self):
        for source in (None, [], {}, "candles", self.source.drop(columns="timestamp")):
            with self.subTest(source=repr(source)), self.assertRaises(ValueError):
                generate_expanding_walk_forward_windows(source, 5, 3)

    def test_non_datetime_missing_and_duplicate_timestamps_rejected(self):
        sources = []
        text = self.source.copy()
        text["timestamp"] = text.timestamp.astype(str)
        sources.append(text)
        missing = self.source.copy()
        missing.loc[2, "timestamp"] = pd.NaT
        sources.append(missing)
        duplicate = self.source.copy()
        duplicate.loc[2, "timestamp"] = duplicate.timestamp.iloc[1]
        sources.append(duplicate)
        for source in sources:
            before = source.copy(deep=True)
            with self.subTest(dtype=source.timestamp.dtype), self.assertRaises(ValueError):
                generate_expanding_walk_forward_windows(source, 5, 3)
            pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_non_monotonic_timestamps_are_not_sorted_or_repaired(self):
        source = self.source.iloc[[0, 2, 1, *range(3, 12)]]
        before = source.copy(deep=True)
        with self.assertRaisesRegex(ValueError, "strictly increasing"):
            generate_expanding_walk_forward_windows(source, 5, 3)
        pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_duplicate_candle_columns_rejected(self):
        source = pd.concat([self.source, self.source[["close"]]], axis=1)
        with self.assertRaisesRegex(ValueError, "column names"):
            generate_expanding_walk_forward_windows(source, 5, 3)

    def test_timezone_and_naive_clock_preserved(self):
        for zone in (None, "Asia/Seoul"):
            source = self.source.copy()
            source["timestamp"] = (source.timestamp.dt.tz_localize(None) if zone is None
                                   else source.timestamp.dt.tz_convert(zone))
            table = generate_expanding_walk_forward_windows(source, 5, 3)
            for name in WINDOW_COLUMNS[7:]:
                self.assertEqual(table[name].dtype, source.timestamp.dtype)
            self.assertEqual(table.test_start_timestamp.iloc[0], source.timestamp.iloc[5])

    def test_non_range_duplicate_index_and_extra_dtypes_preserved(self):
        source = self.source.copy()
        source.index = pd.Index([9, 9, 1, 7, 2, 2, 8, 3, 6, 4, 0, 0], name="source_id")
        source["context"] = pd.Categorical(["a", "b"] * 6)
        source["volume"] = pd.array([1, None] * 6, dtype="Int64")
        source = source[["context", "close", "timestamp", "volume", "open"]]
        before = source.copy(deep=True)
        table = generate_expanding_walk_forward_windows(source, 5, 3)
        pd.testing.assert_frame_equal(source, before, check_exact=True)
        self.assertEqual(table.test_start_index.tolist(), [5, 8])

    def test_window_geometry_is_row_based_even_with_timestamp_gaps(self):
        source = self.source[["timestamp"]].copy()
        offsets = [0, 1, 2, 3, 4, 100, 101, 102, 200, 201, 202, 999]
        source["timestamp"] = pd.DatetimeIndex([self.source.timestamp.iloc[0] + offset * HOUR for offset in offsets])
        table = generate_expanding_walk_forward_windows(source, 5, 3)
        self.assertEqual(table.train_rows.tolist(), [5, 8])
        self.assertEqual(table.test_rows.tolist(), [3, 3])
        self.assertEqual(table.test_start_timestamp.iloc[0], source.timestamp.iloc[5])


class ExpandingWalkForwardEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.source = candles([90, 100, 115, 130, 125, 120,
                               180, 200, 220, 240, 235, 230,
                               300, 320, 360, 350, 340, 330])
        self.parameters = dict(candle_interval=HOUR, initial_train_rows=6, test_rows=6)

    def run_evaluation(self, generator=event_strategy, source=None, **kwargs):
        return evaluate_expanding_walk_forward(
            self.source if source is None else source, generator, **{**self.parameters, **kwargs},
        )

    def test_public_imports_return_keys_tuple_and_window_ids(self):
        import trading_lab.robustness as robustness
        self.assertIs(robustness.evaluate_expanding_walk_forward, walk_forward.evaluate_expanding_walk_forward)
        self.assertIs(robustness.generate_expanding_walk_forward_windows,
                      walk_forward.generate_expanding_walk_forward_windows)
        self.assertEqual(robustness.__all__, [
            "chronological_split", "evaluate_strategy_segment", "evaluate_train_test_split",
        ])
        result = self.run_evaluation()
        self.assertEqual(list(result), ["window_definitions", "unused_tail_rows", "windows"])
        self.assertIsInstance(result["windows"], tuple)
        self.assertEqual([w["window_id"] for w in result["windows"]], [1, 2])
        for window in result["windows"]:
            self.assertEqual(list(window), ["window_id", "train", "test"])
            for label in ("train", "test"):
                self.assertEqual(list(window[label]), SEGMENT_KEYS)

    def test_window_generator_is_reused_without_changed_definitions(self):
        with patch.object(walk_forward, "generate_expanding_walk_forward_windows",
                          wraps=generate_expanding_walk_forward_windows) as generator:
            result = self.run_evaluation()
        generator.assert_called_once_with(self.source, 6, 6)
        pd.testing.assert_frame_equal(
            result["window_definitions"], generate_expanding_walk_forward_windows(self.source, 6, 6),
            check_exact=True,
        )

    def test_each_slice_matches_direct_composition_for_all_seven_frames(self):
        source = self.source.copy()
        source.index = pd.Index([99 - i for i in range(18)], name="row_label")
        assumptions = dict(
            candle_interval=HOUR, strategy_kwargs={"tag": "fixed"}, initial_capital=3210.0,
            fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.37,
        )
        result = self.run_evaluation(source=source, **assumptions)
        for window, definition in zip(result["windows"], result["window_definitions"].itertuples(index=False)):
            for label, start, end in (
                ("train", definition.train_start_index, definition.train_end_index),
                ("test", definition.test_start_index, definition.test_end_index),
            ):
                with self.subTest(window=window["window_id"], label=label):
                    expected = evaluate_strategy_segment(source.iloc[start:end], event_strategy, **assumptions)
                    assert_segment_equal(self, window[label], expected)

    def test_correct_slices_and_same_generator_financial_settings_forwarded(self):
        common = MappingProxyType({"tag": "same"})
        assumptions = dict(candle_interval=HOUR, initial_capital=3210.0, fee_rate=0.001,
                           slippage_rate=0.0005, position_fraction=0.37)
        with patch.object(walk_forward, "evaluate_strategy_segment", wraps=evaluate_strategy_segment) as core:
            self.run_evaluation(strategy_kwargs=common, **assumptions)
        self.assertEqual(core.call_count, 4)
        expected_slices = [(0, 6), (6, 12), (0, 12), (12, 18)]
        for call, (start, end) in zip(core.call_args_list, expected_slices):
            pd.testing.assert_frame_equal(call.args[0], self.source.iloc[start:end], check_exact=True)
            self.assertIsNot(call.args[0], self.source)
            self.assertIs(call.args[1], event_strategy)
            self.assertEqual(call.kwargs, dict(**assumptions, strategy_kwargs={"tag": "same"}))
        self.assertEqual(len({id(call.kwargs["strategy_kwargs"]) for call in core.call_args_list}), 4)

    def test_generator_receives_segment_only_copies_with_original_labels_dtypes(self):
        source = self.source.copy()
        source.index = pd.Index([7, 7, *range(16)], name="source_id")
        source["context"] = pd.Categorical(["a", "b"] * 9)
        source["volume"] = pd.array([1, None] * 9, dtype="Int64")
        seen = []
        def generator(frame):
            seen.append(frame.copy(deep=True))
            return event_strategy(frame)
        self.run_evaluation(source=source, generator=generator)
        for actual, (start, end) in zip(seen, ((0, 6), (6, 12), (0, 12), (12, 18))):
            pd.testing.assert_frame_equal(actual, source.iloc[start:end], check_exact=True)

    def test_no_train_test_or_later_train_capital_carry(self):
        result = self.run_evaluation()
        self.assertEqual(result["windows"][0]["train"]["gross_results"].capital_after.iloc[-1], 13_000)
        self.assertEqual(result["windows"][0]["test"]["gross_results"].capital_after.iloc[-1], 12_000)
        for window in result["windows"]:
            for label in ("train", "test"):
                for key in ("gross_equity", "net_equity"):
                    self.assertEqual(window[label][key].equity.iloc[0], 10_000)
                    self.assertEqual(window[label][key].position.iloc[0], 0)
                for key in ("gross_results", "net_results"):
                    self.assertEqual(window[label][key].capital_before.iloc[0], 10_000)
        self.assertEqual(result["windows"][1]["test"]["gross_results"].quantity.iloc[0], 31.25)

    def test_training_open_position_and_prior_test_do_not_carry_state(self):
        source = candles([110, 120, 130, 140, 150, 160] + [50, 60, 70, 80, 90, 95] * 2)
        def generator(frame):
            events = {0: "LONG_ENTRY"} if frame.close.iloc[0] > 100 else {}
            return event_strategy(frame, events=events)
        result = self.run_evaluation(source=source, generator=generator)
        for window in result["windows"]:
            self.assertEqual(window["train"]["trades"].status.tolist(), ["OPEN"])
            self.assertTrue(window["test"]["trades"].empty)
            self.assertTrue(window["test"]["strategy_output"].desired_position.eq(0).all())
            self.assertTrue(window["test"]["execution"].executed_position.eq(0).all())
            self.assertTrue(window["test"]["net_equity"].equity.eq(10_000).all())

    def test_final_train_entry_cannot_borrow_first_test_open(self):
        def generator(frame):
            events = {len(frame) - 1: "LONG_ENTRY"} if frame.timestamp.iloc[0] == self.source.timestamp.iloc[0] else {}
            return event_strategy(frame, events=events)
        result = self.run_evaluation(generator=generator)
        for window in result["windows"]:
            train, test = window["train"], window["test"]
            self.assertEqual(train["strategy_output"].signal.iloc[-1], "LONG_ENTRY")
            self.assertTrue(train["execution"].iloc[-1][["execution_time", "execution_price"]].isna().all())
            self.assertTrue(train["trades"].empty)
            self.assertTrue(test["trades"].empty)
            self.assertTrue(test["execution"].executed_position.eq(0).all())

    def test_final_test_entry_cannot_borrow_next_test_open(self):
        def generator(frame):
            return event_strategy(frame, events={len(frame) - 1: "LONG_ENTRY"})
        result = self.run_evaluation(generator=generator)
        for window in result["windows"]:
            test = window["test"]
            self.assertTrue(test["trades"].empty)
            self.assertTrue(test["execution"].iloc[-1][["execution_time", "execution_price"]].isna().all())
            self.assertTrue(test["execution"].executed_position.eq(0).all())

    def test_final_test_exit_remains_open_without_terminal_liquidation(self):
        def generator(frame):
            return event_strategy(frame, events={0: "LONG_ENTRY", len(frame) - 1: "LONG_EXIT"})
        result = self.run_evaluation(generator=generator, fee_rate=0.001, slippage_rate=0.0005)
        for window in result["windows"]:
            test = window["test"]
            self.assertEqual(test["trades"].status.tolist(), ["OPEN"])
            self.assertTrue(test["trades"][["exit_time", "exit_price"]].isna().all().all())
            self.assertEqual(test["strategy_output"].desired_position.iloc[-1], 0)
            self.assertEqual(test["execution"].executed_position.iloc[0], 0)
            self.assertEqual(test["execution"].executed_position.iloc[-1], 1)
            self.assertTrue(test["net_results"][["exit_fee", "net_pnl", "net_capital_after"]].isna().all().all())
            self.assertEqual(test["net_equity"].position.iloc[-1], 1)

    def test_future_prices_cannot_change_earlier_train_or_test(self):
        source = candles([90, 100, 115, 130, 125, 120] * 4)
        baseline = self.run_evaluation(source=source)
        changed = source.copy(deep=True)
        changed.loc[changed.index[12:], ["open", "close"]] *= 5
        actual = self.run_evaluation(source=changed)
        for label in ("train", "test"):
            assert_segment_equal(self, actual["windows"][0][label], baseline["windows"][0][label])
        self.assertFalse(actual["windows"][1]["test"]["strategy_output"].equals(
            baseline["windows"][1]["test"]["strategy_output"],
        ))

    def test_previous_prices_cannot_change_later_cold_start_test(self):
        baseline = self.run_evaluation()
        changed = self.source.copy(deep=True)
        changed.loc[changed.index[:12], ["open", "close"]] *= 5
        actual = self.run_evaluation(source=changed)
        assert_segment_equal(self, actual["windows"][1]["test"], baseline["windows"][1]["test"])

    def test_unused_tail_is_reported_and_never_evaluated(self):
        source = self.source.iloc[:12].copy()
        result = self.run_evaluation(source=source, initial_train_rows=5, test_rows=3)
        self.assertEqual(len(result["windows"]), 2)
        self.assertEqual(result["unused_tail_rows"], 1)
        self.assertEqual(result["window_definitions"].test_end_index.iloc[-1], 11)
        changed = source.copy()
        changed.loc[11, ["open", "close"]] = 999_999.0
        repeated = self.run_evaluation(source=changed, initial_train_rows=5, test_rows=3)
        assert_walk_forward_equal(self, repeated, result)

    def test_none_kwargs_means_empty_settings_for_every_segment(self):
        seen = []
        def generator(frame, **kwargs):
            seen.append(kwargs)
            return event_strategy(frame)
        self.run_evaluation(generator=generator)
        self.assertEqual(seen, [{}, {}, {}, {}])

    def test_mutable_kwargs_and_source_isolated_for_every_evaluation(self):
        supplied = {"events": {0: "LONG_ENTRY", 2: "LONG_EXIT"}, "notes": ["original"]}
        before, source_before = deepcopy(supplied), self.source.copy(deep=True)
        seen = []
        def generator(frame, *, events, notes):
            seen.append(deepcopy((events, notes)))
            result = event_strategy(frame, events=events)
            events.clear()
            notes.append("changed")
            frame["open"] = 9999.0
            frame["close"] = 8888.0
            return result
        self.run_evaluation(generator=generator, strategy_kwargs=MappingProxyType(supplied))
        self.assertEqual(seen, [(before["events"], before["notes"])] * 4)
        self.assertEqual(supplied, before)
        pd.testing.assert_frame_equal(self.source, source_before, check_exact=True)

    def test_invalid_generator_and_kwargs_rejected(self):
        for generator in (None, 1, "EMA"):
            with self.subTest(generator=generator), self.assertRaisesRegex(ValueError, "callable"):
                self.run_evaluation(generator=generator)
        for kwargs in ([], "tag", 1, {1: "value"}):
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValueError, "strategy_kwargs"):
                self.run_evaluation(strategy_kwargs=kwargs)

    def test_strategy_exception_propagates_and_preserves_inputs(self):
        source_before = self.source.copy(deep=True)
        kwargs = {"notes": ["original"]}
        error = RuntimeError("strategy failed")
        def generator(frame, *, notes):
            frame["close"] = -999
            notes.append("changed")
            raise error
        with self.assertRaises(RuntimeError) as caught:
            self.run_evaluation(generator=generator, strategy_kwargs=kwargs)
        self.assertIs(caught.exception, error)
        pd.testing.assert_frame_equal(self.source, source_before, check_exact=True)
        self.assertEqual(kwargs, {"notes": ["original"]})

    def test_segment_error_stops_without_returning_partial_windows(self):
        initial = evaluate_strategy_segment(self.source.iloc[:6], event_strategy, candle_interval=HOUR)
        error = RuntimeError("second segment failed")
        with patch.object(walk_forward, "evaluate_strategy_segment", side_effect=[initial, error]) as core:
            with self.assertRaises(RuntimeError) as caught:
                self.run_evaluation()
            self.assertEqual(core.call_count, 2)
        self.assertIs(caught.exception, error)

    def test_pipeline_and_equity_errors_propagate(self):
        for name in ("run_backtest_pipeline", "calculate_gross_mark_to_market_equity",
                     "calculate_net_mark_to_market_equity"):
            error = RuntimeError(name + " failed")
            with self.subTest(helper=name), patch.object(evaluation, name, side_effect=error) as helper:
                with self.assertRaises(RuntimeError) as caught:
                    self.run_evaluation()
                self.assertIs(caught.exception, error)
                self.assertEqual(helper.call_count, 1)

    def test_financial_and_interval_validation_stays_with_segment_evaluator(self):
        for settings in ({"initial_capital": 0}, {"fee_rate": True}, {"slippage_rate": np.nan},
                         {"position_fraction": 1.1}, {"candle_interval": 2 * HOUR}):
            with self.subTest(settings=settings), self.assertRaises(ValueError):
                self.run_evaluation(**settings)

    def test_no_sensitivity_stability_selection_summary_or_stitched_equity(self):
        forbidden_calls = (
            "trading_lab.robustness.evaluate_parameter_sensitivity",
            "trading_lab.robustness.sensitivity.evaluate_parameter_sensitivity",
            "trading_lab.robustness.analyze_parameter_stability",
            "trading_lab.robustness.stability.analyze_parameter_stability",
        )
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(path, side_effect=AssertionError("Unexpected grid analysis")))
                     for path in forbidden_calls]
            result = self.run_evaluation()
            for mock in mocks:
                mock.assert_not_called()
        forbidden_keys = {
            "equity", "walk_forward_equity", "stitched_equity", "continuous_equity", "combined_equity",
            "selected_parameters", "best_parameters", "rank", "score", "training_winner", "summary",
        }
        self.assertTrue(forbidden_keys.isdisjoint(result))
        for window in result["windows"]:
            self.assertTrue(forbidden_keys.isdisjoint(window))

    def test_source_and_kwargs_preserved_and_repeated_calls_exact(self):
        before = self.source.copy(deep=True)
        kwargs = {"tag": "unchanged"}
        first = self.run_evaluation(strategy_kwargs=kwargs)
        second = self.run_evaluation(strategy_kwargs=kwargs)
        assert_walk_forward_equal(self, first, second)
        pd.testing.assert_frame_equal(self.source, before, check_exact=True)
        self.assertEqual(kwargs, {"tag": "unchanged"})

    def test_nested_outputs_are_independent_across_segments_and_source(self):
        result = self.run_evaluation()
        all_frames = [frame for window in result["windows"] for label in ("train", "test")
                      for frame in window[label].values()]
        self.assertEqual(len({id(frame) for frame in all_frames}), 28)
        before = deepcopy(result)
        source_before = self.source.copy(deep=True)
        result["windows"][0]["train"]["gross_equity"].loc[0, "equity"] = -999
        for window_number, window in enumerate(result["windows"]):
            for label in ("train", "test"):
                if window_number == 0 and label == "train":
                    continue
                assert_segment_equal(self, window[label], before["windows"][window_number][label])
        pd.testing.assert_frame_equal(self.source, source_before, check_exact=True)

    def test_single_candle_train_and_test_keep_normal_segment_behavior(self):
        result = self.run_evaluation(source=candles([100, 101]), generator=generate_ema_signals,
                                     initial_train_rows=1, test_rows=1)
        self.assertEqual(result["unused_tail_rows"], 0)
        self.assertEqual(len(result["windows"]), 1)
        for label in ("train", "test"):
            segment = result["windows"][0][label]
            self.assertEqual(segment["strategy_output"].signal.tolist(), ["HOLD"])
            self.assertTrue(segment["trades"].empty)
            self.assertEqual(segment["net_equity"].equity.tolist(), [10_000, 10_000])


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class BTCExpandingWalkForwardIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_hash = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash != FROZEN_SHA256:
            raise AssertionError("Frozen BTC snapshot hash mismatch: " + cls.raw_hash)
        cls.source = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        cls.before = cls.source.copy(deep=True)
        cls.parameters = dict(
            candle_interval=HOUR, initial_train_rows=4380, test_rows=1460,
            strategy_kwargs=deepcopy(EMA_KWARGS), initial_capital=INITIAL_CAPITAL,
            fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE, position_fraction=1.0,
        )
        with patch.object(walk_forward, "evaluate_strategy_segment", wraps=evaluate_strategy_segment) as core:
            cls.result = evaluate_expanding_walk_forward(cls.source, generate_ema_signals, **cls.parameters)
        cls.calls = core.call_args_list

    def test_canonical_three_windows_exact_rows_boundaries_and_timestamps(self):
        self.assertEqual(len(self.source), 8760)
        self.assertEqual(len(self.result["windows"]), 3)
        self.assertEqual(self.result["unused_tail_rows"], 0)
        expected = pd.DataFrame([
            [1, 0, 4380, 4380, 5840, 4380, 1460, "2025-10-01 00:00", "2026-04-01 11:00", "2026-04-01 12:00", "2026-06-01 07:00"],
            [2, 0, 5840, 5840, 7300, 5840, 1460, "2025-10-01 00:00", "2026-06-01 07:00", "2026-06-01 08:00", "2026-08-01 03:00"],
            [3, 0, 7300, 7300, 8760, 7300, 1460, "2025-10-01 00:00", "2026-08-01 03:00", "2026-08-01 04:00", "2026-09-30 23:00"],
        ], columns=WINDOW_COLUMNS)
        for column in WINDOW_COLUMNS[7:]:
            expected[column] = pd.to_datetime(expected[column], utc=True)
        pd.testing.assert_frame_equal(self.result["window_definitions"], expected, check_exact=True)

    def test_every_ema_segment_initializes_on_itself_and_has_own_warmup(self):
        for window, definition in zip(self.result["windows"], self.result["window_definitions"].itertuples(index=False)):
            for label, start, end in (("train", 0, definition.train_end_index),
                                      ("test", definition.test_start_index, definition.test_end_index)):
                with self.subTest(window=window["window_id"], label=label):
                    segment = window[label]
                    strategy = segment["strategy_output"]
                    self.assertEqual(len(strategy), end - start)
                    pd.testing.assert_index_equal(strategy.index, self.source.iloc[start:end].index, exact=True)
                    self.assertEqual(strategy.ema_20.iloc[0], self.source.close.iloc[start])
                    self.assertEqual(strategy.ema_50.iloc[0], self.source.close.iloc[start])
                    self.assertTrue(strategy.signal.iloc[:50].eq("HOLD").all())
                    self.assertTrue(strategy.desired_position.iloc[:50].eq(0).all())
                    self.assertTrue(segment["execution"].executed_position.iloc[:50].eq(0).all())
                    self.assertTrue(segment["trades"].entry_time.ge(self.source.timestamp.iloc[start]).all())
                    for key in ("gross_equity", "net_equity"):
                        self.assertEqual(segment[key].equity.iloc[0], INITIAL_CAPITAL)
                        self.assertTrue(segment[key].position.iloc[:51].eq(0).all())

    def test_every_btc_run_receives_fixed_20_50_and_financial_assumptions(self):
        self.assertEqual(len(self.calls), 6)
        expected_kwargs = {key: value for key, value in self.parameters.items()
                           if key not in ("initial_train_rows", "test_rows")}
        expected_sizes = [4380, 1460, 5840, 1460, 7300, 1460]
        for call, size in zip(self.calls, expected_sizes):
            self.assertIs(call.args[1], generate_ema_signals)
            self.assertEqual(len(call.args[0]), size)
            self.assertEqual(call.kwargs, expected_kwargs)
        self.assertEqual(len({id(call.kwargs["strategy_kwargs"]) for call in self.calls}), 6)

    def test_btc_source_settings_and_local_snapshot_preserved(self):
        pd.testing.assert_frame_equal(self.source, self.before, check_exact=True)
        self.assertEqual(self.parameters["strategy_kwargs"], EMA_KWARGS)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash)
