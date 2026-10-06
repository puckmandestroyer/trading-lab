"""Synthetic NET allocation, reserve reconciliation, and compatibility tests."""

from math import nextafter
import unittest
from unittest.mock import call, patch

import numpy as np
import pandas as pd

from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.risk.position_sizing import calculate_position_budget


LEDGER_COLUMNS = ["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"]
FINANCIAL_COLUMNS = [
    "capital_before", "effective_entry_price", "effective_exit_price", "quantity",
    "entry_notional", "exit_notional", "entry_fee", "exit_fee", "total_fees",
    "gross_pnl", "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
]
OPEN_MISSING = [
    "exit_time", "exit_price", "effective_exit_price", "exit_notional", "exit_fee",
    "total_fees", "gross_pnl", "price_adjusted_pnl", "net_pnl", "net_trade_return",
    "net_capital_after",
]


def ledger(prices):
    """Typed non-overlapping trades on a UTC clock; None exit means OPEN."""
    entries = pd.date_range("2025-01-01", periods=len(prices), freq="2h", tz="UTC")
    return pd.DataFrame({
        "trade_id": pd.Series(range(1, len(prices) + 1), dtype="int64"),
        "entry_time": entries,
        "entry_price": pd.Series([entry for entry, _ in prices], dtype="float64"),
        "exit_time": pd.Series([
            time + pd.Timedelta(hours=1) if exit_price is not None else pd.NaT
            for time, (_, exit_price) in zip(entries, prices)
        ], dtype="datetime64[ns, UTC]"),
        "exit_price": pd.Series([
            exit_price if exit_price is not None else np.nan for _, exit_price in prices
        ], dtype="float64"),
        "status": pd.Series([
            "CLOSED" if exit_price is not None else "OPEN" for _, exit_price in prices
        ], dtype="object"),
    })


