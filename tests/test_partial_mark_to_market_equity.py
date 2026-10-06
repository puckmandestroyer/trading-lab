"""Synthetic reserve-aware MTM checks using canonical partial accounting."""

import unittest

import numpy as np
import pandas as pd

from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results


START = pd.Timestamp("2025-01-01", tz="UTC")
HOUR = pd.Timedelta(hours=1)
PATH_COLUMNS = [
    "observation", "candle_timestamp", "valuation_time", "mark_price", "position",
    "active_trade_id", "cash", "quantity", "position_value", "unrealized_pnl", "equity",
]
FINANCIAL_COLUMNS = ["mark_price", "cash", "quantity", "position_value", "unrealized_pnl", "equity"]


def candles(closes):
    return pd.DataFrame({
        "timestamp": pd.date_range(START, periods=len(closes), freq="h"),
        "close": closes,
    })


def ledger(specifications):
    """Each specification is (entry hour, exit hour or None, entry, exit)."""
    rows = [(
        number, START + entry_hour * HOUR, entry_price,
        pd.NaT if exit_hour is None else START + exit_hour * HOUR,
        np.nan if exit_hour is None else exit_price,
        "OPEN" if exit_hour is None else "CLOSED",
    ) for number, (entry_hour, exit_hour, entry_price, exit_price)
        in enumerate(specifications, start=1)]
    trades = pd.DataFrame(rows, columns=[
        "trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status",
    ])
    for column in ("entry_time", "exit_time"):
        trades[column] = pd.Series(trades[column].tolist(), dtype="datetime64[ns, UTC]")
    trades["trade_id"] = trades.trade_id.astype("int64")
    for column in ("entry_price", "exit_price"):
        trades[column] = trades[column].astype("float64")
    return trades


def sources(specifications, fraction=0.5, fee=0.01, slippage=0.02, capital=1_000.0):
    """Produce independent GROSS/NET results through production accounting."""
    trades = ledger(specifications)
    return (
        (calculate_gross_mark_to_market_equity,
         calculate_trade_results(trades, capital, fraction), "capital_after", "entry_price"),
        (calculate_net_mark_to_market_equity,
         calculate_trade_results_with_costs(trades, capital, fee, slippage, fraction),
         "net_capital_after", "effective_entry_price"),
    )


def reserve_cash(trade, basis):
    """Expected cash after the full canonical entry spend, including NET fee."""
    return trade.capital_before - (trade.quantity * getattr(trade, basis) + getattr(trade, "entry_fee", 0.0))


