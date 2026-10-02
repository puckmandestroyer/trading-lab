"""Sequential closed-trade accounting with full allocation and no trading costs."""

from math import isfinite
from numbers import Integral, Real

import pandas as pd


def _positive_number(value, label: str) -> float:
    """Reject strings, booleans, missing values, and non-finite numbers."""
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ValueError(f"{label} must be a finite positive number, not bool.")
    try:
        number = float(value)
    except OverflowError as error:
        raise ValueError(f"{label} must be a finite positive number.") from error
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{label} must be a finite positive number.")
    return number


def calculate_trade_results(
    trades: pd.DataFrame,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Append realized accounting to the Stage 4.5 ledger without changing it.

    Require trade_id, entry_time, entry_price, exit_time, exit_price, status.
    IDs must be consecutive integers starting at 1 in entry-time order. Times
    are pandas datetimes, entries are unique/chronological, and trades cannot
    overlap. At most one OPEN trade is permitted, and it must be final.

    Return exactly those six columns followed by capital_before, quantity,
    trade_return, gross_pnl, capital_after. Preserve input context and index;
    omit optional columns. Financial fields are float64, including empty output.

    Model: one long spot trade at a time, allocating 100% of current capital,
    with no leverage, borrowing, fees, commissions, slippage, or lot rounding.
    quantity = capital_before / entry_price. For CLOSED trades:
    trade_return = exit_price / entry_price - 1 (a decimal, not percent);
    gross_pnl = quantity * (exit_price - entry_price);
    capital_after = capital_before + gross_pnl, then compound into the next trade.

    OPEN trades receive capital_before and quantity only; the three realized
    fields stay NaN. capital_before describes funds BEFORE entering, not cash
    remaining after allocation. No open-trade valuation or equity curve exists.
    Prices/capital use quote-currency units; quantity uses base-asset units.
    No strategy, execution, pairing, files, APIs, or persistence are involved.
    """
    capital = _positive_number(initial_capital, "initial_capital")
    if not isinstance(trades, pd.DataFrame):
        raise ValueError("trades must be a pandas DataFrame.")
    if not trades.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"]
    missing = [column for column in required if column not in trades.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}.")
    ids = trades["trade_id"].tolist()
    if (
        any(not isinstance(value, Integral) or isinstance(value, bool) for value in ids)
        or ids != list(range(1, len(trades) + 1))
    ):
        raise ValueError("trade_id must be unique consecutive integers starting at 1 in row order.")
    if not trades["status"].isin(["CLOSED", "OPEN"]).all():
        raise ValueError("status must be CLOSED or OPEN.")
    open_rows = trades["status"].eq("OPEN")
    if open_rows.sum() > 1:
        raise ValueError("At most one OPEN trade is allowed.")
    if open_rows.any() and not open_rows.iloc[-1]:
        raise ValueError("An OPEN trade must be final; no trade may follow it.")

    result = trades[required].copy()
    financial_columns = ["capital_before", "quantity", "trade_return", "gross_pnl", "capital_after"]
    if trades.empty:
        # An empty ledger may have unspecified object dtypes. Return a stable
        # schema while retaining datetime/timezone dtypes when supplied.
        result["trade_id"] = result["trade_id"].astype("int64")
        for column in ("entry_time", "exit_time"):
            if not pd.api.types.is_datetime64_any_dtype(result[column].dtype):
                result[column] = pd.Series(index=result.index, dtype="datetime64[ns]")
        for column in ("entry_price", "exit_price"):
            result[column] = result[column].astype("float64")
        result["status"] = result["status"].astype("object")
        for column in financial_columns:
            result[column] = pd.Series(index=result.index, dtype="float64")
        return result

    entries = trades["entry_time"]
    if not pd.api.types.is_datetime64_any_dtype(entries.dtype) or entries.isna().any():
        raise ValueError("entry_time must contain non-missing pandas datetimes.")
    if not entries.is_unique or not entries.is_monotonic_increasing:
        raise ValueError("Entry times must be unique and chronological; input will not be sorted.")
    closed_rows = trades["status"].eq("CLOSED")
    if closed_rows.any():
        exits = trades["exit_time"]
        if not pd.api.types.is_datetime64_any_dtype(exits.dtype):
            raise ValueError("CLOSED exit_time must be a pandas datetime column.")
        if exits.dt.tz != entries.dt.tz:
            raise ValueError("Entry and exit times must use the same timezone.")

    accounting = []
    previous_exit = None
    for row in trades[required].itertuples(index=False):
        entry_price = _positive_number(row.entry_price, "entry_price")
        if previous_exit is not None and row.entry_time < previous_exit:
            raise ValueError("Trades must not overlap: entry_time precedes the previous exit_time.")
        has_exit_time = pd.notna(row.exit_time)
        has_exit_price = pd.notna(row.exit_price)
        if row.status == "OPEN" and (has_exit_time or has_exit_price):
            raise ValueError("OPEN trades must have missing exit_time and exit_price.")
        if row.status == "CLOSED" and not (has_exit_time and has_exit_price):
            raise ValueError("CLOSED trades must have both exit_time and exit_price.")

        capital_before = capital
        quantity = capital_before / entry_price
        if not isfinite(quantity) or quantity < 0 or (capital_before > 0 and quantity == 0):
            raise ValueError("Calculated quantity is non-finite, negative, or underflows to zero.")
        if row.status == "OPEN":
            accounting.append([capital_before, quantity, float("nan"), float("nan"), float("nan")])
            continue

        exit_price = _positive_number(row.exit_price, "exit_price")
        if row.exit_time <= row.entry_time:
            raise ValueError("CLOSED exit_time must be strictly after entry_time.")
        trade_return = exit_price / entry_price - 1
        gross_pnl = quantity * (exit_price - entry_price)
        capital_after = capital_before + gross_pnl
        if not all(isfinite(value) for value in (trade_return, gross_pnl, capital_after)) or capital_after < 0:
            raise ValueError("Calculated results must be finite and capital_after non-negative.")
        accounting.append([capital_before, quantity, trade_return, gross_pnl, capital_after])
        capital = capital_after
        previous_exit = row.exit_time

    for column_number, column in enumerate(financial_columns):
        result[column] = pd.Series(
            [row[column_number] for row in accounting], index=result.index, dtype="float64"
        )
    return result
