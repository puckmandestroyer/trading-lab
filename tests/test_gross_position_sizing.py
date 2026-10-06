"""Synthetic GROSS allocation tests; NET, equity, and pipelines are untouched."""

from math import nextafter
import unittest
from unittest.mock import call, patch

import numpy as np
import pandas as pd

from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.risk.position_sizing import calculate_position_budget


LEDGER_COLUMNS = ["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"]
FINANCIAL_COLUMNS = ["capital_before", "quantity", "trade_return", "gross_pnl", "capital_after"]


def ledger(prices):
    """Typed, chronological non-overlapping trades; None exit means OPEN."""
    entries = pd.date_range("2025-01-01", periods=len(prices), freq="2h", tz="UTC")
    return pd.DataFrame({
        "trade_id": pd.Series(range(1, len(prices) + 1), dtype="int64"),
        "entry_time": entries,
        "entry_price": pd.Series([entry for entry, _ in prices], dtype="float64"),
        "exit_time": pd.Series([
            entry_time + pd.Timedelta(hours=1) if exit_price is not None else pd.NaT
            for entry_time, (_, exit_price) in zip(entries, prices)
        ], dtype="datetime64[ns, UTC]"),
        "exit_price": pd.Series([
            exit_price if exit_price is not None else np.nan for _, exit_price in prices
        ], dtype="float64"),
        "status": pd.Series([
            "CLOSED" if exit_price is not None else "OPEN" for _, exit_price in prices
        ], dtype="object"),
    })


