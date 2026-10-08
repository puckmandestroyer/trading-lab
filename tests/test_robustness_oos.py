"""Chronological split, cold-start isolation, and existing-engine composition."""

from fractions import Fraction
import hashlib
from types import MappingProxyType
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.backtest.pipeline import run_backtest_pipeline
from trading_lab.data.market_data import load_ohlcv_csv
from trading_lab.robustness import (
    chronological_split,
    evaluate_strategy_segment,
    evaluate_train_test_split,
)
from trading_lab.robustness import evaluation
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_ema_generic_regression import (
    END, FEE_RATE, FROZEN_SHA256, HOUR, INITIAL_CAPITAL, RAW_BTC,
    SLIPPAGE_RATE, START,
)


SEGMENT_KEYS = [
    "strategy_output", "execution", "trades", "gross_results", "net_results",
    "gross_equity", "net_equity",
]
SPLIT_KEYS = ["split_index", "split_timestamp", "in_sample", "out_of_sample"]
EMA_KWARGS = dict(fast_span=20, slow_span=50, warmup_candles=50)
SYNTHETIC_START = pd.Timestamp("2025-01-01", tz="UTC")


def candles(prices=(90, 100, 105, 110, 100, 105)):
    values = np.asarray(prices, dtype="float64")
    return pd.DataFrame({
        "timestamp": pd.date_range(SYNTHETIC_START, periods=len(values), freq="h"),
        "open": values.copy(),
        "close": values.copy(),
    })


def event_strategy(segment, *, events=None, tag="research"):
    """A non-EMA producer with explicit segment-local event rows."""
    events = {0: "LONG_ENTRY", 2: "LONG_EXIT"} if events is None else events
    state, signals, positions = 0, [], []
    for row in range(len(segment)):
        signal = events.get(row, "HOLD")
        if signal == "LONG_ENTRY":
            state = 1
        elif signal == "LONG_EXIT":
            state = 0
        signals.append(signal)
        positions.append(state)
    return pd.DataFrame({
        "timestamp": segment.timestamp.copy(),
        "signal_time": segment.timestamp + HOUR,
        "signal": pd.Series(signals, index=segment.index, dtype="object"),
        "desired_position": pd.Series(positions, index=segment.index, dtype="int64"),
        "close": segment.close.copy(),
        "tag": pd.Series([tag] * len(segment), index=segment.index, dtype="object"),
    })


def direct_segment(segment, generator, *, strategy_kwargs=None,
                   initial_capital=10_000.0, fee_rate=0.0, slippage_rate=0.0,
                   position_fraction=1.0, candle_interval=HOUR):
    """Independent expected composition through existing public helpers."""
    strategy = generator(segment.copy(deep=True), **(strategy_kwargs or {}))
    pipeline = run_backtest_pipeline(
        segment, strategy, initial_capital=initial_capital, fee_rate=fee_rate,
        slippage_rate=slippage_rate, position_fraction=position_fraction,
    )
    return dict(
        strategy_output=strategy,
        **pipeline,
        gross_equity=calculate_gross_mark_to_market_equity(
            segment, pipeline["gross_results"], candle_interval, initial_capital,
        ),
        net_equity=calculate_net_mark_to_market_equity(
            segment, pipeline["net_results"], candle_interval, initial_capital,
        ),
    )


def assert_segment_equal(test, actual, expected):
    test.assertEqual(list(actual), SEGMENT_KEYS)
    for key in SEGMENT_KEYS:
        with test.subTest(frame=key):
            pd.testing.assert_frame_equal(actual[key], expected[key], check_exact=True)


def ema_windows():
    # Each half has an eligible reversal after its own 50-candle warm-up.
    prices = np.concatenate((np.linspace(140, 90, 60), np.linspace(90, 160, 30)))
    return candles(np.tile(prices, 2))


