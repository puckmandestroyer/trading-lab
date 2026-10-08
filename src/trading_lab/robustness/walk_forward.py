"""Expanding chronological windows with independent fixed-strategy evaluations."""

from collections.abc import Mapping
from copy import deepcopy
from numbers import Integral

import pandas as pd

from trading_lab.robustness.evaluation import evaluate_strategy_segment


_WINDOW_COLUMNS = (
    "window_id", "train_start_index", "train_end_index",
    "test_start_index", "test_end_index", "train_rows", "test_rows",
    "train_start_timestamp", "train_last_timestamp",
    "test_start_timestamp", "test_last_timestamp",
)


def generate_expanding_walk_forward_windows(
    candles: pd.DataFrame,
    initial_train_rows,
    test_rows,
) -> pd.DataFrame:
    """Define deterministic expanding row-count trains and fixed full tests.

    Preserve source order, index, and timezone; never sort, shuffle, or repair.
    Slice endpoints are exclusive. Exclude any partial final test explicitly;
    the evaluator reports its unused tail. Require at least one full window.
    """
    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not candles.columns.is_unique:
        raise ValueError("Candle column names must be unique.")
    if "timestamp" not in candles:
        raise ValueError("candles missing required timestamp column.")
    timestamps = candles["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(timestamps.dtype):
        raise ValueError("timestamp must be a pandas datetime column.")
    if timestamps.isna().any():
        raise ValueError("Timestamps must not be missing.")
    if not timestamps.is_unique or not timestamps.is_monotonic_increasing:
        raise ValueError("Timestamps must be unique and strictly increasing.")
    for name, value in (("initial_train_rows", initial_train_rows), ("test_rows", test_rows)):
        if isinstance(value, bool) or not isinstance(value, Integral) or value <= 0:
            raise ValueError(f"{name} must be a positive integer scalar.")
    # Convert validated NumPy integers before addition to avoid fixed-width
    # integer overflow; never coerce floats into accepted row counts.
    initial_train_rows, test_rows = int(initial_train_rows), int(test_rows)
    if initial_train_rows + test_rows > len(candles):
        raise ValueError("Row counts must allow at least one complete train/test window.")

    rows = []
    for window_id, test_start in enumerate(
        range(initial_train_rows, len(candles) - test_rows + 1, test_rows), start=1,
    ):
        test_end = test_start + test_rows
        rows.append({
            "window_id": window_id,
            "train_start_index": 0,
            "train_end_index": test_start,
            "test_start_index": test_start,
            "test_end_index": test_end,
            "train_rows": test_start,
            "test_rows": test_rows,
            "train_start_timestamp": timestamps.iloc[0],
            "train_last_timestamp": timestamps.iloc[test_start - 1],
            "test_start_timestamp": timestamps.iloc[test_start],
            "test_last_timestamp": timestamps.iloc[test_end - 1],
        })
    return pd.DataFrame(rows, columns=_WINDOW_COLUMNS)


def evaluate_expanding_walk_forward(
    candles: pd.DataFrame,
    strategy_generator,
    *,
    candle_interval,
    initial_train_rows,
    test_rows,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
) -> dict:
    """Evaluate fixed-strategy independent cold-start expanding train/tests.

    Reuse the segment evaluator with equal assumptions and fresh settings for
    every run. Carry no state/capital/trades or boundary fills between slices.
    Return canonical nested results and an explicit unused tail, without
    parameter selection, summary metrics, or stitched equity.
    """
    definitions = generate_expanding_walk_forward_windows(candles, initial_train_rows, test_rows)
    if strategy_kwargs is not None and not isinstance(strategy_kwargs, Mapping):
        raise ValueError("strategy_kwargs must be a mapping or None.")
    common_kwargs = {} if strategy_kwargs is None else dict(strategy_kwargs)
    if any(not isinstance(key, str) for key in common_kwargs):
        raise ValueError("strategy_kwargs keys must be strings.")
    settings = dict(
        candle_interval=candle_interval, initial_capital=initial_capital,
        fee_rate=fee_rate, slippage_rate=slippage_rate, position_fraction=position_fraction,
    )

    windows = []
    for definition in definitions.itertuples(index=False):
        window = {"window_id": definition.window_id}
        for label, start, end in (
            ("train", definition.train_start_index, definition.train_end_index),
            ("test", definition.test_start_index, definition.test_end_index),
        ):
            # Fresh mutable keyword values isolate even overlapping training
            # runs, and keep a strategy's mutations out of every later slice.
            window[label] = evaluate_strategy_segment(
                candles.iloc[start:end].copy(deep=True), strategy_generator,
                strategy_kwargs=deepcopy(common_kwargs), **settings,
            )
        windows.append(window)
    return {
        "window_definitions": definitions,
        "unused_tail_rows": len(candles) - int(definitions["test_end_index"].iloc[-1]),
        "windows": tuple(windows),
    }
