"""Frozen BTC regression for full and fixed partial portfolio allocation.

Stage 5/6 references and tolerances stay unchanged. Partial literals were
captured once through production APIs on the same hash-checked local snapshot.
Only a missing local snapshot permits a skip; no data is downloaded.
"""

import ast
import hashlib
import inspect
import unittest

import numpy as np
import pandas as pd

from trading_lab.analytics import (
    benchmark, drawdown, equity, portfolio_drawdown, risk_adjusted,
    trade_metrics, trade_time,
)
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.pipeline import run_backtest_pipeline, run_ema_execution_pipeline
from trading_lab.backtest.trades import build_trade_ledger
from trading_lab.data.market_data import load_ohlcv_csv
from trading_lab.strategies.ema_trend import generate_ema_signals
from tests.test_ema_generic_regression import (
    END, EXECUTION_COLUMNS, FEE_RATE, FROZEN_SHA256, HOUR, INITIAL_CAPITAL,
    RAW_BTC, RISK_REFERENCES, SLIPPAGE_RATE, START,
)


FRACTIONS = (1.0, 0.5, 0.25)
RESULT_KEYS = ["execution", "trades", "gross_results", "net_results"]
EQUITY_COLUMNS = [
    "observation", "candle_timestamp", "valuation_time", "mark_price", "position",
    "active_trade_id", "cash", "quantity", "position_value", "unrealized_pnl", "equity",
]
METRIC_COLUMNS = [
    "closed_trade_count", "winning_trade_count", "losing_trade_count", "breakeven_trade_count",
    "win_rate", "loss_rate", "breakeven_rate", "average_trade_return", "median_trade_return",
    "average_win_return", "average_loss_return", "best_trade_return", "worst_trade_return",
    "total_realized_pnl", "expectancy_pnl", "profit_factor",
]
REALIZED_COLUMNS = [
    "observation", "closed_trade_number", "capital", "running_peak", "drawdown", "drawdown_amount",
]
PORTFOLIO_COLUMNS = [
    "observation", "valuation_time", "equity", "running_peak", "drawdown", "drawdown_amount",
]
PORTFOLIO_SUMMARY_COLUMNS = [
    "max_portfolio_drawdown", "max_portfolio_drawdown_amount", "peak_observation",
    "trough_observation", "peak_valuation_time", "trough_valuation_time", "peak_equity", "trough_equity",
]
RETURN_COLUMNS = [
    "observation", "period_start_time", "period_end_time",
    "starting_equity", "ending_equity", "period_return",
]
TIME_REFERENCES = {
    "closed_trade_count": 77, "open_trade_count": 1,
    "average_closed_duration_hours": 52.96103896103896,
    "median_closed_duration_hours": 34.0, "minimum_closed_duration_hours": 1.0,
    "maximum_closed_duration_hours": 226.0, "total_closed_duration_hours": 4078.0,
    "open_observed_duration_hours": 11.0, "total_time_in_market_hours": 4089.0,
    "observation_window_hours": 8760.0, "exposure_ratio": 0.46678082191780823,
}
# Same literals/precision as the unchanged Stage 6 frozen regression.
TRADE_REFERENCES = {
    "GROSS": [
        .259740259740, .740259740260, 0.0, .000070588288, -.008735290732,
        .038651616726, -.013466614673, .224171061391, -.043755772679,
        -358.888611656, -4.660891060, .945165760246,
    ],
    "NET": [
        .259740259740, .740259740260, 0.0, -.002925128404, -.011704629367,
        .035540330361, -.016421780603, .220504050556, -.046620207277,
        -2347.469836563, -30.486621254, .675088667158,
    ],
}
# Literal results of the reviewed one-off capture; never derived at runtime.
PARTIAL_REFERENCES = {
    0.5: {
        "last_closed_gross": 9918.391236748259,
        "last_closed_net": 8837.511197655364,
        "final_gross_mtm": 9820.851361993184,
        "final_net_mtm": 8744.110764994484,
        "realized_gross_dd": -0.14248540505494767,
        "realized_net_dd": -0.20423832781018214,
        "portfolio_gross_dd": -0.14809055437971497,
        "portfolio_net_dd": -0.20920070404661006,
        "gross_sharpe": -0.058161849146260235,
        "gross_sortino": -0.08507501805626921,
        "net_sharpe": -0.8824772122392462,
        "net_sortino": -1.2814314707945054,
    },
    0.25: {
        "last_closed_gross": 9985.739621448789,
        "last_closed_net": 9426.098541539295,
        "final_gross_mtm": 9936.638523863317,
        "final_net_mtm": 9376.288042723892,
        "realized_gross_dd": -0.07357702428688317,
        "realized_net_dd": -0.1070450228128268,
        "portfolio_gross_dd": -0.07660787284120885,
        "portfolio_net_dd": -0.10983103209615619,
        "gross_sharpe": -0.054056339584623025,
        "gross_sortino": -0.07914256241587235,
        "net_sharpe": -0.8712069545635516,
        "net_sortino": -1.2663722258083463,
    },
}