class ChronologicalSplitTests(unittest.TestCase):
    def test_default_split_is_70_30_with_no_overlap_or_gap(self):
        source = candles(range(100, 110))
        before = source.copy(deep=True)
        training, testing = chronological_split(source)
        self.assertEqual((len(training), len(testing)), (7, 3))
        self.assertEqual(training.timestamp.iloc[-1] + HOUR, testing.timestamp.iloc[0])
        self.assertTrue(set(training.timestamp).isdisjoint(testing.timestamp))
        pd.testing.assert_frame_equal(pd.concat([training, testing]), before, check_exact=True)
        pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_custom_fraction_floors_the_row_count(self):
        source = candles(range(100, 109))
        training, testing = chronological_split(source, 0.5)
        self.assertEqual((len(training), len(testing)), (4, 5))
        pd.testing.assert_frame_equal(training, source.iloc[:4], check_exact=True)
        pd.testing.assert_frame_equal(testing, source.iloc[4:], check_exact=True)

    def test_split_is_row_based_not_weighted_by_time_or_prices(self):
        source = candles([1, 2, 3, 5000, 9000, 1])
        source["timestamp"] = pd.DatetimeIndex([
            SYNTHETIC_START + hour * HOUR for hour in (0, 1, 2, 100, 101, 102)
        ])
        training, testing = chronological_split(source, 0.5)
        self.assertEqual((len(training), len(testing)), (3, 3))
        self.assertEqual(testing.timestamp.iloc[0], SYNTHETIC_START + 100 * HOUR)

    def test_columns_dtypes_timezone_and_non_range_index_are_preserved(self):
        source = candles()
        source.index = pd.Index([30, 2, 70, 1, 9, 12], name="candle_id")
        source["context"] = pd.Categorical(["a", "b"] * 3)
        source["volume"] = pd.array([1, None, 3, 4, 5, 6], dtype="Int64")
        source = source[["context", "close", "timestamp", "volume", "open"]]
        training, testing = chronological_split(source, 0.5)
        for result, expected in ((training, source.iloc[:3]), (testing, source.iloc[3:])):
            pd.testing.assert_frame_equal(result, expected, check_exact=True)
            self.assertEqual(result.timestamp.dtype, source.timestamp.dtype)

    def test_duplicate_index_labels_do_not_replace_timestamp_order(self):
        source = candles()
        source.index = pd.Index([4, 4, 2, 2, 1, 1], name="label")
        training, testing = chronological_split(source, 0.5)
        pd.testing.assert_index_equal(training.index, source.index[:3], exact=True)
        pd.testing.assert_index_equal(testing.index, source.index[3:], exact=True)

    def test_outputs_are_independent_copies(self):
        source = candles()
        before = source.copy(deep=True)
        training, testing = chronological_split(source, 0.5)
        testing_before = testing.copy(deep=True)
        self.assertIsNot(training, source)
        self.assertIsNot(testing, source)
        self.assertIsNot(training, testing)
        training.iloc[0, training.columns.get_loc("close")] = -999
        pd.testing.assert_frame_equal(testing, testing_before, check_exact=True)
        testing.iloc[0, testing.columns.get_loc("open")] = -888
        self.assertEqual(training.close.iloc[0], -999)
        pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_numpy_and_exact_real_fractions_work(self):
        for fraction in (np.float64(0.5), np.float32(0.5), Fraction(1, 2)):
            with self.subTest(fraction=fraction):
                self.assertEqual(tuple(map(len, chronological_split(candles(), fraction))), (3, 3))

    def test_invalid_fractions_are_rejected_without_mutation(self):
        source = candles()
        before = source.copy(deep=True)
        invalid = (
            0, 1, -0.1, 1.1, True, False, np.bool_(True), np.bool_(False),
            np.nan, np.inf, -np.inf, "0.7", None, 0.7 + 0j, [0.7],
            np.array(0.7), np.array([0.7]), pd.Series([0.7]), {"fraction": 0.7},
            Fraction(10**400, 1),
        )
        for fraction in invalid:
            with self.subTest(fraction=repr(fraction)):
                with self.assertRaisesRegex(ValueError, "train_fraction"):
                    chronological_split(source, fraction)
                pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_non_dataframe_inputs_are_rejected(self):
        for value in (None, [], {}, "candles", pd.Series([1, 2])):
            with self.subTest(value=repr(value)):
                with self.assertRaisesRegex(ValueError, "DataFrame"):
                    chronological_split(value)

    def test_missing_timestamp_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timestamp"):
            chronological_split(candles().drop(columns="timestamp"))

    def test_non_datetime_timestamps_are_not_parsed(self):
        for values in (["2025-01-01", "2025-01-02"], [0, 1]):
            with self.subTest(values=values):
                with self.assertRaisesRegex(ValueError, "datetime"):
                    chronological_split(pd.DataFrame({"timestamp": values}))

    def test_duplicate_columns_are_rejected(self):
        source = candles()
        with self.assertRaisesRegex(ValueError, "column names"):
            chronological_split(pd.concat([source, source[["timestamp"]]], axis=1))

    def test_duplicate_timestamps_are_rejected(self):
        source = candles()
        source.loc[1, "timestamp"] = source.timestamp.iloc[0]
        with self.assertRaisesRegex(ValueError, "unique"):
            chronological_split(source)

    def test_missing_timestamps_are_rejected(self):
        source = candles()
        source.loc[1, "timestamp"] = pd.NaT
        with self.assertRaisesRegex(ValueError, "missing"):
            chronological_split(source)

    def test_non_monotonic_timestamps_are_not_sorted(self):
        for source in (candles().iloc[::-1], candles().iloc[[0, 2, 1, 3, 4, 5]]):
            with self.subTest(index=source.index.tolist()):
                before = source.copy(deep=True)
                with self.assertRaisesRegex(ValueError, "increasing"):
                    chronological_split(source)
                pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_fewer_than_two_rows_are_rejected(self):
        for source in (candles([]), candles([100])):
            with self.subTest(rows=len(source)):
                with self.assertRaisesRegex(ValueError, "at least two"):
                    chronological_split(source)

    def test_valid_fraction_producing_an_empty_side_is_rejected(self):
        # Exact positive/below-one values can round to float endpoints.
        for fraction in (0.1, Fraction(1, 10**400), Fraction(10**400 - 1, 10**400)):
            with self.subTest(fraction=repr(fraction)):
                with self.assertRaisesRegex(ValueError, "non-empty"):
                    chronological_split(candles([100, 101]), fraction)

    def test_two_rows_and_naive_datetime_clock_remain_valid(self):
        source = candles([100, 101])
        source["timestamp"] = source.timestamp.dt.tz_localize(None)
        training, testing = chronological_split(source, 0.5)
        self.assertEqual((len(training), len(testing)), (1, 1))
        self.assertEqual(testing.timestamp.dtype, source.timestamp.dtype)


