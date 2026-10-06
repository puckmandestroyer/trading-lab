"""Synthetic run-level allocation forwarding through generic backtesting."""

import unittest
from unittest.mock import patch

import numpy as np
import pandas as pd

from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.pipeline import run_backtest_pipeline
from tests.test_generic_backtest_pipeline import (
    RESULT_KEYS, closed_example, direct_composition, frames,
)


def two_closed_trades():
    """Explicit next-OPEN fills: 100 -> 110, then 50 -> 60."""
    return frames(
        ["LONG_ENTRY", "HOLD", "LONG_EXIT", "LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"],
        [1, 1, 0, 1, 1, 0, 0], [90, 100, 105, 110, 50, 55, 60],
    )


class GenericPositionSizingPipelineTests(unittest.TestCase):
    def assert_fraction_failure_preserves_inputs(self, candles, strategy, fraction):
        before_candles, before_strategy = candles.copy(deep=True), strategy.copy(deep=True)
        with self.assertRaisesRegex(ValueError, "position_fraction") as direct_error:
            direct_composition(candles, strategy, initial_capital=1_000, position_fraction=fraction)
        with self.assertRaises(ValueError) as pipeline_error:
            run_backtest_pipeline(candles, strategy, initial_capital=1_000, position_fraction=fraction)
        self.assertEqual(str(pipeline_error.exception), str(direct_error.exception))
        pd.testing.assert_frame_equal(candles, before_candles, check_exact=True)
        pd.testing.assert_frame_equal(strategy, before_strategy, check_exact=True)

    def test_default_matches_explicit_full_allocation_for_all_four_frames_exactly(self):
        for candles, strategy in (closed_example(), two_closed_trades(), frames(["LONG_ENTRY", "HOLD"], [1, 1])):
            for fee, slippage in ((0, 0), (0.001, 0.0005)):
                with self.subTest(fee=fee, slippage=slippage, rows=len(candles)):
                    default = run_backtest_pipeline(candles, strategy, 1_000, fee, slippage)
                    full = run_backtest_pipeline(candles, strategy, 1_000, fee, slippage, 1.0)
                    for key in RESULT_KEYS:
                        pd.testing.assert_frame_equal(default[key], full[key], check_exact=True)

    def test_half_closed_zero_cost_trade_sizes_both_accounting_paths(self):
        result = run_backtest_pipeline(*closed_example(), initial_capital=1_000, position_fraction=0.5)
        gross, net = result["gross_results"].iloc[0], result["net_results"].iloc[0]
        self.assertEqual(result["trades"].status.tolist(), ["CLOSED"])
        self.assertEqual(gross.capital_before, 1_000)
        self.assertEqual(gross.quantity, 5)
        self.assertAlmostEqual(gross.trade_return, 0.10)
        self.assertEqual(gross.gross_pnl, 50)
        self.assertEqual(gross.capital_after, 1_050)
        self.assertEqual(net.capital_before, 1_000)
        self.assertEqual(net.quantity, 5)
        self.assertEqual(net.net_pnl, 50)
        self.assertEqual(net.net_trade_return, 0.05)
        self.assertEqual(net.net_capital_after, 1_050)

    def test_quarter_closed_trade_sizes_both_accounting_paths(self):
        result = run_backtest_pipeline(*closed_example(), initial_capital=1_000, position_fraction=0.25)
        gross, net = result["gross_results"].iloc[0], result["net_results"].iloc[0]
        self.assertEqual(gross.quantity, 2.5)
        self.assertEqual(gross.gross_pnl, 25)
        self.assertEqual(gross.capital_after, 1_025)
        self.assertEqual(net.quantity, 2.5)
        self.assertEqual(net.net_pnl, 25)
        self.assertEqual(net.net_trade_return, 0.025)
        self.assertEqual(net.net_capital_after, 1_025)

    def test_partial_fee_and_slippage_reach_independent_net_accounting(self):
        result = run_backtest_pipeline(*closed_example(), 1_000, 0.01, 0.02, 0.5)
        gross, net = result["gross_results"].iloc[0], result["net_results"].iloc[0]
        self.assertEqual(gross.quantity, 5)
        self.assertEqual(gross.capital_after, 1_050)
        self.assertAlmostEqual(net.effective_entry_price, 102)
        self.assertAlmostEqual(net.effective_exit_price, 107.8)
        self.assertAlmostEqual(net.entry_notional + net.entry_fee, 500)
        self.assertGreater(net.entry_fee, 0)
        self.assertGreater(net.exit_fee, 0)
        self.assertLess(net.quantity, gross.quantity)
        self.assertLess(net.net_capital_after, gross.capital_after)

    def test_execution_is_exactly_fraction_independent(self):
        candles, strategy = two_closed_trades()
        full = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, 1.0)
        for fraction in (0.5, 0.25):
            with self.subTest(fraction=fraction):
                partial = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, fraction)
                pd.testing.assert_frame_equal(full["execution"], partial["execution"], check_exact=True)

    def test_ledger_is_exactly_fraction_independent(self):
        candles, strategy = two_closed_trades()
        full = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, 1.0)
        for fraction in (0.5, 0.25):
            with self.subTest(fraction=fraction):
                partial = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, fraction)
                pd.testing.assert_frame_equal(full["trades"], partial["trades"], check_exact=True)

    def test_partial_pipeline_exactly_matches_direct_helper_composition(self):
        examples = (
            closed_example(), two_closed_trades(),
            frames(["LONG_ENTRY", "HOLD"], [1, 1]),
            frames(["HOLD"] * 3, [0] * 3), frames([], []),
        )
        for candles, strategy in examples:
            for fraction in (0.5, 0.25, 0.37):
                with self.subTest(fraction=fraction, rows=len(candles)):
                    parameters = dict(
                        initial_capital=1_000, fee_rate=0.001,
                        slippage_rate=0.0005, position_fraction=fraction,
                    )
                    expected = direct_composition(candles, strategy, **parameters)
                    result = run_backtest_pipeline(candles, strategy, **parameters)
                    for key in RESULT_KEYS:
                        pd.testing.assert_frame_equal(result[key], expected[key], check_exact=True)

    def test_zero_cost_partial_gross_net_economics_reconcile_but_returns_differ(self):
        for fraction in (0.5, 0.25):
            with self.subTest(fraction=fraction):
                result = run_backtest_pipeline(*two_closed_trades(), initial_capital=1_000, position_fraction=fraction)
                gross, net = result["gross_results"], result["net_results"]
                for gross_column, net_column in (
                    ("quantity", "quantity"), ("gross_pnl", "net_pnl"),
                    ("capital_after", "net_capital_after"),
                ):
                    pd.testing.assert_series_equal(gross[gross_column], net[net_column], check_names=False, check_exact=True)
                self.assertAlmostEqual(gross.trade_return.iloc[0], 0.10)
                self.assertAlmostEqual(net.net_trade_return.iloc[0], 0.10 * fraction)
                self.assertNotEqual(gross.trade_return.iloc[0], net.net_trade_return.iloc[0])

    def test_partial_open_position_has_sized_quantity_and_entry_only_accounting(self):
        result = run_backtest_pipeline(
            *frames(["HOLD", "LONG_ENTRY", "HOLD"], [0, 1, 1], [90, 95, 100]),
            initial_capital=1_000, position_fraction=0.5,
        )
        self.assertEqual(result["trades"].status.tolist(), ["OPEN"])
        for key in ("gross_results", "net_results"):
            self.assertEqual(result[key].capital_before.iloc[0], 1_000)
            self.assertEqual(result[key].quantity.iloc[0], 5)
            self.assertTrue(result[key][["exit_time", "exit_price"]].isna().all().all())
        self.assertTrue(result["gross_results"][["trade_return", "gross_pnl", "capital_after"]].isna().all().all())
        self.assertTrue(result["net_results"][[
            "effective_exit_price", "exit_notional", "exit_fee", "total_fees", "gross_pnl",
            "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
        ]].isna().all().all())

    def test_final_unexecuted_partial_entry_creates_no_allocation_rows(self):
        result = run_backtest_pipeline(
            *frames(["HOLD", "LONG_ENTRY"], [0, 1]), initial_capital=1_000, position_fraction=0.5,
        )
        self.assertEqual(result["execution"].executed_position.tolist(), [0, 0])
        self.assertTrue(result["execution"][["execution_time", "execution_price"]].isna().all().all())
        for key in RESULT_KEYS[1:]:
            self.assertTrue(result[key].empty)

    def test_final_unexecuted_partial_exit_leaves_existing_position_open(self):
        candles, strategy = frames(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [1, 1, 0], [90, 100, 105])
        result = run_backtest_pipeline(candles, strategy, initial_capital=1_000, position_fraction=0.5)
        self.assertEqual(strategy.desired_position.iloc[-1], 0)
        self.assertEqual(result["execution"].executed_position.iloc[-1], 1)
        self.assertTrue(result["execution"].iloc[-1][["execution_time", "execution_price"]].isna().all())
        self.assertEqual(result["trades"].status.tolist(), ["OPEN"])
        for key, capital_column in (("gross_results", "capital_after"), ("net_results", "net_capital_after")):
            self.assertEqual(result[key].quantity.iloc[0], 5)
            self.assertTrue(result[key][["exit_time", "exit_price", capital_column]].isna().all().all())

    def test_all_hold_partial_run_retains_normal_execution_and_empty_schemas(self):
        candles, strategy = frames(["HOLD"] * 3, [0] * 3)
        full = run_backtest_pipeline(candles, strategy, position_fraction=1.0)
        partial = run_backtest_pipeline(candles, strategy, position_fraction=0.5)
        self.assertEqual(partial["execution"].executed_position.tolist(), [0, 0, 0])
        self.assertTrue(partial["execution"][["execution_time", "execution_price"]].isna().all().all())
        for key in RESULT_KEYS:
            pd.testing.assert_frame_equal(partial[key], full[key], check_exact=True)
        for key in RESULT_KEYS[1:]:
            self.assertTrue(partial[key].empty)

    def test_invalid_fractions_propagate_even_for_all_hold(self):
        candles, strategy = frames(["HOLD"] * 3, [0] * 3)
        for fraction in (0, 1.2, True, np.nan):
            with self.subTest(fraction=fraction):
                self.assert_fraction_failure_preserves_inputs(candles, strategy, fraction)

    def test_invalid_fractions_propagate_for_nonempty_ledger_and_preserve_inputs(self):
        candles, strategy = closed_example()
        candles["context"] = "keep"
        strategy["diagnostic"] = "keep"
        for fraction in (0, 1.2, True, np.nan):
            with self.subTest(fraction=fraction):
                self.assert_fraction_failure_preserves_inputs(candles, strategy, fraction)

    def test_multiple_partial_trades_compound_current_total_capital(self):
        result = run_backtest_pipeline(*two_closed_trades(), initial_capital=1_000, position_fraction=0.5)
        gross, net = result["gross_results"], result["net_results"]
        self.assertEqual(result["trades"].entry_price.tolist(), [100, 50])
        self.assertEqual(result["trades"].exit_price.tolist(), [110, 60])
        self.assertEqual(gross.capital_before.tolist(), [1_000, 1_050])
        self.assertEqual(gross.quantity.tolist(), [5, 10.5])
        self.assertEqual(gross.gross_pnl.tolist(), [50, 105])
        self.assertEqual(gross.capital_after.tolist(), [1_050, 1_155])
        self.assertEqual(net.capital_before.tolist(), [1_000, 1_050])
        self.assertEqual(net.quantity.tolist(), [5, 10.5])
        self.assertEqual(net.net_pnl.tolist(), [50, 105])
        self.assertEqual(net.net_capital_after.tolist(), [1_050, 1_155])

    def test_nonzero_costs_compound_net_from_its_own_current_capital(self):
        result = run_backtest_pipeline(*two_closed_trades(), 1_000, 0.01, 0.02, 0.5)
        gross, net = result["gross_results"], result["net_results"]
        self.assertEqual(net.capital_before.iloc[1], net.net_capital_after.iloc[0])
        self.assertNotAlmostEqual(net.capital_before.iloc[1], 1_000)
        self.assertNotAlmostEqual(net.capital_before.iloc[1], gross.capital_after.iloc[0])
        self.assertNotAlmostEqual(net.capital_before.iloc[1], 500)
        self.assertAlmostEqual(net.entry_notional.iloc[1] + net.entry_fee.iloc[1], net.net_capital_after.iloc[0] * 0.5)
        self.assertEqual(gross.capital_before.iloc[1], gross.capital_after.iloc[0])
        self.assertLess(net.net_capital_after.iloc[-1], gross.capital_after.iloc[-1])

    def test_numpy_scalar_fraction_reaches_both_accounting_paths(self):
        result = run_backtest_pipeline(*closed_example(), initial_capital=1_000, position_fraction=np.float64(0.5))
        self.assertEqual(result["gross_results"].quantity.iloc[0], 5)
        self.assertEqual(result["net_results"].quantity.iloc[0], 5)

    def test_existing_positional_arguments_preserve_their_meaning(self):
        candles, strategy = closed_example()
        old_form = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005)
        named = run_backtest_pipeline(candles, strategy, initial_capital=1_000, fee_rate=0.001, slippage_rate=0.0005)
        for key in RESULT_KEYS:
            pd.testing.assert_frame_equal(old_form[key], named[key], check_exact=True)
        self.assertEqual(old_form["gross_results"].quantity.iloc[0], 10)

    def test_new_trailing_positional_fraction_matches_named_arguments(self):
        candles, strategy = closed_example()
        positional = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, 0.5)
        named = run_backtest_pipeline(
            candles, strategy, initial_capital=1_000, fee_rate=0.001,
            slippage_rate=0.0005, position_fraction=0.5,
        )
        for key in RESULT_KEYS:
            pd.testing.assert_frame_equal(positional[key], named[key], check_exact=True)

    def test_exact_four_keys_and_no_allocation_metadata_columns(self):
        for fraction in (1.0, 0.5):
            with self.subTest(fraction=fraction):
                result = run_backtest_pipeline(*closed_example(), position_fraction=fraction)
                self.assertEqual(list(result), RESULT_KEYS)
                self.assertEqual(len({id(frame) for frame in result.values()}), 4)
                for frame in result.values():
                    for column in ("position_fraction", "position_budget", "reserve_cash"):
                        self.assertNotIn(column, frame.columns)

    def test_success_preserves_source_columns_index_dtypes_and_timezone(self):
        index = pd.Index([30, 10, 20, 5, 7], name="candle_id")
        timestamps = pd.date_range("2025-03-09 00:00", periods=5, freq="h", tz="America/New_York")
        candles, strategy = closed_example(index=index, timestamps=timestamps)
        candles["context"] = pd.Categorical(["a", "b", "a", "b", "a"])
        strategy["diagnostic"] = pd.Series([1, None, 3, 4, 5], index=index, dtype="Int64")
        before_candles, before_strategy = candles.copy(deep=True), strategy.copy(deep=True)
        result = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, 0.5)
        pd.testing.assert_frame_equal(candles, before_candles, check_exact=True)
        pd.testing.assert_frame_equal(strategy, before_strategy, check_exact=True)
        pd.testing.assert_index_equal(result["execution"].index, index, exact=True)
        self.assertEqual(result["trades"].entry_time.dtype, candles.timestamp.dtype)

    def test_partial_outputs_are_independent_of_each_other_and_inputs(self):
        candles, strategy = closed_example()
        before_candles, before_strategy = candles.copy(deep=True), strategy.copy(deep=True)
        result = run_backtest_pipeline(candles, strategy, 1_000, 0.001, 0.0005, 0.5)
        before = {key: frame.copy(deep=True) for key, frame in result.items()}
        result["gross_results"].loc[0, ["entry_price", "quantity", "gross_pnl"]] = -999
        for key in ("execution", "trades", "net_results"):
            pd.testing.assert_frame_equal(result[key], before[key], check_exact=True)
        pd.testing.assert_frame_equal(candles, before_candles, check_exact=True)
        pd.testing.assert_frame_equal(strategy, before_strategy, check_exact=True)

    def test_empty_typed_partial_inputs_retain_canonical_schemas(self):
        candles, strategy = frames([], [])
        partial = run_backtest_pipeline(candles, strategy, position_fraction=0.5)
        full = run_backtest_pipeline(candles, strategy)
        for key in RESULT_KEYS:
            self.assertTrue(partial[key].empty)
            pd.testing.assert_frame_equal(partial[key], full[key], check_exact=True)

    def test_default_and_partial_calls_always_forward_fraction_to_both_accountants(self):
        candles, strategy = closed_example()
        for parameters, expected_fraction in (({}, 1.0), ({"position_fraction": 0.37}, 0.37)):
            with self.subTest(parameters=parameters):
                with patch("trading_lab.backtest.pipeline.calculate_trade_results", wraps=calculate_trade_results) as gross, \
                     patch("trading_lab.backtest.pipeline.calculate_trade_results_with_costs", wraps=calculate_trade_results_with_costs) as net:
                    result = run_backtest_pipeline(candles, strategy, initial_capital=1_000, **parameters)
                gross.assert_called_once_with(result["trades"], initial_capital=1_000, position_fraction=expected_fraction)
                net.assert_called_once_with(
                    result["trades"], initial_capital=1_000, fee_rate=0.0,
                    slippage_rate=0.0, position_fraction=expected_fraction,
                )
