"""Fixed-fraction capital budgets, independent of trading and accounting."""

from math import isfinite
from numbers import Real


def _positive_float(value, name: str) -> float:
    """Accept real scalars only, with a safely positive finite float value."""
    # Python bool is a Real; NumPy bool is not. Neither is numeric capital.
    if not isinstance(value, Real) or isinstance(value, bool):
        raise ValueError(f"{name} must be a finite positive real number; bools are not allowed.")
    try:
        number = float(value)
    except (OverflowError, TypeError, ValueError) as error:
        raise ValueError(f"{name} must be representable as a finite positive float.") from error
    if not isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and strictly greater than zero.")
    return number


def calculate_position_budget(capital_before, position_fraction=1.0) -> float:
    """Return current portfolio capital times a fixed allocation fraction.

    Require positive finite real capital and a fraction in (0, 1], rejecting
    bools, strings, non-scalars, and unsafe conversion/multiplication to zero.
    Return a finite positive Python float; no minimum allocation is invented.
    This pure helper calculates budget only, not quantity, costs, or reserve.
    """
    capital = _positive_float(capital_before, "capital_before")
    fraction = _positive_float(position_fraction, "position_fraction")
    # Check the original value: an exact fraction above 1 may round to 1.0.
    if position_fraction > 1:
        raise ValueError("position_fraction must satisfy 0 < position_fraction <= 1.")

    budget = capital * fraction
    if not isfinite(budget) or budget <= 0:
        raise ValueError("Resulting position budget must be finite and strictly greater than zero.")
    return budget
