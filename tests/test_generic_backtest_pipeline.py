"""Synthetic composition tests: arbitrary canonical intent through accounting."""

import unittest
from unittest.mock import patch

import pandas as pd

from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.pipeline import run_backtest_pipeline, run_execution_pipeline
from trading_lab.backtest.trades import build_trade_ledger


RESULT_KEYS = ["execution", "trades", "gross_results", "net_results"]


def frames(signals, positions, opens=None, index=None, timestamps=None):
    """Supply explicit non-EMA intent and timestamp/OPEN-only market data."""
    if timestamps is None:
        timestamps = pd.date_range("2025-01-01", periods=len(signals), freq="h", tz="UTC")
    candles = pd.DataFrame({"timestamp": timestamps}, index=index)
    if opens is None:
        opens = [100.0] * len(signals)
    candles["open"] = pd.Series(opens, index=candles.index, dtype="float64")
    strategy = candles[["timestamp"]].copy(deep=True)
    strategy["signal_time"] = strategy.timestamp + pd.Timedelta(hours=1)
    strategy["signal"] = pd.Series(signals, index=candles.index, dtype="object")
    strategy["desired_position"] = pd.Series(positions, index=candles.index, dtype="int64")
    return candles, strategy


def closed_example(**kwargs):
    return frames(
        ["HOLD", "LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"],
        [0, 1, 1, 0, 0], [90, 95, 100, 105, 110], **kwargs,
    )


def direct_composition(candles, strategy, initial_capital=10_000.0,
                       fee_rate=0.0, slippage_rate=0.0):
    """Independent helper calls are the authoritative expected DataFrames."""
    execution = run_execution_pipeline(candles, strategy)
    trades = build_trade_ledger(execution)
    gross = calculate_trade_results(trades, initial_capital=initial_capital)
    net = calculate_trade_results_with_costs(
        trades, initial_capital=initial_capital,
        fee_rate=fee_rate, slippage_rate=slippage_rate,
    )
    return dict(execution=execution, trades=trades, gross_results=gross, net_results=net)


