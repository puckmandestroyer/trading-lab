"""Candle-CLOSE portfolio equity from canonical long spot accounting.

Accounting supplies quantities and total capital. Unallocated capital stays cash:
GROSS spend is quantity * entry_price; NET spend is quantity * effective entry
price + entry_fee. Reserve is total entry capital minus that canonical spend and
stays cash while LONG. Equity is cash plus the raw-CLOSE marked position; actual
exit capital remains authoritative. NET never charges entry fees again or adds
hypothetical liquidation costs. Full allocation stays exactly compatible. A CLOSE
observation precedes next-OPEN fills even when the phases share a timestamp.
No input is modified, quantity resized, or risk/accounting policy rerun.
"""

from datetime import datetime, timedelta
from math import isclose, isfinite
from numbers import Integral, Real

import numpy as np
import pandas as pd


_PATH_COLUMNS = [
    "observation", "candle_timestamp", "valuation_time", "mark_price",
    "position", "active_trade_id", "cash", "quantity", "position_value",
    "unrealized_pnl", "equity",
]
_FINANCIAL_COLUMNS = [
    "mark_price", "cash", "quantity", "position_value", "unrealized_pnl", "equity",
]


def _number(value, label, positive=False):
    """Accept finite real amounts, without parsing strings or accepting bools."""
    condition = "positive" if positive else "non-negative"
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise ValueError(f"{label} must be a finite real {condition} number.")
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(f"{label} must be a finite real {condition} number.") from error
    if not isfinite(number) or number < 0 or (positive and number == 0):
        raise ValueError(f"{label} must be a finite real {condition} number.")
    return number


def _interval(value):
    """Require a duration with explicit units, not a number or calendar offset."""
    if not isinstance(value, (timedelta, np.timedelta64)):
        raise ValueError("candle_interval must be a positive fixed duration.")
    if isinstance(value, np.timedelta64) and np.datetime_data(value.dtype)[0] in ("Y", "M"):
        raise ValueError("candle_interval must be fixed, not calendar-dependent.")
    try:
        interval = pd.Timedelta(value)
        if pd.isna(interval) or interval.value <= 0:
            raise ValueError("Non-positive or missing interval.")
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("candle_interval must be a safely representable positive fixed duration.") from error
    return interval


def _timestamp(value, label):
    """Validate existing datetime scalars; never parse strings/numeric epochs."""
    if not isinstance(value, (datetime, np.datetime64)):
        raise ValueError(f"{label} must be a valid non-missing datetime.")
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError("Missing timestamp.")
        # The output uses nanosecond datetime columns; reject unsafe dates early.
        stamp.value
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(f"{label} must be a safely representable non-missing datetime.") from error
    return stamp


def _timezone_key(stamp):
    """Allow DST offsets within one zone, but reject different implementations."""
    zone = stamp.tz
    if zone is None:
        return None
    name = getattr(zone, "zone", getattr(zone, "key", str(zone)))
    return type(zone), name


def _same_timezone(stamp, expected):
    if _timezone_key(stamp) != expected:
        raise ValueError("All timestamps must be naive or use the same timezone implementation/zone.")


def _frame(frame, required, label):
    if not isinstance(frame, pd.DataFrame):
        raise ValueError(f"{label} must be a pandas DataFrame.")
    if not frame.columns.is_unique:
        raise ValueError(f"{label} column names must be unique.")
    missing = [column for column in required if column not in frame.columns]
    if missing:
        raise ValueError(f"{label} missing required columns: {missing}.")


def _candles(candles, interval):
    """Validate in supplied order and retain each OPEN, CLOSE, and valuation time."""
    _frame(candles, ["timestamp", "close"], "candles")
    if candles.empty:
        raise ValueError("candles must be non-empty.")
    observations = []
    previous = None
    clock = None
    for raw_time, raw_close in candles[["timestamp", "close"]].itertuples(index=False, name=None):
        stamp = _timestamp(raw_time, "timestamp")
        if previous is None:
            clock = _timezone_key(stamp)
        _same_timezone(stamp, clock)
        if previous is not None and stamp.value - previous.value != interval.value:
            raise ValueError("Candle timestamps must be strictly increasing, unique, and exactly spaced by candle_interval.")
        close = _number(raw_close, "close", positive=True)
        try:
            valuation = stamp + interval
            valuation.value
        except (ValueError, OverflowError) as error:
            raise ValueError("Candle valuation time must be safely representable.") from error
        observations.append((stamp, close, valuation))
        previous = stamp
    return observations, clock


