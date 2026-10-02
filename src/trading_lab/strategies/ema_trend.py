"""Causal, long-only EMA crossover signals, independent of execution."""

from numbers import Integral

import numpy as np
import pandas as pd


def generate_ema_signals(
    candles: pd.DataFrame,
    fast_span: int = 20,
    slow_span: int = 50,
    warmup_candles: int = 50,
) -> pd.DataFrame:
    """Return completed-hourly-candle signals without changing input.

    Require timestamp (pandas datetime) and close (numeric, finite, positive).
    Timestamps must be non-missing, unique, and chronological; hourly OHLCV
    continuity validation belongs upstream. Do not sort or repair input.

    Return exactly timestamp, close, ema_{fast_span}, ema_{slow_span},
    warmup_complete, bullish_cross, bearish_cross, signal, desired_position,
    signal_time. Defaults retain the notebook's ema_20/ema_50 names. Preserve
    the input index and timestamp/close values; omit optional input columns.

    Both EMAs use adjust=False and the first close as their seed. The first
    warmup_candles rows initialize the strategy: no events, HOLD, desired state
    0. Eligibility alone never creates an entry. A new bullish crossover while
    flat enters desired state 1; a bearish crossover while long returns to 0.
    Other rows HOLD. State reflects intent AFTER this completed candle.

    signal_time is timestamp + one hour. No fills or execution state are
    calculated; a final-row signal is still a valid strategy decision.
    """
    for name, value in (
        ("fast_span", fast_span),
        ("slow_span", slow_span),
        ("warmup_candles", warmup_candles),
    ):
        if isinstance(value, (bool, np.bool_)) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(f"{name} must be a positive integer.")
    if fast_span >= slow_span:
        raise ValueError("fast_span must be less than slow_span.")

    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not candles.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    required = ["timestamp", "close"]
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

    closes = candles["close"]
    if (
        not pd.api.types.is_numeric_dtype(closes.dtype)
        or pd.api.types.is_bool_dtype(closes.dtype)
        or pd.api.types.is_complex_dtype(closes.dtype)
    ):
        raise ValueError("close must contain finite positive numeric values.")
    close_values = closes.to_numpy(dtype=float, na_value=np.nan)
    if not np.isfinite(close_values).all() or (close_values <= 0).any():
        raise ValueError("close must contain finite positive numeric values.")

    result = candles[required].copy()
    fast_column = f"ema_{fast_span}"
    slow_column = f"ema_{slow_span}"
    result[fast_column] = closes.ewm(span=fast_span, adjust=False).mean()
    result[slow_column] = closes.ewm(span=slow_span, adjust=False).mean()
    observations_seen = pd.Series(range(1, len(result) + 1), index=result.index)
    result["warmup_complete"] = observations_seen > warmup_candles

    previous_fast = result[fast_column].shift(1)
    previous_slow = result[slow_column].shift(1)
    result["bullish_cross"] = (
        (previous_fast <= previous_slow)
        & (result[fast_column] > result[slow_column])
        & result["warmup_complete"]
    )
    result["bearish_cross"] = (
        (previous_fast >= previous_slow)
        & (result[fast_column] < result[slow_column])
        & result["warmup_complete"]
    )

    current_desired_position = 0
    signals = []
    desired_positions = []
    for bullish_cross, bearish_cross in zip(result["bullish_cross"], result["bearish_cross"]):
        signal = "HOLD"
        # Eligible crossovers are events; only the appropriate prior state
        # permits a signal. In particular, bearish while flat remains HOLD.
        if bullish_cross and current_desired_position == 0:
            signal = "LONG_ENTRY"
            current_desired_position = 1
        elif bearish_cross and current_desired_position == 1:
            signal = "LONG_EXIT"
            current_desired_position = 0
        signals.append(signal)
        desired_positions.append(current_desired_position)

    result["signal"] = pd.Series(signals, index=result.index, dtype="object")
    result["desired_position"] = pd.Series(desired_positions, index=result.index, dtype="int64")
    result["signal_time"] = timestamps + pd.Timedelta(hours=1)
    return result