class PartialMarkToMarketEquityTests(unittest.TestCase):
    def test_half_gross_open_gain_and_loss_include_reserve(self):
        function, results, _, _ = sources([(0, None, 100, None)])[0]
        path = function(candles([110, 90]), results, HOUR, 1_000)
        self.assertEqual(path.cash.tolist(), [1_000, 500, 500])
        self.assertEqual(path.quantity.tolist(), [0, 5, 5])
        self.assertEqual(path.position_value.tolist(), [0, 550, 450])
        self.assertEqual(path.unrealized_pnl.tolist(), [0, 50, -50])
        self.assertEqual(path.equity.tolist(), [1_000, 1_050, 950])

    def test_quarter_gross_allocation_retains_three_quarters_in_cash(self):
        function, results, _, _ = sources([(0, None, 100, None)], fraction=0.25)[0]
        path = function(candles([120, 80]), results, HOUR, 1_000)
        self.assertEqual(path.cash.iloc[1:].tolist(), [750, 750])
        self.assertEqual(path.quantity.iloc[1:].tolist(), [2.5, 2.5])
        self.assertEqual(path.equity.tolist(), [1_000, 1_050, 950])

    def test_half_zero_cost_net_open_gain_and_loss_include_reserve(self):
        function, results, _, _ = sources([(0, None, 100, None)], fee=0, slippage=0)[1]
        path = function(candles([110, 90]), results, HOUR, 1_000)
        self.assertEqual(path.cash.tolist(), [1_000, 500, 500])
        self.assertEqual(path.position_value.tolist(), [0, 550, 450])
        self.assertEqual(path.unrealized_pnl.tolist(), [0, 50, -50])
        self.assertEqual(path.equity.tolist(), [1_000, 1_050, 950])

    def test_zero_cost_partial_gross_and_net_paths_match(self):
        specs = [(0, 1, 100, 110), (2, 3, 200, 180), (4, None, 50, None)]
        market = candles([105, 999, 190, 999, 55, 45])
        for fraction in (0.5, 0.25, 0.37):
            with self.subTest(fraction=fraction):
                gross, net = sources(specs, fraction, fee=0, slippage=0)
                gross_path = gross[0](market, gross[1], HOUR, 1_000)
                net_path = net[0](market, net[1], HOUR, 1_000)
                pd.testing.assert_frame_equal(gross_path, net_path, check_exact=True)

    def test_net_partial_entry_fee_is_paid_once_at_raw_entry_mark(self):
        function, results, _, _ = sources([(0, None, 100, None)], slippage=0)[1]
        trade = results.iloc[0]
        path = function(candles([100]), results, HOUR, 1_000)
        mark = path.iloc[-1]
        self.assertAlmostEqual(trade.quantity, 500 / 101)
        self.assertAlmostEqual(mark.cash, 500)
        self.assertEqual(mark.unrealized_pnl, 0)
        self.assertAlmostEqual(mark.equity, 1_000 - trade.entry_fee)
        self.assertEqual(mark.equity, mark.cash + mark.position_value)
        self.assertNotAlmostEqual(mark.equity, 1_000 - 2 * trade.entry_fee)

    def test_net_slippage_only_uses_effective_basis_and_raw_close(self):
        function, results, _, _ = sources([(0, None, 100, None)], fee=0)[1]
        trade = results.iloc[0]
        path = function(candles([100, 110]), results, HOUR, 1_000)
        self.assertAlmostEqual(trade.effective_entry_price, 102)
        self.assertEqual(path.cash.iloc[1:].tolist(), [reserve_cash(trade, "effective_entry_price")] * 2)
        np.testing.assert_allclose(path.cash.iloc[1:], [500, 500], rtol=1e-12, atol=0)
        np.testing.assert_allclose(path.position_value.iloc[1:], trade.quantity * np.array([100, 110]), rtol=1e-12)
        np.testing.assert_allclose(path.unrealized_pnl.iloc[1:], trade.quantity * np.array([-2, 8]), rtol=1e-12)

    def test_net_fee_and_slippage_include_full_entry_spend_in_reserve(self):
        function, results, _, basis = sources([(0, None, 100, None)])[1]
        trade = results.iloc[0]
        mark = function(candles([100]), results, HOUR, 1_000).iloc[-1]
        self.assertEqual(mark.cash, reserve_cash(trade, basis))
        self.assertAlmostEqual(mark.cash, 500)
        self.assertLess(mark.cash, trade.capital_before - trade.quantity * trade.effective_entry_price)
        self.assertEqual(mark.position_value, trade.quantity * 100)
        self.assertAlmostEqual(mark.unrealized_pnl, trade.quantity * (100 - trade.effective_entry_price))
        self.assertAlmostEqual(mark.equity, trade.capital_before - trade.entry_fee + mark.unrealized_pnl)
        self.assertEqual(mark.equity, mark.cash + mark.position_value)

    def test_partial_net_open_charges_no_hypothetical_exit_costs(self):
        function, results, _, basis = sources([(0, None, 100, None)], fee=0.2, slippage=0.1)[1]
        original = results.copy(deep=True)
        market = candles([100, 120])
        path = function(market, results, HOUR, 1_000)
        trade = results.iloc[0]
        self.assertEqual(path.equity.iloc[-1], reserve_cash(trade, basis) + trade.quantity * 120)
        self.assertTrue(results[["exit_time", "exit_fee", "net_pnl", "net_capital_after"]].isna().all().all())
        pd.testing.assert_frame_equal(results, original, check_exact=True)
        irrelevant = results.assign(exit_fee=999_999, effective_exit_price=1)
        pd.testing.assert_frame_equal(path, function(market, irrelevant, HOUR, 1_000), check_exact=True)

    def test_reserve_and_canonical_quantity_stay_constant_while_open(self):
        for function, results, _, basis in sources([(0, None, 100, None)], fraction=0.37):
            with self.subTest(function=function.__name__):
                trade = results.iloc[0]
                path = function(candles([100, 200, 50, 125]), results, HOUR, 1_000)
                self.assertEqual(path.cash.iloc[1:].tolist(), [reserve_cash(trade, basis)] * 4)
                self.assertEqual(path.quantity.iloc[1:].tolist(), [trade.quantity] * 4)
                self.assertGreater(path.position_value.iloc[2], path.position_value.iloc[1])
                self.assertLess(path.position_value.iloc[3], path.position_value.iloc[1])
                self.assertTrue(path.position.iloc[1:].eq(1).all())

    def test_gross_active_equity_equals_total_entry_capital_plus_unrealized(self):
        specs = [(0, 1, 100, 110), (2, None, 200, None)]
        function, results, _, _ = sources(specs, fraction=0.37)[0]
        path = function(candles([105, 999, 190, 210]), results, HOUR, 1_000)
        for trade in results.itertuples():
            active = path[path.active_trade_id.eq(trade.trade_id).fillna(False)]
            np.testing.assert_allclose(active.equity, trade.capital_before + active.unrealized_pnl, rtol=1e-12)

    def test_net_active_equity_equals_capital_minus_paid_fee_plus_unrealized(self):
        specs = [(0, 1, 100, 110), (2, None, 200, None)]
        function, results, _, _ = sources(specs, fraction=0.37)[1]
        path = function(candles([105, 999, 190, 210]), results, HOUR, 1_000)
        for trade in results.itertuples():
            active = path[path.active_trade_id.eq(trade.trade_id).fillna(False)]
            np.testing.assert_allclose(
                active.equity, trade.capital_before - trade.entry_fee + active.unrealized_pnl,
                rtol=1e-12, atol=1e-12,
            )

    def test_partial_gross_exit_returns_total_canonical_cash(self):
        function, results, _, _ = sources([(0, 2, 100, 120)])[0]
        path = function(candles([110, 90, 999, 1]), results, HOUR, 1_000)
        self.assertEqual(path.equity.tolist(), [1_000, 1_050, 950, 1_100, 1_100])
        self.assertEqual(path.cash.tolist(), [1_000, 500, 500, 1_100, 1_100])
        self.assertEqual(path.position.tolist(), [0, 1, 1, 0, 0])
        self.assertTrue(path.active_trade_id.iloc[3:].isna().all())
        self.assertTrue(path[["quantity", "position_value", "unrealized_pnl"]].iloc[3:].eq(0).all().all())
        self.assertEqual(path.cash.iloc[-1], results.capital_after.iloc[0])

    def test_partial_net_exit_uses_canonical_total_without_charging_costs_again(self):
        function, results, after, _ = sources([(0, 2, 100, 120)])[1]
        market = candles([110, 90, 999, 1])
        path = function(market, results, HOUR, 1_000)
        self.assertEqual(path.cash.iloc[3:].tolist(), [results[after].iloc[0]] * 2)
        self.assertEqual(path.equity.iloc[3:].tolist(), [results[after].iloc[0]] * 2)
        self.assertTrue(path[["position", "quantity", "position_value", "unrealized_pnl"]].iloc[3:].eq(0).all().all())
        irrelevant = results.assign(exit_price=-1, exit_fee=999_999, effective_exit_price=1, net_pnl=-999_999)
        pd.testing.assert_frame_equal(path, function(market, irrelevant, HOUR, 1_000), check_exact=True)

    def test_initial_and_flat_states_retain_total_cash(self):
        for function, results, after, _ in sources([(1, 3, 100, 110)]):
            path = function(candles([999, 110, 90, 123]), results, HOUR, 1_000)
            self.assertEqual(path.cash.iloc[:2].tolist(), [1_000, 1_000])
            self.assertEqual(path.equity.iloc[:2].tolist(), [1_000, 1_000])
            self.assertTrue(path[["position", "quantity", "position_value", "unrealized_pnl"]].iloc[:2].eq(0).all().all())
            self.assertEqual(path.equity.iloc[-1], results[after].iloc[0])
            self.assertEqual(path.position.iloc[-1], 0)

    def test_empty_partial_accounting_retains_constant_flat_equity(self):
        for function, results, _, _ in sources([]):
            path = function(candles([90, 110, 80]), results, HOUR, 1_000)
            self.assertEqual(path.cash.tolist(), [1_000] * 4)
            self.assertEqual(path.equity.tolist(), [1_000] * 4)
            self.assertEqual(path.observation.tolist(), [0, 1, 2, 3])
            self.assertTrue(path.active_trade_id.isna().all())
            self.assertTrue(path[["position", "quantity", "position_value", "unrealized_pnl"]].eq(0).all().all())

    def test_multiple_trades_replace_reserve_using_independently_compounded_capital(self):
        specs = [(0, 1, 100, 110), (2, 3, 200, 180), (4, None, 50, None)]
        market = candles([105, 999, 190, 999, 55, 45])
        for function, results, after, basis in sources(specs):
            reserves = []
            path = function(market, results, HOUR, 1_000)
            for trade in results.itertuples():
                entry_row = path[path.candle_timestamp.eq(trade.entry_time)].iloc[0]
                expected_reserve = reserve_cash(trade, basis)
                reserves.append(expected_reserve)
                self.assertEqual(entry_row.cash, expected_reserve)
                self.assertEqual(entry_row.quantity, trade.quantity)
                self.assertEqual(entry_row.equity, expected_reserve + trade.quantity * entry_row.mark_price)
                if trade.status == "CLOSED":
                    exit_row = path[path.candle_timestamp.eq(trade.exit_time)].iloc[0]
                    self.assertEqual(exit_row.cash, getattr(trade, after))
                    self.assertEqual(exit_row.equity, exit_row.cash)
                    self.assertEqual(exit_row.position, 0)
            self.assertNotEqual(reserves[0], reserves[1])
            self.assertNotEqual(reserves[1], reserves[2])
            self.assertEqual(path.cash.iloc[-1], reserves[-1])

    def test_shared_exit_open_precedes_new_partial_entry_and_reserve(self):
        for function, results, after, basis in sources([(0, 1, 100, 110), (1, None, 200, None)]):
            path = function(candles([90, 210, 190]), results, HOUR, 1_000)
            previous, new = results.iloc[0], results.iloc[1]
            self.assertEqual(path.active_trade_id.iloc[1:].tolist(), [1, 2, 2])
            # The CLOSE at the shared boundary still belongs to the old position.
            self.assertEqual(path.valuation_time.iloc[1], previous.exit_time)
            self.assertEqual(path.cash.iloc[1], reserve_cash(previous, basis))
            self.assertEqual(new.capital_before, previous[after])
            self.assertEqual(path.cash.iloc[2:].tolist(), [reserve_cash(new, basis)] * 2)
            self.assertEqual(path.quantity.iloc[2:].tolist(), [new.quantity] * 2)
            self.assertAlmostEqual(path.unrealized_pnl.iloc[2], new.quantity * (210 - new[basis]))
            self.assertEqual(path.equity.iloc[2], reserve_cash(new, basis) + new.quantity * 210)

    def test_final_partial_open_is_marked_without_liquidation_or_realized_results(self):
        for function, results, after, basis in sources([(0, 1, 100, 110), (2, None, 200, None)]):
            original = results.copy(deep=True)
            path = function(candles([105, 999, 210, 220]), results, HOUR, 1_000)
            trade = results.iloc[-1]
            self.assertEqual(path.position.iloc[-1], 1)
            self.assertEqual(path.active_trade_id.iloc[-1], 2)
            self.assertEqual(path.equity.iloc[-1], reserve_cash(trade, basis) + trade.quantity * 220)
            self.assertTrue(pd.isna(trade.exit_time))
            self.assertTrue(pd.isna(trade[after]))
            pd.testing.assert_frame_equal(results, original, check_exact=True)

    def test_future_canonical_exit_does_not_affect_prior_partial_marks(self):
        market = candles([110, 90, 105, 999])
        closed_sources = sources([(0, 3, 100, 120)])
        open_sources = sources([(0, None, 100, None)])
        for closed, opened in zip(closed_sources, open_sources):
            function, results, after, _ = closed
            path = function(market, results, HOUR, 1_000)
            open_path = function(market, opened[1], HOUR, 1_000)
            pd.testing.assert_frame_equal(path.iloc[:4], open_path.iloc[:4], check_exact=True)
            changed = results.copy(deep=True)
            changed[after] += 500
            other = function(market, changed, HOUR, 1_000)
            pd.testing.assert_frame_equal(path.iloc[:4], other.iloc[:4], check_exact=True)
            self.assertEqual(other.equity.iloc[-1], changed[after].iloc[0])

    def test_appending_candles_preserves_partial_equity_prefix(self):
        for function, results, _, _ in sources([(0, None, 100, None)]):
            short = function(candles([110, 90]), results, HOUR, 1_000)
            long = function(candles([110, 90, 120]), results, HOUR, 1_000)
            pd.testing.assert_frame_equal(short, long.iloc[:3], check_exact=True)

    def test_exact_output_schema_dtypes_range_index_and_timezone(self):
        for specs in ([], [(0, None, 100, None)], [(0, 1, 100, 110), (2, None, 50, None)]):
            for function, results, _, _ in sources(specs):
                path = function(candles([100, 110, 90]), results, HOUR, 1_000)
                self.assertEqual(path.columns.tolist(), PATH_COLUMNS)
                pd.testing.assert_index_equal(path.index, pd.RangeIndex(4), exact=True)
                for column in ("observation", "position"):
                    self.assertEqual(str(path[column].dtype), "int64")
                self.assertEqual(str(path.active_trade_id.dtype), "Int64")
                for column in FINANCIAL_COLUMNS:
                    self.assertEqual(str(path[column].dtype), "float64")
                for column in ("candle_timestamp", "valuation_time"):
                    self.assertEqual(str(path[column].dtype), "datetime64[ns, UTC]")

    def test_partial_inputs_preserved_with_custom_indexes_timezone_and_column_order(self):
        for function, results, _, _ in sources([(0, 1, 100, 110), (2, None, 50, None)]):
            market = candles([105, 999, 55])
            market["timestamp"] = market.timestamp.dt.tz_convert("America/New_York")
            for column in ("entry_time", "exit_time"):
                results[column] = results[column].dt.tz_convert("America/New_York")
            market.index = pd.Index([30, 10, 30], name="market_row")
            results.index = pd.Index([8, 8], name="accounting_row")
            market = market.assign(note="keep")[['note', 'close', 'timestamp']]
            results = results.assign(note="keep")[list(results.columns[::-1]) + ["note"]]
            original_market, original_results = market.copy(deep=True), results.copy(deep=True)
            path = function(market, results, HOUR, 1_000)
            self.assertEqual(str(path.valuation_time.dtype), "datetime64[ns, America/New_York]")
            path.loc[1, "quantity"] = 999
            pd.testing.assert_frame_equal(market, original_market, check_exact=True)
            pd.testing.assert_frame_equal(results, original_results, check_exact=True)

    def test_inputs_preserved_on_material_overspend_failure(self):
        for function, results, _, _ in sources([(0, None, 100, None)]):
            market = candles([100, 110]).assign(note="keep")
            market.index = pd.Index([20, 10], name="market_row")
            results["quantity"] *= 3
            results.index = pd.Index([8], name="accounting_row")
            results = results.assign(note="keep")[list(results.columns[::-1]) + ["note"]]
            original_market, original_results = market.copy(deep=True), results.copy(deep=True)
            with self.assertRaisesRegex(ValueError, "exceeding"):
                function(market, results, HOUR, 1_000)
            pd.testing.assert_frame_equal(market, original_market, check_exact=True)
            pd.testing.assert_frame_equal(results, original_results, check_exact=True)

    def test_partial_canonical_required_fields_work_without_sizing_metadata(self):
        for function, results, after, basis in sources([(0, None, 100, None)]):
            required = ["trade_id", "status", "entry_time", "exit_time", "capital_before", "quantity", basis, after]
            if "entry_fee" in results:
                required.append("entry_fee")
            market = candles([110])
            path = function(market, results[required], HOUR, 1_000)
            self.assertGreater(path.cash.iloc[-1], 0)
            pd.testing.assert_frame_equal(path, function(market, results, HOUR, 1_000), check_exact=True)

    def test_net_entry_fee_that_pushes_spend_over_capital_is_rejected(self):
        function, results, _, _ = sources([(0, None, 100, None)])[1]
        self.assertLess(results.quantity.iloc[0] * results.effective_entry_price.iloc[0], 1_000)
        invalid = results.assign(entry_fee=600.0)
        with self.assertRaisesRegex(ValueError, "exceeding"):
            function(candles([100]), invalid, HOUR, 1_000)

    def test_all_in_reconciliation_dust_normalizes_cash_to_exact_zero(self):
        for function, results, _, basis in sources([(0, None, 100, None)], fraction=1.0):
            for adjustment in (-5e-13, 0.0, 5e-13):
                with self.subTest(function=function.__name__, adjustment=adjustment):
                    near_full = results.copy(deep=True)
                    near_full["quantity"] *= 1 + adjustment
                    trade = near_full.iloc[0]
                    self.assertAlmostEqual(reserve_cash(trade, basis), 0, places=8)
                    path = function(candles([100, 110]), near_full, HOUR, 1_000)
                    self.assertEqual(path.cash.iloc[1:].tolist(), [0.0, 0.0])
                    self.assertEqual(path.quantity.iloc[-1], trade.quantity)
                    self.assertEqual(path.equity.iloc[-1], trade.quantity * 110)

    def test_reconciliation_tolerance_is_not_widened_for_near_full_spend(self):
        for function, results, _, basis in sources([(0, None, 100, None)], fraction=1.0):
            below = results.copy(deep=True)
            below["quantity"] *= 1 - 2e-12
            trade = below.iloc[0]
            path = function(candles([100]), below, HOUR, 1_000)
            self.assertGreater(path.cash.iloc[-1], 0)
            self.assertEqual(path.cash.iloc[-1], reserve_cash(trade, basis))
            above = results.copy(deep=True)
            above["quantity"] *= 1 + 2e-12
            with self.assertRaisesRegex(ValueError, "exceeding"):
                function(candles([100]), above, HOUR, 1_000)

    def test_explicit_full_allocation_preserves_exact_default_equity_paths(self):
        trades = ledger([(0, 1, 100, 110), (2, None, 200, None)])
        market = candles([105, 999, 210, 220])
        for equity_function, accounting_function, kwargs in (
            (calculate_gross_mark_to_market_equity, calculate_trade_results, {}),
            (calculate_net_mark_to_market_equity, calculate_trade_results_with_costs,
             {"fee_rate": 0.01, "slippage_rate": 0.02}),
        ):
            default = accounting_function(trades, 1_000, **kwargs)
            full = accounting_function(trades, 1_000, position_fraction=1.0, **kwargs)
            default_path = equity_function(market, default, HOUR, 1_000)
            full_path = equity_function(market, full, HOUR, 1_000)
            pd.testing.assert_frame_equal(default_path, full_path, check_exact=True)
            self.assertEqual(full_path.cash[full_path.position.eq(1)].tolist(), [0.0] * 3)

    def test_partial_capital_before_still_reconciles_with_available_total_capital(self):
        for function, results, _, _ in sources([(0, 1, 100, 110), (2, None, 200, None)]):
            market = candles([100, 110, 210])
            with self.assertRaisesRegex(ValueError, "capital_before"):
                function(market, results, HOUR, 2_000)
            invalid = results.copy(deep=True)
            invalid.loc[1, "capital_before"] += 10
            with self.assertRaisesRegex(ValueError, "capital_before"):
                function(market, invalid, HOUR, 1_000)

    def test_nonfinite_net_full_entry_spend_is_rejected(self):
        function, results, _, _ = sources([(0, None, 1, None)], fee=0, slippage=0, capital=1e308)[1]
        invalid = results.assign(entry_fee=1.5e308)
        with self.assertRaisesRegex(ValueError, "entry spend must be finite"):
            function(candles([1]), invalid, HOUR, 1e308)

    def test_partial_reserve_plus_finite_marked_value_cannot_overflow_equity(self):
        for function, results, _, _ in sources([(0, None, 1, None)], fee=0, slippage=0, capital=1e308):
            self.assertTrue(np.isfinite(results.quantity.iloc[0] * 3))
            with self.assertRaisesRegex(ValueError, "Calculated"):
                function(candles([3]), results, HOUR, 1e308)