def _events(results, label, basis_column, capital_column, candles, clock, initial_capital):
    """Check only the accounting/event context needed to carry portfolio state.

    Entry allocation and available capital are checked, not recomputed. Future
    exit values may be validated here, but only applied at their actual OPEN.
    """
    required = [
        "trade_id", "status", "entry_time", "exit_time", "capital_before",
        "quantity", basis_column, capital_column,
    ]
    if label == "NET":
        required.append("entry_fee")
    _frame(results, required, label)
    if not results["status"].isin(["CLOSED", "OPEN"]).all():
        raise ValueError("status must be CLOSED or OPEN.")
    open_rows = results["status"].eq("OPEN")
    if open_rows.sum() > 1:
        raise ValueError("At most one OPEN trade is allowed.")
    if open_rows.any() and not open_rows.iloc[-1]:
        raise ValueError("An OPEN trade must be final.")

    candle_opens = {stamp.value for stamp, _, _ in candles}
    entries, exits = {}, {}
    previous_entry = previous_exit = None
    available = initial_capital
    for expected_id, row in enumerate(results[required].itertuples(index=False, name=None), start=1):
        trade_id, status, raw_entry, raw_exit, raw_capital, raw_quantity, raw_basis, raw_after = row[:8]
        if not isinstance(trade_id, Integral) or isinstance(trade_id, (bool, np.bool_)) or trade_id != expected_id:
            raise ValueError("trade_id must be canonical consecutive integers starting at 1.")
        entry = _timestamp(raw_entry, "entry_time")
        _same_timezone(entry, clock)
        if entry.value not in candle_opens:
            raise ValueError("entry_time must match a supplied candle OPEN inside the observation window.")
        if previous_entry is not None and entry <= previous_entry:
            raise ValueError("Entries must be strictly chronological; input will not be sorted.")
        if previous_exit is not None and entry < previous_exit:
            raise ValueError("Trades must not overlap.")

        capital = _number(raw_capital, "capital_before", positive=True)
        quantity = _number(raw_quantity, "quantity", positive=True)
        basis = _number(raw_basis, basis_column, positive=True)
        entry_fee = _number(row[8], "entry_fee") if label == "NET" else 0.0
        if not isclose(capital, available, rel_tol=1e-12, abs_tol=0.0):
            raise ValueError("capital_before must reconcile with available canonical cash / initial_capital.")
        entry_value = quantity * basis
        if not isfinite(entry_value) or entry_value <= 0:
            raise ValueError("Canonical entry allocation must be finite and positive.")
        entry_spend = entry_value + entry_fee
        if not isfinite(entry_spend):
            raise ValueError("Canonical entry spend must be finite and positive.")
        if isclose(entry_spend, capital, rel_tol=1e-12, abs_tol=0.0):
            # Preserve exact all-in paths despite self-financing arithmetic dust.
            reserve = 0.0
        elif entry_spend > capital:
            raise ValueError("Canonical entry spend must reconcile without exceeding capital_before.")
        else:
            reserve = capital - entry_spend

        entries[entry.value] = (int(trade_id), quantity, basis, reserve)
        if status == "OPEN":
            if not pd.isna(raw_exit) or not pd.isna(raw_after):
                raise ValueError(f"OPEN exit_time and {capital_column} must remain missing.")
        else:
            exit_time = _timestamp(raw_exit, "exit_time")
            _same_timezone(exit_time, clock)
            if exit_time.value not in candle_opens:
                raise ValueError("exit_time must match a supplied candle OPEN inside the observation window.")
            if exit_time <= entry:
                raise ValueError("CLOSED exit_time must be strictly after entry_time.")
            after = _number(raw_after, capital_column)
            exits[exit_time.value] = after
            available = after
            previous_exit = exit_time
        previous_entry = entry
    return entries, exits


