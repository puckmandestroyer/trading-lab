"""Two-dimensional adjacency, finite local statistics, and frozen BTC grids."""

from contextlib import ExitStack
from copy import deepcopy
import hashlib
from itertools import product
from types import MappingProxyType
import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_lab.data.market_data import load_ohlcv_csv
from trading_lab.robustness import analyze_parameter_stability, evaluate_parameter_sensitivity
from trading_lab.robustness import stability
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_ema_generic_regression import (
    END, FEE_RATE, FROZEN_SHA256, HOUR, INITIAL_CAPITAL, RAW_BTC,
    SLIPPAGE_RATE, START,
)


DIAGNOSTICS = [
    "metric_value", "neighbor_count", "finite_neighbor_count",
    "neighbor_mean", "neighbor_std", "neighbor_min", "neighbor_max",
    "mean_absolute_delta", "max_absolute_delta", "local_min", "local_max", "local_range",
]
FLOAT_DIAGNOSTICS = [name for name in DIAGNOSTICS
                     if name not in ("neighbor_count", "finite_neighbor_count")]


def synthetic_surface(values=None, *, alpha=(1, 2, 3), beta=(10, 20, 30)):
    pairs = list(product(alpha, beta))
    values = np.arange(1, len(pairs) + 1, dtype="float64") if values is None else values
    results = pd.DataFrame(pairs, columns=["alpha", "beta"])
    results["metric"] = values
    return dict(
        split_index=7, split_timestamp=pd.Timestamp("2025-01-01", tz="UTC"),
        parameter_names=("alpha", "beta"), results=results,
    )


def assert_manual_statistics(test, row, center, neighbor_values):
    """Straightforward NumPy reference from explicitly identified neighbors."""
    neighbors = np.asarray(neighbor_values, dtype="float64")
    finite = neighbors[np.isfinite(neighbors)]
    test.assertEqual(row.neighbor_count, len(neighbors))
    test.assertEqual(row.finite_neighbor_count, len(finite))
    expected = {
        "neighbor_mean": np.mean(finite) if len(finite) else np.nan,
        "neighbor_std": np.std(finite, ddof=1) if len(finite) > 1 else np.nan,
        "neighbor_min": np.min(finite) if len(finite) else np.nan,
        "neighbor_max": np.max(finite) if len(finite) else np.nan,
    }
    deltas = np.abs(finite - center) if np.isfinite(center) else np.array([])
    expected["mean_absolute_delta"] = np.mean(deltas) if len(deltas) else np.nan
    expected["max_absolute_delta"] = np.max(deltas) if len(deltas) else np.nan
    region = np.concatenate((finite, [center])) if np.isfinite(center) else finite
    expected["local_min"] = np.min(region) if len(region) else np.nan
    expected["local_max"] = np.max(region) if len(region) else np.nan
    expected["local_range"] = np.ptp(region) if len(region) else np.nan
    np.testing.assert_allclose(
        row[list(expected)].to_numpy(dtype="float64"), list(expected.values()),
        rtol=1e-12, atol=1e-14, equal_nan=True,
    )


