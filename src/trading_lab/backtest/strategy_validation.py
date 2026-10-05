"""Validate generic long-only strategy intent without execution or accounting."""

from numbers import Integral

import pandas as pd


def validate_strategy_output(
    candles: pd.DataFrame,
    strategy_output: pd.DataFrame,
) -> pd.DataFrame:
    """Return an independent, unchanged copy of valid strategy output.

    Decision 010 requires timestamp, signal_time, signal, desired_position.
    Candle input needs only timestamp. Rows, indexes, and timestamp Series
    must match exactly; timestamps must already be unique chronological pandas
    datetimes. Availability is timestamp plus one elapsed hour, including HOLD
    and final rows, preserving the datetime/timezone representation.

    Start desired state FLAT (0). LONG_ENTRY changes 0 to 1; LONG_EXIT changes
    1 to 0; HOLD preserves state. Require integer 0/1, rejecting bools, floats,
    strings, missing values, and invalid transitions with ValueError.

    Preserve all diagnostic columns and both inputs. Do not parse, coerce,
    sort, repair, impose candle spacing/warm-up, prove causality, or create
    fills. A valid final-row event remains valid strategy intent.
    """
    for name, frame in (("candles", candles), ("strategy_output", strategy_output)):
        if not isinstance(frame, pd.DataFrame):
            raise ValueError(f"{name} must be a pandas DataFrame.")
        if not frame.columns.is_unique:
            raise ValueError(f"{name} column names must be unique.")

    if "timestamp" not in candles.columns:
        raise ValueError("candles is missing required column: timestamp.")
    required = ("timestamp", "signal_time", "signal", "desired_position")
    missing = [column for column in required if column not in strategy_output.columns]
    if missing:
        raise ValueError(f"strategy_output is missing required columns: {missing}.")

    if len(strategy_output) != len(candles):
        raise ValueError("Strategy output alignment error: row count differs from candles.")
    if not strategy_output.index.equals(candles.index):
        raise ValueError("Strategy output alignment error: index differs from candles.")

    timestamps = candles["timestamp"]
    strategy_timestamps = strategy_output["timestamp"]
    for name, values in (
        ("candles timestamp", timestamps),
        ("strategy_output timestamp", strategy_timestamps),
    ):
        if not pd.api.types.is_datetime64_any_dtype(values.dtype):
            raise ValueError(f"{name} must be a pandas datetime column.")
        if values.isna().any():
            raise ValueError(f"{name} must not contain missing values.")
    if not timestamps.is_unique:
        raise ValueError("candles timestamps must be unique.")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("candles timestamps must be strictly chronological.")
    if not strategy_timestamps.equals(timestamps):
        raise ValueError("Strategy output alignment error: timestamps differ from candles.")

    signal_times = strategy_output["signal_time"]
    if not pd.api.types.is_datetime64_any_dtype(signal_times.dtype):
        raise ValueError("signal_time must be a pandas datetime column.")
    if signal_times.isna().any():
        raise ValueError("signal_time must not contain missing values.")
    # Timedelta means elapsed time, including when a local DST clock changes.
    try:
        expected_signal_times = strategy_timestamps + pd.Timedelta(hours=1)
    except (OverflowError, ValueError) as error:
        raise ValueError("signal_time cannot represent timestamp plus one hour.") from error
    if not signal_times.equals(expected_signal_times):
        raise ValueError(
            "signal_time must equal timestamp plus one elapsed hour "
            "with the same datetime/timezone representation."
        )

    current_state = 0
    rows = zip(strategy_output["signal"], strategy_output["desired_position"])
    for row_number, (signal, desired_position) in enumerate(rows):
        if not isinstance(signal, str) or signal not in ("LONG_ENTRY", "LONG_EXIT", "HOLD"):
            raise ValueError(
                f"Invalid signal at row {row_number}; expected LONG_ENTRY, LONG_EXIT, or HOLD."
            )
        # Equality alone accepts 1.0 and True. Integral includes NumPy integers;
        # Python bool is excluded explicitly, and NumPy bool is not Integral.
        if (
            isinstance(desired_position, bool)
            or not isinstance(desired_position, Integral)
            or desired_position not in (0, 1)
        ):
            raise ValueError(f"desired_position at row {row_number} must be integer 0 or 1.")

        expected_state = current_state
        if signal == "LONG_ENTRY":
            if current_state != 0:
                raise ValueError(f"LONG_ENTRY at row {row_number} requires FLAT; already LONG.")
            expected_state = 1
        elif signal == "LONG_EXIT":
            if current_state != 1:
                raise ValueError(f"LONG_EXIT at row {row_number} requires LONG; currently FLAT.")
            expected_state = 0
        if desired_position != expected_state:
            raise ValueError(
                f"{signal} at row {row_number} requires desired_position {expected_state}; "
                f"got {desired_position}."
            )
        current_state = expected_state

    return strategy_output.copy(deep=True)