def _calculate_equity(candles, results, candle_interval, initial_capital, label):
    capital = _number(initial_capital, "initial_capital", positive=True)
    interval = _interval(candle_interval)
    observed, clock = _candles(candles, interval)
    basis_column = "entry_price" if label == "GROSS" else "effective_entry_price"
    capital_column = "capital_after" if label == "GROSS" else "net_capital_after"
    entries, exits = _events(results, label, basis_column, capital_column, observed, clock, capital)

    cash, quantity, basis, active_id = capital, 0.0, 0.0, None
    rows = [(0, pd.NaT, observed[0][0], float("nan"), 0, None, cash, 0.0, 0.0, 0.0, cash)]
    for observation, (stamp, mark, valuation) in enumerate(observed, start=1):
        # These events belong to this OPEN, never to the preceding CLOSE row.
        if stamp.value in exits:
            cash = exits[stamp.value]
            quantity, basis, active_id = 0.0, 0.0, None
        if stamp.value in entries:
            active_id, quantity, basis, cash = entries[stamp.value]
        position = int(active_id is not None)
        value = quantity * mark if position else 0.0
        unrealized = quantity * (mark - basis) if position else 0.0
        equity = cash + value
        if not all(isfinite(amount) for amount in (value, unrealized, equity)) or (position and value <= 0):
            raise ValueError("Calculated position value, unrealized PnL, and equity must be finite without value underflow.")
        rows.append((observation, stamp, valuation, mark, position, active_id, cash, quantity, value, unrealized, equity))

    path = pd.DataFrame(rows, columns=_PATH_COLUMNS)
    path[["observation", "position"]] = path[["observation", "position"]].astype("int64")
    path["active_trade_id"] = pd.array([row[5] for row in rows], dtype="Int64")
    path[_FINANCIAL_COLUMNS] = path[_FINANCIAL_COLUMNS].astype("float64")
    first = observed[0][0]
    time_dtype = pd.DatetimeTZDtype(tz=first.tz, unit="ns") if first.tz is not None else "datetime64[ns]"
    for column, offset in (("candle_timestamp", 1), ("valuation_time", 2)):
        path[column] = pd.Series([row[offset] for row in rows], dtype=time_dtype)
    return path


def calculate_gross_mark_to_market_equity(
    candles: pd.DataFrame,
    gross_results: pd.DataFrame,
    candle_interval,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return initial equity plus every candle CLOSE using Stage 4.6 accounting.

    Require timestamp/close candles and canonical trade_id, status, entry_time,
    entry_price, exit_time, capital_before, quantity, capital_after. Reuse entry
    quantity and actual exit cash; derive reserve from capital_before minus
    quantity * entry_price. Retain that cash and mark OPEN holdings at raw CLOSE
    with no sale. Full allocation preserves exact zero reserve.
    Fills must match supplied OPENs. Return decision 006's exact 11 columns on a
    RangeIndex, preserving inputs and a coherent naive or same-zone-aware clock.
    """
    return _calculate_equity(candles, gross_results, candle_interval, initial_capital, "GROSS")


def calculate_net_mark_to_market_equity(
    candles: pd.DataFrame,
    net_results: pd.DataFrame,
    candle_interval,
    initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return candle-CLOSE equity using independent Stage 4.7 cost-aware results.

    Require trade_id, status, entry_time, exit_time, capital_before, quantity,
    effective_entry_price, entry_fee, net_capital_after. Entry fee is already
    paid through canonical sizing; unrealized PnL is price-based, excluding it.
    Derive reserve from capital_before minus quantity * effective_entry_price
    minus entry_fee; retain that cash while marking the canonical quantity.
    Use canonical actual exit cash, never hypothetical liquidation costs or a
    GROSS-minus-costs approximation. Schema, timing, and purity match GROSS.
    """
    return _calculate_equity(candles, net_results, candle_interval, initial_capital, "NET")
