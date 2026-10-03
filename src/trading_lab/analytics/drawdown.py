"""Realized-capital drawdown at initial capital and after CLOSED trades only."""

from math import isfinite
from numbers import Real

import pandas as pd


def _capital(value, name: str, *, allow_zero: bool) -> float:
    """Validate real capital before copying to float64; never parse strings."""
    rule = "non-negative" if allow_zero else "strictly positive"
    message = f"{name} must be finite real numeric and {rule}, not bool, string, or complex."
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ValueError(message)
    try:
        number = float(value)
    except (OverflowError, ValueError) as error:
        raise ValueError(message) from error
    if not isfinite(number) or number < 0 or (not allow_zero and number == 0):
        raise ValueError(message)
    return number


def _calculate_path(
    results: pd.DataFrame, initial_capital: float, capital_column: str, label: str,
) -> pd.DataFrame:
    """Use canonical capital values in input order; accounting stays upstream."""
    initial = _capital(initial_capital, "initial_capital", allow_zero=False)
    if not isinstance(results, pd.DataFrame):
        raise ValueError("results must be a pandas DataFrame.")
    if not results.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["status", "capital_before", capital_column]
    missing = [column for column in required if column not in results.columns]
    if missing:
        raise ValueError(f"{label} drawdown missing required columns: {missing}.")
    if not results["status"].isin(["CLOSED", "OPEN"]).all():
        raise ValueError("status values must be CLOSED or OPEN.")

    # capital_before guards the source schema; it is never inferred as C0.
    # OPEN capital and entry costs do not add or adjust any observation.
    closed_capital = results.loc[results["status"].eq("CLOSED"), capital_column]
    capital = pd.Series([
        initial,
        *[_capital(value, f"CLOSED {capital_column}", allow_zero=True) for value in closed_capital],
    ], dtype="float64")
    running_peak = capital.cummax()
    numbers = pd.Series(range(len(capital)), dtype="int64")
    return pd.DataFrame({
        "observation": numbers,
        "closed_trade_number": numbers.copy(),
        "capital": capital,
        "running_peak": running_peak,
        "drawdown": capital / running_peak - 1,
        "drawdown_amount": capital - running_peak,
    })


def _summarize_path(path: pd.DataFrame, label: str) -> pd.DataFrame:
    """Keep the currency amount from the earliest minimum percentage point."""
    # idxmin chooses the first exact minimum on this ordered RangeIndex.
    # The worst currency decline may occur elsewhere, so do not minimize it.
    trough = path.loc[path["drawdown"].idxmin()]
    return pd.DataFrame({
        "max_realized_drawdown": [float(trough["drawdown"])],
        "max_realized_drawdown_amount": [float(trough["drawdown_amount"])],
    }, index=[label])


def calculate_gross_realized_drawdown(
    results: pd.DataFrame, initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return the six-column decision 004 path from Stage 4.6 capital_after.

    Require status, capital_before, capital_after. Explicit initial capital is
    observation 0; each CLOSED row adds a point in existing input order. Both
    ordinals are int64; capital, peak, drawdown, and amount are float64 on a
    RangeIndex. Drawdown = capital / peak - 1; amount = capital - peak.
    Initial capital must be finite real and positive; CLOSED capital may be
    zero but never negative/missing/non-finite. Bools/strings/complex are errors.
    OPEN rows are excluded and unvalued. Preserve input; never sort or repair.
    Use the same initial capital as accounting; do not infer it or rebuild PnL.
    This path can miss intratrade losses and is not full portfolio drawdown.
    """
    return _calculate_path(results, initial_capital, "capital_after", "GROSS")


def calculate_net_realized_drawdown(
    results: pd.DataFrame, initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return the same six-column path from Stage 4.7 net_capital_after.

    Require status, capital_before, net_capital_after. Apply the gross path's
    validation and observation rules to independent NET capital. Do not use
    gross capital, PnL, fees, or OPEN entry values to reconstruct the path.
    Empty/OPEN-only input produces only initial capital with zero drawdown.
    Inputs remain unchanged; no mark-to-market valuation is introduced.
    """
    return _calculate_path(results, initial_capital, "net_capital_after", "NET")


def summarize_gross_realized_drawdown(
    results: pd.DataFrame, initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return GROSS maximum realized drawdown and its associated currency amount.

    Reuse the gross path; maximum is its most negative drawdown. Exact ties
    select the earliest observation. Empty/increasing/flat paths give 0.0 for
    both fields; zero CLOSED capital gives -1.0 drawdown. Input is unchanged.
    """
    return _summarize_path(calculate_gross_realized_drawdown(results, initial_capital), "GROSS")


def summarize_net_realized_drawdown(
    results: pd.DataFrame, initial_capital: float = 10_000.0,
) -> pd.DataFrame:
    """Return NET maximum realized drawdown and its amount using the net path.

    Return exactly max_realized_drawdown and max_realized_drawdown_amount in
    one row indexed NET, following the same earliest-minimum rule as GROSS.
    Neither this summary nor its path observes losses within an OPEN position.
    """
    return _summarize_path(calculate_net_realized_drawdown(results, initial_capital), "NET")
