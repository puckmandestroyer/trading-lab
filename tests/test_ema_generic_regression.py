"""Frozen local BTC regression: EMA compatibility path versus generic helpers.

References and tolerances come from notebook 03's existing Stage 5 assertions.
The raw snapshot is optional on a fresh clone, following the existing local
BTC test policy. Only its absence permits a skip; no data is downloaded.
"""

import hashlib
from pathlib import Path
import unittest

import numpy as np
import pandas as pd

from trading_lab.analytics.benchmark import (
    calculate_gross_buy_and_hold_benchmark,
    calculate_net_buy_and_hold_benchmark,
)
from trading_lab.analytics.drawdown import (
    calculate_gross_realized_drawdown,
    calculate_net_realized_drawdown,
    summarize_gross_realized_drawdown,
    summarize_net_realized_drawdown,
)
from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.analytics.portfolio_drawdown import (
    calculate_gross_portfolio_drawdown,
    calculate_net_portfolio_drawdown,
    summarize_gross_portfolio_drawdown,
    summarize_net_portfolio_drawdown,
)
from trading_lab.analytics.risk_adjusted import (
    calculate_time_based_returns,
    summarize_risk_adjusted_performance,
)
from trading_lab.analytics.trade_metrics import (
    summarize_gross_trade_performance,
    summarize_net_trade_performance,
)
from trading_lab.analytics.trade_time import (
    calculate_trade_time_breakdown,
    summarize_trade_time_metrics,
)
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.pipeline import (
    run_backtest_pipeline,
    run_ema_execution_pipeline,
    run_execution_pipeline,
)
from trading_lab.backtest.trades import build_trade_ledger
from trading_lab.data.market_data import load_ohlcv_csv
from trading_lab.strategies.ema_trend import generate_ema_signals


RAW_BTC = Path(__file__).resolve().parents[1] / "data/raw/BTCUSDT_1h.csv"
FROZEN_SHA256 = "0be33013ae5decc74112c4a1cfdcb94b387830a37b9d1109b7f6c582d60f1975"
START = pd.Timestamp("2025-10-01", tz="UTC")
END = pd.Timestamp("2026-10-01", tz="UTC")
HOUR = pd.Timedelta(hours=1)
INITIAL_CAPITAL = 10_000.0
# Frozen research assumptions, not current exchange fees.
FEE_RATE = 0.001
SLIPPAGE_RATE = 0.0005
EXECUTION_COLUMNS = [
    "timestamp", "open", "signal", "execution_time", "execution_price", "executed_position",
]

