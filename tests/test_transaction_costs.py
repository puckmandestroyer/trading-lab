"""Synthetic cost accounting, self-financing, and zero-cost regression tests."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results


def ledger(prices):
    """Explicit non-overlapping trades; None exit denotes the final OPEN trade."""
    start = pd.Timestamp("2025-01-01", tz="UTC")
    rows = [{
        "trade_id": number + 1,
        "entry_time": start + pd.Timedelta(hours=2 * number),
        "entry_price": entry,
        "exit_time": pd.NaT if exit_price is None else start + pd.Timedelta(hours=2 * number + 1),
        "exit_price": np.nan if exit_price is None else exit_price,
        "status": "OPEN" if exit_price is None else "CLOSED",
    } for number, (entry, exit_price) in enumerate(prices)]
    result = pd.DataFrame(rows, columns=["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"])
    if rows:
        result["exit_time"] = pd.to_datetime(result["exit_time"], utc=True)
    return result


class TransactionCostTests(unittest.TestCase):
    def test_zero_cost_equivalence_for_closed_and_open_trades(self):
        rows = ledger([(100, 110), (200, 180), (50_000, None)])
        baseline = calculate_trade_results(rows)
        costs = calculate_trade_results_with_costs(rows)
        for original, new in (
            ("capital_before", "capital_before"), ("quantity", "quantity"),
            ("trade_return", "net_trade_return"), ("gross_pnl", "gross_pnl"),
            ("gross_pnl", "net_pnl"), ("capital_after", "net_capital_after"),
        ):
            np.testing.assert_allclose(baseline[original], costs[new], rtol=1e-12, atol=1e-10, equal_nan=True)

    def test_adverse_entry_slippage_increases_price_and_reduces_quantity(self):
        result = calculate_trade_results_with_costs(ledger([(100, None)]), slippage_rate=0.01).iloc[0]
        self.assertAlmostEqual(result.effective_entry_price, 101)
        self.assertAlmostEqual(result.quantity, 10_000 / 101)
        self.assertEqual(result.entry_price, 100)

    def test_adverse_exit_slippage_reduces_effective_exit(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110)]), slippage_rate=0.01).iloc[0]
        self.assertAlmostEqual(result.effective_exit_price, 108.9)
        self.assertEqual(result.exit_price, 110)
        self.assertAlmostEqual(result.price_adjusted_pnl, result.quantity * (108.9 - 101))

    def test_entry_fee_is_charged_on_effective_notional(self):
        result = calculate_trade_results_with_costs(ledger([(100, None)]), fee_rate=0.01, slippage_rate=0.02).iloc[0]
        self.assertAlmostEqual(result.quantity, 10_000 / (102 * 1.01))
        self.assertAlmostEqual(result.entry_notional, result.quantity * 102)
        self.assertAlmostEqual(result.entry_fee, result.entry_notional * 0.01)

    def test_exit_fee_is_charged_on_effective_exit_notional(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110)]), fee_rate=0.01, slippage_rate=0.02).iloc[0]
        self.assertAlmostEqual(result.exit_notional, result.quantity * 107.8)
        self.assertAlmostEqual(result.exit_fee, result.exit_notional * 0.01)
        self.assertAlmostEqual(result.total_fees, result.entry_fee + result.exit_fee)

    def test_self_financing_sizing_includes_entry_fee(self):
        for fee, slippage in ((0, 0), (0.001, 0.0005), (0.5, 0.25)):
            with self.subTest(fee=fee, slippage=slippage):
                result = calculate_trade_results_with_costs(ledger([(100, 110), (50, None)]), fee_rate=fee, slippage_rate=slippage)
                np.testing.assert_allclose(result.entry_notional + result.entry_fee, result.capital_before, rtol=1e-12)
                np.testing.assert_allclose(result.quantity * result.effective_entry_price + result.entry_fee, result.capital_before, rtol=1e-12)

    def test_profitable_trade_gets_worse_after_costs(self):
        rows = ledger([(100, 110)])
        baseline = calculate_trade_results(rows).iloc[0]
        result = calculate_trade_results_with_costs(rows, fee_rate=0.001, slippage_rate=0.0005).iloc[0]
        self.assertLess(result.net_pnl, baseline.gross_pnl)
        self.assertLess(result.net_trade_return, baseline.trade_return)
        self.assertLess(result.net_capital_after, baseline.capital_after)

    def test_losing_trade_gets_worse_after_costs(self):
        rows = ledger([(100, 90)])
        baseline = calculate_trade_results(rows).iloc[0]
        result = calculate_trade_results_with_costs(rows, fee_rate=0.001, slippage_rate=0.0005).iloc[0]
        self.assertLess(result.net_pnl, baseline.gross_pnl)
        self.assertLess(result.net_trade_return, baseline.trade_return)
        self.assertLess(result.net_capital_after, baseline.capital_after)

    def test_multi_trade_compounding_uses_net_capital(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110), (200, 180)]), fee_rate=0.01, slippage_rate=0.02)
        # Independent proceeds factor: sell notional less exit fee divided by
        # entry cost including entry fee. It is applied to current capital.
        first_after = 10_000 * (110 * 0.98 / (100 * 1.02)) * (0.99 / 1.01)
        second_after = first_after * (180 * 0.98 / (200 * 1.02)) * (0.99 / 1.01)
        self.assertAlmostEqual(result.net_capital_after.iloc[0], first_after)
        self.assertAlmostEqual(result.capital_before.iloc[1], first_after)
        self.assertAlmostEqual(result.quantity.iloc[1], first_after / (200 * 1.02 * 1.01))
        self.assertAlmostEqual(result.net_capital_after.iloc[1], second_after)

    def test_open_trade_has_entry_costs_without_exit_or_realized_results(self):
        result = calculate_trade_results_with_costs(ledger([(50_000, None)]), fee_rate=0.001, slippage_rate=0.0005)
        present = ["capital_before", "effective_entry_price", "quantity", "entry_notional", "entry_fee"]
        missing = [
            "effective_exit_price", "exit_notional", "exit_fee", "total_fees", "gross_pnl",
            "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
        ]
        self.assertTrue(result[present].notna().all().all())
        self.assertTrue(result[missing].isna().all().all())
        self.assertGreater(result.entry_fee.iloc[0], 0)
        self.assertTrue(result.exit_price.isna().all())

    def test_final_open_trade_uses_previous_net_capital(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110), (50_000, None)]), fee_rate=0.001, slippage_rate=0.0005)
        self.assertAlmostEqual(result.capital_before.iloc[1], result.net_capital_after.iloc[0])
        self.assertAlmostEqual(result.quantity.iloc[1], result.capital_before.iloc[1] / (50_025 * 1.001))

    def test_zero_fee_positive_slippage_has_no_fees(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110)]), slippage_rate=0.01).iloc[0]
        self.assertEqual(result.entry_fee, 0)
        self.assertEqual(result.exit_fee, 0)
        self.assertEqual(result.total_fees, 0)
        self.assertAlmostEqual(result.net_pnl, result.price_adjusted_pnl)
        self.assertLess(result.price_adjusted_pnl, result.gross_pnl)

    def test_positive_fee_zero_slippage_keeps_effective_prices_recorded(self):
        result = calculate_trade_results_with_costs(ledger([(100, 110)]), fee_rate=0.01).iloc[0]
        self.assertEqual(result.effective_entry_price, result.entry_price)
        self.assertEqual(result.effective_exit_price, result.exit_price)
        self.assertAlmostEqual(result.price_adjusted_pnl, result.gross_pnl)
        self.assertAlmostEqual(result.net_pnl, result.gross_pnl - result.total_fees)

    def test_invalid_fee_and_slippage_parameters_are_rejected(self):
        for name in ("fee_rate", "slippage_rate"):
            for value in (-0.001, 1, 1.01, np.nan, np.inf, -np.inf, "0.001", True, np.bool_(True), None, 1 + 2j, 10 ** 400):
                with self.subTest(name=name, value=str(value)[:30]):
                    with self.assertRaisesRegex(ValueError, name):
                        calculate_trade_results_with_costs(ledger([]), **{name: value})

    def test_valid_numpy_rates_and_custom_initial_capital(self):
        result = calculate_trade_results_with_costs(
            ledger([(100, 110)]), initial_capital=np.float64(123.45),
            fee_rate=np.float64(0.001), slippage_rate=np.float64(0.0005),
        ).iloc[0]
        self.assertAlmostEqual(result.capital_before, 123.45)
        self.assertAlmostEqual(result.entry_notional + result.entry_fee, 123.45)

    def test_invalid_initial_capital_is_rejected(self):
        for value in (0, -1, np.nan, np.inf, "10000", True, None):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, "initial_capital"):
                    calculate_trade_results_with_costs(ledger([]), initial_capital=value)

    def test_input_raw_prices_and_index_are_preserved(self):
        rows = ledger([(100, 110), (200, None)])
        rows.index = pd.Index([30, 10], name="original_trade")
        rows["note"] = "preserve input"
        original = rows.copy(deep=True)
        result = calculate_trade_results_with_costs(rows, fee_rate=0.001, slippage_rate=0.0005)
        pd.testing.assert_frame_equal(rows, original)
        pd.testing.assert_frame_equal(result[rows.columns.drop("note")], rows.drop(columns="note"))
        result.loc[30, "entry_price"] = 999
        pd.testing.assert_frame_equal(rows, original)

    def test_empty_ledger_schema_and_financial_dtypes(self):
        result = calculate_trade_results_with_costs(ledger([]))
        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), [
            "trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status",
            "capital_before", "effective_entry_price", "effective_exit_price", "quantity",
            "entry_notional", "exit_notional", "entry_fee", "exit_fee", "total_fees",
            "gross_pnl", "price_adjusted_pnl", "net_pnl", "net_trade_return", "net_capital_after",
        ])
        for column in result.columns[6:]:
            self.assertEqual(str(result[column].dtype), "float64")
        self.assertEqual(str(result.trade_id.dtype), "int64")
        self.assertEqual(str(result.entry_time.dtype), "datetime64[ns]")
        typed = ledger([]).assign(
            entry_time=pd.Series([], dtype="datetime64[ns, UTC]"),
            exit_time=pd.Series([], dtype="datetime64[ns, UTC]"),
        )
        self.assertEqual(str(calculate_trade_results_with_costs(typed).entry_time.dtype), "datetime64[ns, UTC]")

    def test_arithmetic_identities_and_recorded_price_gross_pnl(self):
        result = calculate_trade_results_with_costs(ledger([(3, 4), (7, 5), (11, 19)]), fee_rate=0.003, slippage_rate=0.002)
        np.testing.assert_allclose(result.entry_notional, result.quantity * result.effective_entry_price, rtol=1e-12)
        np.testing.assert_allclose(result.exit_notional, result.quantity * result.effective_exit_price, rtol=1e-12)
        np.testing.assert_allclose(result.total_fees, result.entry_fee + result.exit_fee, rtol=1e-12)
        np.testing.assert_allclose(result.gross_pnl, result.quantity * (result.exit_price - result.entry_price), rtol=1e-12)
        np.testing.assert_allclose(result.price_adjusted_pnl, result.quantity * (result.effective_exit_price - result.effective_entry_price), rtol=1e-12)
        np.testing.assert_allclose(result.net_pnl, result.price_adjusted_pnl - result.total_fees, rtol=1e-12)
        np.testing.assert_allclose(result.net_trade_return, result.net_pnl / result.capital_before, rtol=1e-12)
        np.testing.assert_allclose(result.net_capital_after, result.capital_before + result.net_pnl, rtol=1e-12)
        np.testing.assert_allclose(result.net_capital_after, result.exit_notional - result.exit_fee, rtol=1e-12)

    def test_ledger_validation_errors_propagate_without_repair(self):
        rows = ledger([(100, 110), (200, None)])
        malformed = [
            rows.drop(columns="entry_price"), rows.assign(trade_id=[1, 1]),
            rows.assign(status=["OPEN", "CLOSED"]), rows.assign(status=["OPEN", "OPEN"]),
            rows.assign(status=["UNKNOWN", "OPEN"]), rows.assign(entry_price=[0, 200]),
        ]
        missing_exit = rows.copy()
        missing_exit.loc[0, "exit_price"] = np.nan
        malformed.append(missing_exit)
        reversed_time = rows.copy()
        reversed_time["entry_time"] = reversed_time.entry_time.iloc[::-1].tolist()
        malformed.append(reversed_time)
        overlap = rows.copy()
        overlap.loc[0, "exit_time"] = rows.loc[1, "entry_time"] + pd.Timedelta(hours=1)
        malformed.append(overlap)
        for number, invalid in enumerate(malformed):
            with self.subTest(number=number):
                original = invalid.copy(deep=True)
                with self.assertRaises(ValueError):
                    calculate_trade_results_with_costs(invalid)
                pd.testing.assert_frame_equal(invalid, original)
        with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
            calculate_trade_results_with_costs(None)

    def test_cost_specific_numeric_overflow_is_rejected(self):
        # Baseline accepts this price; adding slippage/fee overflows unit cost.
        rows = ledger([(1e308, None)])
        with self.assertRaisesRegex(ValueError, "Calculated entry cost"):
            calculate_trade_results_with_costs(rows, fee_rate=0.5, slippage_rate=0.5)


if __name__ == "__main__":
    unittest.main()