class NetPositionSizingTests(unittest.TestCase):
    def test_default_matches_explicit_full_allocation_exactly(self):
        rows = ledger([(3, 4), (7, 5), (11, None)])
        for fee, slippage in ((0, 0), (0.003, 0.002)):
            with self.subTest(fee=fee, slippage=slippage):
                default = calculate_trade_results_with_costs(rows, 123.45, fee, slippage)
                full = calculate_trade_results_with_costs(rows, 123.45, fee, slippage, 1.0)
                pd.testing.assert_frame_equal(default, full, check_exact=True)

    def test_existing_positional_arguments_retain_their_order(self):
        rows = ledger([(100, 110)])
        positional = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, 0.5)
        named = calculate_trade_results_with_costs(
            rows, initial_capital=1_000, fee_rate=0.01,
            slippage_rate=0.02, position_fraction=0.5,
        )
        pd.testing.assert_frame_equal(positional, named, check_exact=True)

    def test_half_allocation_zero_cost_profitable_closed_trade(self):
        trade = calculate_trade_results_with_costs(ledger([(100, 110)]), 1_000, position_fraction=0.5).iloc[0]
        expected = {
            "capital_before": 1_000, "effective_entry_price": 100,
            "effective_exit_price": 110, "quantity": 5, "entry_notional": 500,
            "exit_notional": 550, "entry_fee": 0, "exit_fee": 0, "total_fees": 0,
            "gross_pnl": 50, "price_adjusted_pnl": 50, "net_pnl": 50,
            "net_trade_return": 0.05, "net_capital_after": 1_050,
        }
        for column, value in expected.items():
            self.assertEqual(trade[column], value, column)
        self.assertEqual(trade.capital_before - trade.entry_notional - trade.entry_fee, 500)

    def test_quarter_allocation_zero_cost_profitable_closed_trade(self):
        trade = calculate_trade_results_with_costs(ledger([(100, 120)]), 1_000, position_fraction=0.25).iloc[0]
        self.assertEqual(trade.capital_before, 1_000)
        self.assertEqual(trade.quantity, 2.5)
        self.assertEqual(trade.entry_notional, 250)
        self.assertEqual(trade.net_pnl, 50)
        self.assertEqual(trade.net_trade_return, 0.05)
        self.assertEqual(trade.net_capital_after, 1_050)

    def test_half_allocation_zero_cost_losing_closed_trade(self):
        trade = calculate_trade_results_with_costs(ledger([(100, 90)]), 1_000, position_fraction=0.5).iloc[0]
        self.assertEqual(trade.quantity, 5)
        self.assertEqual(trade.net_pnl, -50)
        self.assertEqual(trade.net_trade_return, -0.05)
        self.assertEqual(trade.net_capital_after, 950)

    def test_partial_entry_fee_is_funded_by_budget_and_not_reserve(self):
        trade = calculate_trade_results_with_costs(ledger([(100, 110)]), 1_000, 0.01, 0, 0.5).iloc[0]
        self.assertAlmostEqual(trade.quantity, 500 / 101)
        self.assertAlmostEqual(trade.entry_fee, trade.entry_notional * 0.01)
        self.assertAlmostEqual(trade.exit_fee, trade.exit_notional * 0.01)
        self.assertGreater(trade.entry_fee, 0)
        spend = trade.entry_notional + trade.entry_fee
        reserve = trade.capital_before - spend
        np.testing.assert_allclose([spend, reserve], [500, 500], rtol=1e-12, atol=1e-12)
        # Subtracting just notional would incorrectly retain the paid fee in cash.
        self.assertGreater(trade.capital_before - trade.entry_notional, reserve)
        np.testing.assert_allclose(
            trade.net_capital_after, reserve + trade.exit_notional - trade.exit_fee,
            rtol=1e-12, atol=1e-12,
        )

    def test_partial_adverse_slippage_keeps_reserve_outside_position(self):
        trade = calculate_trade_results_with_costs(ledger([(100, 110)]), 1_000, 0, 0.01, 0.5).iloc[0]
        self.assertEqual(trade.entry_price, 100)
        self.assertEqual(trade.exit_price, 110)
        self.assertAlmostEqual(trade.effective_entry_price, 101)
        self.assertAlmostEqual(trade.effective_exit_price, 108.9)
        self.assertAlmostEqual(trade.quantity, 500 / 101)
        self.assertEqual(trade.total_fees, 0)
        self.assertAlmostEqual(trade.entry_notional, 500)
        self.assertAlmostEqual(trade.capital_before - trade.entry_notional, 500)
        self.assertAlmostEqual(trade.net_capital_after, 500 + (500 / 101) * 108.9)

    def test_partial_fee_and_slippage_preserve_existing_pnl_conventions(self):
        trade = calculate_trade_results_with_costs(ledger([(100, 110)]), 1_000, 0.01, 0.02, 0.5).iloc[0]
        quantity = 500 / (102 * 1.01)
        self.assertAlmostEqual(trade.quantity, quantity)
        self.assertAlmostEqual(trade.effective_entry_price, 102)
        self.assertAlmostEqual(trade.effective_exit_price, 107.8)
        self.assertAlmostEqual(trade.gross_pnl, quantity * 10)
        self.assertAlmostEqual(trade.price_adjusted_pnl, quantity * (107.8 - 102))
        self.assertAlmostEqual(trade.total_fees, quantity * (102 + 107.8) * 0.01)
        self.assertAlmostEqual(trade.net_pnl, trade.price_adjusted_pnl - trade.total_fees)
        self.assertLess(trade.net_pnl, trade.gross_pnl)

    def test_entry_budget_and_closed_reserve_identities_across_fractions(self):
        rows = ledger([(3, 4), (7, 5), (11, 19)])
        for fraction in (1.0, 0.5, 0.25, 0.37):
            for fee, slippage in ((0, 0), (0.003, 0.002)):
                with self.subTest(fraction=fraction, fee=fee, slippage=slippage):
                    result = calculate_trade_results_with_costs(rows, 123.45, fee, slippage, fraction)
                    spend = result.entry_notional + result.entry_fee
                    reserve = result.capital_before - spend
                    np.testing.assert_allclose(
                        spend, result.capital_before * fraction, rtol=1e-12, atol=1e-12,
                    )
                    np.testing.assert_allclose(
                        reserve, result.capital_before * (1 - fraction), rtol=1e-12, atol=1e-12,
                    )
                    if fraction < 1:
                        self.assertTrue(reserve.gt(0).all())
                    np.testing.assert_allclose(
                        result.net_capital_after, reserve + result.exit_notional - result.exit_fee,
                        rtol=1e-12, atol=1e-12,
                    )
                    np.testing.assert_allclose(
                        result.net_capital_after, result.capital_before + result.net_pnl,
                        rtol=1e-12, atol=1e-12,
                    )

    def test_net_trade_return_uses_total_portfolio_capital(self):
        for fraction in (1.0, 0.5, 0.25):
            for fee, slippage in ((0, 0), (0.01, 0.02)):
                with self.subTest(fraction=fraction, fee=fee, slippage=slippage):
                    result = calculate_trade_results_with_costs(
                        ledger([(100, 110), (50, 45)]), 1_000, fee, slippage, fraction,
                    )
                    np.testing.assert_allclose(
                        result.net_trade_return, result.net_pnl / result.capital_before,
                        rtol=1e-12, atol=1e-12,
                    )

    def test_zero_cost_economic_parity_with_gross_at_same_fraction(self):
        rows = ledger([(100, 110), (50, 45), (200, None)])
        for fraction in (1.0, 0.5, 0.25, 0.37):
            with self.subTest(fraction=fraction):
                gross = calculate_trade_results(rows, 1_000, fraction)
                net = calculate_trade_results_with_costs(rows, 1_000, position_fraction=fraction)
                for gross_column, net_column in (
                    ("capital_before", "capital_before"), ("quantity", "quantity"),
                    ("gross_pnl", "gross_pnl"), ("gross_pnl", "price_adjusted_pnl"),
                    ("gross_pnl", "net_pnl"), ("capital_after", "net_capital_after"),
                ):
                    np.testing.assert_allclose(
                        gross[gross_column], net[net_column],
                        rtol=1e-12, atol=1e-10, equal_nan=True,
                    )
                if fraction == 1:
                    np.testing.assert_allclose(
                        gross.trade_return, net.net_trade_return,
                        rtol=1e-12, atol=1e-10, equal_nan=True,
                    )

    def test_partial_zero_cost_gross_and_net_return_meanings_differ(self):
        rows = ledger([(100, 110)])
        gross = calculate_trade_results(rows, 1_000, 0.5).iloc[0]
        net = calculate_trade_results_with_costs(rows, 1_000, position_fraction=0.5).iloc[0]
        self.assertAlmostEqual(gross.trade_return, 0.10)
        self.assertEqual(net.net_trade_return, 0.05)
        self.assertNotEqual(gross.trade_return, net.net_trade_return)
        self.assertEqual(gross.gross_pnl, net.net_pnl)

    def test_two_closed_trades_compound_current_total_net_capital(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110), (50, 60)]), 1_000, position_fraction=0.5)
        self.assertEqual(result.capital_before.tolist(), [1_000, 1_050])
        self.assertEqual(result.quantity.tolist(), [5, 10.5])
        self.assertEqual(result.entry_notional.tolist(), [500, 525])
        self.assertEqual(result.net_pnl.tolist(), [50, 105])
        self.assertEqual(result.net_capital_after.tolist(), [1_050, 1_155])

    def test_next_budget_uses_net_capital_after_a_loss(self):
        result = calculate_trade_results_with_costs(ledger([(100, 90), (50, 60)]), 1_000, position_fraction=0.5)
        self.assertEqual(result.capital_before.tolist(), [1_000, 950])
        self.assertEqual(result.quantity.tolist(), [5, 9.5])
        self.assertEqual(result.net_capital_after.tolist(), [950, 1_045])

    def test_nonzero_cost_second_entry_uses_prior_net_not_gross_or_initial_capital(self):
        rows = ledger([(100, 110), (50, 60)])
        fee, slippage, fraction = 0.01, 0.02, 0.5
        result = calculate_trade_results_with_costs(rows, 1_000, fee, slippage, fraction)
        gross = calculate_trade_results(rows, 1_000, fraction)
        # Independent cash/proceeds calculation includes reserve, not just sale proceeds.
        first_after = 500 + (500 / (100 * 1.02 * 1.01)) * (110 * 0.98) * 0.99
        second_budget = first_after * fraction
        second_quantity = second_budget / (50 * 1.02 * 1.01)
        second_after = first_after - second_budget + second_quantity * (60 * 0.98) * 0.99
        self.assertAlmostEqual(result.net_capital_after.iloc[0], first_after)
        self.assertAlmostEqual(result.capital_before.iloc[1], first_after)
        self.assertAlmostEqual(result.quantity.iloc[1], second_quantity)
        self.assertAlmostEqual(result.entry_notional.iloc[1] + result.entry_fee.iloc[1], second_budget)
        self.assertAlmostEqual(result.net_capital_after.iloc[1], second_after)
        self.assertNotAlmostEqual(result.capital_before.iloc[1], gross.capital_before.iloc[1])
        self.assertNotAlmostEqual(result.capital_before.iloc[1], 1_000)

    def test_closed_then_open_sizes_from_prior_net_capital_with_costs(self):
        rows = ledger([(100, 110), (50, None)])
        result = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, 0.5)
        final = result.iloc[-1]
        self.assertEqual(final.capital_before, result.net_capital_after.iloc[0])
        self.assertAlmostEqual(final.quantity, final.capital_before * 0.5 / (51 * 1.01))
        self.assertAlmostEqual(final.entry_notional + final.entry_fee, final.capital_before * 0.5)
        self.assertAlmostEqual(
            final.capital_before - final.entry_notional - final.entry_fee, final.capital_before * 0.5,
        )
        self.assertNotAlmostEqual(final.capital_before, calculate_trade_results(rows, 1_000, 0.5).capital_before.iloc[-1])
        self.assertEqual(final.status, "OPEN")
        self.assertTrue(final[OPEN_MISSING].isna().all())

    def test_open_only_partial_allocation_has_entry_fields_without_forced_close(self):
        result = calculate_trade_results_with_costs(ledger([(100, None)]), 1_000, 0.01, 0.02, 0.25)
        self.assertEqual(len(result), 1)
        trade = result.iloc[0]
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.capital_before, 1_000)
        self.assertAlmostEqual(trade.effective_entry_price, 102)
        self.assertAlmostEqual(trade.quantity, 250 / (102 * 1.01))
        self.assertGreater(trade.entry_fee, 0)
        self.assertAlmostEqual(trade.entry_notional + trade.entry_fee, 250)
        self.assertAlmostEqual(trade.capital_before - trade.entry_notional - trade.entry_fee, 750)
        self.assertTrue(trade[OPEN_MISSING].isna().all())

    def test_empty_typed_ledger_preserves_exact_schema_dtypes_and_index(self):
        rows = ledger([])
        rows.index = pd.Index([], dtype="int64", name="source_trade")
        original = rows.copy(deep=True)
        full = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, 1.0)
        half = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, 0.5)
        self.assertTrue(half.empty)
        self.assertEqual(half.columns.tolist(), LEDGER_COLUMNS + FINANCIAL_COLUMNS)
        self.assertEqual(str(half.entry_time.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(half.exit_time.dtype), "datetime64[ns, UTC]")
        pd.testing.assert_index_equal(half.index, rows.index, exact=True)
        pd.testing.assert_frame_equal(half, full, check_exact=True)
        pd.testing.assert_frame_equal(rows, original, check_exact=True)

    def test_invalid_fraction_is_rejected_for_empty_ledger(self):
        for fraction in (0, -0.5, 1.2, True, np.bool_(True), np.nan, np.inf, "0.5"):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_trade_results_with_costs(ledger([]), 1_000, position_fraction=fraction)

    def test_focused_invalid_fractions_are_rejected_for_nonempty_ledger(self):
        for fraction in (0, 1.2, True, np.nan):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_trade_results_with_costs(ledger([(100, 110)]), 1_000, position_fraction=fraction)

    def test_non_range_index_timezone_and_recorded_fields_are_preserved(self):
        rows = ledger([(100, 110), (50, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        for column in ("entry_time", "exit_time"):
            rows[column] = rows[column].dt.tz_convert("America/New_York")
        result = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, np.float64(0.5))
        pd.testing.assert_frame_equal(result[LEDGER_COLUMNS], rows, check_exact=True)
        self.assertEqual(result.index.tolist(), [20, 10])

    def test_success_preserves_source_and_returned_ledger_is_independent(self):
        rows = ledger([(100, 110), (50, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        for column in ("entry_time", "exit_time"):
            rows[column] = rows[column].dt.tz_convert("America/New_York")
        rows["optional_note"] = "untouched"
        rows = rows[rows.columns[::-1]]
        original = rows.copy(deep=True)
        result = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, 0.5)
        pd.testing.assert_frame_equal(rows, original, check_exact=True)
        self.assertNotIn("optional_note", result.columns)
        result.loc[20, "entry_price"] = 999
        pd.testing.assert_frame_equal(rows, original, check_exact=True)

    def test_invalid_fraction_failure_preserves_source(self):
        rows = ledger([(100, 110), (50, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        for column in ("entry_time", "exit_time"):
            rows[column] = rows[column].dt.tz_convert("America/New_York")
        rows["optional_note"] = "untouched"
        rows = rows[rows.columns[::-1]]
        original = rows.copy(deep=True)
        for fraction in (0, 1.2, True, np.nan):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, fraction)
                pd.testing.assert_frame_equal(rows, original, check_exact=True)

    def test_exact_output_columns_and_float64_financial_fields(self):
        for prices in ([(100, 110)], [(100, None)], [(100, 110), (50, None)], []):
            with self.subTest(prices=prices):
                result = calculate_trade_results_with_costs(ledger(prices), 1_000, 0.01, 0.02, 0.5)
                self.assertEqual(result.columns.tolist(), LEDGER_COLUMNS + FINANCIAL_COLUMNS)
                for column in FINANCIAL_COLUMNS:
                    self.assertEqual(str(result[column].dtype), "float64")

    def test_each_net_entry_delegates_its_current_capital_to_budget_helper(self):
        rows = ledger([(100, 110), (50, 60), (100, None)])
        with patch("trading_lab.backtest.costs.calculate_position_budget", wraps=calculate_position_budget) as helper:
            result = calculate_trade_results_with_costs(rows, 1_000, 0.01, 0.02, 0.5)
        self.assertEqual(helper.call_args_list, [
            call(1_000.0, 0.5),
            call(result.net_capital_after.iloc[0], 0.5),
            call(result.net_capital_after.iloc[1], 0.5),
        ])
        self.assertNotEqual(helper.call_args_list[0], helper.call_args_list[1])
        self.assertNotEqual(helper.call_args_list[1], helper.call_args_list[2])

    def test_empty_ledger_delegates_fraction_validation_to_budget_helper(self):
        with patch("trading_lab.backtest.costs.calculate_position_budget", wraps=calculate_position_budget) as helper:
            result = calculate_trade_results_with_costs(ledger([]), 1_000, position_fraction=0.5)
        helper.assert_called_once_with(1_000.0, 0.5)
        self.assertTrue(result.empty)

    def test_fee_and_slippage_validation_precede_ledger_and_fraction_validation(self):
        rows = ledger([(100, 110)]).drop(columns="status")
        for name in ("fee_rate", "slippage_rate"):
            with self.subTest(name=name):
                with patch("trading_lab.backtest.costs.calculate_position_budget", wraps=calculate_position_budget) as helper:
                    with self.assertRaisesRegex(ValueError, name):
                        calculate_trade_results_with_costs(rows, position_fraction=0, **{name: True})
                helper.assert_not_called()

    def test_gross_ledger_validation_precedes_net_fraction_validation(self):
        rows = ledger([(100, 110)]).drop(columns="status")
        with patch("trading_lab.backtest.costs.calculate_position_budget", wraps=calculate_position_budget) as helper:
            with self.assertRaisesRegex(ValueError, "Missing required columns"):
                calculate_trade_results_with_costs(rows, 1_000, position_fraction=0)
        helper.assert_not_called()

    def test_initial_capital_validation_precedes_net_fraction_validation(self):
        with patch("trading_lab.backtest.costs.calculate_position_budget", wraps=calculate_position_budget) as helper:
            with self.assertRaisesRegex(ValueError, "initial_capital"):
                calculate_trade_results_with_costs(ledger([]), 0, position_fraction=False)
        helper.assert_not_called()

    def test_fraction_validation_precedes_net_entry_arithmetic(self):
        with self.assertRaisesRegex(ValueError, "position_fraction"):
            calculate_trade_results_with_costs(ledger([(1e308, None)]), 1_000, 0.5, 0.5, 0)

    def test_partial_budget_underflow_is_rejected_by_helper(self):
        smallest = nextafter(0.0, 1.0)
        self.assertGreater(smallest, 0)
        self.assertEqual(smallest * 0.5, 0.0)
        with self.assertRaisesRegex(ValueError, "position budget"):
            calculate_trade_results_with_costs(ledger([(1, None)]), smallest, position_fraction=0.5)

    def test_partial_quantity_underflow_preserves_net_safety_check(self):
        # Full-allocation GROSS validation remains representable; the NET
        # partial budget is positive, but cannot fund a representable quantity.
        self.assertGreater(1e-300 / 1e23, 0)
        self.assertGreater(1e-300 * 0.1, 0)
        self.assertEqual((1e-300 * 0.1) / 1e23, 0)
        with self.assertRaisesRegex(ValueError, "Calculated quantity/notional"):
            calculate_trade_results_with_costs(ledger([(1e23, None)]), 1e-300, position_fraction=0.1)

    def test_partial_allocation_preserves_effective_entry_cost_overflow_check(self):
        with self.assertRaisesRegex(ValueError, "Calculated entry cost"):
            calculate_trade_results_with_costs(ledger([(1e308, None)]), 1_000, 0.5, 0.5, 0.5)
