"""First-OPEN Buy-and-Hold benchmarks using existing accounting and MTM equity.

One synthetic OPEN trade represents investing at the start of the observation
window. It bypasses strategy/execution logic and never fabricates an exit.
Sizing, costs, candle validation, and valuation remain in the existing helpers.
"""

from datetime import datetime
from math import isfinite
from numbers import Real

import numpy as np
import pandas as pd

from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.backtest.costs import calculate_trade_results_with_costs
from trading_lab.backtest.performance import calculate_trade_results


def _benchmark_trade(candles):
    """Check only what is needed to construct one canonical first-OPEN entry."""
    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not candles.columns.is_unique:
        raise ValueError("candles column names must be unique.")
    missing = [column for column in ["timestamp", "open", "close"] if column not in candles.columns]
    if missing:
        raise ValueError(f"candles missing required columns: {missing}.")
    if candles.empty:
        raise ValueError("candles must be non-empty.")

    raw_open = candles["open"].iloc[0]
    message = "First candle open must be a finite real positive entry price, not bool or string."
    if not isinstance(raw_open, Real) or isinstance(raw_open, (bool, np.bool_)):
        raise ValueError(message)
    try:
        entry_price = float(raw_open)
    except (ValueError, OverflowError) as error:
        raise ValueError(message) from error
    if not isfinite(entry_price) or entry_price <= 0:
        raise ValueError(message)

    entry_time = candles["timestamp"].iloc[0]
    # Guard inference before constructing a datetime column: never parse a
    # malformed string/numeric timestamp into an apparently canonical ledger.
    if not isinstance(entry_time, (datetime, np.datetime64)) or pd.isna(entry_time):
        raise ValueError("First candle timestamp must be an existing non-missing datetime.")
    entry_times = pd.Series([entry_time])
    return pd.DataFrame({
        "trade_id": [1],
        "entry_time": entry_times,
        "entry_price": [entry_price],
        "exit_time": pd.Series([pd.NaT], dtype=entry_times.dtype),
        "exit_price": [np.nan],
        "status": ["OPEN"],
    })


def calculate_gross_buy_and_hold_benchmark(
    candles: pd.DataFrame,
    candle_interval,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return the existing 11-column equity schema for zero-cost Buy-and-Hold.

    Buy at the first candle's raw OPEN, allocating all capital through Stage 4.6
    accounting. Stage 5.11 supplies initial observation 0 before that purchase,
    then every candle CLOSE, for N + 1 rows. Position remains long with active ID
    1; final equity is marked value, not liquidation proceeds. Preserve candles.
    """
    trade = _benchmark_trade(candles)
    results = calculate_trade_results(trade, initial_capital=initial_capital)
    return calculate_gross_mark_to_market_equity(
        candles, results, candle_interval, initial_capital=initial_capital,
    )


def calculate_net_buy_and_hold_benchmark(
    candles: pd.DataFrame,
    candle_interval,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
) -> pd.DataFrame:
    """Return independent cost-aware Buy-and-Hold using Stage 4.7 and Stage 5.11.

    The same first-OPEN purchase incurs adverse entry slippage and an entry fee
    once, with existing self-financing sizing. Hold through the final CLOSE;
    charge no hypothetical exit fee/sell slippage. Reuse all existing validation
    and the exact GROSS equity schema/timing. No source candle is changed.
    """
    trade = _benchmark_trade(candles)
    results = calculate_trade_results_with_costs(
        trade, initial_capital=initial_capital,
        fee_rate=fee_rate, slippage_rate=slippage_rate,
    )
    return calculate_net_mark_to_market_equity(
        candles, results, candle_interval, initial_capital=initial_capital,
    )