def equity_paths(candles, pipeline):
    """Equity stays downstream and receives no sizing policy parameter."""
    return {
        "GROSS": equity.calculate_gross_mark_to_market_equity(
            candles, pipeline["gross_results"], HOUR, INITIAL_CAPITAL,
        ),
        "NET": equity.calculate_net_mark_to_market_equity(
            candles, pipeline["net_results"], HOUR, INITIAL_CAPITAL,
        ),
    }


def downstream_outputs(pipeline, paths):
    """Collect existing public outputs, without duplicating financial formulas."""
    gross, net = pipeline["gross_results"], pipeline["net_results"]
    outputs = {
        "time_breakdown": trade_time.calculate_trade_time_breakdown(pipeline["trades"], START, END),
        "time_summary": trade_time.summarize_trade_time_metrics(pipeline["trades"], START, END),
    }
    for label, results, metrics, realized, realized_summary, portfolio, portfolio_summary in (
        ("GROSS", gross, trade_metrics.summarize_gross_trade_performance,
         drawdown.calculate_gross_realized_drawdown, drawdown.summarize_gross_realized_drawdown,
         portfolio_drawdown.calculate_gross_portfolio_drawdown, portfolio_drawdown.summarize_gross_portfolio_drawdown),
        ("NET", net, trade_metrics.summarize_net_trade_performance,
         drawdown.calculate_net_realized_drawdown, drawdown.summarize_net_realized_drawdown,
         portfolio_drawdown.calculate_net_portfolio_drawdown, portfolio_drawdown.summarize_net_portfolio_drawdown),
    ):
        outputs[label] = {
            "metrics": metrics(results),
            "realized": realized(results, INITIAL_CAPITAL),
            "realized_summary": realized_summary(results, INITIAL_CAPITAL),
            "portfolio": portfolio(paths[label]),
            "portfolio_summary": portfolio_summary(paths[label]),
            "returns": risk_adjusted.calculate_time_based_returns(paths[label]),
            "risk": risk_adjusted.summarize_risk_adjusted_performance(
                paths[label], periods_per_year=8760, risk_free_return_per_period=0.0,
                minimum_acceptable_return_per_period=0.0, label="EMA " + label,
            ),
        }
    return outputs


