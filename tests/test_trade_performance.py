"""Small synthetic ledgers verify realized accounting, compounding, and validation."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.backtest.performance import calculate_trade_results
from trading_lab.backtest.trades import build_trade_ledger


def ledger(prices):
    """Each (entry, exit) pair is a separate trade; None exit means OPEN."""
    rows = []
    start = pd.Timestamp("2025-01-01", tz="UTC")
    for number, (entry, exit_price) in enumerate(prices):
        rows.append({
            "trade_id": number + 1,
            "entry_time": start + pd.Timedelta(hours=2 * number),
            "entry_price": entry,
            "exit_time": pd.NaT if exit_price is None else start + pd.Timedelta(hours=2 * number + 1),
            "exit_price": float("nan") if exit_price is None else exit_price,
            "status": "OPEN" if exit_price is None else "CLOSED",
        })
    result = pd.DataFrame(rows, columns=["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"])
    if rows:
        # All-NaT OPEN exit columns still use the entry clock's UTC dtype.
        result["exit_time"] = pd.to_datetime(result["exit_time"], utc=True)
    return result


class TradePerformanceTests(unittest.TestCase):
    def test_a_profitable_closed_trade(self):
        result = calculate_trade_results(ledger([(100, 110)]))
        trade = result.iloc[0]
        self.assertEqual(trade.capital_before, 10_000)
        self.assertAlmostEqual(trade.quantity, 100)
        self.assertAlmostEqual(trade.trade_return, 0.10)
        self.assertAlmostEqual(trade.gross_pnl, 1_000)
        self.assertAlmostEqual(trade.capital_after, 11_000)

    def test_b_losing_closed_trade(self):
        trade = calculate_trade_results(ledger([(100, 90)])).iloc[0]
        self.assertAlmostEqual(trade.trade_return, -0.10)
        self.assertAlmostEqual(trade.gross_pnl, -1_000)
        self.assertAlmostEqual(trade.capital_after, 9_000)

    def test_c_multiple_trades_compound_plus_then_minus_ten_percent(self):
        result = calculate_trade_results(ledger([(100, 110), (100, 90)]))
        np.testing.assert_allclose(result.capital_before, [10_000, 11_000])
        np.testing.assert_allclose(result.capital_after, [11_000, 9_900])
        self.assertNotAlmostEqual(result.capital_after.iloc[-1], 10_000)

    def test_d_quantity_uses_current_compounded_capital(self):
        result = calculate_trade_results(ledger([(100, 110), (200, 180)]))
        np.testing.assert_allclose(result.quantity, [100, 55])
        self.assertAlmostEqual(result.quantity.iloc[1], result.capital_after.iloc[0] / 200)

    def test_e_open_trade_gets_quantity_but_no_realized_results(self):
        result = calculate_trade_results(ledger([(50_000, None)]))
        self.assertAlmostEqual(result.capital_before.iloc[0], 10_000)
        self.assertAlmostEqual(result.quantity.iloc[0], 0.2)
        self.assertTrue(result[["trade_return", "gross_pnl", "capital_after"]].isna().all().all())
        self.assertTrue(result.exit_time.isna().all())
        self.assertTrue(result.exit_price.isna().all())

    def test_f_final_open_trade_uses_last_closed_capital(self):
        result = calculate_trade_results(ledger([(100, 110), (50_000, None)]))
        self.assertAlmostEqual(result.capital_before.iloc[1], 11_000)
        self.assertAlmostEqual(result.quantity.iloc[1], 0.22)
        self.assertTrue(result.iloc[1][["trade_return", "gross_pnl", "capital_after"]].isna().all())

    def test_g_trade_after_open_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "OPEN trade must be final"):
            calculate_trade_results(ledger([(100, None), (100, 110)]))

    def test_h_multiple_open_trades_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "At most one OPEN"):
            calculate_trade_results(ledger([(100, None), (100, None)]))

    def test_i_closed_trade_missing_either_exit_field_is_rejected(self):
        for column in ("exit_time", "exit_price"):
            with self.subTest(column=column):
                rows = ledger([(100, 110)])
                rows.loc[0, column] = pd.NaT if column == "exit_time" else float("nan")
                with self.assertRaisesRegex(ValueError, "CLOSED trades must have both"):
                    calculate_trade_results(rows)

    def test_j_open_trade_with_either_exit_field_is_rejected(self):
        for column, value in (("exit_time", pd.Timestamp("2025-01-02", tz="UTC")), ("exit_price", 110)):
            with self.subTest(column=column):
                rows = ledger([(100, None)])
                rows.loc[0, column] = value
                with self.assertRaisesRegex(ValueError, "OPEN trades must have missing"):
                    calculate_trade_results(rows)

    def test_k_invalid_initial_capital_is_rejected_even_for_empty_ledger(self):
        for value in (0, -1, np.nan, np.inf, -np.inf, "10000", True, np.bool_(True), None, 1 + 2j, 10 ** 400):
            with self.subTest(value=str(value)[:30]):
                with self.assertRaisesRegex(ValueError, "initial_capital.*finite positive"):
                    calculate_trade_results(ledger([]), initial_capital=value)

    def test_l_invalid_entry_and_exit_prices_are_rejected(self):
        for column in ("entry_price", "exit_price"):
            for value in (0, -1, np.inf, -np.inf, "100", True, 1 + 2j, 10 ** 400):
                with self.subTest(column=column, value=str(value)[:30]):
                    rows = ledger([(100, 110)])
                    rows[column] = rows[column].astype("object")
                    rows.loc[0, column] = value
                    with self.assertRaisesRegex(ValueError, column + ".*finite positive"):
                        calculate_trade_results(rows)
        for value in (np.nan, None, pd.NA):
            with self.subTest(missing_entry=value):
                rows = ledger([(100, 110)])
                rows["entry_price"] = pd.Series([value])
                with self.assertRaisesRegex(ValueError, "entry_price"):
                    calculate_trade_results(rows)

    def test_m_invalid_trade_id_sequence_is_rejected(self):
        for ids in ([1, 1], [2, 1], [1, 3], [0, 1], [1.0, 2.0], ["1", "2"], [True, 2], [None, 2]):
            with self.subTest(ids=ids):
                rows = ledger([(100, 110), (100, 90)])
                rows["trade_id"] = pd.Series(ids, dtype="object")
                with self.assertRaisesRegex(ValueError, "trade_id.*consecutive integers"):
                    calculate_trade_results(rows)

    def test_m_invalid_status_and_entry_order_are_rejected(self):
        for status in ("closed", "UNKNOWN", None, pd.NA):
            with self.subTest(status=status):
                rows = ledger([(100, 110)])
                rows.loc[0, "status"] = status
                with self.assertRaisesRegex(ValueError, "status must be"):
                    calculate_trade_results(rows)
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):
                rows = ledger([(100, 110), (100, 90)])
                rows.loc[1, "entry_time"] = rows.loc[0, "entry_time"] - pd.Timedelta(hours=0 if duplicate else 1)
                with self.assertRaisesRegex(ValueError, "unique and chronological"):
                    calculate_trade_results(rows)

    def test_m_exit_must_strictly_follow_entry(self):
        for difference in (0, -1):
            with self.subTest(difference=difference):
                rows = ledger([(100, 110)])
                rows.loc[0, "exit_time"] = rows.loc[0, "entry_time"] + pd.Timedelta(hours=difference)
                with self.assertRaisesRegex(ValueError, "strictly after"):
                    calculate_trade_results(rows)

    def test_m_overlapping_trades_are_rejected(self):
        rows = ledger([(100, 110), (100, 90)])
        rows.loc[0, "exit_time"] = rows.loc[1, "entry_time"] + pd.Timedelta(hours=1)
        with self.assertRaisesRegex(ValueError, "must not overlap"):
            calculate_trade_results(rows)

    def test_n_input_context_and_index_are_preserved(self):
        rows = ledger([(100, 110), (100, None)])
        rows.index = pd.Index([20, 10], name="source_trade")
        rows["optional_note"] = "untouched"
        original = rows.copy(deep=True)
        result = calculate_trade_results(rows)
        pd.testing.assert_frame_equal(rows, original)
        pd.testing.assert_frame_equal(result[original.columns.drop("optional_note")], original.drop(columns="optional_note"))
        result.loc[20, "entry_price"] = 999
        pd.testing.assert_frame_equal(rows, original)

    def test_o_empty_ledger_has_exact_schema_and_stable_dtypes(self):
        result = calculate_trade_results(ledger([]))
        self.assertTrue(result.empty)
        self.assertEqual(result.columns.tolist(), [
            "trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status",
            "capital_before", "quantity", "trade_return", "gross_pnl", "capital_after",
        ])
        self.assertEqual(str(result.trade_id.dtype), "int64")
        self.assertEqual(str(result.entry_time.dtype), "datetime64[ns]")
        self.assertEqual(str(result.exit_time.dtype), "datetime64[ns]")
        self.assertEqual(str(result.status.dtype), "object")
        for column in result.columns.drop(["trade_id", "entry_time", "exit_time", "status"]):
            self.assertEqual(str(result[column].dtype), "float64")

    def test_o_empty_stage45_ledger_retains_utc_datetime_dtypes(self):
        state = pd.DataFrame({
            "timestamp": pd.Series([], dtype="datetime64[ns, UTC]"),
            "signal": pd.Series([], dtype="object"),
            "execution_time": pd.Series([], dtype="datetime64[ns, UTC]"),
            "execution_price": pd.Series([], dtype="float64"),
            "executed_position": pd.Series([], dtype="int64"),
        })
        result = calculate_trade_results(build_trade_ledger(state))
        self.assertEqual(str(result.entry_time.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(result.exit_time.dtype), "datetime64[ns, UTC]")

    def test_capital_identities_agree_with_floating_point_tolerance(self):
        result = calculate_trade_results(ledger([(3, 4), (7, 5), (11, 19)]), initial_capital=123.45)
        np.testing.assert_allclose(result.capital_after, result.capital_before * (1 + result.trade_return), rtol=1e-12)
        np.testing.assert_allclose(result.capital_after, result.capital_before + result.gross_pnl, rtol=1e-12)
        np.testing.assert_allclose(result.quantity * result.entry_price, result.capital_before, rtol=1e-12)
        np.testing.assert_allclose(result.capital_before.iloc[1:], result.capital_after.iloc[:-1], rtol=1e-12)

    def test_custom_capital_and_no_quantity_rounding(self):
        trade = calculate_trade_results(ledger([(50_000, 55_000)]), initial_capital=np.float64(123.45)).iloc[0]
        self.assertAlmostEqual(trade.quantity, 123.45 / 50_000)
        self.assertAlmostEqual(trade.capital_after, 135.795)

    def test_unchanged_price_has_zero_return_and_pnl(self):
        trade = calculate_trade_results(ledger([(100, 100)])).iloc[0]
        self.assertAlmostEqual(trade.trade_return, 0)
        self.assertAlmostEqual(trade.gross_pnl, 0)
        self.assertAlmostEqual(trade.capital_after, 10_000)

    def test_extreme_loss_keeps_capital_non_negative(self):
        result = calculate_trade_results(ledger([(100, 0.0001)]))
        self.assertGreaterEqual(result.capital_after.iloc[0], 0)
        self.assertAlmostEqual(result.capital_after.iloc[0], 0.01)

    def test_numerical_overflow_and_quantity_underflow_are_rejected(self):
        for entry, exit_price, capital in (
            (1e-308, 1, 1e308),  # Quantity overflow.
            (1, 2, 1e308),      # Capital overflow.
            (1e-308, 1e308, 1e-300),  # Return/PnL overflow.
            (1e308, None, 1e-300),  # Quantity underflow cannot deploy capital.
        ):
            with self.subTest(entry=entry, exit_price=exit_price):
                with self.assertRaisesRegex(ValueError, "Calculated"):
                    calculate_trade_results(ledger([(entry, exit_price)]), initial_capital=capital)

    def test_dataframe_required_columns_and_unique_columns(self):
        with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
            calculate_trade_results(None)
        rows = ledger([(100, 110)])
        for column in rows.columns:
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "Missing required columns"):
                    calculate_trade_results(rows.drop(columns=column))
        with self.assertRaisesRegex(ValueError, "column names must be unique"):
            calculate_trade_results(pd.concat([rows, rows[["status"]]], axis=1))

    def test_missing_non_datetime_and_incompatible_times_rejected(self):
        rows = ledger([(100, 110)])
        with self.assertRaisesRegex(ValueError, "non-missing pandas datetimes"):
            calculate_trade_results(rows.assign(entry_time=pd.NaT))
        with self.assertRaisesRegex(ValueError, "non-missing pandas datetimes"):
            calculate_trade_results(rows.assign(entry_time=rows.entry_time.astype(str)))
        with self.assertRaisesRegex(ValueError, "pandas datetime column"):
            calculate_trade_results(rows.assign(exit_time=rows.exit_time.astype(str)))
        with self.assertRaisesRegex(ValueError, "same timezone"):
            calculate_trade_results(rows.assign(exit_time=rows.exit_time.dt.tz_localize(None)))

    def test_naive_datetime_ledger_is_supported_without_conversion(self):
        rows = ledger([(100, 110)])
        rows["entry_time"] = rows.entry_time.dt.tz_localize(None)
        rows["exit_time"] = rows.exit_time.dt.tz_localize(None)
        result = calculate_trade_results(rows)
        pd.testing.assert_frame_equal(result[rows.columns], rows)


if __name__ == "__main__":
    unittest.main()