# Preserve notebook 03's full risk-adjusted references and rtol/atol below.
RISK_REFERENCES = {
    "EMA GROSS": {
        "period_count": 8760,
        "mean_period_return": -2.0683176916843968e-06,
        "period_return_std": 0.002959051114370877,
        "annualized_volatility": 0.2769520092682945,
        "downside_deviation": 0.0020263178149198557,
        "annualized_downside_deviation": 0.1896529558184091,
        "sharpe_ratio": -0.06542094793615756,
        "sortino_ratio": -0.0955348304537029,
    },
    "EMA NET": {
        "period_count": 8760,
        "mean_period_return": -2.8594091376066328e-05,
        "period_return_std": 0.002963890304851665,
        "annualized_volatility": 0.27740493268025496,
        "downside_deviation": 0.002044937507796038,
        "annualized_downside_deviation": 0.19139566358339935,
        "sharpe_ratio": -0.9029552504138654,
        "sortino_ratio": -1.3087247420587158,
    },
    "Buy & Hold GROSS": {
        "period_count": 8760,
        "mean_period_return": -2.4428516033462405e-05,
        "period_return_std": 0.004691032974579669,
        "annualized_volatility": 0.43905662918225197,
        "downside_deviation": 0.0033458453953830987,
        "annualized_downside_deviation": 0.31315397035628184,
        "sharpe_ratio": -0.4873945323447151,
        "sortino_ratio": -0.6833501111599045,
    },
    "Buy & Hold NET": {
        "period_count": 8760,
        "mean_period_return": -2.4599834130156483e-05,
        "period_return_std": 0.004690998671222503,
        "annualized_volatility": 0.4390534185639407,
        "downside_deviation": 0.003345845395383099,
        "annualized_downside_deviation": 0.3131539703562819,
        "sharpe_ratio": -0.49081623754351356,
        "sortino_ratio": -0.6881424710502572,
    },
}


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class EMAGenericRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Check identity BEFORE computing EMA or financial outputs.
        cls.raw_hash_before = hashlib.sha256(RAW_BTC.read_bytes()).hexdigest()
        if cls.raw_hash_before != FROZEN_SHA256:
            raise AssertionError(f"Frozen BTC SHA-256 mismatch: {cls.raw_hash_before}")
        cls.candles = load_ohlcv_csv(RAW_BTC, interval="60", start=START, end=END)
        identity = (len(cls.candles), cls.candles.timestamp.iloc[0],
                    cls.candles.timestamp.iloc[-1], cls.candles.open.iloc[0])
        expected = (8760, START, END - HOUR, 114_051.1)
        if identity != expected:
            raise AssertionError(f"Frozen BTC identity mismatch: expected {expected}, actual {identity}")
        cls.candles_before = cls.candles.copy(deep=True)

        # Each full strategy/execution/accounting path runs once for the class.
        cls.strategy = generate_ema_signals(cls.candles, fast_span=20, slow_span=50, warmup_candles=50)
        cls.strategy_before = cls.strategy.copy(deep=True)
        cls.legacy = run_ema_execution_pipeline(cls.candles, fast_span=20, slow_span=50, warmup_candles=50)
        cls.execution = run_execution_pipeline(cls.candles, cls.strategy)
        cls.backtest = run_backtest_pipeline(
            cls.candles, cls.strategy, initial_capital=INITIAL_CAPITAL,
            fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE,
        )
        cls.legacy_ledger = build_trade_ledger(cls.legacy)
        cls.legacy_gross = calculate_trade_results(cls.legacy_ledger, initial_capital=INITIAL_CAPITAL)
        cls.legacy_net = calculate_trade_results_with_costs(
            cls.legacy_ledger, initial_capital=INITIAL_CAPITAL,
            fee_rate=FEE_RATE, slippage_rate=SLIPPAGE_RATE,
        )
        cls.accounting_before = {
            key: cls.backtest[key].copy(deep=True) for key in ("trades", "gross_results", "net_results")
        }
        gross, net = cls.backtest["gross_results"], cls.backtest["net_results"]
        cls.equity = {
            "GROSS": calculate_gross_mark_to_market_equity(cls.candles, gross, HOUR, INITIAL_CAPITAL),
            "NET": calculate_net_mark_to_market_equity(cls.candles, net, HOUR, INITIAL_CAPITAL),
        }
        cls.legacy_equity = {
            "GROSS": calculate_gross_mark_to_market_equity(cls.candles, cls.legacy_gross, HOUR, INITIAL_CAPITAL),
            "NET": calculate_net_mark_to_market_equity(cls.candles, cls.legacy_net, HOUR, INITIAL_CAPITAL),
        }
        cls.realized_paths = {
            "GROSS": calculate_gross_realized_drawdown(gross, INITIAL_CAPITAL),
            "NET": calculate_net_realized_drawdown(net, INITIAL_CAPITAL),
        }
        cls.realized_summaries = {
            "GROSS": summarize_gross_realized_drawdown(gross, INITIAL_CAPITAL),
            "NET": summarize_net_realized_drawdown(net, INITIAL_CAPITAL),
        }
        cls.portfolio_paths = {
            "GROSS": calculate_gross_portfolio_drawdown(cls.equity["GROSS"]),
            "NET": calculate_net_portfolio_drawdown(cls.equity["NET"]),
        }
        cls.portfolio_summaries = {
            "GROSS": summarize_gross_portfolio_drawdown(cls.equity["GROSS"]),
            "NET": summarize_net_portfolio_drawdown(cls.equity["NET"]),
        }
        cls.time_breakdown = calculate_trade_time_breakdown(cls.backtest["trades"], START, END)
        cls.time_summary = summarize_trade_time_metrics(cls.backtest["trades"], START, END)
        cls.trade_summaries = {
            "GROSS": summarize_gross_trade_performance(gross),
            "NET": summarize_net_trade_performance(net),
        }
        cls.benchmarks = {
            "GROSS": calculate_gross_buy_and_hold_benchmark(cls.candles, HOUR, INITIAL_CAPITAL),
            "NET": calculate_net_buy_and_hold_benchmark(
                cls.candles, HOUR, INITIAL_CAPITAL, FEE_RATE, SLIPPAGE_RATE,
            ),
        }
        cls.benchmark_drawdowns = {
            "GROSS": summarize_gross_portfolio_drawdown(cls.benchmarks["GROSS"]),
            "NET": summarize_net_portfolio_drawdown(cls.benchmarks["NET"]),
        }
        cls.risk_paths = {
            "EMA GROSS": cls.equity["GROSS"], "EMA NET": cls.equity["NET"],
            "Buy & Hold GROSS": cls.benchmarks["GROSS"], "Buy & Hold NET": cls.benchmarks["NET"],
        }
        cls.equity_before = {label: path.copy(deep=True) for label, path in cls.risk_paths.items()}
        cls.returns = {label: calculate_time_based_returns(path) for label, path in cls.risk_paths.items()}
        cls.risk_summaries = {
            label: summarize_risk_adjusted_performance(
                path, periods_per_year=8760, risk_free_return_per_period=0.0,
                minimum_acceptable_return_per_period=0.0, label=label,
            ) for label, path in cls.risk_paths.items()
        }

    def test_frozen_snapshot_identity_and_hash(self):
        self.assertEqual(len(self.candles), 8760)
        self.assertEqual(self.candles.timestamp.iloc[0], START)
        self.assertEqual(self.candles.timestamp.iloc[-1], END - HOUR)
        self.assertEqual(self.candles.open.iloc[0], 114_051.1)
        self.assertEqual(self.raw_hash_before, FROZEN_SHA256)

    def test_frozen_ema_strategy_counts_warmup_and_first_entry(self):
        self.assertEqual(int(self.strategy.bullish_cross.sum()), 78)
        self.assertEqual(int(self.strategy.bearish_cross.sum()), 78)
        self.assertEqual(int(self.strategy.signal.eq("LONG_ENTRY").sum()), 78)
        self.assertEqual(int(self.strategy.signal.eq("LONG_EXIT").sum()), 77)
        self.assertEqual(self.strategy.desired_position.iloc[-1], 1)
        self.assertEqual(self.strategy.signal.iloc[:50].tolist(), ["HOLD"] * 50)
        self.assertEqual(self.strategy.desired_position.iloc[:50].tolist(), [0] * 50)
        self.assertFalse(self.strategy.warmup_complete.iloc[:50].any())
        self.assertTrue(self.strategy.warmup_complete.iloc[50])
        first = self.strategy.loc[self.strategy.signal.eq("LONG_ENTRY")].iloc[0]
        self.assertEqual(first.timestamp, pd.Timestamp("2025-10-13 02:00", tz="UTC"))

    def test_strategy_output_exactly_matches_legacy_strategy_subset(self):
        pd.testing.assert_frame_equal(self.strategy, self.legacy[self.strategy.columns], check_exact=True)

    def test_generic_execution_exactly_matches_both_execution_paths(self):
        self.assertEqual(self.execution.columns.tolist(), EXECUTION_COLUMNS)
        self.assertEqual(list(self.backtest), ["execution", "trades", "gross_results", "net_results"])
        pd.testing.assert_frame_equal(self.execution, self.legacy[EXECUTION_COLUMNS], check_exact=True)
        pd.testing.assert_frame_equal(self.backtest["execution"], self.execution, check_exact=True)

    def test_frozen_execution_counts_and_first_next_open_fill(self):
        filled = self.execution.execution_time.notna()
        self.assertEqual(int((filled & self.execution.signal.eq("LONG_ENTRY")).sum()), 78)
        self.assertEqual(int((filled & self.execution.signal.eq("LONG_EXIT")).sum()), 77)
        first = self.execution.loc[filled & self.execution.signal.eq("LONG_ENTRY")].iloc[0]
        self.assertEqual(first.timestamp, pd.Timestamp("2025-10-13 02:00", tz="UTC"))
        self.assertEqual(first.execution_time, pd.Timestamp("2025-10-13 03:00", tz="UTC"))
        self.assertEqual(first.execution_price, 115_332.3)
        receiving = self.candles.loc[self.candles.timestamp.eq(first.execution_time)].iloc[0]
        self.assertEqual(first.execution_price, receiving.open)
        # Adjacent CLOSE/OPEN prices can coincide; fill timing and the source
        # OPEN above establish the execution convention, not price inequality.
        self.assertEqual(first.executed_position, 0)
        self.assertEqual(self.execution.executed_position.iloc[-1], 1)

    def test_ledger_exact_parity_counts_ids_and_final_open(self):
        trades = self.backtest["trades"]
        pd.testing.assert_frame_equal(trades, self.legacy_ledger, check_exact=True)
        self.assertEqual(len(trades), 78)
        self.assertEqual(int(trades.status.eq("CLOSED").sum()), 77)
        self.assertEqual(int(trades.status.eq("OPEN").sum()), 1)
        self.assertEqual(trades.trade_id.tolist(), list(range(1, 79)))
        self.assertEqual(trades.status.iloc[-1], "OPEN")
        self.assertEqual(trades.entry_time.iloc[-1], pd.Timestamp("2026-09-30 13:00", tz="UTC"))
        self.assertTrue(trades.iloc[-1][["exit_time", "exit_price"]].isna().all())

    def test_gross_accounting_exact_parity_and_frozen_realized_capital(self):
        gross = self.backtest["gross_results"]
        pd.testing.assert_frame_equal(gross, self.legacy_gross, check_exact=True)
        last_closed = gross.loc[gross.status.eq("CLOSED")].iloc[-1]
        np.testing.assert_allclose(last_closed.capital_after, 9641.111388344, rtol=1e-10)
        self.assertTrue(gross.iloc[-1][["capital_before", "quantity"]].notna().all())
        self.assertTrue(gross.iloc[-1][["trade_return", "gross_pnl", "capital_after"]].isna().all())

    def test_net_accounting_exact_parity_and_frozen_realized_capital(self):
        net = self.backtest["net_results"]
        pd.testing.assert_frame_equal(net, self.legacy_net, check_exact=True)
        last_closed = net.loc[net.status.eq("CLOSED")].iloc[-1]
        np.testing.assert_allclose(last_closed.net_capital_after, 7652.530163437, rtol=1e-10)
        self.assertTrue(net.iloc[-1][[
            "capital_before", "effective_entry_price", "quantity", "entry_notional", "entry_fee",
        ]].notna().all())
        self.assertTrue(net.iloc[-1][[
            "exit_time", "exit_price", "effective_exit_price", "exit_notional", "exit_fee",
            "total_fees", "gross_pnl", "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
        ]].isna().all())

    def test_mark_to_market_exact_parity_and_frozen_final_open_marks(self):
        for label, reference in (("GROSS", 9451.485313939314), ("NET", 7490.776562851941)):
            with self.subTest(label=label):
                path = self.equity[label]
                pd.testing.assert_frame_equal(path, self.legacy_equity[label], check_exact=True)
                self.assertEqual(len(path), 8761)
                self.assertEqual(path.valuation_time.iloc[0], START)
                self.assertEqual(path.valuation_time.iloc[-1], END)
                self.assertEqual(path.position.iloc[-1], 1)
                self.assertEqual(path.active_trade_id.iloc[-1], 78)
                self.assertEqual(path.cash.iloc[-1], 0)
                np.testing.assert_allclose(path.equity.iloc[-1], reference, rtol=1e-12, atol=1e-9)
                self.assertEqual(self.backtest["trades"].status.iloc[-1], "OPEN")

    def test_frozen_realized_capital_drawdown_references(self):
        for label, reference, trough in (
            ("GROSS", -0.2672342545498746, 33), ("NET", -0.37185533262673254, 66),
        ):
            with self.subTest(label=label):
                path = self.realized_paths[label]
                self.assertEqual(len(path), 78)
                self.assertEqual(path.capital.iloc[0], INITIAL_CAPITAL)
                self.assertEqual(int(path.drawdown.idxmin()), trough)
                np.testing.assert_allclose(
                    self.realized_summaries[label].loc[label, "max_realized_drawdown"],
                    reference, rtol=1e-12, atol=1e-14,
                )

    def test_frozen_candle_close_portfolio_drawdown_references(self):
        for label, reference, peak, trough in (
            ("GROSS", -0.2767943814221776, 308, 3687),
            ("NET", -0.37967960980713844, 308, 7369),
        ):
            with self.subTest(label=label):
                self.assertEqual(len(self.portfolio_paths[label]), 8761)
                summary = self.portfolio_summaries[label].loc[label]
                self.assertEqual(summary.peak_observation, peak)
                self.assertEqual(summary.trough_observation, trough)
                np.testing.assert_allclose(summary.max_portfolio_drawdown, reference, rtol=1e-12, atol=1e-14)

    def test_frozen_trade_duration_and_exposure_summary(self):
        references = {
            "closed_trade_count": 77, "open_trade_count": 1,
            "average_closed_duration_hours": 52.96103896103896,
            "median_closed_duration_hours": 34.0, "minimum_closed_duration_hours": 1.0,
            "maximum_closed_duration_hours": 226.0, "total_closed_duration_hours": 4078.0,
            "open_observed_duration_hours": 11.0, "total_time_in_market_hours": 4089.0,
            "observation_window_hours": 8760.0, "exposure_ratio": 0.46678082191780823,
        }
        self.assertEqual(self.time_summary.columns.tolist(), list(references))
        np.testing.assert_allclose(
            self.time_summary.loc["TIME"].to_numpy(dtype=float), list(references.values()),
            rtol=1e-12, atol=1e-12,
        )
        self.assertEqual(self.time_breakdown.closed_duration_hours.iloc[0], 27)
        self.assertTrue(pd.isna(self.time_breakdown.closed_duration_hours.iloc[-1]))
        self.assertEqual(self.time_breakdown.observed_time_in_market_hours.iloc[-1], 11)

    def test_frozen_closed_trade_performance_summaries(self):
        columns = [
            "win_rate", "loss_rate", "breakeven_rate", "average_trade_return", "median_trade_return",
            "average_win_return", "average_loss_return", "best_trade_return", "worst_trade_return",
            "total_realized_pnl", "expectancy_pnl", "profit_factor",
        ]
        references = {
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
        counts = ["closed_trade_count", "winning_trade_count", "losing_trade_count", "breakeven_trade_count"]
        for label, reference in references.items():
            with self.subTest(label=label):
                summary = self.trade_summaries[label]
                self.assertEqual(summary.columns.tolist(), counts + columns)
                self.assertEqual(tuple(summary.loc[label, counts]), (77, 20, 57, 0))
                np.testing.assert_allclose(
                    summary.loc[label, columns].to_numpy(dtype=float), reference, rtol=1e-10, atol=1e-9,
                )

    def test_frozen_time_based_returns_and_risk_adjusted_references(self):
        reference_returns = self.returns["EMA GROSS"]
        for label, references in RISK_REFERENCES.items():
            with self.subTest(label=label):
                returns = self.returns[label]
                self.assertEqual(len(returns), 8760)
                for column in ("observation", "period_start_time", "period_end_time"):
                    pd.testing.assert_series_equal(returns[column], reference_returns[column], check_exact=True)
                self.assertEqual(returns.period_start_time.iloc[0], START)
                self.assertEqual(returns.period_end_time.iloc[-1], END)
                summary = self.risk_summaries[label]
                self.assertEqual(summary.columns.tolist(), list(references))
                np.testing.assert_allclose(
                    summary.loc[label].to_numpy(dtype=float), list(references.values()), rtol=1e-12, atol=1e-14,
                )
                if label.startswith("EMA"):
                    self.assertEqual(returns.period_return.iloc[0], 0)
                    self.assertGreater(int(returns.period_return.eq(0).sum()), 0)
                    self.assertNotEqual(returns.period_return.iloc[-1], 0)

    def test_frozen_buy_and_hold_comparison_references(self):
        for label, final_equity, drawdown, advantage in (
            ("GROSS", 7331.468087550229, -0.5373383889204555, 2120.017226389085),
            ("NET", 7320.483701755746, -0.5373383889204554, 170.292861096195),
        ):
            with self.subTest(label=label):
                benchmark = self.benchmarks[label]
                self.assertEqual(len(benchmark), 8761)
                self.assertEqual(benchmark.position.iloc[-1], 1)
                self.assertEqual(benchmark.active_trade_id.iloc[-1], 1)
                for column in ("observation", "valuation_time"):
                    pd.testing.assert_series_equal(benchmark[column], self.equity[label][column], check_exact=True)
                np.testing.assert_allclose(benchmark.equity.iloc[-1], final_equity, rtol=1e-12, atol=1e-10)
                np.testing.assert_allclose(
                    self.benchmark_drawdowns[label].loc[label, "max_portfolio_drawdown"],
                    drawdown, rtol=1e-12, atol=1e-14,
                )
                np.testing.assert_allclose(
                    self.equity[label].equity.iloc[-1] - benchmark.equity.iloc[-1],
                    advantage, rtol=1e-12, atol=1e-10,
                )

    def test_candles_strategy_accounting_equity_and_raw_file_are_preserved(self):
        pd.testing.assert_frame_equal(self.candles, self.candles_before, check_exact=True)
        pd.testing.assert_frame_equal(self.strategy, self.strategy_before, check_exact=True)
        for key, before in self.accounting_before.items():
            pd.testing.assert_frame_equal(self.backtest[key], before, check_exact=True)
        for label, before in self.equity_before.items():
            pd.testing.assert_frame_equal(self.risk_paths[label], before, check_exact=True)
        self.assertEqual(hashlib.sha256(RAW_BTC.read_bytes()).hexdigest(), self.raw_hash_before)


if __name__ == "__main__":
    unittest.main()
