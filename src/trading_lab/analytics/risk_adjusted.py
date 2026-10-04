"""Simple time-based portfolio returns and decision 009's Sharpe/Sortino.

Consume marked portfolio equity, including unchanged cash periods and final OPEN
marks. Annualization is explicit; no candles, trade returns, or costs are rebuilt.
"""

from datetime import datetime
from math import isfinite, sqrt
from numbers import Integral, Real

import numpy as np
import pandas as pd


_RETURN_COLUMNS = [
    "observation", "period_start_time", "period_end_time",
    "starting_equity", "ending_equity", "period_return",
]
_SUMMARY_COLUMNS = [
    "period_count", "mean_period_return", "period_return_std",
    "annualized_volatility", "downside_deviation",
    "annualized_downside_deviation", "sharpe_ratio", "sortino_ratio",
]


def _number(value, label, positive=False):
    """Accept finite real numbers without parsing strings or accepting bools."""
    message = f"{label} must be a finite real {'positive ' if positive else ''}number."
    if not isinstance(value, Real) or isinstance(value, (bool, np.bool_)):
        raise ValueError(message)
    try:
        number = float(value)
    except (ValueError, OverflowError) as error:
        raise ValueError(message) from error
    if not isfinite(number) or (positive and number <= 0):
        raise ValueError(message)
    return number


def _timestamp(value):
    """Retain the existing naive or same-zone-aware clock, without parsing."""
    message = "valuation_time must be a safely representable non-missing datetime."
    if not isinstance(value, (datetime, np.datetime64)):
        raise ValueError(message)
    try:
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError(message)
        stamp.value  # Output datetime columns use nanosecond resolution.
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(message) from error
    return stamp


def _validated_equity(equity_path):
    """Validate supplied order, equal elapsed intervals, and safe denominators."""
    if not isinstance(equity_path, pd.DataFrame):
        raise ValueError("equity_path must be a pandas DataFrame.")
    if not equity_path.columns.is_unique:
        raise ValueError("equity_path column names must be unique.")
    required = ["observation", "valuation_time", "equity"]
    missing = [column for column in required if column not in equity_path.columns]
    if missing:
        raise ValueError(f"equity_path missing required columns: {missing}.")
    if len(equity_path) < 2:
        raise ValueError("equity_path must contain at least two equity observations.")

    times, amounts = [], []
    clock = spacing = None
    for expected, (ordinal, raw_time, raw_equity) in enumerate(
        equity_path[required].itertuples(index=False, name=None)
    ):
        if not isinstance(ordinal, Integral) or isinstance(ordinal, (bool, np.bool_)) or ordinal != expected:
            raise ValueError("observation must be consecutive integers 0, 1, ..., N.")
        stamp = _timestamp(raw_time)
        zone = stamp.tz
        key = None if zone is None else (type(zone), getattr(zone, "zone", getattr(zone, "key", str(zone))))
        if expected == 0:
            clock = key
        elif key != clock:
            raise ValueError("valuation_time must be all naive or use the same timezone implementation/zone.")
        if times:
            elapsed = stamp.value - times[-1].value
            if elapsed <= 0:
                raise ValueError("valuation_time must be strictly increasing and unique.")
            if spacing is None:
                spacing = elapsed
            elif elapsed != spacing:
                raise ValueError("valuation_time must have equally spaced elapsed intervals.")
        amount = _number(raw_equity, "equity")
        # An exact nonzero Real must not become a false zero-equity loss.
        if amount == 0.0 and raw_equity != 0:
            raise ValueError("Nonzero equity must not underflow to float64 zero.")
        if amount < 0 or (expected == 0 and amount == 0):
            raise ValueError("First equity must be positive; later equity must be non-negative.")
        times.append(stamp)
        amounts.append(amount)
    if any(amount == 0 for amount in amounts[:-1]):
        raise ValueError("Starting equity must be positive for every return; zero is allowed only at the final observation.")
    return times, np.array(amounts, dtype="float64")