def snapshot_values(pipeline, paths, analytics):
    """Select measured public fields only; expected partial values are literals."""
    values = {}
    for label, result_key, capital_column in (
        ("GROSS", "gross_results", "capital_after"),
        ("NET", "net_results", "net_capital_after"),
    ):
        key = label.lower()
        results = pipeline[result_key]
        values["last_closed_" + key] = results.loc[results.status.eq("CLOSED"), capital_column].iloc[-1]
        values["final_" + key + "_mtm"] = paths[label].equity.iloc[-1]
        values["realized_" + key + "_dd"] = analytics[label]["realized_summary"].loc[label, "max_realized_drawdown"]
        values["portfolio_" + key + "_dd"] = analytics[label]["portfolio_summary"].loc[label, "max_portfolio_drawdown"]
        values[key + "_sharpe"] = analytics[label]["risk"].loc["EMA " + label, "sharpe_ratio"]
        values[key + "_sortino"] = analytics[label]["risk"].loc["EMA " + label, "sortino_ratio"]
    return values


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class PositionSizingAnalyticsRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw_hash = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash != FROZEN_SHA256:
            raise AssertionError("Frozen BTC snapshot hash mismatch: " + cls.raw_hash)
        cls.candles = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        identity = (len(cls.candles), cls.candles.timestamp.iloc[0],
                    cls.candles.timestamp.iloc[-1], cls.candles.open.iloc[0])
        if identity != (8760, START, END - HOUR, 114_051.1):
            raise AssertionError("Frozen BTC snapshot identity mismatch: " + repr(identity))
        cls.candles_before = cls.candles.copy(deep=True)
        cls.strategies, cls.pipelines, cls.paths, cls.analytics = {}, {}, {}, {}
        cls.strategy_before, cls.pipeline_before, cls.equity_before = {}, {}, {}
        for fraction in FRACTIONS:
            strategy = generate_ema_signals(cls.candles, fast_span=20, slow_span=50, warmup_candles=50)
            cls.strategies[fraction] = strategy
            cls.strategy_before[fraction] = strategy.copy(deep=True)
            pipeline = run_backtest_pipeline(
                cls.candles, strategy, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE, fraction,
            )
            cls.pipelines[fraction] = pipeline
            cls.pipeline_before[fraction] = {key: frame.copy(deep=True) for key, frame in pipeline.items()}
            paths = equity_paths(cls.candles, pipeline)
            cls.paths[fraction] = paths
            cls.equity_before[fraction] = {label: frame.copy(deep=True) for label, frame in paths.items()}
            cls.analytics[fraction] = downstream_outputs(pipeline, paths)

        cls.default = run_backtest_pipeline(
            cls.candles, cls.strategies[1.0], INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE,
        )
        cls.default_paths = equity_paths(cls.candles, cls.default)
        cls.legacy = run_ema_execution_pipeline(cls.candles, 20, 50, 50)
        legacy_trades = build_trade_ledger(cls.legacy)
        cls.legacy_results = {
            "execution": cls.legacy[EXECUTION_COLUMNS], "trades": legacy_trades,
            "gross_results": calculate_trade_results(legacy_trades, INITIAL_CAPITAL),
            "net_results": calculate_trade_results_with_costs(
                legacy_trades, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE,
            ),
        }
        cls.legacy_paths = equity_paths(cls.candles, cls.legacy_results)
        cls.benchmarks = {
            "GROSS": benchmark.calculate_gross_buy_and_hold_benchmark(cls.candles, HOUR, INITIAL_CAPITAL),
            "NET": benchmark.calculate_net_buy_and_hold_benchmark(
                cls.candles, HOUR, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE,
            ),
        }
        cls.benchmark_before = {label: path.copy(deep=True) for label, path in cls.benchmarks.items()}

    def assert_partial_equity(self, label, result_key, basis):
        for fraction in (0.5, 0.25):
            with self.subTest(fraction=fraction, label=label):
                path, results = self.paths[fraction][label], self.pipelines[fraction][result_key]
                self.assertEqual(len(path), 8761)
                self.assertEqual(path.columns.tolist(), EQUITY_COLUMNS)
                pd.testing.assert_series_equal(path.dtypes, self.paths[1.0][label].dtypes)
                pd.testing.assert_index_equal(path.index, pd.RangeIndex(8761), exact=True)
                pd.testing.assert_series_equal(path.valuation_time, self.paths[1.0][label].valuation_time, check_exact=True)
                self.assertEqual(path.equity.iloc[0], INITIAL_CAPITAL)
                self.assertEqual(path.position.iloc[-1], 1)
                self.assertEqual(path.active_trade_id.iloc[-1], 78)
                self.assertTrue(path.cash[path.position.eq(1)].gt(0).all())
                self.assertTrue(np.isfinite(path[EQUITY_COLUMNS[6:]].to_numpy()).all())
                for trade in results.itertuples():
                    active = path.loc[path.active_trade_id.eq(trade.trade_id).fillna(False)]
                    spend = trade.quantity * getattr(trade, basis) + getattr(trade, "entry_fee", 0.0)
                    np.testing.assert_allclose(active.cash, trade.capital_before - spend, rtol=1e-12, atol=1e-12)
                    self.assertTrue(active.quantity.eq(trade.quantity).all())
                self.assertEqual(results.status.iloc[-1], "OPEN")
                capital_column = "capital_after" if label == "GROSS" else "net_capital_after"
                self.assertTrue(results.iloc[-1][["exit_time", "exit_price", capital_column]].isna().all())
                # A final OPEN mark includes reserve, with no synthetic sale.
                last = path.iloc[-1]
                self.assertEqual(last.equity, last.cash + last.quantity * self.candles.close.iloc[-1])

    def assert_partial_snapshot(self, fraction):
        actual = snapshot_values(self.pipelines[fraction], self.paths[fraction], self.analytics[fraction])
        for field, expected in PARTIAL_REFERENCES[fraction].items():
            with self.subTest(fraction=fraction, field=field):
                if field.startswith("last_closed"):
                    np.testing.assert_allclose(actual[field], expected, rtol=1e-10)
                elif field.startswith("final_"):
                    np.testing.assert_allclose(actual[field], expected, rtol=1e-12, atol=1e-9)
                else:
                    np.testing.assert_allclose(actual[field], expected, rtol=1e-12, atol=1e-14)

    def test_canonical_snapshot_identity_and_hash(self):
        self.assertEqual(len(self.candles), 8760)
        self.assertEqual(self.candles.timestamp.iloc[0], START)
        self.assertEqual(self.candles.timestamp.iloc[-1], END - HOUR)
        self.assertEqual(self.candles.open.iloc[0], 114_051.1)
        self.assertEqual(self.raw_hash, FROZEN_SHA256)

    def test_full_strategy_matches_legacy_and_frozen_intent(self):
        strategy = self.strategies[1.0]
        pd.testing.assert_frame_equal(strategy, self.legacy[strategy.columns], check_exact=True)
        self.assertEqual((int(strategy.bullish_cross.sum()), int(strategy.bearish_cross.sum())), (78, 78))
        self.assertEqual((int(strategy.signal.eq("LONG_ENTRY").sum()), int(strategy.signal.eq("LONG_EXIT").sum())), (78, 77))
        self.assertEqual(strategy.signal.iloc[:50].tolist(), ["HOLD"] * 50)
        self.assertEqual(strategy.desired_position.iloc[-1], 1)

    def test_omitted_and_explicit_full_pipeline_match_exactly(self):
        self.assertEqual(list(self.pipelines[1.0]), RESULT_KEYS)
        for key in RESULT_KEYS:
            pd.testing.assert_frame_equal(self.default[key], self.pipelines[1.0][key], check_exact=True)
            pd.testing.assert_frame_equal(self.legacy_results[key], self.pipelines[1.0][key], check_exact=True)

    def test_omitted_and_explicit_full_equity_match_exactly(self):
        for label in ("GROSS", "NET"):
            pd.testing.assert_frame_equal(self.default_paths[label], self.paths[1.0][label], check_exact=True)
            pd.testing.assert_frame_equal(self.legacy_paths[label], self.paths[1.0][label], check_exact=True)

    def test_full_execution_and_ledger_counts_and_final_open(self):
        execution, trades = self.pipelines[1.0]["execution"], self.pipelines[1.0]["trades"]
        filled = execution.execution_time.notna()
        self.assertEqual(int((filled & execution.signal.eq("LONG_ENTRY")).sum()), 78)
        self.assertEqual(int((filled & execution.signal.eq("LONG_EXIT")).sum()), 77)
        self.assertEqual((len(trades), int(trades.status.eq("CLOSED").sum()), int(trades.status.eq("OPEN").sum())), (78, 77, 1))
        self.assertEqual(trades.trade_id.tolist(), list(range(1, 79)))
        self.assertEqual(trades.entry_time.iloc[-1], pd.Timestamp("2026-09-30 13:00", tz="UTC"))
        self.assertEqual(trades.status.iloc[-1], "OPEN")
        self.assertTrue(trades.iloc[-1][["exit_time", "exit_price"]].isna().all())

    def test_full_last_closed_gross_capital_is_frozen(self):
        results = self.pipelines[1.0]["gross_results"]
        np.testing.assert_allclose(results.loc[results.status.eq("CLOSED"), "capital_after"].iloc[-1], 9641.111388344, rtol=1e-10)

    def test_full_last_closed_net_capital_is_frozen(self):
        results = self.pipelines[1.0]["net_results"]
        np.testing.assert_allclose(results.loc[results.status.eq("CLOSED"), "net_capital_after"].iloc[-1], 7652.530163437, rtol=1e-10)

    def test_full_final_gross_mtm_is_frozen(self):
        np.testing.assert_allclose(self.paths[1.0]["GROSS"].equity.iloc[-1], 9451.485313939314, rtol=1e-12, atol=1e-9)

    def test_full_final_net_mtm_is_frozen(self):
        np.testing.assert_allclose(self.paths[1.0]["NET"].equity.iloc[-1], 7490.776562851941, rtol=1e-12, atol=1e-9)

    def test_full_closed_trade_metrics_preserve_all_frozen_fields(self):
        for label, expected in TRADE_REFERENCES.items():
            summary = self.analytics[1.0][label]["metrics"]
            self.assertEqual(summary.columns.tolist(), METRIC_COLUMNS)
            self.assertEqual(tuple(summary.loc[label, METRIC_COLUMNS[:4]]), (77, 20, 57, 0))
            np.testing.assert_allclose(summary.loc[label, METRIC_COLUMNS[4:]].to_numpy(dtype=float), expected, rtol=1e-10, atol=1e-9)

    def test_full_realized_drawdown_preserves_frozen_references(self):
        for label, expected, trough in (("GROSS", -0.2672342545498746, 33), ("NET", -0.37185533262673254, 66)):
            output = self.analytics[1.0][label]
            self.assertEqual(len(output["realized"]), 78)
            self.assertEqual(int(output["realized"].drawdown.idxmin()), trough)
            np.testing.assert_allclose(output["realized_summary"].loc[label, "max_realized_drawdown"], expected, rtol=1e-12, atol=1e-14)

    def test_full_trade_time_preserves_frozen_references(self):
        summary = self.analytics[1.0]["time_summary"]
        self.assertEqual(summary.columns.tolist(), list(TIME_REFERENCES))
        np.testing.assert_allclose(summary.loc["TIME"].to_numpy(dtype=float), list(TIME_REFERENCES.values()), rtol=1e-12, atol=1e-12)
        breakdown = self.analytics[1.0]["time_breakdown"]
        self.assertEqual(breakdown.closed_duration_hours.iloc[0], 27)
        self.assertTrue(pd.isna(breakdown.closed_duration_hours.iloc[-1]))
        self.assertEqual(breakdown.observed_time_in_market_hours.iloc[-1], 11)

    def test_full_portfolio_drawdown_preserves_frozen_references(self):
        for label, expected, peak, trough in (("GROSS", -0.2767943814221776, 308, 3687), ("NET", -0.37967960980713844, 308, 7369)):
            summary = self.analytics[1.0][label]["portfolio_summary"].loc[label]
            self.assertEqual((summary.peak_observation, summary.trough_observation), (peak, trough))
            np.testing.assert_allclose(summary.max_portfolio_drawdown, expected, rtol=1e-12, atol=1e-14)

    def test_full_benchmark_preserves_frozen_values_and_alignment(self):
        for label, final, expected_dd, advantage, summarize in (
            ("GROSS", 7331.468087550229, -0.5373383889204555, 2120.017226389085, portfolio_drawdown.summarize_gross_portfolio_drawdown),
            ("NET", 7320.483701755746, -0.5373383889204554, 170.292861096195, portfolio_drawdown.summarize_net_portfolio_drawdown),
        ):
            path = self.benchmarks[label]
            self.assertEqual(len(path), 8761)
            self.assertEqual(path.position.iloc[-1], 1)
            self.assertEqual(path.active_trade_id.iloc[-1], 1)
            for column in ("observation", "valuation_time"):
                pd.testing.assert_series_equal(path[column], self.paths[1.0][label][column], check_exact=True)
            np.testing.assert_allclose(path.equity.iloc[-1], final, rtol=1e-12, atol=1e-10)
            np.testing.assert_allclose(summarize(path).loc[label, "max_portfolio_drawdown"], expected_dd, rtol=1e-12, atol=1e-14)
            np.testing.assert_allclose(self.paths[1.0][label].equity.iloc[-1] - path.equity.iloc[-1], advantage, rtol=1e-12, atol=1e-10)

    def test_full_hourly_returns_and_all_risk_adjusted_references(self):
        paths = {"EMA " + label: path for label, path in self.paths[1.0].items()}
        paths.update({"Buy & Hold " + label: path for label, path in self.benchmarks.items()})
        for label, path in paths.items():
            returns = risk_adjusted.calculate_time_based_returns(path)
            self.assertEqual(len(returns), 8760)
            self.assertEqual(returns.period_start_time.iloc[0], START)
            self.assertEqual(returns.period_end_time.iloc[-1], END)
            expected = RISK_REFERENCES[label]
            summary = risk_adjusted.summarize_risk_adjusted_performance(path, 8760, 0.0, 0.0, label)
            self.assertEqual(summary.columns.tolist(), list(expected))
            np.testing.assert_allclose(summary.loc[label].to_numpy(dtype=float), list(expected.values()), rtol=1e-12, atol=1e-14)

    def test_strategy_is_exactly_fraction_independent(self):
        for fraction in (0.5, 0.25):
            pd.testing.assert_frame_equal(self.strategies[fraction], self.strategies[1.0], check_exact=True)

    def test_execution_is_exactly_fraction_independent(self):
        for fraction in (0.5, 0.25):
            pd.testing.assert_frame_equal(self.pipelines[fraction]["execution"], self.pipelines[1.0]["execution"], check_exact=True)

    def test_ledger_is_exactly_fraction_independent(self):
        for fraction in (0.5, 0.25):
            pd.testing.assert_frame_equal(self.pipelines[fraction]["trades"], self.pipelines[1.0]["trades"], check_exact=True)

    def test_gross_closed_trade_return_is_exactly_fraction_independent(self):
        full = self.pipelines[1.0]["gross_results"]
        for fraction in (0.5, 0.25):
            partial = self.pipelines[fraction]["gross_results"]
            pd.testing.assert_series_equal(partial.loc[partial.status.eq("CLOSED"), "trade_return"], full.loc[full.status.eq("CLOSED"), "trade_return"], check_exact=True)

    def test_net_closed_trade_return_scales_with_fraction(self):
        full = self.pipelines[1.0]["net_results"]
        for fraction in (0.5, 0.25):
            partial = self.pipelines[fraction]["net_results"]
            mask = partial.status.eq("CLOSED")
            np.testing.assert_allclose(partial.loc[mask, "net_trade_return"], fraction * full.loc[mask, "net_trade_return"], rtol=1e-12, atol=1e-14)

    def test_win_loss_classification_is_fraction_independent(self):
        for key, return_column in (("gross_results", "trade_return"), ("net_results", "net_trade_return")):
            full = self.pipelines[1.0][key]
            full_returns = full.loc[full.status.eq("CLOSED"), return_column]
            for fraction in (0.5, 0.25):
                partial = self.pipelines[fraction][key]
                returns = partial.loc[partial.status.eq("CLOSED"), return_column]
                tolerance = trade_metrics.BREAKEVEN_TOLERANCE
                for actual, expected in (
                    (returns > tolerance, full_returns > tolerance),
                    (returns < -tolerance, full_returns < -tolerance),
                    (returns.abs() <= tolerance, full_returns.abs() <= tolerance),
                ):
                    pd.testing.assert_series_equal(actual, expected, check_exact=True)

    def test_duration_and_exposure_are_exactly_fraction_independent(self):
        for fraction in (0.5, 0.25):
            for key in ("time_breakdown", "time_summary"):
                pd.testing.assert_frame_equal(self.analytics[fraction][key], self.analytics[1.0][key], check_exact=True)

    def test_partial_gross_equity_includes_canonical_reserve(self):
        self.assert_partial_equity("GROSS", "gross_results", "entry_price")

    def test_partial_net_equity_includes_reserve_and_paid_entry_fee(self):
        self.assert_partial_equity("NET", "net_results", "effective_entry_price")

    def test_partial_closed_trade_metrics_accept_canonical_results_and_exclude_open(self):
        for fraction in (0.5, 0.25):
            for label, key, summarize in (
                ("GROSS", "gross_results", trade_metrics.summarize_gross_trade_performance),
                ("NET", "net_results", trade_metrics.summarize_net_trade_performance),
            ):
                summary = self.analytics[fraction][label]["metrics"]
                self.assertEqual(tuple(summary.loc[label, METRIC_COLUMNS[:4]]), (77, 20, 57, 0))
                self.assertTrue(np.isfinite(summary.to_numpy()).all())
                pd.testing.assert_frame_equal(summary, summarize(self.pipelines[fraction][key].iloc[:-1]), check_exact=True)

    def test_partial_realized_drawdown_accepts_total_capital_and_excludes_open(self):
        for fraction in (0.5, 0.25):
            for label, key, capital_column, calculate in (
                ("GROSS", "gross_results", "capital_after", drawdown.calculate_gross_realized_drawdown),
                ("NET", "net_results", "net_capital_after", drawdown.calculate_net_realized_drawdown),
            ):
                output = self.analytics[fraction][label]
                path, summary = output["realized"], output["realized_summary"]
                self.assertEqual(path.columns.tolist(), REALIZED_COLUMNS)
                self.assertEqual(len(path), 78)
                self.assertEqual(path.capital.iloc[0], INITIAL_CAPITAL)
                results = self.pipelines[fraction][key]
                np.testing.assert_array_equal(path.capital.iloc[1:], results.loc[results.status.eq("CLOSED"), capital_column])
                self.assertTrue(np.isfinite(path.to_numpy()).all())
                self.assertTrue(path.drawdown.between(-1, 0).all())
                self.assertTrue(np.isfinite(summary.to_numpy()).all())
                self.assertEqual(summary.loc[label, "max_realized_drawdown"], path.drawdown.min())
                pd.testing.assert_frame_equal(path, calculate(results.iloc[:-1], INITIAL_CAPITAL), check_exact=True)

    def test_partial_portfolio_drawdown_accepts_equity_with_exact_alignment(self):
        for fraction in (0.5, 0.25):
            for label in ("GROSS", "NET"):
                output, source = self.analytics[fraction][label], self.paths[fraction][label]
                path, summary = output["portfolio"], output["portfolio_summary"]
                self.assertEqual(path.columns.tolist(), PORTFOLIO_COLUMNS)
                self.assertEqual(len(path), 8761)
                pd.testing.assert_frame_equal(path[["observation", "valuation_time", "equity"]], source[["observation", "valuation_time", "equity"]], check_exact=True)
                self.assertTrue(np.isfinite(path[["equity", "running_peak", "drawdown", "drawdown_amount"]]).all().all())
                self.assertTrue(path.drawdown.between(-1, 0).all())
                self.assertEqual(summary.loc[label, "max_portfolio_drawdown"], path.drawdown.min())

    def test_partial_time_returns_retain_full_clock_cash_zeros_and_final_open(self):
        for fraction in (0.5, 0.25):
            for label in ("GROSS", "NET"):
                returns, source = self.analytics[fraction][label]["returns"], self.paths[fraction][label]
                self.assertEqual(returns.columns.tolist(), RETURN_COLUMNS)
                self.assertEqual(len(returns), 8760)
                for column in ("observation", "period_start_time", "period_end_time"):
                    pd.testing.assert_series_equal(returns[column], self.analytics[1.0][label]["returns"][column], check_exact=True)
                np.testing.assert_array_equal(returns.starting_equity, source.equity.iloc[:-1])
                np.testing.assert_array_equal(returns.ending_equity, source.equity.iloc[1:])
                self.assertTrue(np.isfinite(returns[["starting_equity", "ending_equity", "period_return"]]).all().all())
                self.assertEqual(returns.period_return.iloc[0], 0)
                self.assertGreater(int(returns.period_return.eq(0).sum()), 0)
                self.assertNotEqual(returns.period_return.iloc[-1], 0)
                self.assertEqual(returns.period_end_time.iloc[-1], END)

    def test_partial_sharpe_sortino_and_support_metrics_are_finite(self):
        for fraction in (0.5, 0.25):
            for label in ("GROSS", "NET"):
                summary = self.analytics[fraction][label]["risk"]
                self.assertEqual(summary.columns.tolist(), list(RISK_REFERENCES["EMA " + label]))
                self.assertEqual(summary.period_count.iloc[0], 8760)
                self.assertTrue(np.isfinite(summary.to_numpy()).all())

    def test_benchmark_is_exactly_independent_of_strategy_fraction(self):
        for fraction in FRACTIONS:
            # Strategy allocation is intentionally not an input to the benchmark.
            paths = {
                "GROSS": benchmark.calculate_gross_buy_and_hold_benchmark(self.candles, HOUR, INITIAL_CAPITAL),
                "NET": benchmark.calculate_net_buy_and_hold_benchmark(self.candles, HOUR, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE),
            }
            for label, path in paths.items():
                pd.testing.assert_frame_equal(path, self.benchmarks[label], check_exact=True)
                pd.testing.assert_series_equal(path.valuation_time, self.paths[fraction][label].valuation_time, check_exact=True)

    def test_partial_analytics_keep_existing_schemas_labels_and_dtypes(self):
        schemas = {
            "metrics": METRIC_COLUMNS, "realized": REALIZED_COLUMNS,
            "realized_summary": ["max_realized_drawdown", "max_realized_drawdown_amount"],
            "portfolio": PORTFOLIO_COLUMNS, "portfolio_summary": PORTFOLIO_SUMMARY_COLUMNS,
            "returns": RETURN_COLUMNS, "risk": list(RISK_REFERENCES["EMA GROSS"]),
        }
        for fraction in (0.5, 0.25):
            for label in ("GROSS", "NET"):
                for key, columns in schemas.items():
                    frame = self.analytics[fraction][label][key]
                    self.assertIsInstance(frame, pd.DataFrame)
                    self.assertEqual(frame.columns.tolist(), columns)
                    pd.testing.assert_series_equal(frame.dtypes, self.analytics[1.0][label][key].dtypes)
                    if key in ("metrics", "realized_summary", "portfolio_summary", "risk"):
                        self.assertEqual(frame.index.tolist(), ["EMA " + label if key == "risk" else label])
                    else:
                        pd.testing.assert_index_equal(frame.index, pd.RangeIndex(len(frame)), exact=True)
            time_summary = self.analytics[fraction]["time_summary"]
            self.assertEqual(time_summary.columns.tolist(), list(TIME_REFERENCES))
            self.assertEqual(time_summary.dtypes.astype(str).tolist(), ["int64"] * 2 + ["float64"] * 9)

    def test_analytics_have_no_risk_import_or_position_fraction_parameter(self):
        for module in (benchmark, drawdown, equity, portfolio_drawdown, risk_adjusted, trade_metrics, trade_time):
            tree = ast.parse(inspect.getsource(module))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom):
                    self.assertFalse((node.module or "").startswith("trading_lab.risk"))
                elif isinstance(node, ast.Import):
                    self.assertFalse(any(alias.name.startswith("trading_lab.risk") for alias in node.names))
            for name, function in inspect.getmembers(module, inspect.isfunction):
                if not name.startswith("_") and function.__module__ == module.__name__:
                    self.assertNotIn("position_fraction", inspect.signature(function).parameters)

    def test_upstream_inputs_and_raw_snapshot_are_preserved(self):
        pd.testing.assert_frame_equal(self.candles, self.candles_before, check_exact=True)
        for fraction in FRACTIONS:
            pd.testing.assert_frame_equal(self.strategies[fraction], self.strategy_before[fraction], check_exact=True)
            for key in RESULT_KEYS:
                pd.testing.assert_frame_equal(self.pipelines[fraction][key], self.pipeline_before[fraction][key], check_exact=True)
            for label in ("GROSS", "NET"):
                pd.testing.assert_frame_equal(self.paths[fraction][label], self.equity_before[fraction][label], check_exact=True)
        for label in ("GROSS", "NET"):
            pd.testing.assert_frame_equal(self.benchmarks[label], self.benchmark_before[label], check_exact=True)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash)

    def test_repeated_full_and_partial_pipeline_and_equity_are_deterministic(self):
        for fraction in FRACTIONS:
            repeated = run_backtest_pipeline(self.candles, self.strategies[fraction], INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE, fraction)
            for key in RESULT_KEYS:
                pd.testing.assert_frame_equal(repeated[key], self.pipelines[fraction][key], check_exact=True)
            paths = equity_paths(self.candles, repeated)
            for label in ("GROSS", "NET"):
                pd.testing.assert_frame_equal(paths[label], self.paths[fraction][label], check_exact=True)

    def test_half_allocation_canonical_literal_snapshot(self):
        self.assert_partial_snapshot(0.5)

    def test_quarter_allocation_canonical_literal_snapshot(self):
        self.assert_partial_snapshot(0.25)

    def test_smaller_allocations_reduce_losses_and_drawdowns_in_this_snapshot_only(self):
        snapshots = {
            fraction: snapshot_values(self.pipelines[fraction], self.paths[fraction], self.analytics[fraction])
            for fraction in FRACTIONS
        }
        for field in (
            "last_closed_gross", "last_closed_net", "final_gross_mtm", "final_net_mtm",
            "realized_gross_dd", "realized_net_dd", "portfolio_gross_dd", "portfolio_net_dd",
        ):
            self.assertLess(snapshots[1.0][field], snapshots[0.5][field])
            self.assertLess(snapshots[0.5][field], snapshots[0.25][field])
            self.assertLess(snapshots[0.25][field], INITIAL_CAPITAL if field.startswith(("last_", "final_")) else 0)


if __name__ == "__main__":
    unittest.main()
