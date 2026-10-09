"""Downstream-only diagnostics, neutral tables, and independent-window statistics."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from types import MappingProxyType
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_lab.analytics.portfolio_drawdown import (
    summarize_gross_portfolio_drawdown,
    summarize_net_portfolio_drawdown,
)
from trading_lab.analytics.risk_adjusted import summarize_risk_adjusted_performance
from trading_lab.analytics.trade_time import summarize_trade_time_metrics
from trading_lab.data.market_data import load_ohlcv_csv
from trading_lab.robustness import (
    evaluate_expanding_walk_forward,
    evaluate_train_test_split,
    summarize_train_test_diagnostics,
    summarize_walk_forward_diagnostics,
)
from trading_lab.robustness import diagnostics
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_ema_generic_regression import (
    END, FEE_RATE, FROZEN_SHA256, HOUR, INITIAL_CAPITAL, RAW_BTC,
    SLIPPAGE_RATE, START,
)
from tests.test_robustness_oos import EMA_KWARGS, SEGMENT_KEYS, candles, event_strategy


METRICS = [
    "trade_count", "closed_trade_count", "exposure_ratio", "initial_equity",
    "gross_final_equity", "net_final_equity", "gross_total_return", "net_total_return",
    "gross_max_portfolio_drawdown", "net_max_portfolio_drawdown",
    "gross_sharpe", "gross_sortino", "net_sharpe", "net_sortino",
]
COMPARABLE = [
    "trade_count", "closed_trade_count", "exposure_ratio",
    "gross_final_equity", "net_final_equity", "gross_total_return", "net_total_return",
    "gross_max_portfolio_drawdown", "net_max_portfolio_drawdown",
    "gross_sharpe", "gross_sortino", "net_sharpe", "net_sortino",
]
METADATA = [
    "window_id", "train_rows", "test_rows", "train_start_timestamp",
    "train_last_timestamp", "test_start_timestamp", "test_last_timestamp",
]
COUNTS = {"trade_count", "closed_trade_count"}
SPLIT_KEYS = ["split_index", "split_timestamp", "segment_metrics", "comparison"]
WALK_KEYS = ["unused_tail_rows", "window_metrics", "window_comparison", "test_metric_summary"]
COMPARISON_COLUMNS = ["metric", "in_sample_value", "out_of_sample_value", "oos_minus_is"]
WINDOW_COMPARISON_COLUMNS = ["window_id", "metric", "train_value", "test_value", "test_minus_train"]
SUMMARY_COLUMNS = ["metric", "finite_count", "mean", "median", "minimum", "maximum"]
RISK = dict(periods_per_year=8760.0, risk_free_return_per_period=0.0,
            minimum_acceptable_return_per_period=0.0)
FINANCE = dict(candle_interval=HOUR, initial_capital=3210.0, fee_rate=0.001,
               slippage_rate=0.0005, position_fraction=0.37)


def precomputed_split(**kwargs):
    source = candles([100, 100, 90, 80, 130, 120, 200, 200, 230, 220, 210, 240])
    return evaluate_train_test_split(
        source, event_strategy, **{**FINANCE, "train_fraction": 0.5,
                                 "strategy_kwargs": {"events": {0: "LONG_ENTRY", 2: "LONG_EXIT", 4: "LONG_ENTRY"}},
                                 **kwargs},
    )


def precomputed_walk(source=None, **kwargs):
    source = candles([100, 100, 105, 110, 120, 130] * 4) if source is None else source
    return evaluate_expanding_walk_forward(
        source, event_strategy, **{**FINANCE, "initial_train_rows": 6, "test_rows": 6,
                                 "strategy_kwargs": {"events": {0: "LONG_ENTRY"}}, **kwargs},
    )


def direct_metrics(segment, **kwargs):
    """Expected values from public analytics and the specified endpoint return."""
    trades, gross, net = segment["trades"], segment["gross_equity"], segment["net_equity"]
    time = summarize_trade_time_metrics(trades, gross.valuation_time.iloc[0], gross.valuation_time.iloc[-1])
    expected = {
        "trade_count": len(trades), "closed_trade_count": int(trades.status.eq("CLOSED").sum()),
        "exposure_ratio": time.loc["TIME", "exposure_ratio"],
        "initial_equity": float(gross.equity.iloc[0]),
    }
    for label, path, drawdown in (
        ("gross", gross, summarize_gross_portfolio_drawdown),
        ("net", net, summarize_net_portfolio_drawdown),
    ):
        dd, risk = drawdown(path), summarize_risk_adjusted_performance(path, **{**RISK, **kwargs})
        expected[f"{label}_final_equity"] = float(path.equity.iloc[-1])
        expected[f"{label}_total_return"] = float(path.equity.iloc[-1]) / float(path.equity.iloc[0]) - 1
        expected[f"{label}_max_portfolio_drawdown"] = dd.iloc[0]["max_portfolio_drawdown"]
        expected[f"{label}_sharpe"] = risk.iloc[0]["sharpe_ratio"]
        expected[f"{label}_sortino"] = risk.iloc[0]["sortino_ratio"]
    return pd.Series(expected)[METRICS].astype("float64")


def assert_nested_equal(test, actual, expected):
    if isinstance(expected, pd.DataFrame):
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)
    elif isinstance(expected, dict):
        test.assertEqual(list(actual), list(expected))
        for name in expected:
            assert_nested_equal(test, actual[name], expected[name])
    elif isinstance(expected, tuple):
        test.assertIsInstance(actual, tuple)
        test.assertEqual(len(actual), len(expected))
        for left, right in zip(actual, expected):
            assert_nested_equal(test, left, right)
    else:
        test.assertEqual(actual, expected)


def assert_metric_row(test, actual, segment, **risk):
    pd.testing.assert_series_equal(
        actual[METRICS].astype("float64"), direct_metrics(segment, **risk),
        check_exact=True, check_names=False,
    )


def with_test_ratios(walk, sharpe, sortino=None):
    """Stub helper ratios to isolate table/finite policy from financial formulas."""
    selected = {id(window["test"]["net_equity"]): index for index, window in enumerate(walk["windows"])}
    def risk(path, **settings):
        result = summarize_risk_adjusted_performance(path, **settings)
        if id(path) in selected:
            index = selected[id(path)]
            result["sharpe_ratio"] = sharpe[index]
            if sortino is not None:
                result["sortino_ratio"] = sortino[index]
        return result
    return patch.object(diagnostics, "summarize_risk_adjusted_performance", side_effect=risk)


class TrainTestDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.input = precomputed_split()

    def test_explicit_imports_and_historical_wildcard_contract(self):
        import trading_lab.robustness as package
        self.assertIs(package.summarize_train_test_diagnostics, diagnostics.summarize_train_test_diagnostics)
        self.assertIs(package.summarize_walk_forward_diagnostics, diagnostics.summarize_walk_forward_diagnostics)
        self.assertEqual(package.__all__, ["chronological_split", "evaluate_strategy_segment", "evaluate_train_test_split"])
        for name in ("evaluate_parameter_sensitivity", "analyze_parameter_stability",
                     "generate_expanding_walk_forward_windows", "evaluate_expanding_walk_forward"):
            self.assertTrue(callable(getattr(package, name)))

    def test_exact_return_keys_and_preserved_split_metadata(self):
        result = summarize_train_test_diagnostics(self.input)
        self.assertEqual(list(result), SPLIT_KEYS)
        self.assertEqual(result["split_index"], 6)
        self.assertEqual(result["split_timestamp"], self.input["split_timestamp"])

    def test_exact_segment_schema_order_labels_and_fresh_range_index(self):
        table = summarize_train_test_diagnostics(self.input)["segment_metrics"]
        self.assertEqual(table.columns.tolist(), ["segment", *METRICS])
        self.assertEqual(table.segment.tolist(), ["IN_SAMPLE", "OUT_OF_SAMPLE"])
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(2), exact=True)

    def test_count_and_financial_dtypes(self):
        table = summarize_train_test_diagnostics(self.input)["segment_metrics"]
        for name in METRICS:
            self.assertEqual(table[name].dtype, "int64" if name in COUNTS else "float64")

    def test_open_is_counted_without_becoming_closed(self):
        result = summarize_train_test_diagnostics(self.input)
        self.assertEqual(result["segment_metrics"].trade_count.tolist(), [2, 2])
        self.assertEqual(result["segment_metrics"].closed_trade_count.tolist(), [1, 1])
        for name in ("in_sample", "out_of_sample"):
            self.assertEqual(self.input[name]["trades"].status.tolist(), ["CLOSED", "OPEN"])

    def test_initial_equity_is_each_segments_own_capital(self):
        table = summarize_train_test_diagnostics(self.input)["segment_metrics"]
        self.assertEqual(table.initial_equity.tolist(), [3210.0, 3210.0])
        self.assertNotEqual(table.gross_final_equity.iloc[0], table.initial_equity.iloc[1])

    def test_final_open_holding_uses_marked_equity_without_liquidation(self):
        source = precomputed_split(strategy_kwargs={"events": {0: "LONG_ENTRY"}})
        before = deepcopy(source)
        table = summarize_train_test_diagnostics(source)["segment_metrics"]
        for index, name in enumerate(("in_sample", "out_of_sample")):
            segment = source[name]
            self.assertEqual(segment["trades"].status.tolist(), ["OPEN"])
            for label in ("gross", "net"):
                self.assertEqual(table[f"{label}_final_equity"].iloc[index], segment[f"{label}_equity"].equity.iloc[-1])
                self.assertNotEqual(table[f"{label}_final_equity"].iloc[index], 3210)
            self.assertTrue(segment["trades"][["exit_time", "exit_price"]].isna().all().all())
        assert_nested_equal(self, source, before)

    def test_total_return_is_endpoint_derived_without_annualizing(self):
        table = summarize_train_test_diagnostics(self.input, periods_per_year=50)["segment_metrics"]
        for index, key in enumerate(("in_sample", "out_of_sample")):
            for label in ("gross", "net"):
                path = self.input[key][f"{label}_equity"]
                self.assertEqual(table[f"{label}_total_return"].iloc[index], float(path.equity.iloc[-1]) / float(path.equity.iloc[0]) - 1)

    def test_exact_public_analytics_parity_with_nondefault_risk_settings(self):
        settings = dict(periods_per_year=100.0, risk_free_return_per_period=0.001,
                        minimum_acceptable_return_per_period=0.002)
        table = summarize_train_test_diagnostics(self.input, **settings)["segment_metrics"]
        for index, key in enumerate(("in_sample", "out_of_sample")):
            assert_metric_row(self, table.iloc[index], self.input[key], **settings)

    def test_exposure_helper_receives_gross_first_and_last_valuation_times(self):
        with patch.object(diagnostics, "summarize_trade_time_metrics", wraps=summarize_trade_time_metrics) as helper:
            summarize_train_test_diagnostics(self.input)
        self.assertEqual(helper.call_count, 2)
        for call, key in zip(helper.call_args_list, ("in_sample", "out_of_sample")):
            gross = self.input[key]["gross_equity"]
            self.assertIs(call.args[0], self.input[key]["trades"])
            self.assertEqual(call.args[1:], (gross.valuation_time.iloc[0], gross.valuation_time.iloc[-1]))

    def test_drawdown_uses_both_existing_public_wrappers(self):
        with patch.object(diagnostics, "summarize_gross_portfolio_drawdown", wraps=summarize_gross_portfolio_drawdown) as gross:
            with patch.object(diagnostics, "summarize_net_portfolio_drawdown", wraps=summarize_net_portfolio_drawdown) as net:
                summarize_train_test_diagnostics(self.input)
        for helper, label in ((gross, "gross"), (net, "net")):
            self.assertEqual(helper.call_count, 2)
            for call, key in zip(helper.call_args_list, ("in_sample", "out_of_sample")):
                self.assertIs(call.args[0], self.input[key][f"{label}_equity"])

    def test_risk_settings_pass_unchanged_to_all_four_paths(self):
        settings = dict(periods_per_year=123.0, risk_free_return_per_period=-0.001,
                        minimum_acceptable_return_per_period=0.003)
        with patch.object(diagnostics, "summarize_risk_adjusted_performance", wraps=summarize_risk_adjusted_performance) as helper:
            summarize_train_test_diagnostics(self.input, **settings)
        self.assertEqual(helper.call_count, 4)
        paths = [self.input[key][f"{label}_equity"] for key in ("in_sample", "out_of_sample") for label in ("gross", "net")]
        for call, path in zip(helper.call_args_list, paths):
            self.assertIs(call.args[0], path)
            self.assertEqual(call.kwargs, settings)

    def test_exact_long_form_comparison_schema_order_and_dtypes(self):
        table = summarize_train_test_diagnostics(self.input)["comparison"]
        self.assertEqual(table.columns.tolist(), COMPARISON_COLUMNS)
        self.assertEqual(table.metric.tolist(), COMPARABLE)
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(13), exact=True)
        self.assertTrue(table[COMPARISON_COLUMNS[1:]].dtypes.eq("float64").all())
        self.assertNotIn("initial_equity", table.metric.tolist())

    def test_comparison_is_neutral_oos_minus_is(self):
        result = summarize_train_test_diagnostics(self.input)
        rows = result["segment_metrics"]
        expected = pd.DataFrame([
            [name, float(rows[name].iloc[0]), float(rows[name].iloc[1]), float(rows[name].iloc[1]) - float(rows[name].iloc[0])]
            for name in COMPARABLE
        ], columns=COMPARISON_COLUMNS)
        pd.testing.assert_frame_equal(result["comparison"], expected, check_exact=True)

    def test_no_trade_cash_path_preserves_nan_ratios(self):
        source = precomputed_split(initial_capital=1234.0, strategy_kwargs={"events": {}})
        table = summarize_train_test_diagnostics(source)["segment_metrics"]
        self.assertTrue(table[["trade_count", "closed_trade_count", "exposure_ratio", "gross_total_return", "net_total_return"]].eq(0).all().all())
        self.assertTrue(table[["initial_equity", "gross_final_equity", "net_final_equity"]].eq(1234).all().all())
        self.assertTrue(table[["gross_sharpe", "gross_sortino", "net_sharpe", "net_sortino"]].isna().all().all())

    def test_actual_no_downside_sortino_remains_positive_infinity(self):
        source = evaluate_train_test_split(
            candles([100, 100, 200, 400, 800, 1600] * 2), event_strategy,
            candle_interval=HOUR, train_fraction=0.5, strategy_kwargs={"events": {0: "LONG_ENTRY"}},
        )
        table = summarize_train_test_diagnostics(source)["segment_metrics"]
        self.assertTrue(np.isposinf(table[["gross_sortino", "net_sortino"]]).all().all())
        self.assertTrue(np.isfinite(table[["gross_sharpe", "net_sharpe"]]).all().all())

    def test_nonfinite_comparison_preserves_ieee_subtraction(self):
        pairs = [(np.inf, np.inf), (-np.inf, np.nan), (3.0, np.inf), (np.inf, np.nan)]
        summaries = [pd.DataFrame({"sharpe_ratio": [sharpe], "sortino_ratio": [sortino]}) for sharpe, sortino in pairs]
        with patch.object(diagnostics, "summarize_risk_adjusted_performance", side_effect=summaries):
            result = summarize_train_test_diagnostics(self.input)
        comparison = result["comparison"].set_index("metric")
        self.assertTrue(np.isneginf(comparison.loc["gross_sharpe", "oos_minus_is"]))
        self.assertTrue(np.isnan(comparison.loc["gross_sortino", "oos_minus_is"]))
        self.assertTrue(np.isposinf(comparison.loc["net_sharpe", "oos_minus_is"]))
        self.assertTrue(np.isnan(comparison.loc["net_sortino", "oos_minus_is"]))
        self.assertTrue(np.isneginf(result["segment_metrics"].net_sharpe.iloc[0]))

    def test_read_only_mappings_and_structurally_equivalent_objects_work(self):
        source = {**self.input, "annotation": "not a production identity"}
        for name in ("in_sample", "out_of_sample"):
            source[name] = MappingProxyType(source[name])
        actual = summarize_train_test_diagnostics(MappingProxyType(source))
        assert_nested_equal(self, actual, summarize_train_test_diagnostics(self.input))

    def test_input_preservation_and_fresh_output_frames(self):
        before = deepcopy(self.input)
        result = summarize_train_test_diagnostics(self.input)
        result["segment_metrics"].loc[0, "net_final_equity"] = -999
        result["comparison"].loc[0, "oos_minus_is"] = -999
        assert_nested_equal(self, self.input, before)
        self.assertNotEqual(summarize_train_test_diagnostics(self.input)["segment_metrics"].net_final_equity.iloc[0], -999)

    def test_repeated_calls_are_exactly_deterministic(self):
        assert_nested_equal(self, summarize_train_test_diagnostics(self.input), summarize_train_test_diagnostics(self.input))

    def test_malformed_top_level_structure_and_split_metadata_rejected(self):
        invalid = [None, [], {}, pd.DataFrame()]
        invalid.extend({key: value for key, value in self.input.items() if key != missing} for missing in self.input)
        invalid.extend({**self.input, "split_index": value} for value in (0, -1, True, np.bool_(True), 6.0, "6", None))
        invalid.extend({**self.input, "split_timestamp": value} for value in (None, pd.NaT, "2025-01-01", 1, [self.input["split_timestamp"]]))
        for source in invalid:
            with self.subTest(source=repr(source)[:80]), self.assertRaises(ValueError):
                summarize_train_test_diagnostics(source)

    def test_malformed_canonical_segment_structure_rejected(self):
        invalid = [None, [], {}]
        invalid.extend({key: value for key, value in self.input["in_sample"].items() if key != missing} for missing in SEGMENT_KEYS)
        invalid.extend({**self.input["in_sample"], key: None} for key in SEGMENT_KEYS)
        for segment in invalid:
            with self.subTest(segment=repr(segment)[:80]), self.assertRaises(ValueError):
                summarize_train_test_diagnostics({**self.input, "in_sample": segment})

    def test_different_gross_net_initial_equities_rejected_exactly(self):
        source = deepcopy(self.input)
        source["in_sample"]["net_equity"].loc[0, "equity"] = np.nextafter(3210.0, np.inf)
        with self.assertRaisesRegex(ValueError, "initial equity must match exactly"):
            summarize_train_test_diagnostics(source)

    def test_no_classification_ranking_or_original_backtest_outputs(self):
        result = summarize_train_test_diagnostics(self.input)
        forbidden = {"robust", "fragile", "stable", "unstable", "pass", "fail", "recommendation", "rank", "score", "robustness_score"}
        self.assertTrue(forbidden.isdisjoint(result))
        for name in ("segment_metrics", "comparison"):
            self.assertTrue(forbidden.isdisjoint(result[name].columns))
        self.assertTrue(set(SEGMENT_KEYS).isdisjoint(result))


class WalkForwardDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.input = precomputed_walk()

    def test_exact_return_keys_and_explicit_unused_tail(self):
        source = precomputed_walk(candles(range(100, 112)), initial_train_rows=5, test_rows=3)
        result = summarize_walk_forward_diagnostics(source)
        self.assertEqual(list(result), WALK_KEYS)
        self.assertEqual(result["unused_tail_rows"], 1)
        self.assertEqual(len(result["window_metrics"]), 2)

    def test_exact_wide_schema_and_one_row_per_window(self):
        table = summarize_walk_forward_diagnostics(self.input)["window_metrics"]
        self.assertEqual(table.columns.tolist(), [*METADATA, *[f"{prefix}_{name}" for prefix in ("train", "test") for name in METRICS]])
        self.assertEqual(table.window_id.tolist(), [1, 2, 3])
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(3), exact=True)

    def test_wide_counts_int64_and_other_metric_fields_float64(self):
        table = summarize_walk_forward_diagnostics(self.input)["window_metrics"]
        self.assertTrue(table[METADATA[:3]].dtypes.eq("int64").all())
        for prefix in ("train", "test"):
            for name in METRICS:
                self.assertEqual(table[f"{prefix}_{name}"].dtype, "int64" if name in COUNTS else "float64")

    def test_metadata_comes_from_authoritative_definitions(self):
        source = deepcopy(self.input)
        definitions = source["window_definitions"]
        definitions.index = pd.Index([88, 3, 3], name="definition_label")
        for name in METADATA[3:]:
            definitions[name] = definitions[name].dt.tz_convert("Asia/Seoul")
        before = deepcopy(source)
        table = summarize_walk_forward_diagnostics(source)["window_metrics"]
        pd.testing.assert_frame_equal(table[METADATA], definitions[METADATA].reset_index(drop=True), check_exact=True)
        assert_nested_equal(self, source, before)

    def test_naive_timestamp_metadata_is_preserved(self):
        source = deepcopy(self.input)
        for name in METADATA[3:]:
            source["window_definitions"][name] = source["window_definitions"][name].dt.tz_localize(None)
        table = summarize_walk_forward_diagnostics(source)["window_metrics"]
        self.assertTrue(table[METADATA[3:]].dtypes.eq("datetime64[ns]").all())

    def test_exact_train_and_test_public_analytics_parity(self):
        settings = dict(periods_per_year=200.0, risk_free_return_per_period=0.001,
                        minimum_acceptable_return_per_period=0.002)
        table = summarize_walk_forward_diagnostics(self.input, **settings)["window_metrics"]
        for index, window in enumerate(self.input["windows"]):
            for label in ("train", "test"):
                actual = table.iloc[index][[f"{label}_{name}" for name in METRICS]].copy()
                actual.index = METRICS
                assert_metric_row(self, actual, window[label], **settings)

    def test_every_train_test_initial_equity_remains_independent(self):
        table = summarize_walk_forward_diagnostics(self.input)["window_metrics"]
        self.assertTrue(table[["train_initial_equity", "test_initial_equity"]].eq(3210).all().all())
        self.assertTrue(table.test_net_final_equity.ne(table.test_initial_equity).all())

    def test_exact_window_comparison_schema_order_and_dtypes(self):
        table = summarize_walk_forward_diagnostics(self.input)["window_comparison"]
        self.assertEqual(table.columns.tolist(), WINDOW_COMPARISON_COLUMNS)
        self.assertEqual(table.window_id.tolist(), [window_id for window_id in (1, 2, 3) for _ in COMPARABLE])
        self.assertEqual(table.metric.tolist(), COMPARABLE * 3)
        self.assertEqual(table.window_id.dtype, "int64")
        self.assertTrue(table[WINDOW_COMPARISON_COLUMNS[2:]].dtypes.eq("float64").all())
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(39), exact=True)

    def test_neutral_window_deltas_are_test_minus_train(self):
        result = summarize_walk_forward_diagnostics(self.input)
        metrics = result["window_metrics"]
        expected = pd.DataFrame([
            [row.window_id, name, float(getattr(row, f"train_{name}")), float(getattr(row, f"test_{name}")),
             float(getattr(row, f"test_{name}")) - float(getattr(row, f"train_{name}"))]
            for row in metrics.itertuples(index=False) for name in COMPARABLE
        ], columns=WINDOW_COMPARISON_COLUMNS)
        pd.testing.assert_frame_equal(result["window_comparison"], expected, check_exact=True)

    def test_exact_cross_window_summary_schema_order_and_dtypes(self):
        table = summarize_walk_forward_diagnostics(self.input)["test_metric_summary"]
        self.assertEqual(table.columns.tolist(), SUMMARY_COLUMNS)
        self.assertEqual(table.metric.tolist(), COMPARABLE)
        self.assertEqual(table.finite_count.dtype, "int64")
        self.assertTrue(table[SUMMARY_COLUMNS[2:]].dtypes.eq("float64").all())
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(13), exact=True)

    def test_finite_test_trade_count_statistics_are_descriptive(self):
        table = summarize_walk_forward_diagnostics(self.input)["test_metric_summary"].set_index("metric")
        self.assertEqual(table.loc["trade_count", "finite_count"], 3)
        self.assertEqual(table.loc["trade_count", SUMMARY_COLUMNS[2:]].tolist(), [1.0] * 4)
        self.assertEqual(table.loc["closed_trade_count", SUMMARY_COLUMNS[2:]].tolist(), [0.0] * 4)

    def test_finite_mean_and_median_are_distinct_descriptive_statistics(self):
        with with_test_ratios(self.input, [1.0, 2.0, 9.0]):
            result = summarize_walk_forward_diagnostics(self.input)
        row = result["test_metric_summary"].set_index("metric").loc["net_sharpe"]
        self.assertEqual(row.finite_count, 3)
        self.assertEqual(row[SUMMARY_COLUMNS[2:]].tolist(), [4.0, 2.0, 1.0, 9.0])

    def test_windows_stay_in_definition_order_without_performance_sorting(self):
        source = precomputed_walk(candles(
            [100] * 6 + [100, 100, 110, 120, 130, 150]
            + [200, 200, 160, 140, 120, 100] + [100, 100, 105, 110, 115, 120]
        ), fee_rate=0.0, slippage_rate=0.0, position_fraction=1.0)
        result = summarize_walk_forward_diagnostics(source)
        table = result["window_metrics"]
        self.assertEqual(table.window_id.tolist(), [1, 2, 3])
        self.assertGreater(table.test_net_total_return.iloc[0], table.test_net_total_return.iloc[2])
        self.assertGreater(table.test_net_total_return.iloc[2], table.test_net_total_return.iloc[1])
        self.assertEqual(result["window_comparison"].window_id.tolist(), [i for i in (1, 2, 3) for _ in COMPARABLE])

    def test_mixed_nonfinite_ratios_retained_and_summary_uses_finite_only(self):
        source = precomputed_walk(candles(range(100, 130)), initial_train_rows=5, test_rows=5)
        values = [np.nan, np.inf, -np.inf, 1.0, 3.0]
        before = deepcopy(source)
        with with_test_ratios(source, values):
            result = summarize_walk_forward_diagnostics(source)
        np.testing.assert_array_equal(result["window_metrics"].test_net_sharpe.to_numpy(), values)
        comparison = result["window_comparison"].query("metric == 'net_sharpe'")
        np.testing.assert_array_equal(comparison.test_value.to_numpy(), values)
        row = result["test_metric_summary"].set_index("metric").loc["net_sharpe"]
        self.assertEqual(row.finite_count, 2)
        self.assertEqual(row[SUMMARY_COLUMNS[2:]].tolist(), [2.0, 2.0, 1.0, 3.0])
        self.assertEqual(len(result["window_metrics"]), 5)
        assert_nested_equal(self, source, before)

    def test_zero_finite_values_produce_nan_statistics(self):
        with with_test_ratios(self.input, [np.nan, np.inf, -np.inf]):
            result = summarize_walk_forward_diagnostics(self.input)
        row = result["test_metric_summary"].set_index("metric").loc["net_sharpe"]
        self.assertEqual(row.finite_count, 0)
        self.assertTrue(row[SUMMARY_COLUMNS[2:]].isna().all())
        self.assertEqual(len(result["window_metrics"]), 3)

    def test_one_finite_value_is_all_four_descriptive_statistics(self):
        with with_test_ratios(self.input, [np.inf, 7.0, np.nan]):
            result = summarize_walk_forward_diagnostics(self.input)
        row = result["test_metric_summary"].set_index("metric").loc["net_sharpe"]
        self.assertEqual(row.finite_count, 1)
        self.assertEqual(row[SUMMARY_COLUMNS[2:]].tolist(), [7.0] * 4)

    def test_actual_cash_windows_keep_raw_nan_and_zero_finite_count(self):
        source = precomputed_walk(strategy_kwargs={"events": {}})
        result = summarize_walk_forward_diagnostics(source)
        self.assertTrue(result["window_metrics"].test_net_sharpe.isna().all())
        self.assertTrue(result["window_comparison"].query("metric == 'net_sharpe'").test_minus_train.isna().all())
        self.assertEqual(result["test_metric_summary"].set_index("metric").loc["net_sharpe", "finite_count"], 0)

    def test_two_independent_ten_percent_windows_are_not_compounded(self):
        source = precomputed_walk(
            candles([100, 100, 105, 108, 110] * 3), initial_train_rows=5, test_rows=5,
            initial_capital=100.0, fee_rate=0.0, slippage_rate=0.0, position_fraction=1.0,
        )
        result = summarize_walk_forward_diagnostics(source)
        self.assertTrue(result["window_metrics"].test_initial_equity.eq(100).all())
        self.assertTrue(result["window_metrics"].test_net_final_equity.eq(110).all())
        row = result["test_metric_summary"].set_index("metric").loc["net_total_return"]
        self.assertEqual(row.finite_count, 2)
        for name in SUMMARY_COLUMNS[2:]:
            self.assertAlmostEqual(row[name], 0.10)
            self.assertNotEqual(row[name], 0.21)
        self.assertNotIn("aggregate_return", result["test_metric_summary"].metric.tolist())

    def test_no_score_classification_recommendation_or_stitched_portfolio(self):
        result = summarize_walk_forward_diagnostics(self.input)
        forbidden = {
            "aggregate_return", "compounded_return", "combined_equity", "portfolio_return", "stitched_return",
            "equity", "walk_forward_equity", "stitched_equity", "continuous_equity",
            "robust_window_fraction", "success_rate", "pass_rate", "stability_score", "robustness_score",
            "robust", "fragile", "stable", "unstable", "pass", "fail", "recommendation", "rank", "score",
        }
        self.assertTrue(forbidden.isdisjoint(result))
        for name in WALK_KEYS[1:]:
            self.assertTrue(forbidden.isdisjoint(result[name].columns))
        self.assertTrue(forbidden.isdisjoint(result["test_metric_summary"].metric.tolist()))

    def test_read_only_outer_and_window_mappings_are_accepted(self):
        source = {**self.input, "windows": tuple(MappingProxyType(window) for window in self.input["windows"])}
        actual = summarize_walk_forward_diagnostics(MappingProxyType(source))
        assert_nested_equal(self, actual, summarize_walk_forward_diagnostics(self.input))

    def test_inputs_preserved_and_all_three_tables_are_fresh(self):
        before = deepcopy(self.input)
        result = summarize_walk_forward_diagnostics(self.input)
        result["window_metrics"].loc[0, "train_rows"] = -999
        result["window_comparison"].loc[0, "test_value"] = -999
        result["test_metric_summary"].loc[0, "mean"] = -999
        assert_nested_equal(self, self.input, before)
        repeated = summarize_walk_forward_diagnostics(self.input)
        for name in WALK_KEYS[1:]:
            self.assertIsNot(result[name], repeated[name])

    def test_repeated_calls_with_custom_risk_settings_are_exact(self):
        settings = dict(periods_per_year=50, risk_free_return_per_period=-0.002,
                        minimum_acceptable_return_per_period=-0.001)
        assert_nested_equal(self, summarize_walk_forward_diagnostics(self.input, **settings),
                            summarize_walk_forward_diagnostics(self.input, **settings))

    def test_invalid_top_level_mapping_and_tail_rejected(self):
        invalid = [None, [], {}, pd.DataFrame()]
        invalid.extend({key: value for key, value in self.input.items() if key != missing} for missing in self.input)
        invalid.extend({**self.input, "unused_tail_rows": value} for value in (-1, True, np.bool_(True), 0.0, "0", None))
        for source in invalid:
            with self.subTest(source=repr(source)[:80]), self.assertRaises(ValueError):
                summarize_walk_forward_diagnostics(source)

    def test_invalid_definition_structure_and_required_metadata_rejected(self):
        definitions = self.input["window_definitions"]
        invalid = [None, [], definitions.iloc[:0], pd.concat([definitions, definitions[["window_id"]]], axis=1)]
        invalid.extend(definitions.drop(columns=name) for name in METADATA)
        for table in invalid:
            with self.subTest(table=repr(table)[:80]), self.assertRaises(ValueError):
                summarize_walk_forward_diagnostics({**self.input, "window_definitions": table})

    def test_invalid_definition_integer_and_timestamp_metadata_rejected(self):
        for name in METADATA[:3]:
            for value in (0, True, 1.0, "1", None, 2**64, np.uint64(2**63)):
                table = self.input["window_definitions"].copy()
                table[name] = pd.Series([value] * len(table), dtype="object")
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    summarize_walk_forward_diagnostics({**self.input, "window_definitions": table})
        for name in METADATA[3:]:
            for missing in (False, True):
                table = self.input["window_definitions"].copy()
                if missing:
                    table.loc[0, name] = pd.NaT
                else:
                    table[name] = table[name].astype(str)
                with self.subTest(name=name, missing=missing), self.assertRaises(ValueError):
                    summarize_walk_forward_diagnostics({**self.input, "window_definitions": table})

    def test_windows_must_be_matching_length_tuple(self):
        for windows in (None, list(self.input["windows"]), (), self.input["windows"][:-1], self.input["windows"] * 2):
            with self.subTest(windows=repr(windows)[:80]), self.assertRaises(ValueError):
                summarize_walk_forward_diagnostics({**self.input, "windows": windows})

    def test_window_id_reconciliation_rejects_mismatch_duplicates_and_bool(self):
        for value in (99, True, 1.0, None):
            source = deepcopy(self.input)
            source["windows"][0]["window_id"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                summarize_walk_forward_diagnostics(source)
        source = deepcopy(self.input)
        source["window_definitions"].loc[1, "window_id"] = 1
        with self.assertRaisesRegex(ValueError, "unique"):
            summarize_walk_forward_diagnostics(source)
        source = {**self.input, "windows": self.input["windows"][::-1]}
        with self.assertRaisesRegex(ValueError, "reconcile"):
            summarize_walk_forward_diagnostics(source)

    def test_malformed_per_window_mapping_and_segments_rejected(self):
        invalid = [None, {}, {"window_id": 1, "train": self.input["windows"][0]["train"]}]
        invalid.extend({**self.input["windows"][0], name: {}} for name in ("train", "test"))
        for window in invalid:
            source = {**self.input, "windows": (window, *self.input["windows"][1:])}
            with self.subTest(window=repr(window)[:80]), self.assertRaises(ValueError):
                summarize_walk_forward_diagnostics(source)

    def test_gross_net_initial_equity_mismatch_in_later_window_rejected(self):
        source = deepcopy(self.input)
        source["windows"][2]["test"]["net_equity"].loc[0, "equity"] += 1
        with self.assertRaisesRegex(ValueError, "initial equity must match exactly"):
            summarize_walk_forward_diagnostics(source)


class DownstreamArchitectureTests(unittest.TestCase):
    def test_both_summaries_work_when_all_strategy_research_and_backtest_calls_are_unavailable(self):
        split, walk = precomputed_split(), precomputed_walk()
        expected_split, expected_walk = summarize_train_test_diagnostics(split), summarize_walk_forward_diagnostics(walk)
        forbidden = (
            "trading_lab.strategies.ema_trend.generate_ema_signals",
            "trading_lab.backtest.pipeline.run_backtest_pipeline",
            "trading_lab.robustness.evaluation.run_backtest_pipeline",
            "trading_lab.robustness.evaluation.evaluate_strategy_segment",
            "trading_lab.robustness.evaluation.evaluate_train_test_split",
            "trading_lab.robustness.sensitivity.evaluate_train_test_split",
            "trading_lab.robustness.sensitivity.evaluate_parameter_sensitivity",
            "trading_lab.robustness.stability.analyze_parameter_stability",
            "trading_lab.robustness.walk_forward.evaluate_strategy_segment",
            "trading_lab.robustness.walk_forward.evaluate_expanding_walk_forward",
            "trading_lab.robustness.evaluate_strategy_segment",
            "trading_lab.robustness.evaluate_train_test_split",
            "trading_lab.robustness.evaluate_parameter_sensitivity",
            "trading_lab.robustness.analyze_parameter_stability",
            "trading_lab.robustness.evaluate_expanding_walk_forward",
        )
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError("Research rerun is forbidden"))) for name in forbidden]
            assert_nested_equal(self, summarize_train_test_diagnostics(split), expected_split)
            assert_nested_equal(self, summarize_walk_forward_diagnostics(walk), expected_walk)
            for mock in mocks:
                mock.assert_not_called()
        self.assertTrue({name.rsplit(".", 1)[-1] for name in forbidden}.isdisjoint(vars(diagnostics)))

    def test_existing_analytics_errors_propagate_without_partial_output_or_input_mutation(self):
        for caller, source in ((summarize_train_test_diagnostics, precomputed_split()),
                               (summarize_walk_forward_diagnostics, precomputed_walk())):
            for name in ("summarize_trade_time_metrics", "summarize_gross_portfolio_drawdown",
                         "summarize_net_portfolio_drawdown", "summarize_risk_adjusted_performance"):
                before = deepcopy(source)
                error = RuntimeError(name + " failed")
                with self.subTest(caller=caller.__name__, helper=name), patch.object(diagnostics, name, side_effect=error) as helper:
                    with self.assertRaises(RuntimeError) as caught:
                        caller(source)
                    self.assertIs(caught.exception, error)
                    self.assertEqual(helper.call_count, 1)
                assert_nested_equal(self, source, before)

    def test_later_segment_analytics_error_is_not_skipped(self):
        source = precomputed_walk()
        error = ValueError("later NET path failed")
        good = summarize_net_portfolio_drawdown(source["windows"][0]["train"]["net_equity"])
        with patch.object(diagnostics, "summarize_net_portfolio_drawdown", side_effect=[good, good, error]) as helper:
            with self.assertRaises(ValueError) as caught:
                summarize_walk_forward_diagnostics(source)
            self.assertIs(caught.exception, error)
            self.assertEqual(helper.call_count, 3)

    def test_risk_parameter_validation_is_delegated_unchanged(self):
        invalid = (
            {"periods_per_year": 0}, {"periods_per_year": True}, {"periods_per_year": "8760"},
            {"risk_free_return_per_period": np.nan}, {"risk_free_return_per_period": False},
            {"minimum_acceptable_return_per_period": np.inf}, {"minimum_acceptable_return_per_period": "0"},
        )
        for caller, source in ((summarize_train_test_diagnostics, precomputed_split()),
                               (summarize_walk_forward_diagnostics, precomputed_walk())):
            for settings in invalid:
                with self.subTest(caller=caller.__name__, settings=settings), self.assertRaises(ValueError):
                    caller(source, **settings)

    def test_financial_frame_validation_remains_with_existing_analytics(self):
        split, walk = precomputed_split(), precomputed_walk()
        cases = [(summarize_train_test_diagnostics, split, split["in_sample"]),
                 (summarize_walk_forward_diagnostics, walk, walk["windows"][0]["train"])]
        for caller, source, segment in cases:
            segment["gross_equity"] = segment["gross_equity"].drop(columns="equity")
            with self.subTest(caller=caller.__name__), patch.object(diagnostics, "summarize_gross_portfolio_drawdown", wraps=summarize_gross_portfolio_drawdown) as helper:
                with self.assertRaisesRegex(ValueError, "missing required columns"):
                    caller(source)
                helper.assert_called_once_with(segment["gross_equity"])


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class BTCRobustnessDiagnosticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_hash = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash != FROZEN_SHA256:
            raise AssertionError("Frozen BTC snapshot hash mismatch: " + cls.raw_hash)
        cls.source = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        cls.source_before = cls.source.copy(deep=True)
        settings = dict(candle_interval=HOUR, strategy_kwargs=deepcopy(EMA_KWARGS),
                        initial_capital=INITIAL_CAPITAL, fee_rate=FEE_RATE,
                        slippage_rate=SLIPPAGE_RATE, position_fraction=1.0)
        cls.split = evaluate_train_test_split(cls.source, generate_ema_signals, train_fraction=0.70, **settings)
        cls.walk = evaluate_expanding_walk_forward(cls.source, generate_ema_signals, initial_train_rows=4380, test_rows=1460, **settings)
        cls.split_before, cls.walk_before = deepcopy(cls.split), deepcopy(cls.walk)
        cls.split_summary = summarize_train_test_diagnostics(cls.split, **RISK)
        cls.walk_summary = summarize_walk_forward_diagnostics(cls.walk, **RISK)

    def test_canonical_btc_single_split_metadata_and_table_shapes(self):
        self.assertEqual(len(self.source), 8760)
        self.assertEqual(self.split_summary["split_index"], 6132)
        self.assertEqual(self.split_summary["split_timestamp"], pd.Timestamp("2026-06-13 12:00", tz="UTC"))
        self.assertEqual(len(self.split["in_sample"]["strategy_output"]), 6132)
        self.assertEqual(len(self.split["out_of_sample"]["strategy_output"]), 2628)
        self.assertEqual(self.split_summary["segment_metrics"].shape, (2, 15))
        self.assertEqual(self.split_summary["comparison"].shape, (13, 4))
        self.assertTrue(self.split_summary["segment_metrics"].initial_equity.eq(10_000).all())

    def test_canonical_btc_three_walk_forward_windows_and_table_shapes(self):
        result = self.walk_summary
        self.assertEqual(result["unused_tail_rows"], 0)
        self.assertEqual(result["window_metrics"].shape, (3, 35))
        self.assertEqual(result["window_comparison"].shape, (39, 5))
        self.assertEqual(result["test_metric_summary"].shape, (13, 6))
        self.assertEqual(result["window_metrics"].train_rows.tolist(), [4380, 5840, 7300])
        self.assertEqual(result["window_metrics"].test_rows.tolist(), [1460] * 3)
        self.assertTrue(result["window_metrics"][["train_initial_equity", "test_initial_equity"]].eq(10_000).all().all())
        self.assertEqual(list(result), WALK_KEYS)

    def test_btc_all_segment_metrics_match_helpers_and_canonical_sanity(self):
        rows = []
        for index, key in enumerate(("in_sample", "out_of_sample")):
            row = self.split_summary["segment_metrics"].iloc[index]
            assert_metric_row(self, row, self.split[key])
            rows.append(row[METRICS])
        for index, window in enumerate(self.walk["windows"]):
            for label in ("train", "test"):
                row = self.walk_summary["window_metrics"].iloc[index][[f"{label}_{name}" for name in METRICS]].copy()
                row.index = METRICS
                assert_metric_row(self, row, window[label])
                rows.append(row)
        for row in rows:
            self.assertGreaterEqual(row.trade_count, 0)
            self.assertLessEqual(row.closed_trade_count, row.trade_count)
            self.assertTrue(0 <= row.exposure_ratio <= 1)
            for label in ("gross", "net"):
                self.assertGreaterEqual(row[f"{label}_final_equity"], 0)
                self.assertLessEqual(row[f"{label}_max_portfolio_drawdown"], 0)
                self.assertEqual(row[f"{label}_total_return"], row[f"{label}_final_equity"] / row.initial_equity - 1)

    def test_btc_inputs_and_frozen_local_snapshot_remain_unchanged(self):
        assert_nested_equal(self, self.split, self.split_before)
        assert_nested_equal(self, self.walk, self.walk_before)
        pd.testing.assert_frame_equal(self.source, self.source_before, check_exact=True)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash)