class GrossPositionSizingTests(unittest.TestCase):
    def test_default_matches_explicit_full_allocation_exactly(self):
        rows = ledger([(3, 4), (7, 5), (11, None)])
        default = calculate_trade_results(rows, initial_capital=123.45)
        full = calculate_trade_results(rows, initial_capital=123.45, position_fraction=1.0)
        pd.testing.assert_frame_equal(default, full, check_exact=True)

    def test_half_allocation_profitable_closed_trade(self):
        trade = calculate_trade_results(ledger([(100, 110)]), 1_000, 0.5).iloc[0]
        self.assertEqual(trade.capital_before, 1_000)
        self.assertEqual(trade.quantity, 5)
        self.assertAlmostEqual(trade.trade_return, 0.10)
        self.assertEqual(trade.gross_pnl, 50)
        self.assertEqual(trade.capital_after, 1_050)

    def test_quarter_allocation_profitable_closed_trade(self):
        trade = calculate_trade_results(ledger([(100, 120)]), 1_000, 0.25).iloc[0]
        self.assertEqual(trade.capital_before, 1_000)
        self.assertEqual(trade.quantity, 2.5)
        self.assertAlmostEqual(trade.trade_return, 0.20)
        self.assertEqual(trade.gross_pnl, 50)
        self.assertEqual(trade.capital_after, 1_050)

    def test_half_allocation_losing_closed_trade(self):
        trade = calculate_trade_results(ledger([(100, 90)]), 1_000, 0.5).iloc[0]
        self.assertEqual(trade.quantity, 5)
        self.assertAlmostEqual(trade.trade_return, -0.10)
        self.assertEqual(trade.gross_pnl, -50)
        self.assertEqual(trade.capital_after, 950)
        self.assertEqual(trade.capital_before - trade.quantity * trade.entry_price, 500)

    def test_trade_return_remains_raw_position_return_for_every_fraction(self):
        rows = ledger([(100, 110), (100, 90)])
        full = calculate_trade_results(rows, 1_000)
        for fraction in (0.5, 0.25):
            with self.subTest(fraction=fraction):
                partial = calculate_trade_results(rows, 1_000, fraction)
                pd.testing.assert_series_equal(partial.trade_return, full.trade_return, check_exact=True)
        half = calculate_trade_results(rows.iloc[:1], 1_000, 0.5).iloc[0]
        self.assertAlmostEqual(half.trade_return, 0.10)
        self.assertAlmostEqual(half.gross_pnl / half.capital_before, 0.05)

    def test_first_trade_pnl_scales_with_fraction(self):
        rows = ledger([(100, 110)])
        for fraction, expected in ((1.0, 100), (0.5, 50), (0.25, 25)):
            with self.subTest(fraction=fraction):
                self.assertEqual(calculate_trade_results(rows, 1_000, fraction).gross_pnl.iloc[0], expected)

    def test_reserve_cash_reconciles_with_exit_position_value(self):
        result = calculate_trade_results(ledger([(3, 4), (7, 5), (11, 19)]), 123.45, 0.37)
        reserve = result.capital_before - result.quantity * result.entry_price
        self.assertTrue(reserve.gt(0).all())
        np.testing.assert_allclose(
            reserve, result.capital_before * (1 - 0.37), rtol=1e-12, atol=1e-12,
        )
        np.testing.assert_allclose(
            result.capital_after, reserve + result.quantity * result.exit_price,
            rtol=1e-12, atol=1e-12,
        )
        np.testing.assert_allclose(
            result.capital_after, result.capital_before + result.gross_pnl,
            rtol=1e-12, atol=1e-12,
        )

    def test_two_closed_trades_compound_from_current_total_capital(self):
        result = calculate_trade_results(ledger([(100, 110), (50, 60)]), 1_000, 0.5)
        self.assertEqual(result.capital_before.tolist(), [1_000, 1_050])
        self.assertEqual(result.quantity.tolist(), [5, 10.5])
        self.assertEqual(result.gross_pnl.tolist(), [50, 105])
        self.assertEqual(result.capital_after.tolist(), [1_050, 1_155])

    def test_next_budget_uses_capital_after_a_loss(self):
        result = calculate_trade_results(ledger([(100, 90), (50, 60)]), 1_000, 0.5)
        self.assertEqual(result.capital_before.tolist(), [1_000, 950])
        self.assertEqual(result.quantity.tolist(), [5, 9.5])
        self.assertEqual(result.capital_after.tolist(), [950, 1_045])

    def test_closed_then_open_uses_last_closed_total_capital(self):
        result = calculate_trade_results(ledger([(100, 110), (50, None)]), 1_000, 0.5)
        final = result.iloc[-1]
        self.assertEqual(final.status, "OPEN")
        self.assertEqual(final.capital_before, 1_050)
        self.assertEqual(final.quantity, 10.5)
        self.assertEqual(final.quantity * final.entry_price, 525)
        self.assertTrue(final[["trade_return", "gross_pnl", "capital_after"]].isna().all())
        self.assertTrue(final[["exit_time", "exit_price"]].isna().all())

    def test_open_only_partial_allocation_has_no_realized_result_or_forced_close(self):
        result = calculate_trade_results(ledger([(100, None)]), 1_000, 0.5)
        self.assertEqual(len(result), 1)
        trade = result.iloc[0]
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.capital_before, 1_000)
        self.assertEqual(trade.quantity, 5)
        self.assertEqual(trade.capital_before - trade.quantity * trade.entry_price, 500)
        self.assertTrue(trade[["exit_time", "exit_price", "trade_return", "gross_pnl", "capital_after"]].isna().all())

    def test_empty_typed_ledger_retains_exact_full_allocation_schema_and_dtypes(self):
        rows = ledger([])
        full = calculate_trade_results(rows, 1_000, 1.0)
        half = calculate_trade_results(rows, 1_000, 0.5)
        self.assertTrue(half.empty)
        self.assertEqual(half.columns.tolist(), LEDGER_COLUMNS + FINANCIAL_COLUMNS)
        self.assertEqual(str(half.entry_time.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(half.exit_time.dtype), "datetime64[ns, UTC]")
        pd.testing.assert_frame_equal(half, full, check_exact=True)

    def test_non_range_index_and_timezone_are_preserved(self):
        rows = ledger([(100, 110), (50, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        for column in ("entry_time", "exit_time"):
            rows[column] = rows[column].dt.tz_convert("America/New_York")
        result = calculate_trade_results(rows, 1_000, np.float64(0.5))
        pd.testing.assert_frame_equal(result[LEDGER_COLUMNS], rows, check_exact=True)
        self.assertEqual(result.index.tolist(), [20, 10])
        self.assertEqual(result.index.name, "source_trade")

    def test_success_preserves_source_and_returned_ledger_fields_are_independent(self):
        rows = ledger([(100, 110), (50, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        rows["optional_note"] = "untouched"
        original = rows.copy(deep=True)
        result = calculate_trade_results(rows, 1_000, 0.5)
        pd.testing.assert_frame_equal(rows, original, check_exact=True)
        self.assertNotIn("optional_note", result.columns)
        result.loc[20, "entry_price"] = 999
        pd.testing.assert_frame_equal(rows, original, check_exact=True)

    def test_invalid_fraction_failure_preserves_source(self):
        rows = ledger([(100, 110), (50, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        rows["optional_note"] = "untouched"
        original = rows.copy(deep=True)
        for fraction in (0, 1.2, True, np.nan):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_trade_results(rows, 1_000, fraction)
                pd.testing.assert_frame_equal(rows, original, check_exact=True)

    def test_exact_output_columns_and_float64_financial_fields(self):
        for prices in ([(100, 110)], [(100, None)], [(100, 110), (50, None)], []):
            with self.subTest(prices=prices):
                result = calculate_trade_results(ledger(prices), 1_000, 0.5)
                self.assertEqual(result.columns.tolist(), LEDGER_COLUMNS + FINANCIAL_COLUMNS)
                for column in FINANCIAL_COLUMNS:
                    self.assertEqual(str(result[column].dtype), "float64")

    def test_each_entry_delegates_its_current_capital_to_budget_helper(self):
        rows = ledger([(100, 110), (50, 60), (100, None)])
        with patch("trading_lab.backtest.performance.calculate_position_budget", wraps=calculate_position_budget) as helper:
            calculate_trade_results(rows, 1_000, 0.5)
        self.assertEqual(helper.call_args_list, [call(1_000.0, 0.5), call(1_050.0, 0.5), call(1_155.0, 0.5)])

    def test_empty_ledger_delegates_fraction_validation_to_budget_helper(self):
        with patch("trading_lab.backtest.performance.calculate_position_budget", wraps=calculate_position_budget) as helper:
            result = calculate_trade_results(ledger([]), 1_000, 0.5)
        helper.assert_called_once_with(1_000.0, 0.5)
        self.assertTrue(result.empty)

    def test_invalid_fraction_is_rejected_for_empty_ledger(self):
        for fraction in (0, 1.2, True, np.nan):
            with self.subTest(fraction=fraction):
                with self.assertRaisesRegex(ValueError, "position_fraction"):
                    calculate_trade_results(ledger([]), 1_000, fraction)

    def test_budget_underflow_is_rejected_by_helper(self):
        smallest = nextafter(0.0, 1.0)
        self.assertGreater(smallest, 0)
        self.assertEqual(smallest * 0.5, 0.0)
        with self.assertRaisesRegex(ValueError, "position budget"):
            calculate_trade_results(ledger([(1, None)]), smallest, 0.5)

    def test_partial_allocation_preserves_quantity_underflow_rejection(self):
        with self.assertRaisesRegex(ValueError, "Calculated quantity"):
            calculate_trade_results(ledger([(1e308, None)]), 1e-300, 0.5)

    def test_partial_allocation_preserves_quantity_overflow_rejection(self):
        with self.assertRaisesRegex(ValueError, "Calculated quantity"):
            calculate_trade_results(ledger([(1e-308, None)]), 1e308, 0.5)

    def test_partial_allocation_preserves_nonfinite_result_rejection(self):
        with self.assertRaisesRegex(ValueError, "Calculated results"):
            calculate_trade_results(ledger([(1, 4)]), 1e308, 0.5)

    def test_missing_ledger_columns_are_rejected_before_fraction_validation(self):
        rows = ledger([(100, 110)]).drop(columns="status")
        with patch("trading_lab.backtest.performance.calculate_position_budget", wraps=calculate_position_budget) as helper:
            with self.assertRaisesRegex(ValueError, "Missing required columns"):
                calculate_trade_results(rows, 1_000, 0)
        helper.assert_not_called()

    def test_initial_capital_validation_still_precedes_fraction_validation(self):
        with self.assertRaisesRegex(ValueError, "initial_capital.*finite positive"):
            calculate_trade_results(ledger([]), 0, False)