class StrategySegmentEvaluationTests(unittest.TestCase):
    def test_exact_return_keys_and_package_exports(self):
        import trading_lab.robustness as robustness
        result = evaluate_strategy_segment(candles(), event_strategy, candle_interval=HOUR)
        self.assertEqual(list(result), SEGMENT_KEYS)
        self.assertEqual(robustness.__all__, [
            "chronological_split", "evaluate_strategy_segment", "evaluate_train_test_split",
        ])
        self.assertIs(robustness.evaluate_strategy_segment, evaluation.evaluate_strategy_segment)

    def test_simple_non_ema_generator_works_with_existing_schemas(self):
        result = evaluate_strategy_segment(candles(), event_strategy, candle_interval=HOUR)
        self.assertEqual(result["trades"].status.tolist(), ["CLOSED"])
        self.assertEqual(result["trades"].entry_price.iloc[0], 100)
        self.assertEqual(result["trades"].exit_price.iloc[0], 110)
        self.assertEqual(len(result["gross_equity"]), 7)
        self.assertEqual(len(result["net_equity"].columns), 11)

    def test_public_ema_generator_has_normal_in_segment_warmup(self):
        segment = ema_windows().iloc[:90]
        result = evaluate_strategy_segment(segment, generate_ema_signals, candle_interval=HOUR)
        warmup = result["strategy_output"].iloc[:50]
        self.assertTrue(warmup.signal.eq("HOLD").all())
        self.assertTrue(warmup.desired_position.eq(0).all())
        self.assertTrue(result["gross_equity"].position.iloc[:51].eq(0).all())
        self.assertGreater(len(result["trades"]), 0)

    def test_exact_direct_composition_parity_with_costs_and_partial_sizing(self):
        segment = candles()
        segment.index = pd.Index([8, 3, 7, 1, 6, 2], name="row")
        parameters = dict(
            candle_interval=HOUR, initial_capital=3210.0, fee_rate=0.001,
            slippage_rate=0.0005, position_fraction=0.37,
            strategy_kwargs={"events": {1: "LONG_ENTRY", 3: "LONG_EXIT"}, "tag": "custom"},
        )
        actual = evaluate_strategy_segment(segment, event_strategy, **parameters)
        expected = direct_segment(segment, event_strategy, **parameters)
        assert_segment_equal(self, actual, expected)

    def test_generator_receives_only_an_independent_segment_copy(self):
        source = candles(range(100, 120))
        segment = source.iloc[7:13]
        seen = []
        def generator(frame):
            seen.append(frame)
            return event_strategy(frame)
        evaluate_strategy_segment(segment, generator, candle_interval=HOUR)
        self.assertEqual(len(seen), 1)
        self.assertIsNot(seen[0], segment)
        self.assertEqual(len(seen[0]), 6)
        pd.testing.assert_frame_equal(seen[0], segment, check_exact=True)

    def test_kwargs_mapping_is_forwarded_without_mutation(self):
        supplied = {"events": {}, "tag": "unchanged"}
        mapping = MappingProxyType(supplied)
        seen = []
        def generator(frame, **kwargs):
            seen.append(kwargs.copy())
            result = event_strategy(frame, **kwargs)
            kwargs.clear()
            return result
        result = evaluate_strategy_segment(
            candles(), generator, candle_interval=HOUR, strategy_kwargs=mapping,
        )
        self.assertEqual(seen, [supplied])
        self.assertEqual(supplied, {"events": {}, "tag": "unchanged"})
        self.assertTrue(result["strategy_output"].tag.eq("unchanged").all())

    def test_none_kwargs_means_no_keyword_arguments(self):
        seen = []
        def generator(frame, **kwargs):
            seen.append(kwargs)
            return event_strategy(frame)
        evaluate_strategy_segment(candles(), generator, candle_interval=HOUR)
        self.assertEqual(seen, [{}])

    def test_invalid_generator_is_rejected(self):
        for generator in (None, 1, "EMA", []):
            with self.subTest(generator=repr(generator)):
                with self.assertRaisesRegex(ValueError, "callable"):
                    evaluate_strategy_segment(candles(), generator, candle_interval=HOUR)

    def test_invalid_kwargs_mapping_or_keyword_names_are_rejected(self):
        for kwargs in ([], [("tag", "x")], "tag", 1, {1: "bad"}):
            with self.subTest(kwargs=repr(kwargs)):
                with self.assertRaisesRegex(ValueError, "strategy_kwargs"):
                    evaluate_strategy_segment(
                        candles(), event_strategy, candle_interval=HOUR, strategy_kwargs=kwargs,
                    )

    def test_mutating_generator_cannot_change_source_or_market_fill_prices(self):
        source = candles()
        before = source.copy(deep=True)
        def generator(frame):
            frame["open"] = 9999.0
            frame["close"] = 8888.0
            return event_strategy(frame)
        result = evaluate_strategy_segment(source, generator, candle_interval=HOUR)
        pd.testing.assert_frame_equal(source, before, check_exact=True)
        self.assertEqual(result["trades"].entry_price.iloc[0], 100)
        self.assertEqual(result["gross_equity"].mark_price.iloc[1], 90)

    def test_generator_exception_propagates_and_preserves_source(self):
        source = candles()
        before = source.copy(deep=True)
        error = RuntimeError("research failure")
        def generator(frame):
            frame["close"] = -999
            raise error
        with patch.object(evaluation, "run_backtest_pipeline") as pipeline:
            with self.assertRaises(RuntimeError) as caught:
                evaluate_strategy_segment(source, generator, candle_interval=HOUR)
            pipeline.assert_not_called()
        self.assertIs(caught.exception, error)
        pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_financial_arguments_and_interval_are_forwarded_unchanged(self):
        source = candles()
        capital, fee, slippage, fraction = 3210.0, 0.001, 0.0005, np.float64(0.37)
        with patch.object(evaluation, "run_backtest_pipeline", wraps=run_backtest_pipeline) as pipeline, \
             patch.object(evaluation, "calculate_gross_mark_to_market_equity", wraps=calculate_gross_mark_to_market_equity) as gross, \
             patch.object(evaluation, "calculate_net_mark_to_market_equity", wraps=calculate_net_mark_to_market_equity) as net:
            result = evaluate_strategy_segment(
                source, event_strategy, candle_interval=HOUR, initial_capital=capital,
                fee_rate=fee, slippage_rate=slippage, position_fraction=fraction,
            )
        self.assertEqual(pipeline.call_count, 1)
        self.assertIs(pipeline.call_args.args[0], source)
        self.assertEqual(pipeline.call_args.kwargs, dict(
            initial_capital=capital, fee_rate=fee, slippage_rate=slippage,
            position_fraction=fraction,
        ))
        self.assertIs(pipeline.call_args.kwargs["position_fraction"], fraction)
        gross.assert_called_once_with(source, result["gross_results"], HOUR, capital)
        net.assert_called_once_with(source, result["net_results"], HOUR, capital)

    def test_lower_financial_validation_propagates_without_rewriting(self):
        source = candles()
        before = source.copy(deep=True)
        for parameters in (
            {"initial_capital": 0}, {"fee_rate": True},
            {"slippage_rate": np.nan}, {"position_fraction": 1.1},
        ):
            with self.subTest(parameters=parameters):
                with self.assertRaises(ValueError) as direct_error:
                    run_backtest_pipeline(source, event_strategy(source), **parameters)
                with self.assertRaises(ValueError) as actual_error:
                    evaluate_strategy_segment(source, event_strategy, candle_interval=HOUR, **parameters)
                self.assertEqual(str(actual_error.exception), str(direct_error.exception))
                pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_malformed_strategy_output_is_not_repaired(self):
        source = candles()
        for malformed in (
            event_strategy(source).iloc[::-1], event_strategy(source).iloc[:-1],
            event_strategy(source).drop(columns="desired_position"),
        ):
            with self.subTest(rows=len(malformed), columns=list(malformed)):
                with self.assertRaises(ValueError):
                    evaluate_strategy_segment(source, lambda frame: malformed, candle_interval=HOUR)

    def test_equity_interval_validation_is_delegated(self):
        for interval in (2 * HOUR, 0, pd.Timedelta(0)):
            with self.subTest(interval=interval):
                with self.assertRaisesRegex(ValueError, "candle_interval"):
                    evaluate_strategy_segment(candles(), event_strategy, candle_interval=interval)

    def test_pipeline_exception_propagates_before_equity(self):
        error = RuntimeError("pipeline failure")
        with patch.object(evaluation, "run_backtest_pipeline", side_effect=error), \
             patch.object(evaluation, "calculate_gross_mark_to_market_equity") as gross:
            with self.assertRaises(RuntimeError) as caught:
                evaluate_strategy_segment(candles(), event_strategy, candle_interval=HOUR)
            gross.assert_not_called()
        self.assertIs(caught.exception, error)

    def test_equity_exception_propagates_without_partial_result(self):
        error = RuntimeError("equity failure")
        with patch.object(evaluation, "calculate_gross_mark_to_market_equity", side_effect=error), \
             patch.object(evaluation, "calculate_net_mark_to_market_equity") as net:
            with self.assertRaises(RuntimeError) as caught:
                evaluate_strategy_segment(candles(), event_strategy, candle_interval=HOUR)
            net.assert_not_called()
        self.assertIs(caught.exception, error)

    def test_final_entry_remains_unfilled_without_a_trade(self):
        result = evaluate_strategy_segment(
            candles([100, 110]), event_strategy, candle_interval=HOUR,
            strategy_kwargs={"events": {1: "LONG_ENTRY"}},
        )
        self.assertTrue(result["execution"].iloc[-1][["execution_time", "execution_price"]].isna().all())
        self.assertTrue(result["trades"].empty)
        self.assertTrue(result["execution"].executed_position.eq(0).all())
        self.assertTrue(result["gross_equity"].equity.eq(10_000).all())

    def test_final_exit_leaves_open_accounting_and_a_marked_position(self):
        result = evaluate_strategy_segment(
            candles([90, 100, 110]), event_strategy, candle_interval=HOUR,
            fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.5,
        )
        self.assertEqual(result["strategy_output"].desired_position.iloc[-1], 0)
        self.assertEqual(result["execution"].executed_position.iloc[-1], 1)
        self.assertTrue(result["execution"].iloc[-1][["execution_time", "execution_price"]].isna().all())
        self.assertEqual(result["trades"].status.tolist(), ["OPEN"])
        self.assertTrue(result["gross_results"][["exit_time", "exit_price", "capital_after"]].isna().all().all())
        self.assertTrue(result["net_results"][["exit_time", "exit_fee", "net_pnl", "net_capital_after"]].isna().all().all())
        self.assertEqual(result["gross_equity"].position.iloc[-1], 1)
        self.assertEqual(result["net_equity"].position.iloc[-1], 1)
        self.assertEqual(result["net_equity"].quantity.iloc[-1], result["net_results"].quantity.iloc[0])

    def test_open_end_without_exit_signal_is_marked_not_liquidated(self):
        result = evaluate_strategy_segment(
            candles(), event_strategy, candle_interval=HOUR,
            strategy_kwargs={"events": {0: "LONG_ENTRY"}},
        )
        self.assertEqual(result["trades"].status.tolist(), ["OPEN"])
        self.assertTrue(result["trades"][["exit_time", "exit_price"]].isna().all().all())
        self.assertEqual(result["gross_equity"].position.iloc[-1], 1)

    def test_returned_frames_are_independent_of_source_and_each_other(self):
        source = candles()
        source_before = source.copy(deep=True)
        result = evaluate_strategy_segment(source, event_strategy, candle_interval=HOUR)
        self.assertEqual(len({id(frame) for frame in result.values()}), 7)
        before = {key: frame.copy(deep=True) for key, frame in result.items()}
        for key, column in (
            ("strategy_output", "close"), ("execution", "open"), ("trades", "entry_price"),
            ("gross_results", "entry_price"), ("net_results", "entry_price"),
            ("gross_equity", "equity"), ("net_equity", "equity"),
        ):
            with self.subTest(frame=key):
                result[key].iloc[0, result[key].columns.get_loc(column)] = -999
                for other in SEGMENT_KEYS:
                    if other != key:
                        pd.testing.assert_frame_equal(result[other], before[other], check_exact=True)
                result[key] = before[key].copy(deep=True)
                pd.testing.assert_frame_equal(source, source_before, check_exact=True)

    def test_strategy_output_returning_source_itself_is_detached(self):
        source = candles()
        for column, values in event_strategy(source).items():
            source[column] = values
        before = source.copy(deep=True)
        result = evaluate_strategy_segment(source, lambda frame: source, candle_interval=HOUR)
        self.assertIsNot(result["strategy_output"], source)
        result["strategy_output"].loc[0, "close"] = -999
        pd.testing.assert_frame_equal(source, before, check_exact=True)

    def test_single_candle_ema_segment_keeps_initial_cash_and_warmup(self):
        result = evaluate_strategy_segment(candles([100]), generate_ema_signals, candle_interval=HOUR)
        self.assertEqual(result["strategy_output"].signal.tolist(), ["HOLD"])
        self.assertTrue(result["trades"].empty)
        self.assertEqual(result["net_equity"].equity.tolist(), [10_000, 10_000])