def calculate_time_based_returns(equity_path: pd.DataFrame) -> pd.DataFrame:
    """Return E_i / E_(i-1) - 1 for every actual interval, retaining cash zeros.

    Require at least two canonical observations on an equally spaced coherent
    clock. A positive-to-zero final transition is -1; an earlier zero fails.
    Return exactly decision 009's six columns on a fresh RangeIndex. Observation
    is the ending ordinal 1..N, with no fake initial return. Preserve the source.
    """
    times, equity = _validated_equity(equity_path)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        returns = equity[1:] / equity[:-1] - 1
    if not np.isfinite(returns).all():
        raise ValueError("Calculated period returns must be representable finite float64 values.")
    first = times[0]
    time_dtype = pd.DatetimeTZDtype(tz=first.tz, unit="ns") if first.tz is not None else "datetime64[ns]"
    return pd.DataFrame({
        "observation": np.arange(1, len(equity), dtype="int64"),
        "period_start_time": pd.Series(times[:-1], dtype=time_dtype),
        "period_end_time": pd.Series(times[1:], dtype=time_dtype),
        "starting_equity": equity[:-1].copy(),
        "ending_equity": equity[1:].copy(),
        "period_return": returns,
    }, columns=_RETURN_COLUMNS)


def _ratio(numerator, denominator, annualization):
    """Represent exact zero-denominator cases explicitly, without an epsilon."""
    if denominator == 0:
        if numerator == 0:
            return float("nan")
        return float("inf") if numerator > 0 else float("-inf")
    result = numerator / denominator * annualization
    if not isfinite(result):
        raise ValueError("Calculated ratios must be finite except documented zero-denominator cases.")
    return result


def summarize_risk_adjusted_performance(
    equity_path: pd.DataFrame,
    periods_per_year: float,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
    label: str = "PORTFOLIO",
) -> pd.DataFrame:
    """Summarize the canonical returns with sample-std Sharpe and all-period Sortino.

    Annualization uses sqrt(explicit periods_per_year), never sample row count.
    Current hourly crypto research uses 8760 and zero per-period rf/MAR. Downside
    deviation is sqrt(mean(min(return - MAR, 0)**2)) over ALL periods. With only
    one return, sample std/annualized volatility and Sharpe are undefined (NaN);
    Sortino remains defined under its documented zero-downside convention.
    """
    periods = _number(periods_per_year, "periods_per_year", positive=True)
    risk_free = _number(risk_free_return_per_period, "risk_free_return_per_period")
    target = _number(minimum_acceptable_return_per_period, "minimum_acceptable_return_per_period")
    if not isinstance(label, str) or not label.strip():
        raise ValueError("label must be a non-empty string.")
    returns = calculate_time_based_returns(equity_path)["period_return"].to_numpy(copy=True)
    count = len(returns)
    annualization = sqrt(periods)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        excess = returns - risk_free
        downside = np.minimum(returns - target, 0.0)
        mean_return = float(np.mean(returns))
        mean_excess = float(np.mean(excess))
        mean_above_target = mean_return - target
        period_std = float(np.std(returns, ddof=1)) if count >= 2 else float("nan")
        excess_std = float(np.std(excess, ddof=1)) if count >= 2 else float("nan")
        # Scaling the RMS avoids overflow/underflow when squaring downside.
        # Non-downside periods still contribute zero to the ALL-period mean.
        downside_scale = float(np.max(np.abs(downside)))
        downside_deviation = (
            float(downside_scale * np.sqrt(np.mean((downside / downside_scale) ** 2)))
            if downside_scale > 0 else 0.0
        )
        volatility = period_std * annualization
        annualized_downside = downside_deviation * annualization
    finite_values = [mean_return, mean_excess, mean_above_target, downside_scale, downside_deviation, annualized_downside]
    if count >= 2:
        finite_values.extend([period_std, excess_std, volatility])
    if not np.isfinite(excess).all() or not np.isfinite(downside).all() or not all(isfinite(value) for value in finite_values):
        raise ValueError("Calculated risk-adjusted intermediates must be representable finite float64 values.")
    sharpe = _ratio(mean_excess, excess_std, annualization) if count >= 2 else float("nan")
    sortino = _ratio(mean_above_target, downside_deviation, annualization)
    summary = pd.DataFrame([[
        count, mean_return, period_std, volatility, downside_deviation,
        annualized_downside, sharpe, sortino,
    ]], columns=_SUMMARY_COLUMNS, index=[label])
    summary["period_count"] = summary["period_count"].astype("int64")
    summary[_SUMMARY_COLUMNS[1:]] = summary[_SUMMARY_COLUMNS[1:]].astype("float64")
    return summary
