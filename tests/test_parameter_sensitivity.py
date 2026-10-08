"""Deterministic, descriptive grids composed from accepted research APIs."""

from copy import deepcopy
import hashlib
from itertools import product
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
from trading_lab.robustness import evaluate_parameter_sensitivity, evaluate_train_test_split
from trading_lab.robustness import evaluation, sensitivity
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_ema_generic_regression import (
    END, FEE_RATE, FROZEN_SHA256, HOUR, INITIAL_CAPITAL, RAW_BTC,
    SLIPPAGE_RATE, START,
)
from tests.test_robustness_oos import candles, event_strategy


METRICS = [
    "trade_count", "closed_trade_count", "exposure_ratio",
    "gross_final_equity", "net_final_equity",
    "gross_max_portfolio_drawdown", "net_max_portfolio_drawdown",
    "gross_sharpe", "gross_sortino", "net_sharpe", "net_sortino",
]
METRIC_COLUMNS = [f"{prefix}_{name}" for prefix in ("is", "oos") for name in METRICS]
RISK_KWARGS = dict(
    periods_per_year=8760.0, risk_free_return_per_period=0.0,
    minimum_acceptable_return_per_period=0.0,
)


def timed_strategy(frame, *, entry_after=0, exit_after=2, tag="research"):
    """Tiny non-EMA producer: parameter values control segment-local events."""
    if entry_after is not None and exit_after is not None and exit_after <= entry_after:
        raise ValueError("exit_after must follow entry_after.")
    events = {}
    if entry_after is not None:
        events[entry_after] = "LONG_ENTRY"
        if exit_after is not None:
            events[exit_after] = "LONG_EXIT"
    return event_strategy(frame, events=events, tag=tag)


def direct_metrics(split, **risk_kwargs):
    """Expected composition uses only existing public analytics, no formulas."""
    settings = {**RISK_KWARGS, **risk_kwargs}
    expected = {}
    for prefix, key in (("is", "in_sample"), ("oos", "out_of_sample")):
        segment = split[key]
        trades = segment["trades"]
        gross, net = segment["gross_equity"], segment["net_equity"]
        time = summarize_trade_time_metrics(
            trades, gross.valuation_time.iloc[0], gross.valuation_time.iloc[-1],
        )
        expected[f"{prefix}_trade_count"] = len(trades)
        expected[f"{prefix}_closed_trade_count"] = int(trades.status.eq("CLOSED").sum())
        expected[f"{prefix}_exposure_ratio"] = time.loc["TIME", "exposure_ratio"]
        for label, path, drawdown in (
            ("gross", gross, summarize_gross_portfolio_drawdown),
            ("net", net, summarize_net_portfolio_drawdown),
        ):
            dd = drawdown(path)
            risk = summarize_risk_adjusted_performance(path, **settings)
            expected[f"{prefix}_{label}_final_equity"] = path.equity.iloc[-1]
            expected[f"{prefix}_{label}_max_portfolio_drawdown"] = dd.iloc[0]["max_portfolio_drawdown"]
            expected[f"{prefix}_{label}_sharpe"] = risk.iloc[0]["sharpe_ratio"]
            expected[f"{prefix}_{label}_sortino"] = risk.iloc[0]["sortino_ratio"]
    return pd.Series(expected)[METRIC_COLUMNS].astype("float64")


def assert_metrics_equal(actual, expected):
    pd.testing.assert_series_equal(
        actual[METRIC_COLUMNS].astype("float64"), expected,
        check_exact=True, check_names=False,
    )


