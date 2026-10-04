"""Candle-CLOSE portfolio drawdown from authoritative equity paths (decision 007).

GROSS and NET use identical mathematics on independently supplied equity paths.
Their wrappers express caller intent, not source detection from identical schemas.
No accounting, marking, trade-status handling, or input mutation occurs here.
"""

from datetime import datetime
from math import isfinite
from numbers import Integral, Real

import numpy as np
import pandas as pd


_REQUIRED_COLUMNS = ["observation", "valuation_time", "equity"]
_FINANCIAL_COLUMNS = ["equity", "running_peak", "drawdown", "drawdown_amount"]


def _equity(value, *, initial):
    """Validate real equity before copying to float64; never parse or repair it."""
    rule = "strictly positive" if initial else "non-negative"
    message = f"equity must be finite real numeric and {rule}, safely representable as float64."
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise ValueError(message)
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError(message) from error
    if not isfinite(number) or number < 0 or (initial and number == 0):
        raise ValueError(message)
    # A nonzero source amount must not silently become zero during conversion.
    if number == 0 and value != 0:
        raise ValueError(message)
    return number


def _valuation_time(value):
    """Accept existing datetime scalars that fit the nanosecond output clock."""
    if not isinstance(value, (datetime, np.datetime64)):
        raise ValueError("valuation_time must be a valid non-missing datetime.")
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError("Missing timestamp.")
        stamp.value
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError("valuation_time must be a safely representable non-missing datetime.") from error
    return stamp


def _timezone_key(stamp):
    """Match timezone implementation/zone while allowing same-zone DST offsets."""
    zone = stamp.tz
    if zone is None:
        return None
    name = getattr(zone, "zone", getattr(zone, "key", str(zone)))
    return type(zone), name


def _calculate_path(equity_path):
    """Validate the three authoritative columns, then calculate causal peaks."""
    if not isinstance(equity_path, pd.DataFrame):
        raise ValueError("equity_path must be a pandas DataFrame.")
    if not equity_path.columns.is_unique:
        raise ValueError("equity_path column names must be unique.")
    missing = [column for column in _REQUIRED_COLUMNS if column not in equity_path.columns]
    if missing:
        raise ValueError(f"equity_path missing required columns: {missing}.")
    if equity_path.empty:
        raise ValueError("equity_path must contain at least the initial observation.")

    observations, times, values = [], [], []
    previous_time = None
    clock = None
    for expected, (observation, raw_time, raw_equity) in enumerate(
        equity_path[_REQUIRED_COLUMNS].itertuples(index=False, name=None)
    ):
        if (
            not isinstance(observation, Integral)
            or isinstance(observation, (bool, np.bool_))
            or observation != expected
        ):
            raise ValueError("observation must be canonical consecutive integers starting at 0.")
        stamp = _valuation_time(raw_time)
        if previous_time is None:
            clock = _timezone_key(stamp)
        if _timezone_key(stamp) != clock:
            raise ValueError("valuation_time must be all naive or use the same timezone implementation/zone.")
        if previous_time is not None and stamp <= previous_time:
            raise ValueError("valuation_time must be strictly increasing without duplicates.")
        observations.append(int(observation))
        times.append(stamp)
        values.append(_equity(raw_equity, initial=expected == 0))
        previous_time = stamp

    first = times[0]
    time_dtype = pd.DatetimeTZDtype(tz=first.tz, unit="ns") if first.tz is not None else "datetime64[ns]"
    equity = pd.Series(values, dtype="float64")
    # cummax only uses this row and earlier rows, never the eventual maximum.
    running_peak = equity.cummax()
    path = pd.DataFrame({
        "observation": pd.Series(observations, dtype="int64"),
        "valuation_time": pd.Series(times, dtype=time_dtype),
        "equity": equity,
        "running_peak": running_peak,
        "drawdown": equity / running_peak - 1,
        "drawdown_amount": equity - running_peak,
    })
    if not np.isfinite(path[_FINANCIAL_COLUMNS].to_numpy()).all():
        raise ValueError("Calculated portfolio drawdown fields must be finite float64.")
    return path


def _summarize_path(path, label):
    """Select the earliest exact minimum trough and its latest matching peak."""
    # idxmin selects the first exact minimum on this ordered RangeIndex.
    trough_number = int(path["drawdown"].idxmin())
    trough = path.iloc[trough_number]
    preceding_equity = path.loc[:trough_number, "equity"]
    matching_peaks = preceding_equity[preceding_equity.eq(trough["running_peak"])]
    peak_number = int(matching_peaks.index[-1])
    peak = path.iloc[peak_number]
    # The amount belongs to the percentage trough, not the worst currency loss.
    return pd.DataFrame({
        "max_portfolio_drawdown": [float(trough["drawdown"])],
        "max_portfolio_drawdown_amount": [float(trough["drawdown_amount"])],
        "peak_observation": [int(peak["observation"])],
        "trough_observation": [int(trough["observation"])],
        "peak_valuation_time": pd.array([peak["valuation_time"]], dtype=path["valuation_time"].dtype),
        "trough_valuation_time": pd.array([trough["valuation_time"]], dtype=path["valuation_time"].dtype),
        "peak_equity": [float(peak["equity"])],
        "trough_equity": [float(trough["equity"])],
    }, index=[label])


def calculate_gross_portfolio_drawdown(
    gross_equity_path: pd.DataFrame,
) -> pd.DataFrame:
    """Return decision 007's six-column path from supplied GROSS equity.

    Require observation, valuation_time, equity; ignore extra columns. Retain
    initial observation 0 and each CLOSE on a new RangeIndex, with int64 ordinals,
    float64 financial fields, and a coherent datetime clock. Peak is the maximum
    observed so far; drawdown = equity / peak - 1; amount = equity - peak.
    Initial equity is positive, later equity non-negative. Never mutate input.
    """
    return _calculate_path(gross_equity_path)


def calculate_net_portfolio_drawdown(
    net_equity_path: pd.DataFrame,
) -> pd.DataFrame:
    """Apply the same pure calculation to independently supplied NET equity.

    Schema, validation, initial point, and causal peaks match GROSS. No costs or
    equity are reconstructed. Final OPEN marks already in the input are included
    naturally. Identical source schemas cannot establish GROSS/NET provenance.
    """
    return _calculate_path(net_equity_path)


def summarize_gross_portfolio_drawdown(
    gross_equity_path: pd.DataFrame,
) -> pd.DataFrame:
    """Return the exact eight-field GROSS summary, reusing the validated path.

    Minimum percentage drawdown selects the earliest exact tied trough, then
    the latest exact matching peak at or before it. The amount is from that
    trough. Flat/increasing paths select observation 0 as both peak and trough.
    """
    return _summarize_path(calculate_gross_portfolio_drawdown(gross_equity_path), "GROSS")


def summarize_net_portfolio_drawdown(
    net_equity_path: pd.DataFrame,
) -> pd.DataFrame:
    """Return the same eight-field summary indexed NET, without input mutation.

    Use the independent NET path and the same exact earliest-trough/latest-peak
    rules. This measures candle-CLOSE risk and can miss intrabar/tick losses.
    No trade status, liquidation, duration, or recovery calculation is involved.
    """
    return _summarize_path(calculate_net_portfolio_drawdown(net_equity_path), "NET")
