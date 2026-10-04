"""First-OPEN benchmark behavior, validation delegation, and optional local BTC checks."""

from datetime import datetime
from pathlib import Path
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

from trading_lab.analytics.benchmark import (
    calculate_gross_buy_and_hold_benchmark,
    calculate_net_buy_and_hold_benchmark,
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
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.pipeline import run_ema_execution_pipeline
from trading_lab.backtest.trades import build_trade_ledger
from trading_lab.data.market_data import load_ohlcv_csv


START = pd.Timestamp("2025-01-01", tz="UTC")
HOUR = pd.Timedelta(hours=1)
COLUMNS = [
    "observation", "candle_timestamp", "valuation_time", "mark_price", "position",
    "active_trade_id", "cash", "quantity", "position_value", "unrealized_pnl", "equity",
]
FUNCTIONS = [calculate_gross_buy_and_hold_benchmark, calculate_net_buy_and_hold_benchmark]
RAW_BTC = Path(__file__).resolve().parents[1] / "data/raw/BTCUSDT_1h.csv"


def candles(closes=(110, 90, 120)):
    return pd.DataFrame({
        "timestamp": pd.date_range(START, periods=len(closes), freq="h"),
        "open": [100] * len(closes), "close": list(closes),
    })


def entry_ledger(source):
    """Independent canonical accounting fixture for the expected entry."""
    times = pd.Series([source.timestamp.iloc[0]])
    return pd.DataFrame({
        "trade_id": [1], "entry_time": times, "entry_price": [float(source.open.iloc[0])],
        "exit_time": pd.Series([pd.NaT], dtype=times.dtype),
        "exit_price": [np.nan], "status": ["OPEN"],
    })


class BuyAndHoldBenchmarkTests(unittest.TestCase):
    def assert_invalid(self, source, message):
        for function in FUNCTIONS:
            with self.subTest(function=function.__name__):
                with self.assertRaisesRegex(ValueError, message):
                    function(source, HOUR, 1_000)

    def test_exact_gross_schema(self):
        path = FUNCTIONS[0](candles(), HOUR, 1_000)
        self.assertEqual(path.columns.tolist(), COLUMNS)
        pd.testing.assert_index_equal(path.index, pd.RangeIndex(4))

    def test_exact_net_schema(self):
        path = FUNCTIONS[1](candles(), HOUR, 1_000, .01, .02)
        self.assertEqual(path.columns.tolist(), COLUMNS)
        pd.testing.assert_index_equal(path.index, pd.RangeIndex(4))

    def test_output_dtypes_match_existing_equity(self):
        for function in FUNCTIONS:
            path = function(candles(), HOUR, 1_000)
            self.assertEqual(str(path.observation.dtype), "int64")
            self.assertEqual(str(path.position.dtype), "int64")
            self.assertEqual(str(path.active_trade_id.dtype), "Int64")
            for column in ["mark_price", "cash", "quantity", "position_value", "unrealized_pnl", "equity"]:
                self.assertEqual(str(path[column].dtype), "float64")
            for column in ["candle_timestamp", "valuation_time"]:
                self.assertEqual(str(path[column].dtype), "datetime64[ns, UTC]")

    def test_n_candles_produce_n_plus_one_observations(self):
        for size in [1, 3, 12]:
            for function in FUNCTIONS:
                path = function(candles([100] * size), HOUR, 1_000)
                self.assertEqual(len(path), size + 1)
                self.assertEqual(path.observation.tolist(), list(range(size + 1)))

    def test_initial_observation_is_flat_capital_before_purchase(self):
        for function in FUNCTIONS:
            initial = function(candles(), HOUR, 725).iloc[0]
            self.assertEqual(initial.observation, 0)
            self.assertEqual(initial.valuation_time, START)
            self.assertEqual(initial.position, 0)
            self.assertTrue(pd.isna(initial.active_trade_id))
            self.assertTrue(pd.isna(initial.mark_price))
            self.assertTrue(pd.isna(initial.candle_timestamp))
            self.assertEqual(initial.cash, 725)
            self.assertEqual(initial.equity, 725)
            self.assertEqual(initial[["quantity", "position_value", "unrealized_pnl"]].tolist(), [0, 0, 0])

    def test_entry_is_first_open_not_first_close_or_later_open(self):
        source = candles([150, 120, 80])
        source["open"] = [100, 999, 500]
        path = FUNCTIONS[0](source, HOUR, 1_000)
        self.assertEqual(path.quantity.iloc[1], 10)
        self.assertEqual(path.equity.tolist(), [1_000, 1_500, 1_200, 800])

    def test_first_held_close_follows_first_open_by_interval(self):
        for function in FUNCTIONS:
            path = function(candles([110]), HOUR, 1_000)
            self.assertEqual(path.position.tolist(), [0, 1])
            self.assertEqual(path.candle_timestamp.iloc[1], START)
            self.assertEqual(path.valuation_time.iloc[1], START + HOUR)

    def test_position_stays_long_with_active_trade_id_one(self):
        for function in FUNCTIONS:
            path = function(candles(), HOUR, 1_000)
            self.assertTrue(path.position.iloc[1:].eq(1).all())
            self.assertTrue(path.active_trade_id.iloc[1:].eq(1).all())
            self.assertTrue(path.cash.iloc[1:].eq(0).all())
            self.assertTrue(path.quantity.iloc[1:].eq(path.quantity.iloc[1]).all())

    def test_gross_quantity_matches_existing_accounting(self):
        source = candles()
        result = calculate_trade_results(entry_ledger(source), 1_000)
        path = FUNCTIONS[0](source, HOUR, 1_000)
        self.assertEqual(path.quantity.iloc[1], result.quantity.iloc[0])
        self.assertEqual(path.quantity.iloc[1], 10)

    def test_net_quantity_matches_existing_self_financing_accounting(self):
        source = candles()
        result = calculate_trade_results_with_costs(entry_ledger(source), 1_000, .01, .02)
        path = FUNCTIONS[1](source, HOUR, 1_000, .01, .02)
        self.assertEqual(path.quantity.iloc[1], result.quantity.iloc[0])
        entry = result.iloc[0]
        self.assertAlmostEqual(entry.quantity * entry.effective_entry_price + entry.entry_fee, 1_000)

    def test_entry_costs_are_incurred_once_not_again_at_each_mark(self):
        source = candles()
        result = calculate_trade_results_with_costs(entry_ledger(source), 1_000, .01, .02)
        source["close"] = result.effective_entry_price.iloc[0]
        path = FUNCTIONS[1](source, HOUR, 1_000, .01, .02)
        np.testing.assert_allclose(path.equity.iloc[1:], 1_000 - result.entry_fee.iloc[0])
        self.assertTrue(path.unrealized_pnl.iloc[1:].eq(0).all())

    def test_final_mark_has_no_hypothetical_exit_cost(self):
        source = candles([100, 100, 100])
        result = calculate_trade_results_with_costs(entry_ledger(source), 1_000, .01, .02)
        path = FUNCTIONS[1](source, HOUR, 1_000, .01, .02)
        self.assertEqual(path.equity.iloc[-1], result.quantity.iloc[0] * 100)
        self.assertEqual(path.equity.iloc[-1], path.equity.iloc[1])
        self.assertEqual(path.position.iloc[-1], 1)

    def test_final_equity_is_final_close_marked_value(self):
        for function in FUNCTIONS:
            source = candles([110, 90, 80])
            path = function(source, HOUR, 1_000)
            self.assertEqual(path.equity.iloc[-1], path.quantity.iloc[-1] * 80)
            self.assertEqual(path.position_value.iloc[-1], path.equity.iloc[-1])
            self.assertEqual(path.mark_price.iloc[-1], 80)
            self.assertEqual(path.valuation_time.iloc[-1], START + 3 * HOUR)

    def test_zero_cost_net_equals_gross_exactly(self):
        source = candles()
        pd.testing.assert_frame_equal(FUNCTIONS[0](source, HOUR, 1_000), FUNCTIONS[1](source, HOUR, 1_000, 0, 0))

    def test_gross_delegates_one_canonical_open_trade_to_accounting_and_equity(self):
        source = candles()
        with patch('trading_lab.analytics.benchmark.calculate_trade_results', wraps=calculate_trade_results) as accounting:
            with patch('trading_lab.analytics.benchmark.calculate_gross_mark_to_market_equity', wraps=calculate_gross_mark_to_market_equity) as marking:
                FUNCTIONS[0](source, HOUR, 1_000)
        accounting.assert_called_once()
        marking.assert_called_once()
        pd.testing.assert_frame_equal(accounting.call_args.args[0], entry_ledger(source))
        self.assertIs(marking.call_args.args[0], source)

    def test_net_delegates_rates_and_leaves_canonical_exit_missing(self):
        source = candles()
        with patch('trading_lab.analytics.benchmark.calculate_trade_results_with_costs', wraps=calculate_trade_results_with_costs) as accounting:
            with patch('trading_lab.analytics.benchmark.calculate_net_mark_to_market_equity', wraps=calculate_net_mark_to_market_equity) as marking:
                FUNCTIONS[1](source, HOUR, 1_000, .01, .02)
        accounting.assert_called_once()
        marking.assert_called_once()
        trade = accounting.call_args.args[0]
        pd.testing.assert_frame_equal(trade, entry_ledger(source))
        self.assertTrue(trade.exit_time.isna().all() and trade.exit_price.isna().all())
        self.assertEqual(accounting.call_args.kwargs, {'initial_capital': 1_000, 'fee_rate': .01, 'slippage_rate': .02})

    def test_candles_values_dtypes_order_and_duplicate_index_are_preserved(self):
        source = candles()
        source["extra"] = pd.Series([1, pd.NA, 3], dtype="Int64")
        source = source[["extra", "close", "timestamp", "open"]]
        source.index = pd.Index([8, 8, -4], name="original")
        original = source.copy(deep=True)
        for function in FUNCTIONS:
            function(source, HOUR, 1_000)
            pd.testing.assert_frame_equal(source, original)

    def test_output_independence_in_both_directions(self):
        for function in FUNCTIONS:
            source = candles()
            original_source = source.copy(deep=True)
            path = function(source, HOUR, 1_000)
            path.at[1, "equity"] = 7
            path.at[1, "valuation_time"] = START - HOUR
            pd.testing.assert_frame_equal(source, original_source)
            original_path = path.copy(deep=True)
            source.at[0, "close"] = 500
            source.at[0, "timestamp"] = START - HOUR
            pd.testing.assert_frame_equal(path, original_path)

    def test_dataframe_required(self):
        for value in [None, [], {}, pd.Series([100])]:
            self.assert_invalid(value, "DataFrame")

    def test_unique_columns_required(self):
        source = candles()
        self.assert_invalid(pd.concat([source, source[["open"]]], axis=1), "unique")

    def test_required_columns_checked_even_on_empty_input(self):
        for size in [0, 3]:
            source = candles([100] * size)
            for column in ["timestamp", "open", "close"]:
                self.assert_invalid(source.drop(columns=column), "missing required columns")

    def test_empty_input_rejected(self):
        self.assert_invalid(candles([]), "non-empty")

    def test_malformed_first_open_fails_without_price_parsing(self):
        for value in [True, np.bool_(True), "100", None, pd.NA, np.nan, np.inf, -np.inf, 0, -1, 100 + 0j, 10**400]:
            source = candles()
            source["open"] = source.open.astype(object)
            source.at[0, "open"] = value
            self.assert_invalid(source, "First candle open")

    def test_malformed_first_timestamp_fails_without_inference_parsing(self):
        for value in ["2025-01-01", 1_735_689_600, None, pd.NaT, np.datetime64("NaT"), True]:
            source = candles()
            source["timestamp"] = source.timestamp.astype(object)
            source.at[0, "timestamp"] = value
            self.assert_invalid(source, "First candle timestamp")

    def test_existing_equity_time_validation_propagates(self):
        for values in [[START, START, START + HOUR], [START, START + 2 * HOUR, START + 3 * HOUR], [START + HOUR, START, START + 2 * HOUR]]:
            source = candles()
            source["timestamp"] = values
            self.assert_invalid(source, "strictly increasing")
        source = candles()
        source["timestamp"] = pd.Series([START, "2025-01-01 01:00", START + 2 * HOUR], dtype=object)
        self.assert_invalid(source, "timestamp")

    def test_existing_equity_close_validation_propagates(self):
        for value in [False, "100", np.nan, np.inf, -1, 0]:
            source = candles()
            source["close"] = source.close.astype(object)
            source.at[1, "close"] = value
            self.assert_invalid(source, "close")

    def test_existing_interval_validation_propagates(self):
        for value in [None, 1, "1h", True, pd.Timedelta(0), pd.Timedelta(hours=2)]:
            for function in FUNCTIONS:
                with self.assertRaisesRegex(ValueError, "interval"):
                    function(candles(), value, 1_000)

    def test_existing_initial_capital_validation_propagates(self):
        for value in [True, np.bool_(True), 0, -1, np.nan, np.inf, "1000"]:
            for function in FUNCTIONS:
                with self.assertRaisesRegex(ValueError, "initial_capital"):
                    function(candles(), HOUR, value)

    def test_existing_fee_and_slippage_validation_propagates(self):
        for field in ["fee_rate", "slippage_rate"]:
            for value in [True, np.bool_(True), -.1, 1, np.nan, np.inf, "0.01"]:
                with self.assertRaisesRegex(ValueError, field):
                    FUNCTIONS[1](candles(), HOUR, 1_000, **{field: value})

    def test_timezone_coherence_validation_propagates(self):
        source = candles()
        source["timestamp"] = pd.Series([START, (START + HOUR).tz_convert("Asia/Seoul"), START + 2 * HOUR], dtype=object)
        self.assert_invalid(source, "timezone")

    def test_naive_existing_datetime_clock_is_supported(self):
        source = candles()
        source["timestamp"] = pd.Series([datetime(2025, 1, 1, hour=i) for i in range(3)], dtype=object)
        for function in FUNCTIONS:
            path = function(source, HOUR, 1_000)
            self.assertEqual(str(path.valuation_time.dtype), "datetime64[ns]")
            self.assertEqual(path.valuation_time.iloc[-1], pd.Timestamp("2025-01-01 03:00"))

    def test_dst_same_zone_observations_preserve_elapsed_hour_alignment(self):
        source = candles()
        source["timestamp"] = pd.date_range("2025-11-02 00:00", periods=3, freq="h", tz=ZoneInfo("America/New_York"))
        for function in FUNCTIONS:
            path = function(source, HOUR, 1_000)
            self.assertEqual(path.valuation_time.tolist(), [source.timestamp.iloc[0], *(source.timestamp + HOUR).tolist()])

    def test_only_first_open_is_an_entry_and_optional_columns_are_ignored(self):
        source = candles()
        modified = source.copy()
        modified["open"] = pd.Series([100, "not another fill", None], dtype=object)
        modified["signal"] = "invalid-but-irrelevant"
        modified["high"] = np.nan
        for function in FUNCTIONS:
            pd.testing.assert_frame_equal(function(source, HOUR, 1_000), function(modified, HOUR, 1_000))

    def test_later_candle_changes_cannot_change_earlier_path(self):
        source = candles()
        modified = source.copy()
        modified.at[2, "close"] = 500
        modified.at[2, "open"] = 999
        for function in FUNCTIONS:
            pd.testing.assert_frame_equal(function(source, HOUR, 1_000).iloc[:3], function(modified, HOUR, 1_000).iloc[:3])

    def test_appending_candles_preserves_causal_prefix(self):
        source = candles([110, 90, 120, 50, 500])
        for function in FUNCTIONS:
            for size in [1, 3]:
                pd.testing.assert_frame_equal(function(source.iloc[:size], HOUR, 1_000), function(source, HOUR, 1_000).iloc[:size + 1])

    def test_existing_portfolio_drawdown_helpers_accept_benchmark_paths(self):
        for benchmark, calculate, summarize, label in zip(
            FUNCTIONS, [calculate_gross_portfolio_drawdown, calculate_net_portfolio_drawdown],
            [summarize_gross_portfolio_drawdown, summarize_net_portfolio_drawdown], ["GROSS", "NET"],
        ):
            equity = benchmark(candles(), HOUR, 1_000)
            path = calculate(equity)
            summary = summarize(equity)
            self.assertEqual(len(path), 4)
            self.assertEqual(summary.index.tolist(), [label])
            self.assertEqual(summary.trough_observation.iloc[0], 2)
            self.assertEqual(summary.max_portfolio_drawdown.iloc[0], 900 / 1_100 - 1)


@unittest.skipUnless(RAW_BTC.is_file(), "Local ignored BTC snapshot is unavailable.")
class LocalBTCBenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.candles = load_ohlcv_csv(RAW_BTC)
        cls.candles_before = cls.candles.copy(deep=True)
        cls.gross_benchmark = FUNCTIONS[0](cls.candles, HOUR, 10_000)
        cls.net_benchmark = FUNCTIONS[1](cls.candles, HOUR, 10_000, .001, .0005)
        trades = build_trade_ledger(run_ema_execution_pipeline(cls.candles))
        cls.gross_ema = calculate_gross_mark_to_market_equity(cls.candles, calculate_trade_results(trades, 10_000), HOUR, 10_000)
        cls.net_ema = calculate_net_mark_to_market_equity(cls.candles, calculate_trade_results_with_costs(trades, 10_000, .001, .0005), HOUR, 10_000)

    def test_actual_btc_first_open_entry_final_mark_and_drawdown_integration(self):
        self.assertEqual(len(self.candles), 8760)
        self.assertEqual(self.candles.timestamp.iloc[0], pd.Timestamp("2025-10-01", tz="UTC"))
        self.assertEqual(self.candles.open.iloc[0], 114_051.1)
        for equity, summarize, label in [
            (self.gross_benchmark, summarize_gross_portfolio_drawdown, "GROSS"),
            (self.net_benchmark, summarize_net_portfolio_drawdown, "NET"),
        ]:
            self.assertEqual(len(equity), 8761)
            self.assertEqual(equity.position.iloc[-1], 1)
            self.assertEqual(equity.active_trade_id.iloc[-1], 1)
            self.assertEqual(equity.valuation_time.iloc[-1], pd.Timestamp("2026-10-01", tz="UTC"))
            self.assertEqual(equity.equity.iloc[-1], equity.quantity.iloc[-1] * self.candles.close.iloc[-1])
            self.assertEqual(summarize(equity).index.tolist(), [label])
        pd.testing.assert_frame_equal(self.candles, self.candles_before)

    def test_actual_btc_benchmark_observations_align_exactly_with_ema_paths(self):
        for benchmark, ema in [(self.gross_benchmark, self.gross_ema), (self.net_benchmark, self.net_ema)]:
            pd.testing.assert_series_equal(benchmark.observation, ema.observation)
            pd.testing.assert_series_equal(benchmark.valuation_time, ema.valuation_time)
            self.assertEqual(benchmark.equity.iloc[0], ema.equity.iloc[0])
            self.assertEqual(benchmark.equity.iloc[0], 10_000)


if __name__ == "__main__":
    unittest.main()