class ParameterSensitivityTests(unittest.TestCase):
    def setUp(self):
        self.source = candles([100, 100, 90, 80, 130, 120] * 2)
        # Deliberately non-alphabetical keys and unsorted values.
        self.grid = {"exit_after": [3, 2], "entry_after": [0, 1]}
        self.settings = dict(candle_interval=HOUR, train_fraction=0.5)

    def run_grid(self, grid=None, generator=timed_strategy, **kwargs):
        return evaluate_parameter_sensitivity(
            self.source, generator, self.grid if grid is None else grid,
            **{**self.settings, **kwargs},
        )

    def test_public_package_import_and_exact_return_key_order(self):
        import trading_lab.robustness as robustness
        self.assertIs(robustness.evaluate_parameter_sensitivity, sensitivity.evaluate_parameter_sensitivity)
        self.assertEqual(list(self.run_grid()), [
            "split_index", "split_timestamp", "parameter_names", "results",
        ])

    def test_parameter_names_and_cartesian_order_are_supplied_order(self):
        result = self.run_grid()
        self.assertEqual(result["parameter_names"], ("exit_after", "entry_after"))
        self.assertEqual(result["results"][["exit_after", "entry_after"]].values.tolist(),
                         [[3, 0], [3, 1], [2, 0], [2, 1]])
        self.assertEqual(len(result["results"]), 4)

    def test_exact_columns_range_index_and_scalar_dtypes(self):
        table = self.run_grid()["results"]
        self.assertEqual(table.columns.tolist(), ["exit_after", "entry_after", *METRIC_COLUMNS])
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(4), exact=True)
        for column in METRIC_COLUMNS:
            dtype = "int64" if column.endswith("trade_count") else "float64"
            self.assertEqual(table[column].dtype, dtype)
        self.assertEqual(table.exit_after.dtype, "int64")
        self.assertEqual(table.entry_after.dtype, "int64")

    def test_tuple_range_and_read_only_mapping_are_accepted(self):
        grid = MappingProxyType({"exit_after": (3, 2), "entry_after": range(2)})
        actual = self.run_grid(grid)["results"]
        pd.testing.assert_frame_equal(actual, self.run_grid()["results"], check_exact=True)

    def test_generic_grid_and_common_kwargs_reach_each_segment(self):
        seen = []
        def generator(frame, **kwargs):
            seen.append(kwargs.copy())
            return timed_strategy(frame, **kwargs)
        self.run_grid(generator=generator, strategy_kwargs={"tag": "common"})
        expected = [dict(exit_after=x, entry_after=y, tag="common")
                    for x, y in product([3, 2], [0, 1]) for _ in range(2)]
        self.assertEqual(seen, expected)

    def test_small_grid_matches_direct_composition_for_every_metric(self):
        parameters = dict(
            **self.settings, initial_capital=3210.0, fee_rate=0.001,
            slippage_rate=0.0005, position_fraction=0.37,
        )
        risk = dict(periods_per_year=100.0, risk_free_return_per_period=0.001,
                    minimum_acceptable_return_per_period=0.002)
        result = self.run_grid(**parameters, **risk)
        for index, (exit_after, entry_after) in enumerate(product([3, 2], [0, 1])):
            direct = evaluate_train_test_split(
                self.source, timed_strategy, **parameters,
                strategy_kwargs=dict(exit_after=exit_after, entry_after=entry_after),
            )
            assert_metrics_equal(result["results"].iloc[index], direct_metrics(direct, **risk))
            self.assertEqual(result["split_index"], direct["split_index"])
            self.assertEqual(result["split_timestamp"], direct["split_timestamp"])

    def test_shared_split_metadata_matches_supplied_candles(self):
        result = self.run_grid()
        self.assertEqual(result["split_index"], 6)
        self.assertEqual(result["split_timestamp"], self.source.timestamp.iloc[6])

    def test_mismatched_split_metadata_is_rejected(self):
        direct = evaluate_train_test_split(self.source, timed_strategy, **self.settings)
        for changed in ({"split_index": 5}, {"split_timestamp": direct["split_timestamp"] + HOUR}):
            with self.subTest(changed=changed):
                with patch.object(sensitivity, "evaluate_train_test_split",
                                  side_effect=[direct, {**direct, **changed}]) as core:
                    with self.assertRaisesRegex(RuntimeError, "split metadata"):
                        self.run_grid({"exit_after": [2, 3]})
                    self.assertEqual(core.call_count, 2)

    def test_later_better_equity_does_not_reorder_rows(self):
        table = self.run_grid({"exit_after": [1, 3]})["results"]
        self.assertGreater(table.is_gross_final_equity.iloc[1], table.is_gross_final_equity.iloc[0])
        self.assertGreater(table.oos_net_final_equity.iloc[1], table.oos_net_final_equity.iloc[0])
        self.assertEqual(table.exit_after.tolist(), [1, 3])

    def test_no_selection_or_ranking_output(self):
        result = self.run_grid()
        self.assertTrue({"rank", "score", "selected", "best", "recommendation"}.isdisjoint(result["results"].columns))
        self.assertTrue({"best_parameters", "selected_parameters", "winner"}.isdisjoint(result))

    def test_no_trade_path_keeps_cash_and_undefined_risk_metrics(self):
        result = self.run_grid({"entry_after": [None]}, initial_capital=1234.0)
        row = result["results"].iloc[0]
        for prefix in ("is", "oos"):
            self.assertEqual(row[f"{prefix}_trade_count"], 0)
            self.assertEqual(row[f"{prefix}_closed_trade_count"], 0)
            self.assertEqual(row[f"{prefix}_exposure_ratio"], 0)
            for label in ("gross", "net"):
                self.assertEqual(row[f"{prefix}_{label}_final_equity"], 1234)
                self.assertEqual(row[f"{prefix}_{label}_max_portfolio_drawdown"], 0)
                self.assertTrue(np.isnan(row[f"{prefix}_{label}_sharpe"]))
                self.assertTrue(np.isnan(row[f"{prefix}_{label}_sortino"]))

    def test_final_open_position_uses_marked_path_without_liquidation(self):
        parameters = dict(**self.settings, fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.5)
        result = self.run_grid({"exit_after": [None]}, **parameters)
        direct = evaluate_train_test_split(
            self.source, timed_strategy, **parameters, strategy_kwargs={"exit_after": None},
        )
        row = result["results"].iloc[0]
        assert_metrics_equal(row, direct_metrics(direct))
        for prefix, key in (("is", "in_sample"), ("oos", "out_of_sample")):
            segment = direct[key]
            self.assertEqual(segment["trades"].status.tolist(), ["OPEN"])
            self.assertTrue(segment["trades"][["exit_time", "exit_price"]].isna().all().all())
            self.assertEqual(row[f"{prefix}_trade_count"], 1)
            self.assertEqual(row[f"{prefix}_closed_trade_count"], 0)
            self.assertGreater(row[f"{prefix}_net_final_equity"], 10_000)
            self.assertLess(row[f"{prefix}_net_max_portfolio_drawdown"], 0)
            self.assertEqual(segment["net_equity"].position.iloc[-1], 1)

    def test_final_unfilled_exit_does_not_become_closed(self):
        row = self.run_grid({"exit_after": [5]})["results"].iloc[0]
        self.assertEqual(row.is_trade_count, 1)
        self.assertEqual(row.is_closed_trade_count, 0)
        self.assertEqual(row.oos_trade_count, 1)
        self.assertEqual(row.oos_closed_trade_count, 0)

    def test_documented_nan_and_signed_infinities_are_preserved(self):
        summaries = [pd.DataFrame({"sharpe_ratio": [sharpe], "sortino_ratio": [sortino]})
                     for sharpe, sortino in ((np.nan, np.inf), (-np.inf, np.nan))] * 2
        with patch.object(sensitivity, "summarize_risk_adjusted_performance", side_effect=summaries):
            row = self.run_grid({"exit_after": [2]})["results"].iloc[0]
        for prefix in ("is", "oos"):
            self.assertTrue(np.isnan(row[f"{prefix}_gross_sharpe"]))
            self.assertEqual(row[f"{prefix}_gross_sortino"], np.inf)
            self.assertEqual(row[f"{prefix}_net_sharpe"], -np.inf)
            self.assertTrue(np.isnan(row[f"{prefix}_net_sortino"]))

    def test_invalid_grid_mappings_and_keys_are_rejected_before_evaluation(self):
        invalid = (None, [], [("exit_after", [2])], 7, {}, {1: [2]}, {"": [2]})
        for grid in invalid:
            with self.subTest(grid=grid), patch.object(sensitivity, "evaluate_train_test_split") as core:
                with self.assertRaisesRegex(ValueError, "parameter_grid"):
                    evaluate_parameter_sensitivity(
                        self.source, timed_strategy, grid, **self.settings,
                    )
                core.assert_not_called()

    def test_invalid_candidate_containers_are_rejected(self):
        for values in ([], (), range(0), "23", b"23", {2, 3}, frozenset({2, 3}), {"x": 2}, 2, None):
            with self.subTest(values=repr(values)), patch.object(sensitivity, "evaluate_train_test_split") as core:
                with self.assertRaisesRegex(ValueError, "ordered sequences"):
                    self.run_grid({"exit_after": values})
                core.assert_not_called()

    def test_overlapping_grid_and_common_keys_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.run_grid(strategy_kwargs={"exit_after": 3})

    def test_metric_column_collision_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "collide"):
            self.run_grid({"is_trade_count": [1]})

    def test_invalid_common_kwargs_are_rejected(self):
        for kwargs in ([], "tag", 1, {1: "value"}):
            with self.subTest(kwargs=kwargs):
                with self.assertRaisesRegex(ValueError, "strategy_kwargs"):
                    self.run_grid(strategy_kwargs=kwargs)

    def test_invalid_strategy_combination_stops_without_partial_return(self):
        seen = []
        def generator(frame, **kwargs):
            seen.append(kwargs["exit_after"])
            return timed_strategy(frame, **kwargs)
        with self.assertRaisesRegex(ValueError, "must follow"):
            self.run_grid({"exit_after": [2, 0, 3]}, generator=generator)
        self.assertEqual(seen, [2, 2, 0])

    def test_ema_parameter_validity_is_delegated(self):
        with self.assertRaisesRegex(ValueError, "fast_span must be less"):
            self.run_grid({"fast_span": [2, 4], "slow_span": [3]},
                          generator=generate_ema_signals, strategy_kwargs={"warmup_candles": 1})

    def test_strategy_exception_propagates_unchanged(self):
        error = RuntimeError("strategy failed")
        def generator(frame, **kwargs):
            raise error
        with self.assertRaises(RuntimeError) as caught:
            self.run_grid(generator=generator)
        self.assertIs(caught.exception, error)

    def test_evaluation_exception_propagates_and_stops_grid(self):
        error = RuntimeError("evaluation failed")
        with patch.object(sensitivity, "evaluate_train_test_split", side_effect=error) as core:
            with self.assertRaises(RuntimeError) as caught:
                self.run_grid()
            self.assertEqual(core.call_count, 1)
        self.assertIs(caught.exception, error)

    def test_pipeline_and_equity_errors_propagate(self):
        for name in ("run_backtest_pipeline", "calculate_gross_mark_to_market_equity",
                     "calculate_net_mark_to_market_equity"):
            error = RuntimeError(name + " failed")
            with self.subTest(helper=name), patch.object(evaluation, name, side_effect=error) as helper:
                with self.assertRaises(RuntimeError) as caught:
                    self.run_grid()
                self.assertIs(caught.exception, error)
                self.assertEqual(helper.call_count, 1)

    def test_each_analytics_exception_propagates(self):
        for name in ("summarize_trade_time_metrics", "summarize_gross_portfolio_drawdown",
                     "summarize_net_portfolio_drawdown", "summarize_risk_adjusted_performance"):
            error = RuntimeError(name + " failed")
            with self.subTest(helper=name), patch.object(sensitivity, name, side_effect=error):
                with self.assertRaises(RuntimeError) as caught:
                    self.run_grid()
                self.assertIs(caught.exception, error)

    def test_all_combinations_receive_identical_financial_and_risk_settings(self):
        parameters = dict(
            candle_interval=HOUR, train_fraction=0.5, initial_capital=3210.0,
            fee_rate=0.001, slippage_rate=0.0005, position_fraction=0.37,
        )
        risk = dict(periods_per_year=100.0, risk_free_return_per_period=0.001,
                    minimum_acceptable_return_per_period=0.002)
        with patch.object(sensitivity, "evaluate_train_test_split", wraps=evaluate_train_test_split) as core, \
             patch.object(sensitivity, "summarize_risk_adjusted_performance", wraps=summarize_risk_adjusted_performance) as analytics:
            self.run_grid(**parameters, **risk, strategy_kwargs={"tag": "same"})
        self.assertEqual(core.call_count, 4)
        for call, (exit_after, entry_after) in zip(core.call_args_list, product([3, 2], [0, 1])):
            self.assertIs(call.args[0], self.source)
            self.assertIs(call.args[1], timed_strategy)
            self.assertEqual(call.kwargs, dict(
                **parameters, strategy_kwargs=dict(tag="same", exit_after=exit_after, entry_after=entry_after),
            ))
        self.assertEqual(analytics.call_count, 16)
        for call in analytics.call_args_list:
            self.assertEqual(call.kwargs, risk)

    def test_exposure_and_analytics_receive_canonical_paths_and_full_clock(self):
        captured = []
        def core(*args, **kwargs):
            result = evaluate_train_test_split(*args, **kwargs)
            captured.append(result)
            return result
        with patch.object(sensitivity, "evaluate_train_test_split", side_effect=core), \
             patch.object(sensitivity, "summarize_trade_time_metrics", wraps=summarize_trade_time_metrics) as time, \
             patch.object(sensitivity, "summarize_gross_portfolio_drawdown", wraps=summarize_gross_portfolio_drawdown) as gross, \
             patch.object(sensitivity, "summarize_net_portfolio_drawdown", wraps=summarize_net_portfolio_drawdown) as net, \
             patch.object(sensitivity, "summarize_risk_adjusted_performance", wraps=summarize_risk_adjusted_performance) as risk:
            self.run_grid({"exit_after": [None]})
        for index, key in enumerate(("in_sample", "out_of_sample")):
            segment = captured[0][key]
            path = segment["gross_equity"]
            self.assertIs(time.call_args_list[index].args[0], segment["trades"])
            self.assertEqual(time.call_args_list[index].args[1:],
                             (path.valuation_time.iloc[0], path.valuation_time.iloc[-1]))
            self.assertIs(gross.call_args_list[index].args[0], path)
            self.assertIs(net.call_args_list[index].args[0], segment["net_equity"])
            self.assertIs(risk.call_args_list[2 * index].args[0], path)
            self.assertIs(risk.call_args_list[2 * index + 1].args[0], segment["net_equity"])

    def test_invalid_analytics_assumptions_are_delegated(self):
        for kwargs in ({"periods_per_year": 0}, {"risk_free_return_per_period": True},
                       {"minimum_acceptable_return_per_period": np.nan}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.run_grid(**kwargs)

    def test_source_grid_and_common_kwargs_preserved_after_success(self):
        common = {"tag": "unchanged"}
        before_source, before_grid, before_common = self.source.copy(deep=True), deepcopy(self.grid), deepcopy(common)
        self.run_grid(strategy_kwargs=common)
        pd.testing.assert_frame_equal(self.source, before_source, check_exact=True)
        self.assertEqual(self.grid, before_grid)
        self.assertEqual(common, before_common)

    def test_source_grid_and_common_kwargs_preserved_after_failure(self):
        grid, common = {"exit_after": [2, 0, 3]}, {"tag": "unchanged"}
        before_source, before_grid, before_common = self.source.copy(deep=True), deepcopy(grid), deepcopy(common)
        with self.assertRaises(ValueError):
            self.run_grid(grid, strategy_kwargs=common)
        pd.testing.assert_frame_equal(self.source, before_source, check_exact=True)
        self.assertEqual(grid, before_grid)
        self.assertEqual(common, before_common)

    def test_mutable_candidate_and_common_values_are_isolated_per_run(self):
        grid, common = {"settings": [[2], [3]]}, {"notes": ["original"]}
        before = deepcopy((grid, common))
        seen = []
        def generator(frame, *, settings, notes):
            seen.append((settings.copy(), notes.copy()))
            exit_after = settings[0]
            settings.append(99)
            notes.append("changed")
            frame["open"] = 9999.0
            return timed_strategy(frame, exit_after=exit_after)
        source_before = self.source.copy(deep=True)
        self.run_grid(grid, generator=generator, strategy_kwargs=common)
        self.assertEqual((grid, common), before)
        # Stage 8.2 shares kwargs inside one IS/OOS evaluation. The next grid
        # combination must still start from the caller's original settings.
        self.assertEqual(seen, [
            ([2], ["original"]), ([2, 99], ["original", "changed"]),
            ([3], ["original"]), ([3, 99], ["original", "changed"]),
        ])
        pd.testing.assert_frame_equal(self.source, source_before, check_exact=True)

    def test_repeated_evaluation_is_exactly_deterministic(self):
        first, second = self.run_grid(), self.run_grid()
        for key in ("split_index", "split_timestamp", "parameter_names"):
            self.assertEqual(first[key], second[key])
        pd.testing.assert_frame_equal(first["results"], second["results"], check_exact=True)


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class BTCParameterSensitivityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_hash = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash != FROZEN_SHA256:
            raise AssertionError("Frozen BTC snapshot hash mismatch: " + cls.raw_hash)
        cls.source = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        cls.before = cls.source.copy(deep=True)
        cls.grid = {"fast_span": [10, 15, 20, 25, 30], "slow_span": [40, 50, 60, 70, 80]}
        cls.parameters = dict(
            candle_interval=HOUR, train_fraction=0.70, initial_capital=INITIAL_CAPITAL,
            fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE, position_fraction=1.0,
        )
        cls.result = evaluate_parameter_sensitivity(
            cls.source, generate_ema_signals, cls.grid, **cls.parameters,
            strategy_kwargs={"warmup_candles": 50}, **RISK_KWARGS,
        )

    def test_canonical_grid_has_25_rows_in_exact_product_order(self):
        self.assertEqual(self.result["parameter_names"], ("fast_span", "slow_span"))
        table = self.result["results"]
        self.assertEqual(len(table), 25)
        self.assertEqual(list(table[["fast_span", "slow_span"]].itertuples(index=False, name=None)),
                         list(product(self.grid["fast_span"], self.grid["slow_span"])))
        self.assertEqual(table.columns.tolist(), ["fast_span", "slow_span", *METRIC_COLUMNS])
        pd.testing.assert_index_equal(table.index, pd.RangeIndex(25), exact=True)

    def test_default_btc_split_remains_6132_2628(self):
        self.assertEqual(len(self.source), 8760)
        self.assertEqual(self.result["split_index"], 6132)
        self.assertEqual(len(self.source) - self.result["split_index"], 2628)
        self.assertEqual(self.result["split_timestamp"], pd.Timestamp("2026-06-13 12:00", tz="UTC"))

    def test_20_50_baseline_row_matches_direct_evaluation_and_analytics(self):
        direct = evaluate_train_test_split(
            self.source, generate_ema_signals, **self.parameters,
            strategy_kwargs=dict(fast_span=20, slow_span=50, warmup_candles=50),
        )
        table = self.result["results"]
        baseline = table.loc[table.fast_span.eq(20) & table.slow_span.eq(50)]
        self.assertEqual(len(baseline), 1)
        assert_metrics_equal(baseline.iloc[0], direct_metrics(direct))

    def test_local_snapshot_and_source_are_preserved(self):
        pd.testing.assert_frame_equal(self.source, self.before, check_exact=True)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash)
