"""Explicit synthetic fills test pairing, timing, and validation without PnL."""

import unittest

import pandas as pd

from trading_lab.backtest.execution import apply_next_open_execution
from trading_lab.backtest.trades import build_trade_ledger


def backtest(signals, positions, fills=None):
    """Fill mapping: source row -> (receiving hour, price); states are explicit."""
    rows = pd.DataFrame({
        "timestamp": pd.date_range("2025-01-01", periods=len(signals), freq="h", tz="UTC"),
        "signal": pd.Series(signals, dtype="object"),
        "execution_time": pd.Series(pd.NaT, index=range(len(signals)), dtype="datetime64[ns, UTC]"),
        "execution_price": pd.Series(float("nan"), index=range(len(signals)), dtype="float64"),
        "executed_position": pd.Series(positions, dtype="int64"),
    })
    for row, (hour, price) in (fills or {}).items():
        rows.loc[row, "execution_time"] = pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=hour)
        rows.loc[row, "execution_price"] = price
    return rows


class TradeLedgerTests(unittest.TestCase):
    def closed_example(self):
        return backtest(
            ["HOLD", "LONG_ENTRY", "HOLD", "HOLD", "LONG_EXIT", "HOLD"],
            [0, 0, 1, 1, 1, 0], {1: (2, 100), 4: (5, 110)},
        )

    def test_a_one_closed_trade_uses_recorded_fill_time_and_price(self):
        rows = self.closed_example()
        # Other price fields and desired state cannot supply fill information.
        rows["open"] = 999
        rows["close"] = 888
        rows["desired_position"] = 0
        ledger = build_trade_ledger(rows)
        self.assertEqual(len(ledger), 1)
        trade = ledger.iloc[0]
        self.assertEqual(trade.trade_id, 1)
        self.assertEqual(trade.status, "CLOSED")
        self.assertEqual(trade.entry_time, rows.loc[1, "execution_time"])
        self.assertEqual(trade.entry_price, 100)
        self.assertEqual(trade.exit_time, rows.loc[4, "execution_time"])
        self.assertEqual(trade.exit_price, 110)

    def test_b_multiple_closed_trades_have_independent_sequential_ids(self):
        rows = backtest(
            ["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"] * 2,
            [0, 1, 1, 0] * 2,
            {0: (1, 100), 2: (3, 110), 4: (5, 120), 6: (7, 115)},
        )
        ledger = build_trade_ledger(rows)
        self.assertEqual(ledger.trade_id.tolist(), [1, 2])
        self.assertEqual(ledger.status.tolist(), ["CLOSED", "CLOSED"])
        self.assertEqual(ledger.entry_price.tolist(), [100, 120])
        self.assertEqual(ledger.exit_price.tolist(), [110, 115])
        self.assertTrue(ledger.entry_time.lt(ledger.exit_time).all())

    def test_c_final_open_trade_has_no_fabricated_exit(self):
        rows = backtest(["LONG_ENTRY", "HOLD", "HOLD"], [0, 1, 1], {0: (1, 100)})
        rows["close"] = [100, 110, 999]
        trade = build_trade_ledger(rows).iloc[0]
        self.assertEqual(trade.status, "OPEN")
        self.assertEqual(trade.entry_price, 100)
        self.assertTrue(pd.isna(trade.exit_time))
        self.assertTrue(pd.isna(trade.exit_price))

    def test_d_final_unexecuted_exit_leaves_trade_open_despite_flat_intent(self):
        rows = backtest(["LONG_ENTRY", "HOLD", "LONG_EXIT"], [0, 1, 1], {0: (1, 100)})
        rows["desired_position"] = [1, 1, 0]
        ledger = build_trade_ledger(rows)
        self.assertEqual(ledger.status.tolist(), ["OPEN"])
        self.assertTrue(ledger.exit_time.isna().all())
        self.assertTrue(ledger.exit_price.isna().all())

    def test_e_final_unexecuted_entry_creates_no_trade(self):
        rows = backtest(["HOLD", "LONG_ENTRY"], [0, 0])
        rows["desired_position"] = [0, 1]
        self.assertTrue(build_trade_ledger(rows).empty)

    def test_f_all_hold_has_empty_typed_six_column_schema(self):
        ledger = build_trade_ledger(backtest(["HOLD"] * 3, [0] * 3))
        self.assertTrue(ledger.empty)
        self.assertEqual(ledger.columns.tolist(), [
            "trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status",
        ])
        self.assertEqual(str(ledger.trade_id.dtype), "int64")
        self.assertEqual(str(ledger.entry_time.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(ledger.exit_time.dtype), "datetime64[ns, UTC]")
        self.assertEqual(str(ledger.entry_price.dtype), "float64")
        self.assertEqual(str(ledger.exit_price.dtype), "float64")

    def test_g_executed_exit_without_open_trade_is_rejected(self):
        rows = backtest(["LONG_EXIT", "HOLD"], [0, 0], {0: (1, 110)})
        with self.assertRaisesRegex(ValueError, "LONG_EXIT without an open trade"):
            build_trade_ledger(rows)

    def test_h_second_executed_entry_while_open_is_rejected(self):
        rows = backtest(["LONG_ENTRY", "LONG_ENTRY", "HOLD"], [0, 1, 1], {0: (1, 100), 1: (2, 110)})
        with self.assertRaisesRegex(ValueError, "LONG_ENTRY.*already open"):
            build_trade_ledger(rows)

    def test_i_partial_execution_metadata_is_rejected(self):
        for column in ("execution_time", "execution_price"):
            with self.subTest(column=column):
                rows = self.closed_example()
                rows.loc[1, column] = pd.NaT if column == "execution_time" else float("nan")
                with self.assertRaisesRegex(ValueError, "both be present or both missing"):
                    build_trade_ledger(rows)

    def test_j_non_positive_non_finite_and_non_numeric_fill_prices_rejected(self):
        for price in (0, -1, float("inf"), -float("inf"), "100", True, 1 + 2j):
            with self.subTest(price=price):
                rows = self.closed_example()
                rows["execution_price"] = rows.execution_price.astype("object")
                rows.loc[1, "execution_price"] = price
                with self.assertRaisesRegex(ValueError, "finite and positive"):
                    build_trade_ledger(rows)

    def test_k_out_of_order_and_equal_fill_times_are_rejected(self):
        for exit_hour in (1, 2):
            with self.subTest(exit_hour=exit_hour):
                rows = self.closed_example()
                rows.loc[4, "execution_time"] = pd.Timestamp("2025-01-01", tz="UTC") + pd.Timedelta(hours=exit_hour)
                with self.assertRaisesRegex(ValueError, "strictly chronological"):
                    build_trade_ledger(rows)

    def test_l_input_is_preserved_with_non_default_index(self):
        rows = self.closed_example()
        rows.index = [60, 50, 40, 30, 20, 10]
        rows["optional_context"] = "keep me"
        original = rows.copy(deep=True)
        ledger = build_trade_ledger(rows)
        pd.testing.assert_frame_equal(rows, original)
        ledger.loc[0, "entry_price"] = 999
        pd.testing.assert_frame_equal(rows, original)

    def test_m_incorrect_entry_and_exit_receiving_states_are_rejected(self):
        for receiver, incorrect_state in ((2, 0), (5, 1)):
            with self.subTest(receiver=receiver):
                rows = self.closed_example()
                rows.loc[receiver, "executed_position"] = incorrect_state
                with self.assertRaisesRegex(ValueError, "Receiving executed_position"):
                    build_trade_ledger(rows)

    def test_m_source_state_is_previous_position_not_new_intent(self):
        rows = self.closed_example()
        rows.loc[1, "executed_position"] = 1
        with self.assertRaisesRegex(ValueError, "disagrees with recorded trade state"):
            build_trade_ledger(rows)

    def test_m_hold_state_cannot_change_without_recorded_fill(self):
        rows = backtest(["HOLD", "HOLD"], [0, 1])
        with self.assertRaisesRegex(ValueError, "disagrees with recorded trade state"):
            build_trade_ledger(rows)

    def test_closed_trade_then_open_trade_preserves_both(self):
        rows = backtest(
            ["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD", "LONG_ENTRY", "HOLD"],
            [0, 1, 1, 0, 0, 1], {0: (1, 100), 2: (3, 110), 4: (5, 120)},
        )
        ledger = build_trade_ledger(rows)
        self.assertEqual(ledger.status.tolist(), ["CLOSED", "OPEN"])
        self.assertEqual(ledger.trade_id.tolist(), [1, 2])
        self.assertTrue(pd.isna(ledger.loc[1, "exit_time"]))

    def test_empty_input_returns_same_schema_as_no_trade_input(self):
        empty = build_trade_ledger(backtest([], []))
        holds = build_trade_ledger(backtest(["HOLD"], [0]))
        pd.testing.assert_frame_equal(empty, holds)

    def test_missing_columns_duplicate_columns_and_non_dataframe_rejected(self):
        rows = self.closed_example()
        with self.assertRaisesRegex(ValueError, "pandas DataFrame"):
            build_trade_ledger(None)
        for column in ("timestamp", "signal", "execution_time", "execution_price", "executed_position"):
            with self.subTest(column=column):
                with self.assertRaisesRegex(ValueError, "Missing required columns"):
                    build_trade_ledger(rows.drop(columns=column))
        with self.assertRaisesRegex(ValueError, "column names must be unique"):
            build_trade_ledger(pd.concat([rows, rows[["signal"]]], axis=1))

    def test_invalid_timestamps_and_source_order_are_rejected(self):
        rows = self.closed_example()
        with self.assertRaisesRegex(ValueError, "chronological"):
            build_trade_ledger(rows.iloc[::-1])
        with self.assertRaisesRegex(ValueError, "pandas datetime"):
            build_trade_ledger(rows.assign(timestamp=rows.timestamp.astype(str)))
        for value in (rows.timestamp.iloc[0], pd.NaT):
            with self.subTest(value=value):
                invalid = rows.copy()
                invalid.loc[1, "timestamp"] = value
                with self.assertRaisesRegex(ValueError, "non-missing and unique"):
                    build_trade_ledger(invalid)

    def test_invalid_execution_time_type_and_timezone_are_rejected(self):
        rows = self.closed_example()
        with self.assertRaisesRegex(ValueError, "pandas datetimes"):
            build_trade_ledger(rows.assign(execution_time=rows.execution_time.astype(str)))
        with self.assertRaisesRegex(ValueError, "same timezone"):
            build_trade_ledger(rows.assign(execution_time=rows.execution_time.dt.tz_localize(None)))

    def test_fill_must_follow_source_and_match_receiving_timestamp(self):
        rows = self.closed_example()
        rows.loc[1, "execution_time"] = rows.loc[1, "timestamp"]
        with self.assertRaisesRegex(ValueError, "after its signal candle"):
            build_trade_ledger(rows)
        rows.loc[1, "execution_time"] = rows.loc[3, "timestamp"]
        with self.assertRaisesRegex(ValueError, "Receiving timestamp"):
            build_trade_ledger(rows)

    def test_invalid_signals_and_hold_execution_metadata_are_rejected(self):
        rows = backtest(["HOLD", "HOLD"], [0, 0], {0: (1, 100)})
        with self.assertRaisesRegex(ValueError, "HOLD cannot have execution metadata"):
            build_trade_ledger(rows)
        for signal in ("BUY", None, pd.NA):
            with self.subTest(signal=signal):
                rows = backtest(["HOLD"], [0])
                rows.loc[0, "signal"] = signal
                with self.assertRaisesRegex(ValueError, "Signals must be"):
                    build_trade_ledger(rows)

    def test_invalid_position_values_are_rejected(self):
        for value in (-1, 2, None, "1", True):
            with self.subTest(value=value):
                rows = backtest(["HOLD"], [0])
                rows["executed_position"] = pd.Series([value])
                with self.assertRaisesRegex(ValueError, "only 0.*or 1"):
                    build_trade_ledger(rows)

    def test_naive_timestamps_and_all_missing_object_metadata_are_supported(self):
        rows = self.closed_example()
        rows["timestamp"] = rows.timestamp.dt.tz_localize(None)
        rows["execution_time"] = rows.execution_time.dt.tz_localize(None)
        ledger = build_trade_ledger(rows)
        self.assertEqual(str(ledger.entry_time.dtype), "datetime64[ns]")
        holds = backtest(["HOLD"], [0]).assign(execution_time=None, execution_price=None)
        self.assertTrue(build_trade_ledger(holds).empty)

    def test_existing_execution_helper_output_integrates_without_recalculation(self):
        rows = pd.DataFrame({
            "timestamp": pd.date_range("2025-01-01", periods=4, freq="h", tz="UTC"),
            "open": [99, 100, 105, 110],
            "signal": ["LONG_ENTRY", "HOLD", "LONG_EXIT", "HOLD"],
        })
        executions = apply_next_open_execution(rows)
        ledger = build_trade_ledger(executions)
        self.assertEqual(ledger.status.tolist(), ["CLOSED"])
        self.assertEqual(ledger.entry_price.tolist(), [100])
        self.assertEqual(ledger.exit_price.tolist(), [110])
        self.assertEqual(ledger.loc[0, "entry_time"], rows.loc[1, "timestamp"])
        self.assertEqual(ledger.loc[0, "exit_time"], rows.loc[3, "timestamp"])


if __name__ == "__main__":
    unittest.main()
