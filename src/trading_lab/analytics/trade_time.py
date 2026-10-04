"""Ledger-based elapsed trade durations and binary time-in-market exposure."""

from datetime import datetime
from math import isfinite

import numpy as np
import pandas as pd


def _timestamp(value, name: str) -> pd.Timestamp:
    """Accept existing datetime scalars, never parse strings or numeric epochs."""
    if not isinstance(value, (datetime, pd.Timestamp, np.datetime64)):
        raise ValueError(f"{name} must be a non-missing timestamp object, not a string or number.")
    try:
        timestamp = pd.Timestamp(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name} must be a valid timestamp.") from error
    if pd.isna(timestamp):
        raise ValueError(f"{name} must be a non-missing timestamp.")
    return timestamp


def _same_timezone(timestamp: pd.Timestamp, reference: pd.Timestamp, name: str) -> None:
    """Keep timezone implementations/zones explicit, including across DST."""
    def zone_key(value):
        zone = value.tz
        # pytz uses different offset objects within the same zone across DST.
        return type(zone), getattr(zone, "zone", getattr(zone, "key", zone))

    if zone_key(timestamp) != zone_key(reference):
        raise ValueError(f"{name} and observation_start must use the same timezone (or all be naive).")


def _elapsed(end: pd.Timestamp, start: pd.Timestamp, name: str) -> pd.Timedelta:
    """Reject unsafe or non-positive elapsed intervals without rounding."""
    try:
        duration = end - start
        hours = _hours(duration)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError(f"{name} must have safely representable positive elapsed duration.") from error
    if not isfinite(hours) or hours <= 0:
        raise ValueError(f"{name} must have positive elapsed duration.")
    return duration


def _hours(duration: pd.Timedelta) -> float:
    # Equivalent to elapsed seconds / 3600, preserving sub-microsecond precision.
    return float(duration / pd.Timedelta(hours=1))


def _validated_breakdown(trades: pd.DataFrame, observation_start, observation_end):
    """Share validation, per-trade intervals, and exact elapsed totals for both APIs."""
    if not isinstance(trades, pd.DataFrame):
        raise ValueError("trades must be a pandas DataFrame.")
    if not trades.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["trade_id", "status", "entry_time", "exit_time"]
    missing = [column for column in required if column not in trades.columns]
    if missing:
        raise ValueError(f"Missing required ledger columns: {missing}.")
    if not trades["status"].isin(["CLOSED", "OPEN"]).all():
        raise ValueError("status values must be CLOSED or OPEN.")

    start = _timestamp(observation_start, "observation_start")
    end = _timestamp(observation_end, "observation_end")
    _same_timezone(end, start, "observation_end")
    window_duration = _elapsed(end, start, "Observation window")
    open_count = int(trades["status"].eq("OPEN").sum())
    if open_count > 1:
        raise ValueError("At most one OPEN trade is allowed.")
    if open_count and trades["status"].iloc[-1] != "OPEN":
        raise ValueError("An OPEN trade must be the final ledger row.")

    result = trades[required].copy(deep=True)
    closed_hours, observed_hours = [], []
    total_closed_duration = pd.Timedelta(0)
    open_duration = pd.Timedelta(0)
    previous_exit = None
    for row_number, (_, status, entry_value, exit_value) in enumerate(
        result.itertuples(index=False, name=None)
    ):
        entry = _timestamp(entry_value, f"entry_time at row {row_number}")
        _same_timezone(entry, start, f"entry_time at row {row_number}")
        if not start <= entry < end:
            raise ValueError("Every entry_time must lie within [observation_start, observation_end).")
        if previous_exit is not None and entry < previous_exit:
            raise ValueError("Trade intervals must be chronological and non-overlapping; input will not be sorted.")

        if status == "CLOSED":
            exit_time = _timestamp(exit_value, f"CLOSED exit_time at row {row_number}")
            _same_timezone(exit_time, start, f"CLOSED exit_time at row {row_number}")
            if exit_time > end:
                raise ValueError("CLOSED exit_time must not exceed observation_end.")
            duration = _elapsed(exit_time, entry, f"CLOSED duration at row {row_number}")
            closed_hours.append(_hours(duration))
            # Aggregate elapsed intervals before converting totals to float hours.
            try:
                total_closed_duration += duration
            except (TypeError, ValueError, OverflowError) as error:
                raise ValueError("Total CLOSED duration must be safely representable.") from error
            previous_exit = exit_time
        else:
            if not pd.api.types.is_scalar(exit_value) or not pd.isna(exit_value):
                raise ValueError("OPEN exit_time must be missing; no exit will be fabricated.")
            duration = _elapsed(end, entry, f"OPEN observed duration at row {row_number}")
            open_duration = duration
            closed_hours.append(float("nan"))
        observed_hours.append(_hours(duration))

    # Matching source indexes preserves even duplicate labels without sorting.
    result["closed_duration_hours"] = pd.Series(closed_hours, index=result.index, dtype="float64")
    result["observed_time_in_market_hours"] = pd.Series(observed_hours, index=result.index, dtype="float64")
    return result, window_duration, total_closed_duration, open_duration