class TrainTestEvaluationTests(unittest.TestCase):
    def setUp(self):
        self.source = candles([90, 100, 115, 130, 125, 120, 180, 200, 220, 240, 235, 230])

    def test_exact_keys_boundary_metadata_and_segment_parity(self):
        actual = evaluate_train_test_split(self.source, event_strategy, candle_interval=HOUR, train_fraction=0.5)
        self.assertEqual(list(actual), SPLIT_KEYS)
        self.assertEqual(actual["split_index"], 6)
        self.assertEqual(actual["split_timestamp"], self.source.timestamp.iloc[6])
        for key, segment in zip(("in_sample", "out_of_sample"), chronological_split(self.source, 0.5)):
            assert_segment_equal(self, actual[key], direct_segment(segment, event_strategy))

    def test_generator_is_called_twice_on_only_its_own_segment(self):
        seen = []
        def generator(frame):
            seen.append(frame.copy(deep=True))
            return event_strategy(frame)
        evaluate_train_test_split(self.source, generator, candle_interval=HOUR, train_fraction=0.5)
        self.assertEqual(len(seen), 2)
        pd.testing.assert_frame_equal(seen[0], self.source.iloc[:6], check_exact=True)
        pd.testing.assert_frame_equal(seen[1], self.source.iloc[6:], check_exact=True)

    def test_both_evaluations_receive_the_same_configured_assumptions(self):
        kwargs = MappingProxyType({"tag": "same"})
        parameters = dict(
            candle_interval=HOUR, strategy_kwargs=kwargs, initial_capital=3210.0,
            fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.5,
        )
        with patch.object(evaluation, "evaluate_strategy_segment", wraps=evaluate_strategy_segment) as segment:
            result = evaluate_train_test_split(self.source, event_strategy, train_fraction=0.5, **parameters)
        self.assertEqual(segment.call_count, 2)
        for call in segment.call_args_list:
            self.assertIs(call.args[1], event_strategy)
            self.assertEqual(call.kwargs, parameters)
            self.assertIs(call.kwargs["strategy_kwargs"], kwargs)
        for label in ("in_sample", "out_of_sample"):
            self.assertEqual(result[label]["gross_equity"].equity.iloc[0], 3210)
            self.assertEqual(result[label]["net_equity"].equity.iloc[0], 3210)

    def test_oos_uses_initial_capital_not_is_ending_capital(self):
        result = evaluate_train_test_split(self.source, event_strategy, candle_interval=HOUR, train_fraction=0.5)
        self.assertEqual(result["in_sample"]["gross_results"].capital_after.iloc[-1], 13_000)
        for key in ("gross_results", "net_results"):
            self.assertEqual(result["out_of_sample"][key].capital_before.iloc[0], 10_000)
            self.assertEqual(result["out_of_sample"][key].quantity.iloc[0], 50)

    def test_final_is_entry_cannot_use_the_first_oos_open(self):
        source = candles([100, 110, 9999, 200])
        def final_entry(frame):
            return event_strategy(frame, events={len(frame) - 1: "LONG_ENTRY"})
        result = evaluate_train_test_split(source, final_entry, candle_interval=HOUR, train_fraction=0.5)
        training, testing = result["in_sample"], result["out_of_sample"]
        self.assertTrue(training["execution"].iloc[-1][["execution_time", "execution_price"]].isna().all())
        self.assertTrue(training["trades"].empty)
        self.assertEqual(testing["execution"].executed_position.iloc[0], 0)
        self.assertTrue(testing["trades"].empty)
        self.assertTrue(training["net_equity"].equity.eq(10_000).all())

    def test_oos_does_not_inherit_is_desired_execution_or_open_trade_state(self):
        source = candles([110, 120, 130, 50, 60, 70])
        def enter_high_segment(frame):
            events = {0: "LONG_ENTRY"} if frame.close.iloc[0] > 100 else {}
            return event_strategy(frame, events=events)
        result = evaluate_train_test_split(source, enter_high_segment, candle_interval=HOUR, train_fraction=0.5)
        training, testing = result["in_sample"], result["out_of_sample"]
        self.assertEqual(training["strategy_output"].desired_position.iloc[-1], 1)
        self.assertEqual(training["execution"].executed_position.iloc[-1], 1)
        self.assertEqual(training["trades"].status.tolist(), ["OPEN"])
        self.assertTrue(testing["strategy_output"].desired_position.eq(0).all())
        self.assertTrue(testing["execution"].executed_position.eq(0).all())
        self.assertTrue(testing["trades"].empty)
        self.assertTrue(testing["net_equity"].equity.eq(10_000).all())

    def test_future_oos_prices_cannot_change_any_is_frame(self):
        source = ema_windows()
        parameters = dict(candle_interval=HOUR, train_fraction=0.5, strategy_kwargs=EMA_KWARGS,
                          fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.5)
        baseline = evaluate_train_test_split(source, generate_ema_signals, **parameters)
        changed = source.copy(deep=True)
        changed.loc[changed.index[90:], ["open", "close"]] *= 5
        actual = evaluate_train_test_split(changed, generate_ema_signals, **parameters)
        self.assertGreater(len(baseline["in_sample"]["trades"]), 0)
        assert_segment_equal(self, actual["in_sample"], baseline["in_sample"])

    def test_prior_is_prices_cannot_change_any_cold_start_oos_frame(self):
        source = ema_windows()
        parameters = dict(candle_interval=HOUR, train_fraction=0.5, strategy_kwargs=EMA_KWARGS,
                          fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.5)
        baseline = evaluate_train_test_split(source, generate_ema_signals, **parameters)
        changed = source.copy(deep=True)
        changed.loc[changed.index[:90], ["open", "close"]] = changed.iloc[:90][["open", "close"]].to_numpy()[::-1] * 3
        actual = evaluate_train_test_split(changed, generate_ema_signals, **parameters)
        assert_segment_equal(self, actual["out_of_sample"], baseline["out_of_sample"])
        self.assertEqual(actual["out_of_sample"]["strategy_output"].ema_20.iloc[0], source.close.iloc[90])

    def test_repeated_calls_are_deterministic_and_preserve_input(self):
        before = self.source.copy(deep=True)
        parameters = dict(candle_interval=HOUR, train_fraction=0.5, fee_rate=0.001,
                          slippage_rate=0.0005, position_fraction=0.5)
        first = evaluate_train_test_split(self.source, event_strategy, **parameters)
        second = evaluate_train_test_split(self.source, event_strategy, **parameters)
        for label in ("in_sample", "out_of_sample"):
            assert_segment_equal(self, first[label], second[label])
        pd.testing.assert_frame_equal(self.source, before, check_exact=True)

    def test_is_oos_result_objects_and_source_are_independent(self):
        before = self.source.copy(deep=True)
        result = evaluate_train_test_split(self.source, event_strategy, candle_interval=HOUR, train_fraction=0.5)
        all_frames = [frame for label in ("in_sample", "out_of_sample") for frame in result[label].values()]
        self.assertEqual(len({id(frame) for frame in all_frames}), 14)
        testing_before = {key: frame.copy(deep=True) for key, frame in result["out_of_sample"].items()}
        result["in_sample"]["gross_equity"].loc[0, "equity"] = -999
        assert_segment_equal(self, result["out_of_sample"], testing_before)
        pd.testing.assert_frame_equal(self.source, before, check_exact=True)

    def test_failed_oos_evaluation_propagates_instead_of_returning_partial_output(self):
        before = self.source.copy(deep=True)
        error = RuntimeError("OOS failed")
        def generator(frame):
            if frame.timestamp.iloc[0] == self.source.timestamp.iloc[6]:
                raise error
            return event_strategy(frame)
        with self.assertRaises(RuntimeError) as caught:
            evaluate_train_test_split(self.source, generator, candle_interval=HOUR, train_fraction=0.5)
        self.assertIs(caught.exception, error)
        pd.testing.assert_frame_equal(self.source, before, check_exact=True)


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class BTCRobustnessOOSIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_hash = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash != FROZEN_SHA256:
            raise AssertionError("Frozen BTC snapshot hash mismatch: " + cls.raw_hash)
        cls.source = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        cls.before = cls.source.copy(deep=True)
        cls.parameters = dict(
            candle_interval=HOUR, strategy_kwargs=EMA_KWARGS,
            initial_capital=INITIAL_CAPITAL, fee_rate=FEE_RATE,
            slippage_rate=SLIPPAGE_RATE, position_fraction=1.0,
        )
        cls.result = evaluate_train_test_split(cls.source, generate_ema_signals, **cls.parameters)

    def test_frozen_btc_default_split_counts_and_timestamp(self):
        self.assertEqual(len(self.source), 8760)
        self.assertEqual(self.result["split_index"], 6132)
        self.assertEqual(len(self.result["in_sample"]["strategy_output"]), 6132)
        self.assertEqual(len(self.result["out_of_sample"]["strategy_output"]), 2628)
        self.assertEqual(self.result["split_timestamp"], pd.Timestamp("2026-06-13 12:00", tz="UTC"))

    def test_btc_segment_schemas_and_values_match_direct_composition(self):
        for label, segment in zip(("in_sample", "out_of_sample"), chronological_split(self.source)):
            with self.subTest(segment=label):
                expected = direct_segment(segment, generate_ema_signals, **self.parameters)
                assert_segment_equal(self, self.result[label], expected)
                self.assertEqual(len(self.result[label]["gross_equity"]), len(segment) + 1)

    def test_btc_oos_ema_initialization_and_portfolio_state_are_fresh(self):
        testing = self.result["out_of_sample"]
        strategy = testing["strategy_output"]
        first_close = self.source.close.iloc[6132]
        self.assertEqual(strategy.ema_20.iloc[0], first_close)
        self.assertEqual(strategy.ema_50.iloc[0], first_close)
        self.assertTrue(strategy.signal.iloc[:50].eq("HOLD").all())
        self.assertTrue(strategy.desired_position.iloc[:50].eq(0).all())
        self.assertTrue(testing["execution"].executed_position.iloc[:50].eq(0).all())
        self.assertTrue(testing["trades"].entry_time.ge(self.result["split_timestamp"]).all())
        for label in ("in_sample", "out_of_sample"):
            for key in ("gross_equity", "net_equity"):
                self.assertEqual(self.result[label][key].equity.iloc[0], INITIAL_CAPITAL)
                self.assertTrue(self.result[label][key].position.iloc[:51].eq(0).all())

    def test_btc_repeatability_input_and_raw_snapshot_preservation(self):
        repeated = evaluate_train_test_split(self.source, generate_ema_signals, **self.parameters)
        for label in ("in_sample", "out_of_sample"):
            assert_segment_equal(self, repeated[label], self.result[label])
        pd.testing.assert_frame_equal(self.source, self.before, check_exact=True)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash)