class GenericBacktestPipelineTests(unittest.TestCase):
    def assert_direct_parity(self, candles, strategy, **parameters):
        expected = direct_composition(candles, strategy, **parameters)
        result = run_backtest_pipeline(candles, strategy, **parameters)
        self.assertEqual(list(result), RESULT_KEYS)
        self.assertEqual(len({id(frame) for frame in result.values()}), 4)
        for key in RESULT_KEYS:
            pd.testing.assert_frame_equal(result[key], expected[key], check_exact=True)
        return result

    def assert_open_accounting(self, result):
        self.assertEqual(result["trades"].status.tolist(), ["OPEN"])
        for key in ("trades", "gross_results", "net_results"):
            self.assertTrue(result[key][["exit_time", "exit_price"]].isna().all().all())
        gross = result["gross_results"]
        self.assertTrue(gross[["capital_before", "quantity"]].notna().all().all())
        self.assertTrue(gross[["trade_return", "gross_pnl", "capital_after"]].isna().all().all())
        net = result["net_results"]
        self.assertTrue(net[[
            "capital_before", "effective_entry_price", "quantity", "entry_notional", "entry_fee",
        ]].notna().all().all())
        self.assertTrue(net[[
            "effective_exit_price", "exit_notional", "exit_fee", "total_fees", "gross_pnl",
            "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
        ]].isna().all().all())

    def assert_error_propagates(self, candles, strategy, message, **parameters):
        market_before = candles.copy(deep=True)
        intent_before = strategy.copy(deep=True)
        with self.assertRaisesRegex(ValueError, message) as direct_error:
            direct_composition(candles, strategy, **parameters)
        # Raising, rather than returning, also excludes a partially filled dict.
        with self.assertRaises(ValueError) as pipeline_error:
            run_backtest_pipeline(candles, strategy, **parameters)
        self.assertEqual(type(pipeline_error.exception), type(direct_error.exception))
        self.assertEqual(str(pipeline_error.exception), str(direct_error.exception))
        pd.testing.assert_frame_equal(candles, market_before, check_exact=True)
        pd.testing.assert_frame_equal(strategy, intent_before, check_exact=True)

    def test_non_ema_closed_trade_reaches_independent_gross_and_net_accounting(self):
        candles, strategy = closed_example()
        # Research model assumptions only; no exchange or EMA implementation.
        result = self.assert_direct_parity(
            candles, strategy, initial_capital=1_000.0,
            fee_rate=0.001, slippage_rate=0.0005,
        )
        execution = result["execution"]
        self.assertEqual(execution.executed_position.tolist(), [0, 0, 1, 1, 0])
        self.assertEqual(execution.execution_time.iloc[1], candles.timestamp.iloc[2])
        self.assertEqual(execution.execution_time.iloc[3], candles.timestamp.iloc[4])
        trade = result["trades"].iloc[0]
        self.assertEqual(result["trades"].status.tolist(), ["CLOSED"])
        self.assertEqual(trade.trade_id, 1)
        self.assertEqual(trade.entry_time, candles.timestamp.iloc[2])
        self.assertEqual(trade.exit_time, candles.timestamp.iloc[4])
        self.assertEqual(trade.entry_price, 100)
        self.assertEqual(trade.exit_price, 110)
        gross = result["gross_results"].iloc[0]
        self.assertEqual(gross.quantity, 10)
        self.assertAlmostEqual(gross.trade_return, 0.1)
        self.assertEqual(gross.gross_pnl, 100)
        self.assertEqual(gross.capital_after, 1_100)
        net = result["net_results"].iloc[0]
        self.assertAlmostEqual(net.effective_entry_price, 100.05)
        self.assertAlmostEqual(net.effective_exit_price, 109.945)
        self.assertGreater(net.entry_fee, 0)
        self.assertGreater(net.exit_fee, 0)
        self.assertLess(net.quantity, gross.quantity)
        self.assertLess(net.net_pnl, gross.gross_pnl)
        self.assertLess(net.net_capital_after, gross.capital_after)
        self.assertNotEqual(net.gross_pnl, gross.gross_pnl)

    def test_executed_entry_remains_open_with_entry_only_accounting(self):
        result = self.assert_direct_parity(
            *frames(["HOLD", "LONG_ENTRY", "HOLD"], [0, 1, 1], [90, 95, 100]),
            initial_capital=1_000, fee_rate=0.001, slippage_rate=0.0005,
        )
        self.assert_open_accounting(result)
        self.assertEqual(result["gross_results"].quantity.iloc[0], 10)
        self.assertGreater(result["net_results"].entry_fee.iloc[0], 0)
        self.assertEqual(result["execution"].executed_position.iloc[-1], 1)

    def test_final_unexecuted_entry_creates_no_trade_or_financial_rows(self):
        result = self.assert_direct_parity(*frames(["HOLD", "LONG_ENTRY"], [0, 1]))
        self.assertTrue(result["execution"].execution_time.isna().all())
        self.assertTrue(result["execution"].execution_price.isna().all())
        self.assertEqual(result["execution"].executed_position.tolist(), [0, 0])
        for key in RESULT_KEYS[1:]:
            self.assertTrue(result[key].empty)

    def test_final_unexecuted_exit_leaves_existing_trade_open(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0])
        result = self.assert_direct_parity(candles, strategy, fee_rate=0.001, slippage_rate=0.0005)
        self.assert_open_accounting(result)
        self.assertEqual(strategy.desired_position.iloc[-1], 0)
        self.assertEqual(result["execution"].executed_position.iloc[-1], 1)
        self.assertTrue(pd.isna(result["execution"].execution_time.iloc[-1]))
        self.assertTrue(pd.isna(result["execution"].execution_price.iloc[-1]))

    def test_all_hold_has_no_fills_and_helper_defined_empty_financial_schemas(self):
        result = self.assert_direct_parity(*frames(["HOLD"] * 3, [0] * 3))
        self.assertEqual(result["execution"].executed_position.tolist(), [0, 0, 0])
        self.assertTrue(result["execution"][["execution_time", "execution_price"]].isna().all().all())
        for key in RESULT_KEYS[1:]:
            self.assertTrue(result[key].empty)

    def test_multiple_trades_have_sequential_ids_and_separate_compounding(self):
        result = self.assert_direct_parity(
            *frames(
                ["LONG_ENTRY", "HOLD", "LONG_EXIT", "LONG_ENTRY", "LONG_EXIT", "LONG_ENTRY", "HOLD"],
                [1, 1, 0, 1, 0, 1, 1], [90, 100, 105, 110, 200, 180, 300],
            ), initial_capital=1_000, fee_rate=0.001, slippage_rate=0.0005,
        )
        self.assertEqual(result["trades"].trade_id.tolist(), [1, 2, 3])
        self.assertEqual(result["trades"].status.tolist(), ["CLOSED", "CLOSED", "OPEN"])
        gross = result["gross_results"]
        net = result["net_results"]
        self.assertEqual(gross.capital_before.tolist(), [1_000, 1_100, 990])
        for row in (1, 2):
            self.assertEqual(gross.capital_before.iloc[row], gross.capital_after.iloc[row - 1])
            self.assertEqual(net.capital_before.iloc[row], net.net_capital_after.iloc[row - 1])
            self.assertLess(net.capital_before.iloc[row], gross.capital_before.iloc[row])
        self.assertTrue(pd.isna(gross.capital_after.iloc[-1]))
        self.assertTrue(pd.isna(net.net_capital_after.iloc[-1]))

    def test_zero_costs_preserve_gross_and_net_economic_equivalence(self):
        result = self.assert_direct_parity(*closed_example(), initial_capital=1_000)
        gross = result["gross_results"]
        net = result["net_results"]
        for gross_column, net_column in (
            ("capital_before", "capital_before"), ("quantity", "quantity"),
            ("trade_return", "net_trade_return"), ("gross_pnl", "gross_pnl"),
            ("gross_pnl", "net_pnl"), ("capital_after", "net_capital_after"),
        ):
            pd.testing.assert_series_equal(
                gross[gross_column], net[net_column], check_names=False, rtol=1e-12, atol=1e-10,
            )
        self.assertEqual(net.total_fees.iloc[0], 0)

    def test_changed_diagnostics_do_not_change_any_output_or_override_market_prices(self):
        candles, strategy = closed_example()
        parameters = dict(initial_capital=1_000, fee_rate=0.001, slippage_rate=0.0005)
        baseline = run_backtest_pipeline(candles, strategy, **parameters)
        strategy["breakout_level"] = "unused"
        strategy["z_score"] = pd.NA
        strategy["ema_20"] = float("inf")
        strategy["ema_50"] = "irrelevant"
        strategy["open"] = -999
        strategy["execution_price"] = -1
        strategy["gross_pnl"] = 999_999
        result = self.assert_direct_parity(candles, strategy, **parameters)
        for key in RESULT_KEYS:
            pd.testing.assert_frame_equal(result[key], baseline[key], check_exact=True)

    def test_delegation_order_unchanged_parameters_and_exact_helper_outputs(self):
        candles, strategy = closed_example()
        # Deliberately distinct helper schemas prove orchestration does not rebuild them.
        execution = pd.DataFrame({"execution_helper": [1]})
        trades = pd.DataFrame({"ledger_helper": [2]})
        gross = pd.DataFrame({"gross_helper": [3]})
        net = pd.DataFrame({"net_helper": [4]})
        capital, fee, slippage = 1234, 0.001, 0.0005
        calls = []

        def execute(market, intent):
            calls.append("execution")
            self.assertIs(market, candles)
            self.assertIs(intent, strategy)
            return execution

        def pair(rows):
            calls.append("trades")
            self.assertIs(rows, execution)
            return trades

        def account_gross(rows, *, initial_capital):
            calls.append("gross_results")
            self.assertIs(rows, trades)
            self.assertIs(initial_capital, capital)
            return gross

        def account_net(rows, *, initial_capital, fee_rate, slippage_rate):
            calls.append("net_results")
            self.assertIs(rows, trades)
            self.assertIs(initial_capital, capital)
            self.assertIs(fee_rate, fee)
            self.assertIs(slippage_rate, slippage)
            return net

        with patch("trading_lab.backtest.pipeline.run_execution_pipeline", side_effect=execute) as executor, \
             patch("trading_lab.backtest.pipeline.build_trade_ledger", side_effect=pair) as ledger, \
             patch("trading_lab.backtest.pipeline.calculate_trade_results", side_effect=account_gross) as gross_helper, \
             patch("trading_lab.backtest.pipeline.calculate_trade_results_with_costs", side_effect=account_net) as net_helper:
            result = run_backtest_pipeline(candles, strategy, capital, fee, slippage)
            for helper in (executor, ledger, gross_helper, net_helper):
                helper.assert_called_once()
        self.assertEqual(calls, RESULT_KEYS)
        self.assertEqual(list(result), RESULT_KEYS)
        for key, frame in zip(RESULT_KEYS, (execution, trades, gross, net)):
            self.assertIs(result[key], frame)

    def test_invalid_strategy_error_propagates_without_partial_return_or_mutation(self):
        candles, strategy = closed_example()
        strategy.loc[1, "signal"] = "BUY"
        self.assert_error_propagates(candles, strategy, "signal")

    def test_execution_spacing_and_used_open_errors_propagate(self):
        timestamps = pd.date_range("2025-01-01", periods=2, freq="2h", tz="UTC")
        self.assert_error_propagates(
            *frames(["LONG_ENTRY", "HOLD"], [1, 1], timestamps=timestamps), "one-hour spacing",
        )
        self.assert_error_propagates(
            *frames(["LONG_ENTRY", "HOLD"], [1, 1], [100, 0]), "Execution OPEN",
        )

    def test_accounting_parameter_errors_propagate_and_preserve_inputs(self):
        for name, value in (("initial_capital", 0), ("fee_rate", True), ("slippage_rate", 1)):
            with self.subTest(parameter=name):
                self.assert_error_propagates(*closed_example(), name, **{name: value})

    def test_inputs_and_other_outputs_survive_gross_and_execution_mutation(self):
        candles, strategy = closed_example()
        candles["context"] = pd.Categorical(["a", "b", "a", "b", "a"])
        strategy["diagnostic"] = pd.Series([1, None, 3, 4, 5], dtype="Int64")
        candles_before = candles.copy(deep=True)
        strategy_before = strategy.copy(deep=True)
        result = run_backtest_pipeline(candles, strategy, fee_rate=0.001, slippage_rate=0.0005)
        before = {key: frame.copy(deep=True) for key, frame in result.items()}
        pd.testing.assert_frame_equal(candles, candles_before, check_exact=True)
        pd.testing.assert_frame_equal(strategy, strategy_before, check_exact=True)
        result["gross_results"].loc[0, ["entry_price", "quantity", "gross_pnl"]] = -999
        result["gross_results"].loc[0, "entry_time"] += pd.Timedelta(days=1)
        for key in ("execution", "trades", "net_results"):
            pd.testing.assert_frame_equal(result[key], before[key], check_exact=True)
        gross_after = result["gross_results"].copy(deep=True)
        result["execution"].loc[0, "open"] = -1
        result["execution"].loc[0, "signal"] = "changed"
        result["execution"].loc[0, "timestamp"] += pd.Timedelta(days=1)
        for key in ("trades", "net_results"):
            pd.testing.assert_frame_equal(result[key], before[key], check_exact=True)
        pd.testing.assert_frame_equal(result["gross_results"], gross_after, check_exact=True)
        pd.testing.assert_frame_equal(candles, candles_before, check_exact=True)
        pd.testing.assert_frame_equal(strategy, strategy_before, check_exact=True)

    def test_non_range_index_and_aware_clock_follow_each_helpers_convention(self):
        index = pd.Index([30, 10, 20, 5, 7], name="candle_id")
        timestamps = pd.date_range("2025-03-09 00:00", periods=5, freq="h", tz="America/New_York")
        candles, strategy = closed_example(index=index, timestamps=timestamps)
        result = self.assert_direct_parity(candles, strategy, fee_rate=0.001, slippage_rate=0.0005)
        pd.testing.assert_index_equal(result["execution"].index, index)
        # Ledger creates its own trade index; both accounting paths retain that index.
        pd.testing.assert_index_equal(result["trades"].index, pd.RangeIndex(1))
        for key in RESULT_KEYS[1:]:
            pd.testing.assert_index_equal(result[key].index, result["trades"].index)
            self.assertEqual(result[key].entry_time.dtype, candles.timestamp.dtype)
            self.assertEqual(result[key].exit_time.dtype, candles.timestamp.dtype)
            self.assertEqual(result[key].entry_time.iloc[0], timestamps[2])
            self.assertEqual(result[key].exit_time.iloc[0], timestamps[4])

    def test_empty_typed_inputs_delegate_all_four_canonical_schemas_and_dtypes(self):
        result = self.assert_direct_parity(*frames([], []))
        for frame in result.values():
            self.assertTrue(frame.empty)
        self.assertEqual(str(result["execution"].timestamp.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(result["execution"].execution_time.dtype), "datetime64[ns, UTC]")
        for key in RESULT_KEYS[1:]:
            self.assertEqual(str(result[key].trade_id.dtype), "int64")
            self.assertEqual(str(result[key].entry_time.dtype), "datetime64[ns, UTC]")
            self.assertEqual(str(result[key].exit_time.dtype), "datetime64[ns, UTC]")
        for key in ("gross_results", "net_results"):
            for column in result[key].columns[6:]:
                self.assertEqual(str(result[key][column].dtype), "float64")


if __name__ == "__main__":
    unittest.main()