def calculate_trade_time_breakdown(
    trades: pd.DataFrame, observation_start, observation_end,
) -> pd.DataFrame:
    """Return decision 005's six-column time table from recorded ledger fills.

    Require trade_id, status, entry_time, exit_time and explicit positive
    [observation_start, observation_end) boundaries. CLOSED duration uses
    [entry_time, exit_time); final OPEN uses [entry_time, observation_end) for
    exposure only, with NaN completed duration and its original missing exit.
    Keep source rows/index/values/dtypes/timezones; new duration fields are
    float64. Reject malformed boundaries, timestamps, statuses, order/overlap,
    and multiple/non-final OPEN trades without parsing, sorting, or clipping.
    Accept datetime/Timestamp/NumPy datetime64 scalars, consistently naive or
    aware with the same timezone. No accounting, valuation, or GROSS/NET split.
    """
    breakdown, _, _, _ = _validated_breakdown(trades, observation_start, observation_end)
    return breakdown


def summarize_trade_time_metrics(
    trades: pd.DataFrame, observation_start, observation_end,
) -> pd.DataFrame:
    """Return the exact 11-field TIME summary using the validated breakdown.

    CLOSED descriptive statistics exclude OPEN; observed OPEN time contributes
    to total time in market / explicit window duration. Counts are int64 and
    other fields float64. With no CLOSED trades, four descriptive fields are
    NaN; absent populations have zero totals. Empty exposure is 0.0 and an
    OPEN position held throughout the window gives 1.0. Inputs stay unchanged.
    Exposure is binary holding time for a non-overlapping single position,
    without rounding, annualization, clamping, or price/size/leverage weighting.
    """
    breakdown, window, total_closed, observed_open = _validated_breakdown(
        trades, observation_start, observation_end,
    )
    closed = breakdown.loc[breakdown["status"].eq("CLOSED"), "closed_duration_hours"]
    total_time = total_closed + observed_open
    window_hours = _hours(window)
    metrics = {
        "closed_trade_count": len(closed),
        "open_trade_count": int(breakdown["status"].eq("OPEN").sum()),
        "average_closed_duration_hours": float(closed.mean()),
        "median_closed_duration_hours": float(closed.median()),
        "minimum_closed_duration_hours": float(closed.min()),
        "maximum_closed_duration_hours": float(closed.max()),
        "total_closed_duration_hours": _hours(total_closed),
        "open_observed_duration_hours": _hours(observed_open),
        "total_time_in_market_hours": _hours(total_time),
        "observation_window_hours": window_hours,
        "exposure_ratio": _hours(total_time) / window_hours,
    }
    return pd.DataFrame([metrics], index=["TIME"])