class ParameterStabilityTests(unittest.TestCase):
    def setUp(self):
        self.source = synthetic_surface()

    def test_explicit_package_import_and_exact_return_key_order(self):
        import trading_lab.robustness as robustness
        self.assertIs(robustness.analyze_parameter_stability, stability.analyze_parameter_stability)
        self.assertEqual(robustness.__all__, [
            "chronological_split", "evaluate_strategy_segment", "evaluate_train_test_split",
        ])
        result = analyze_parameter_stability(self.source, "metric")
        self.assertEqual(list(result), [
            "parameter_names", "metric", "parameter_levels", "surface", "local_stability",
        ])
        self.assertEqual(result["parameter_names"], ("alpha", "beta"))
        self.assertEqual(result["metric"], "metric")

    def test_exact_surface_local_columns_and_range_indices(self):
        result = analyze_parameter_stability(self.source, "metric")
        self.assertEqual(result["surface"].columns.tolist(), ["alpha", "beta", "metric"])
        self.assertEqual(result["local_stability"].columns.tolist(), ["alpha", "beta", *DIAGNOSTICS])
        for key in ("surface", "local_stability"):
            pd.testing.assert_index_equal(result[key].index, pd.RangeIndex(9), exact=True)
            pd.testing.assert_frame_equal(
                result[key][["alpha", "beta"]], self.source["results"][["alpha", "beta"]], check_exact=True,
            )

    def test_counts_int64_and_all_other_diagnostics_float64(self):
        local = analyze_parameter_stability(self.source, "metric")["local_stability"]
        for name in ("neighbor_count", "finite_neighbor_count"):
            self.assertEqual(local[name].dtype, "int64")
        for name in FLOAT_DIAGNOSTICS:
            self.assertEqual(local[name].dtype, "float64")
        self.assertEqual(local.alpha.dtype, self.source["results"].alpha.dtype)
        self.assertEqual(local.beta.dtype, self.source["results"].beta.dtype)

    def test_corner_edge_interior_match_exact_manual_neighbors(self):
        local = analyze_parameter_stability(self.source, "metric")["local_stability"]
        for index, center, neighbors in (
            (0, 1.0, [2, 4, 5]),
            (1, 2.0, [1, 3, 4, 5, 6]),
            (4, 5.0, [1, 2, 3, 4, 6, 7, 8, 9]),
        ):
            with self.subTest(index=index):
                assert_manual_statistics(self, local.iloc[index], center, neighbors)
        self.assertEqual(local.neighbor_count.tolist(), [3, 5, 3, 5, 8, 5, 3, 5, 3])

    def test_center_uses_sample_std_and_excludes_self_from_neighbor_statistics(self):
        values = np.ones(9)
        values[4] = 100.0
        row = analyze_parameter_stability(synthetic_surface(values), "metric")["local_stability"].iloc[4]
        self.assertEqual(row.neighbor_mean, 1.0)
        self.assertEqual(row.neighbor_std, 0.0)
        self.assertEqual((row.neighbor_min, row.neighbor_max), (1.0, 1.0))
        self.assertEqual((row.local_min, row.local_max, row.local_range), (1.0, 100.0, 99.0))
        row = analyze_parameter_stability(self.source, "metric")["local_stability"].iloc[4]
        self.assertAlmostEqual(row.neighbor_std, np.sqrt(60 / 7))
        self.assertNotEqual(row.neighbor_std, np.sqrt(60 / 8))

    def test_absolute_deltas_keep_metric_units(self):
        row = analyze_parameter_stability(self.source, "metric")["local_stability"].iloc[4]
        self.assertEqual(row.mean_absolute_delta, 2.5)
        self.assertEqual(row.max_absolute_delta, 4.0)
        scaled = synthetic_surface(np.arange(1, 10, dtype="float64") * 10)
        other = analyze_parameter_stability(scaled, "metric")["local_stability"].iloc[4]
        self.assertEqual(other.mean_absolute_delta, row.mean_absolute_delta * 10)
        self.assertEqual(other.max_absolute_delta, row.max_absolute_delta * 10)
        self.assertEqual(other.local_range, row.local_range * 10)

    def test_parameter_levels_first_occurrence_and_unsorted_adjacency(self):
        source = synthetic_surface(alpha=(20, 10, 30), beta=(200, 100))
        result = analyze_parameter_stability(source, "metric")
        self.assertEqual(list(result["parameter_levels"]), ["alpha", "beta"])
        self.assertEqual(result["parameter_levels"], {"alpha": (20, 10, 30), "beta": (200, 100)})
        pd.testing.assert_frame_equal(result["surface"], source["results"], check_exact=True)
        # 20 is the supplied corner level, adjacent to 10 but not 30.
        assert_manual_statistics(self, result["local_stability"].iloc[0], 1.0, [2, 3, 4])

    def test_irregular_spacing_and_string_labels_do_not_define_distance(self):
        for alpha, beta in (((10, 15, 1000), (1, 2, 500)),
                            (("third", "first", "second"), ("z", "a", "b"))):
            with self.subTest(alpha=alpha):
                source = synthetic_surface(alpha=alpha, beta=beta)
                result = analyze_parameter_stability(source, "metric")
                self.assertEqual(result["parameter_levels"], {"alpha": alpha, "beta": beta})
                assert_manual_statistics(self, result["local_stability"].iloc[0], 1.0, [2, 4, 5])
                pd.testing.assert_series_equal(result["local_stability"].alpha, source["results"].alpha, check_exact=True)

    def test_5_by_5_geometry_has_four_corners_twelve_edges_nine_interiors(self):
        source = synthetic_surface(alpha=range(5), beta=range(5))
        local = analyze_parameter_stability(source, "metric")["local_stability"]
        self.assertEqual(local.neighbor_count.value_counts().to_dict(), {5: 12, 8: 9, 3: 4})

    def test_single_cell_has_no_neighbors_and_finite_local_range_zero(self):
        source = synthetic_surface([7.0], alpha=(1,), beta=(10,))
        row = analyze_parameter_stability(source, "metric")["local_stability"].iloc[0]
        assert_manual_statistics(self, row, 7.0, [])
        self.assertEqual(row.neighbor_count, 0)
        self.assertEqual((row.local_min, row.local_max, row.local_range), (7.0, 7.0, 0.0))

    def test_single_axis_neighbors_clip_without_wrapping(self):
        source = synthetic_surface([1.0, 2.0, 3.0], alpha=(1,), beta=(10, 20, 30))
        local = analyze_parameter_stability(source, "metric")["local_stability"]
        self.assertEqual(local.neighbor_count.tolist(), [1, 2, 1])
        assert_manual_statistics(self, local.iloc[0], 1.0, [2.0])

    def test_zero_finite_neighbors_keep_undefined_summaries_and_deltas(self):
        source = synthetic_surface([10.0, np.nan, np.inf, -np.inf], alpha=(1, 2), beta=(10, 20))
        row = analyze_parameter_stability(source, "metric")["local_stability"].iloc[0]
        assert_manual_statistics(self, row, 10.0, [np.nan, np.inf, -np.inf])
        self.assertEqual(row.neighbor_count, 3)
        self.assertEqual(row.finite_neighbor_count, 0)
        self.assertTrue(row[["neighbor_mean", "neighbor_std", "neighbor_min", "neighbor_max",
                             "mean_absolute_delta", "max_absolute_delta"]].isna().all())

    def test_one_finite_neighbor_has_nan_sample_std(self):
        source = synthetic_surface([10.0, 4.0, np.nan, np.inf], alpha=(1, 2), beta=(10, 20))
        row = analyze_parameter_stability(source, "metric")["local_stability"].iloc[0]
        assert_manual_statistics(self, row, 10.0, [4.0, np.nan, np.inf])
        self.assertEqual(row.finite_neighbor_count, 1)
        self.assertEqual(row.neighbor_mean, 4.0)
        self.assertTrue(np.isnan(row.neighbor_std))

    def test_nonfinite_center_has_nan_deltas_and_finite_neighbor_local_region(self):
        for center in (np.nan, np.inf, -np.inf):
            with self.subTest(center=center):
                source = synthetic_surface([center, 2.0, 4.0, 6.0], alpha=(1, 2), beta=(10, 20))
                row = analyze_parameter_stability(source, "metric")["local_stability"].iloc[0]
                assert_manual_statistics(self, row, center, [2.0, 4.0, 6.0])
                self.assertTrue(np.isnan(row.mean_absolute_delta))
                self.assertTrue(np.isnan(row.max_absolute_delta))
                self.assertEqual((row.local_min, row.local_max, row.local_range), (2.0, 6.0, 4.0))

    def test_all_nonfinite_surface_preserved_without_dropping_cells(self):
        values = [np.nan, np.inf, -np.inf, np.nan]
        source = synthetic_surface(values, alpha=(1, 2), beta=(10, 20))
        result = analyze_parameter_stability(source, "metric")
        pd.testing.assert_frame_equal(result["surface"], source["results"], check_exact=True)
        local = result["local_stability"]
        np.testing.assert_array_equal(local.metric_value, values)
        self.assertEqual(len(local), 4)
        self.assertEqual(local.neighbor_count.tolist(), [3, 3, 3, 3])
        self.assertTrue(local.finite_neighbor_count.eq(0).all())
        self.assertTrue(local[FLOAT_DIAGNOSTICS[1:]].isna().all().all())

    def test_mixed_nonfinite_grid_excludes_only_nonfinite_neighbors(self):
        values = [np.nan, 2.0, np.inf, 4.0, 5.0, 6.0, -np.inf, 8.0, 9.0]
        source = synthetic_surface(values)
        result = analyze_parameter_stability(source, "metric")
        pd.testing.assert_frame_equal(result["surface"], source["results"], check_exact=True)
        row = result["local_stability"].iloc[4]
        assert_manual_statistics(self, row, 5.0, [np.nan, 2, np.inf, 4, 6, -np.inf, 8, 9])
        self.assertEqual(row.neighbor_count, 8)
        self.assertEqual(row.finite_neighbor_count, 5)

    def test_plateau_like_case_reports_small_variation(self):
        source = synthetic_surface(1 + np.linspace(-0.04, 0.04, 9))
        row = analyze_parameter_stability(source, "metric")["local_stability"].iloc[4]
        self.assertLess(row.mean_absolute_delta, 0.05)
        self.assertLess(row.local_range, 0.1)

    def test_spike_like_case_has_larger_variation_than_plateau(self):
        values = 1 + np.linspace(-0.04, 0.04, 9)
        plateau = analyze_parameter_stability(synthetic_surface(values), "metric")["local_stability"].iloc[4]
        values[4] = 101.0
        spike = analyze_parameter_stability(synthetic_surface(values), "metric")["local_stability"].iloc[4]
        self.assertGreater(spike.mean_absolute_delta, plateau.mean_absolute_delta * 100)
        self.assertGreater(spike.local_range, plateau.local_range * 100)

    def test_metric_direction_does_not_change_absolute_variation(self):
        positive = analyze_parameter_stability(self.source, "metric")["local_stability"]
        negative = analyze_parameter_stability(synthetic_surface(-np.arange(1, 10)), "metric")["local_stability"]
        for column in ("neighbor_std", "mean_absolute_delta", "max_absolute_delta", "local_range"):
            np.testing.assert_array_equal(positive[column], negative[column])

    def test_no_classification_score_ranking_or_selection_output(self):
        result = analyze_parameter_stability(self.source, "metric")
        forbidden = {
            "stable", "plateau", "fragile", "rank", "score", "selected", "best",
            "winner", "recommendation", "stability_score", "robustness_score",
            "better_neighbor_count", "local_best", "global_best",
        }
        self.assertTrue(forbidden.isdisjoint(result))
        self.assertTrue(forbidden.isdisjoint(result["local_stability"].columns))

    def test_analysis_does_not_call_sensitivity_oos_or_backtest(self):
        forbidden = (
            "trading_lab.robustness.evaluate_parameter_sensitivity",
            "trading_lab.robustness.sensitivity.evaluate_parameter_sensitivity",
            "trading_lab.robustness.evaluate_train_test_split",
            "trading_lab.robustness.evaluation.evaluate_train_test_split",
            "trading_lab.backtest.pipeline.run_backtest_pipeline",
        )
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(path, side_effect=AssertionError("Backtest rerun")))
                     for path in forbidden]
            analyze_parameter_stability(self.source, "metric")
            for mock in mocks:
                mock.assert_not_called()

    def test_invalid_mapping_or_missing_canonical_fields_rejected(self):
        invalid = [None, [], "result", {}]
        invalid.extend({k: v for k, v in self.source.items() if k != missing} for missing in self.source)
        for source in invalid:
            with self.subTest(source=repr(source)), self.assertRaisesRegex(ValueError, "canonical fields"):
                analyze_parameter_stability(source, "metric")

    def test_exactly_two_distinct_nonempty_parameter_names_required(self):
        invalid = (None, ["alpha", "beta"], (), ("alpha",), ("alpha", "beta", "gamma"),
                   ("alpha", "alpha"), ("", "beta"), (1, "beta"))
        for names in invalid:
            with self.subTest(names=names), self.assertRaisesRegex(ValueError, "two distinct"):
                analyze_parameter_stability({**self.source, "parameter_names": names}, "metric")

    def test_non_dataframe_and_empty_results_rejected(self):
        for table in (None, [], {}, self.source["results"].iloc[:0]):
            with self.subTest(table=repr(table)), self.assertRaisesRegex(ValueError, "non-empty pandas DataFrame"):
                analyze_parameter_stability({**self.source, "results": table}, "metric")

    def test_missing_parameter_column_and_duplicate_columns_rejected(self):
        table = self.source["results"]
        for malformed in (table.drop(columns="alpha"), pd.concat([table, table[["alpha"]]], axis=1)):
            with self.subTest(columns=malformed.columns.tolist()), self.assertRaises(ValueError):
                analyze_parameter_stability({**self.source, "results": malformed}, "metric")

    def test_source_must_have_canonical_range_index(self):
        for index in (pd.Index(np.arange(9)), pd.RangeIndex(1, 10), pd.RangeIndex(0, 18, 2)):
            table = self.source["results"].copy()
            table.index = index
            with self.subTest(index=index), self.assertRaisesRegex(ValueError, "RangeIndex"):
                analyze_parameter_stability({**self.source, "results": table}, "metric")

    def test_missing_invalid_or_parameter_metric_rejected(self):
        for metric in (None, 1, "", "missing", "alpha", "beta"):
            with self.subTest(metric=metric), self.assertRaisesRegex(ValueError, "metric"):
                analyze_parameter_stability(self.source, metric)

    def test_nonnumeric_bool_and_complex_metric_dtypes_rejected(self):
        for values in (["1"] * 9, pd.Series(range(9), dtype="object"), [True] * 9, [1 + 2j] * 9):
            table = self.source["results"].copy()
            table["metric"] = values
            with self.subTest(dtype=table.metric.dtype), self.assertRaisesRegex(ValueError, "numeric dtype"):
                analyze_parameter_stability({**self.source, "results": table}, "metric")

    def test_duplicate_pairs_rejected_even_when_row_count_matches_rectangle(self):
        table = self.source["results"].copy()
        table.loc[4, ["alpha", "beta"]] = table.loc[0, ["alpha", "beta"]]
        with self.assertRaisesRegex(ValueError, "Duplicate parameter pairs"):
            analyze_parameter_stability({**self.source, "results": table}, "metric")

    def test_missing_cartesian_cell_rejected_without_repair(self):
        table = self.source["results"].drop(index=4).reset_index(drop=True)
        before = table.copy(deep=True)
        with self.assertRaisesRegex(ValueError, "complete rectangular"):
            analyze_parameter_stability({**self.source, "results": table}, "metric")
        pd.testing.assert_frame_equal(table, before, check_exact=True)

    def test_missing_unhashable_and_diagnostic_collision_labels_rejected(self):
        for value in (np.nan, None, [1, 2]):
            table = self.source["results"].copy()
            table["alpha"] = table.alpha.astype("object")
            table.at[0, "alpha"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "labels"):
                analyze_parameter_stability({**self.source, "results": table}, "metric")
        table = self.source["results"].rename(columns={"alpha": "neighbor_mean"})
        with self.assertRaisesRegex(ValueError, "collide"):
            analyze_parameter_stability({**self.source, "parameter_names": ("neighbor_mean", "beta"),
                                         "results": table}, "metric")

    def test_integer_count_and_float_exposure_metrics_accepted(self):
        table = self.source["results"]
        table["oos_trade_count"] = np.arange(9, dtype="int64")
        table["is_exposure_ratio"] = np.linspace(0, 1, 9)
        for metric in ("oos_trade_count", "is_exposure_ratio"):
            with self.subTest(metric=metric):
                result = analyze_parameter_stability(self.source, metric)
                pd.testing.assert_series_equal(result["surface"][metric], table[metric], check_exact=True)
                self.assertEqual(result["local_stability"].metric_value.dtype, "float64")

    def test_read_only_mapping_with_extra_fields_accepted(self):
        source = MappingProxyType({**self.source, "research_note": "unchanged"})
        result = analyze_parameter_stability(source, "metric")
        pd.testing.assert_frame_equal(result["surface"], self.source["results"], check_exact=True)

    def test_inputs_preserved_and_returned_frames_are_independent(self):
        before = deepcopy(self.source)
        result = analyze_parameter_stability(self.source, "metric")
        self.assertIsNot(result["surface"], self.source["results"])
        self.assertIsNot(result["surface"], result["local_stability"])
        local_before = result["local_stability"].copy(deep=True)
        result["surface"].loc[0, ["alpha", "metric"]] = [999, -999]
        pd.testing.assert_frame_equal(result["local_stability"], local_before, check_exact=True)
        result["local_stability"].loc[0, "metric_value"] = -888
        result["parameter_levels"]["alpha"] = (999,)
        pd.testing.assert_frame_equal(self.source["results"], before["results"], check_exact=True)
        for key in ("split_index", "split_timestamp", "parameter_names"):
            self.assertEqual(self.source[key], before[key])

    def test_repeated_analysis_is_exactly_deterministic(self):
        first = analyze_parameter_stability(self.source, "metric")
        second = analyze_parameter_stability(self.source, "metric")
        for key in ("parameter_names", "parameter_levels", "metric"):
            self.assertEqual(first[key], second[key])
        for key in ("surface", "local_stability"):
            pd.testing.assert_frame_equal(first[key], second[key], check_exact=True)


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class BTCParameterStabilityIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_hash = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash != FROZEN_SHA256:
            raise AssertionError("Frozen BTC snapshot hash mismatch: " + cls.raw_hash)
        cls.candles = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        cls.candles_before = cls.candles.copy(deep=True)
        cls.source = evaluate_parameter_sensitivity(
            cls.candles, generate_ema_signals,
            {"fast_span": [10, 15, 20, 25, 30], "slow_span": [40, 50, 60, 70, 80]},
            candle_interval=HOUR, train_fraction=0.70, strategy_kwargs={"warmup_candles": 50},
            initial_capital=INITIAL_CAPITAL, fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE,
            position_fraction=1.0, periods_per_year=8760,
            risk_free_return_per_period=0.0, minimum_acceptable_return_per_period=0.0,
        )
        cls.before = deepcopy(cls.source)
        cls.metrics = ("oos_net_final_equity", "oos_net_sharpe", "oos_net_max_portfolio_drawdown")
        cls.analyses = {metric: analyze_parameter_stability(cls.source, metric) for metric in cls.metrics}

    def test_canonical_25_cell_grid_accepted_for_three_oos_net_metrics(self):
        self.assertEqual(len(self.candles), 8760)
        self.assertEqual(self.source["split_index"], 6132)
        self.assertEqual(self.source["split_timestamp"], pd.Timestamp("2026-06-13 12:00", tz="UTC"))
        for metric, result in self.analyses.items():
            with self.subTest(metric=metric):
                self.assertEqual(len(result["surface"]), 25)
                self.assertEqual(len(result["local_stability"]), 25)
                self.assertEqual(result["parameter_levels"], {
                    "fast_span": (10, 15, 20, 25, 30), "slow_span": (40, 50, 60, 70, 80),
                })
                pd.testing.assert_frame_equal(
                    result["surface"], self.source["results"][["fast_span", "slow_span", metric]],
                    check_exact=True,
                )

    def test_btc_corner_edge_and_interior_geometry(self):
        for metric, result in self.analyses.items():
            with self.subTest(metric=metric):
                local = result["local_stability"].set_index(["fast_span", "slow_span"])
                self.assertEqual(local.loc[(10, 40), "neighbor_count"], 3)
                self.assertEqual(local.loc[(10, 50), "neighbor_count"], 5)
                self.assertEqual(local.loc[(20, 50), "neighbor_count"], 8)
                self.assertEqual(local.neighbor_count.value_counts().to_dict(), {5: 12, 8: 9, 3: 4})

    def test_20_50_statistics_match_exact_eight_geometric_neighbors(self):
        pairs = [(15, 40), (15, 50), (15, 60), (20, 40),
                 (20, 60), (25, 40), (25, 50), (25, 60)]
        indexed = self.source["results"].set_index(["fast_span", "slow_span"])
        for metric, result in self.analyses.items():
            with self.subTest(metric=metric):
                local = result["local_stability"]
                row = local.loc[local.fast_span.eq(20) & local.slow_span.eq(50)].iloc[0]
                center = indexed.loc[(20, 50), metric]
                neighbors = [indexed.loc[pair, metric] for pair in pairs]
                assert_manual_statistics(self, row, center, neighbors)
                self.assertEqual(row.neighbor_count, 8)

    def test_sensitivity_candles_and_local_snapshot_preserved(self):
        pd.testing.assert_frame_equal(self.source["results"], self.before["results"], check_exact=True)
        for key in ("split_index", "split_timestamp", "parameter_names"):
            self.assertEqual(self.source[key], self.before[key])
        pd.testing.assert_frame_equal(self.candles, self.candles_before, check_exact=True)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash)
