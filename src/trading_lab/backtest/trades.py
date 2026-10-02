"""Pair recorded long-only execution fills into trades, without PnL."""

from math import isfinite
from numbers import Real

import pandas as pd


def build_trade_ledger(backtest: pd.DataFrame) -> pd.DataFrame:
    """Return one row per actually executed entry, without changing input.

    Require timestamp, signal, execution_time, execution_price,
    executed_position. Input rows must be chronological with unique pandas
    datetime timestamps. Present execution times must be pandas datetimes in
    the same timezone; recorded fills must be strictly chronological.

    Execution metadata belongs to the SOURCE signal row N and describes its
    already simulated N+1 fill. Only LONG_ENTRY/LONG_EXIT with both metadata
    fields present open/close trades. Partial metadata, HOLD fills, invalid
    prices, impossible ordering, pairing, or position state raise ValueError.
    Where N+1 exists, its timestamp and executed state must match that fill.
    This checks existing output; it does not calculate executions or prices.

    Return exactly trade_id (sequential integers starting at 1), entry_time,
    entry_price, exit_time, exit_price, status. CLOSED means both fills exist;
    OPEN means only an entry exists, with NaT/NaN exit fields. Final unexecuted
    entries create no trade; unexecuted exits leave an existing trade OPEN.
    Ignore optional desired_position and market-price columns. Never force an
    exit or calculate returns, PnL, fees, quantity, or portfolio values.
    """
    if not isinstance(backtest, pd.DataFrame):
        raise ValueError("backtest must be a pandas DataFrame.")
    if not backtest.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["timestamp", "signal", "execution_time", "execution_price", "executed_position"]
    missing = [column for column in required if column not in backtest.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}.")

    timestamps = backtest["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(timestamps.dtype):
        raise ValueError("timestamp must be a pandas datetime column.")
    if timestamps.isna().any() or not timestamps.is_unique:
        raise ValueError("Timestamps must be non-missing and unique.")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("Timestamps must be chronological; input will not be sorted.")
    execution_times = backtest["execution_time"]
    if execution_times.notna().any():
        if not pd.api.types.is_datetime64_any_dtype(execution_times.dtype):
            raise ValueError("Present execution_time values must be pandas datetimes.")
        if execution_times.dt.tz != timestamps.dt.tz:
            raise ValueError("execution_time and timestamp must use the same timezone.")
    if not backtest["signal"].isin(["LONG_ENTRY", "LONG_EXIT", "HOLD"]).all():
        raise ValueError("Signals must be LONG_ENTRY, LONG_EXIT, or HOLD.")
    positions = backtest["executed_position"]
    if pd.api.types.is_bool_dtype(positions.dtype) or not positions.isin([0, 1]).all():
        raise ValueError("executed_position must contain only 0 (flat) or 1 (long).")

    trades = []
    open_trade = None
    last_fill_time = None
    for row_number, row in enumerate(backtest[required].itertuples(index=False)):
        # The preceding signal's recorded fill applies during this candle.
        # This row's own signal must not change its already-held position.
        expected_state = 1 if open_trade is not None else 0
        if row.executed_position != expected_state:
            raise ValueError(f"executed_position at row {row_number} disagrees with recorded trade state.")
        has_time = pd.notna(row.execution_time)
        has_price = pd.notna(row.execution_price)
        if has_time != has_price:
            raise ValueError(f"Execution time and price must both be present or both missing at row {row_number}.")
        if not has_time:
            continue  # A signal alone is not proof of an executed trade.
        if row.signal == "HOLD":
            raise ValueError(f"HOLD cannot have execution metadata at row {row_number}.")
        if not isinstance(row.execution_price, Real) or isinstance(row.execution_price, bool):
            raise ValueError(f"Execution price at row {row_number} must be finite and positive.")
        price = float(row.execution_price)
        if not isfinite(price) or price <= 0:
            raise ValueError(f"Execution price at row {row_number} must be finite and positive.")
        if last_fill_time is not None and row.execution_time <= last_fill_time:
            raise ValueError("Actual fills must be strictly chronological; entry must precede exit.")
        if row.execution_time <= row.timestamp:
            raise ValueError(f"Execution time must be after its signal candle timestamp at row {row_number}.")

        if row.signal == "LONG_ENTRY":
            if open_trade is not None:
                raise ValueError("Executed LONG_ENTRY while a trade is already open.")
            open_trade = {
                "trade_id": len(trades) + 1,
                "entry_time": row.execution_time,
                "entry_price": price,
                "exit_time": pd.NaT,
                "exit_price": float("nan"),
                "status": "OPEN",
            }
            trades.append(open_trade)
            receiving_state = 1
        else:
            if open_trade is None:
                raise ValueError("Executed LONG_EXIT without an open trade.")
            open_trade["exit_time"] = row.execution_time
            open_trade["exit_price"] = price
            open_trade["status"] = "CLOSED"
            open_trade = None
            receiving_state = 0

        if row_number + 1 < len(backtest):
            if timestamps.iloc[row_number + 1] != row.execution_time:
                raise ValueError(f"Receiving timestamp at row {row_number + 1} disagrees with execution_time.")
            if positions.iloc[row_number + 1] != receiving_state:
                raise ValueError(f"Receiving executed_position at row {row_number + 1} disagrees with fill.")
        last_fill_time = row.execution_time

    columns = ["trade_id", "entry_time", "entry_price", "exit_time", "exit_price", "status"]
    ledger = pd.DataFrame(trades, columns=columns)
    ledger["trade_id"] = ledger["trade_id"].astype("int64")
    for column in ("entry_time", "exit_time"):
        ledger[column] = pd.Series(ledger[column], dtype=timestamps.dtype)
    for column in ("entry_price", "exit_price"):
        ledger[column] = ledger[column].astype("float64")
    ledger["status"] = ledger["status"].astype("object")
    return ledger
