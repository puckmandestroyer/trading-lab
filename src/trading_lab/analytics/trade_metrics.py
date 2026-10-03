"""CLOSED-trade summaries for the independent Stage 4 gross and net paths."""

from math import isfinite
from numbers import Real

import pandas as pd


BREAKEVEN_TOLERANCE = 1e-12


def _finite_numbers(values: pd.Series, column: str) -> pd.Series:
    """Validate each CLOSED value before copying to float64; never parse strings."""
    numbers = []
    for value in values:
        if not isinstance(value, Real) or isinstance(value, bool):
            raise ValueError(f"CLOSED {column} values must be finite numeric values, not bool or strings.")
        try:
            number = float(value)
        except OverflowError as error:
            raise ValueError(f"CLOSED {column} values must be finite.") from error
        if not isfinite(number):
            raise ValueError(f"CLOSED {column} values must be finite and non-missing.")
        numbers.append(number)
    return pd.Series(numbers, index=values.index, dtype="float64")


def _summarize(
    results: pd.DataFrame,
    label: str,
    return_column: str,
    pnl_column: str,
    capital_after_column: str,
) -> pd.DataFrame:
    """Use explicit source columns and the decision 003 metric definitions."""
    if not isinstance(results, pd.DataFrame):
        raise ValueError("results must be a pandas DataFrame.")
    if not results.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["status", return_column, pnl_column, "capital_before", capital_after_column]
    missing = [column for column in required if column not in results.columns]
    if missing:
        raise ValueError(f"{label} summary missing required columns: {missing}.")
    if not results["status"].isin(["CLOSED", "OPEN"]).all():
        raise ValueError("status values must be CLOSED or OPEN.")

    # Capital columns guard the source schema. Accounting already validated
    # their semantics; these 16 metrics need only CLOSED returns and PnL.
    closed = results.loc[results["status"].eq("CLOSED")]
    returns = _finite_numbers(closed[return_column], return_column)
    pnl = _finite_numbers(closed[pnl_column], pnl_column)
    wins = returns > BREAKEVEN_TOLERANCE
    losses = returns < -BREAKEVEN_TOLERANCE
    breakevens = returns.abs() <= BREAKEVEN_TOLERANCE
    count = len(closed)
    win_count = int(wins.sum())
    loss_count = int(losses.sum())
    breakeven_count = int(breakevens.sum())

    # Use return masks with PnL values. Breakeven residuals remain in all-trade
    # statistics, but contribute nothing to these profit-factor aggregates.
    positive_pnl_sum = float(pnl.loc[wins].sum())
    absolute_negative_pnl_sum = abs(float(pnl.loc[losses].sum()))
    if absolute_negative_pnl_sum > 0:
        profit_factor = positive_pnl_sum / absolute_negative_pnl_sum
    elif positive_pnl_sum > 0:
        profit_factor = float("inf")
    else:
        profit_factor = float("nan")

    # Dict order defines the exact 16-column output. Separate column values
    # retain integer counts and float statistics, including empty-population NaN.
    metrics = {
        "closed_trade_count": count,
        "winning_trade_count": win_count,
        "losing_trade_count": loss_count,
        "breakeven_trade_count": breakeven_count,
        "win_rate": win_count / count if count else float("nan"),
        "loss_rate": loss_count / count if count else float("nan"),
        "breakeven_rate": breakeven_count / count if count else float("nan"),
        "average_trade_return": float(returns.mean()),
        "median_trade_return": float(returns.median()),
        "average_win_return": float(returns.loc[wins].mean()),
        "average_loss_return": float(returns.loc[losses].mean()),
        "best_trade_return": float(returns.max()),
        "worst_trade_return": float(returns.min()),
        "total_realized_pnl": float(pnl.sum()),
        "expectancy_pnl": float(pnl.mean()),
        "profit_factor": profit_factor,
    }
    return pd.DataFrame([metrics], index=[label])


def summarize_gross_trade_performance(results: pd.DataFrame) -> pd.DataFrame:
    """Summarize Stage 4.6 zero-cost accounting in one row indexed GROSS.

    Require status, trade_return, gross_pnl, capital_before, capital_after.
    Stage 4.7 gross_pnl uses cost-aware quantity and is not this source.
    Return exactly the 16 decision 003 metrics in contract order. Counts are
    integers; return/rate fields are decimals; PnL/expectancy use quote currency.
    Classification uses unrounded returns and BREAKEVEN_TOLERANCE = 1e-12.
    OPEN rows are excluded and never valued. No input is modified or repaired.
    Empty counts/total PnL are zero; undefined statistics are NaN. Profit factor
    is WIN PnL / absolute LOSS PnL, +inf for profit only, 0 for loss only, and
    NaN for no eligible PnL. No accounting or strategy logic is recalculated.
    """
    return _summarize(results, "GROSS", "trade_return", "gross_pnl", "capital_after")


def summarize_net_trade_performance(results: pd.DataFrame) -> pd.DataFrame:
    """Summarize Stage 4.7 cost-aware accounting in one row indexed NET.

    Require status, net_trade_return, net_pnl, capital_before, net_capital_after.
    Use the same 16-metric contract and edge cases as the gross summary, with
    independent net-return classification and net-PnL aggregation. OPEN entry
    fees and quantities do not enter these metrics. Preserve all input values,
    including breakeven residuals; do not recalculate fees, sizing, or valuation.
    Validation checks source schema/status and finite real CLOSED return/PnL
    values (not bool, string, or complex); full ledger validation stays upstream.
    """
    return _summarize(results, "NET", "net_trade_return", "net_pnl", "net_capital_after")
