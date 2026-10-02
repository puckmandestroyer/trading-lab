"""Next-candle OPEN execution timing and long-only state, without PnL."""

from math import isfinite
from numbers import Real

import pandas as pd


def apply_next_open_execution(candles: pd.DataFrame) -> pd.DataFrame:
    """Map completed hourly signals to next-open fills without changing input.

    Required columns: timestamp (pandas datetime), open, signal. Timestamps must
    be non-missing, unique, chronological, and exactly one hour apart. Signals
    must be LONG_ENTRY, LONG_EXIT, or HOLD. Every OPEN used for a fill must be a
    finite positive real number; full OHLCV validation belongs upstream.

    Return exactly: timestamp, open, signal, execution_time, execution_price,
    executed_position. Preserve the input index and required-column values.
    Optional columns, including desired_position and signal_time, are not used
    or changed. Hourly signal availability follows decision 002.

    Row semantics are deliberately explicit:
    - execution_time/price on row N describe that row's signal's fill at N+1.
    - executed_position on row N is the state AFTER any preceding signal fills
      at N's OPEN, and BEFORE N's own completed-candle signal can execute.

    Start flat. Reject entries while long and exits while flat, including invalid
    final-candle events. A valid final event has NaT/NaN execution metadata and
    does not change state. HOLD also has no execution metadata. No terminal
    closing, signal generation, trade pairing, or financial metrics are added.
    """
    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not candles.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["timestamp", "open", "signal"]
    missing = [column for column in required if column not in candles.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}.")

    timestamps = candles["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(timestamps.dtype):
        raise ValueError("timestamp must be a pandas datetime column.")
    if timestamps.isna().any():
        raise ValueError("Timestamps must not be missing.")
    if not timestamps.is_unique:
        raise ValueError("Timestamps must be unique.")
    if not timestamps.is_monotonic_increasing:
        raise ValueError("Timestamps must be chronological.")
    if not timestamps.diff().iloc[1:].eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Timestamps must have continuous one-hour spacing.")

    allowed_signals = {"LONG_ENTRY", "LONG_EXIT", "HOLD"}
    invalid_signals = ~candles["signal"].isin(allowed_signals)
    if invalid_signals.any():
        examples = candles.loc[invalid_signals, "signal"].head().tolist()
        raise ValueError(f"Invalid signal values: {examples}; expected LONG_ENTRY, LONG_EXIT, or HOLD.")

    result = candles[required].copy()
    execution_times = [pd.NaT] * len(candles)
    execution_prices = [float("nan")] * len(candles)
    executed_positions = []
    current_state = 0

    for row_number, signal in enumerate(candles["signal"]):
        # The prior event's next-open fill now applies during this candle.
        # Store it before considering this row's own close-derived signal.
        executed_positions.append(current_state)
        if signal == "HOLD":
            continue
        if signal == "LONG_ENTRY" and current_state != 0:
            raise ValueError(f"LONG_ENTRY at row {row_number} requires flat executed state; already long.")
        if signal == "LONG_EXIT" and current_state != 1:
            raise ValueError(f"LONG_EXIT at row {row_number} requires long executed state; currently flat.")
        if row_number == len(candles) - 1:
            continue  # Valid signal, but no next candle: no fill or state change.

        next_open = candles["open"].iloc[row_number + 1]
        if not isinstance(next_open, Real) or isinstance(next_open, bool):
            raise ValueError(f"Execution OPEN at row {row_number + 1} must be a finite positive number.")
        price = float(next_open)
        if not isfinite(price) or price <= 0:
            raise ValueError(f"Execution OPEN at row {row_number + 1} must be a finite positive number.")

        execution_times[row_number] = timestamps.iloc[row_number + 1]
        execution_prices[row_number] = price
        # Prepare the state for N+1; row N's stored state is unchanged.
        current_state = 1 if signal == "LONG_ENTRY" else 0

    result["execution_time"] = pd.Series(execution_times, index=result.index, dtype=timestamps.dtype)
    result["execution_price"] = pd.Series(execution_prices, index=result.index, dtype="float64")
    result["executed_position"] = pd.Series(executed_positions, index=result.index, dtype="int64")
    return result
