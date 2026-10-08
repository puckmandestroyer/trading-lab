"""Split supplied candles and compose independent, cold-start evaluations."""

from collections.abc import Mapping
from math import isfinite
from numbers import Real

import pandas as pd

from trading_lab.analytics.equity import (
    calculate_gross_mark_to_market_equity,
    calculate_net_mark_to_market_equity,
)
from trading_lab.backtest.pipeline import run_backtest_pipeline


def chronological_split(
    candles: pd.DataFrame,
    train_fraction: float = 0.70,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return independent IS/OOS copies at a chronological row-count boundary.

    Default to 70/30; floor the IS row count. Require at least two rows,
    strictly increasing datetime timestamps, and a finite real fraction in
    (0, 1) yielding two non-empty sides. Never sort, shuffle, or reset indices;
    preserve all columns, dtypes, timezone, and original index labels.
    """
    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not candles.columns.is_unique:
        raise ValueError("Candle column names must be unique.")
    if "timestamp" not in candles.columns:
        raise ValueError("candles missing required timestamp column.")
    timestamps = candles["timestamp"]
    if not pd.api.types.is_datetime64_any_dtype(timestamps.dtype):
        raise ValueError("timestamp must be a pandas datetime column.")
    if timestamps.isna().any():
        raise ValueError("Timestamps must not be missing.")
    if not timestamps.is_unique or not timestamps.is_monotonic_increasing:
        raise ValueError("Timestamps must be unique and strictly increasing.")
    if len(candles) < 2:
        raise ValueError("candles must contain at least two rows.")

    message = "train_fraction must be a finite real scalar strictly between 0 and 1."
    if isinstance(train_fraction, bool) or not isinstance(train_fraction, Real):
        raise ValueError(message)
    try:
        fraction = float(train_fraction)
    except (ValueError, OverflowError) as error:
        raise ValueError(message) from error
    if not isfinite(fraction) or not 0 < train_fraction < 1:
        raise ValueError(message)
    split_index = int(len(candles) * fraction)
    if split_index == 0 or split_index == len(candles):
        raise ValueError("train_fraction must produce non-empty IS and OOS segments.")
    return (
        candles.iloc[:split_index].copy(deep=True),
        candles.iloc[split_index:].copy(deep=True),
    )


def evaluate_strategy_segment(
    candles: pd.DataFrame,
    strategy_generator,
    *,
    candle_interval,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
) -> dict:
    """Evaluate one self-contained cold-start segment through existing APIs.

    Invoke a Decision-010 strategy generator on a segment-only independent
    copy, with its normal initialization inside that segment. Reuse the
    generic backtest and GROSS/NET reserve-aware equity; return their canonical
    frames without summary analytics or terminal liquidation. Delegate their
    validation and propagate errors; preserve candles and the kwargs mapping.
    """
    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not callable(strategy_generator):
        raise ValueError("strategy_generator must be callable.")
    if strategy_kwargs is not None and not isinstance(strategy_kwargs, Mapping):
        raise ValueError("strategy_kwargs must be a mapping or None.")
    kwargs = {} if strategy_kwargs is None else dict(strategy_kwargs)
    if any(not isinstance(key, str) for key in kwargs):
        raise ValueError("strategy_kwargs keys must be strings.")

    strategy_output = strategy_generator(candles.copy(deep=True), **kwargs)
    pipeline = run_backtest_pipeline(
        candles,
        strategy_output,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        position_fraction=position_fraction,
    )
    gross_equity = calculate_gross_mark_to_market_equity(
        candles, pipeline["gross_results"], candle_interval, initial_capital,
    )
    net_equity = calculate_net_mark_to_market_equity(
        candles, pipeline["net_results"], candle_interval, initial_capital,
    )
    return {
        # Detach even a generator output that aliases a caller-owned frame.
        "strategy_output": strategy_output.copy(deep=True),
        "execution": pipeline["execution"],
        "trades": pipeline["trades"],
        "gross_results": pipeline["gross_results"],
        "net_results": pipeline["net_results"],
        "gross_equity": gross_equity,
        "net_equity": net_equity,
    }


def evaluate_train_test_split(
    candles: pd.DataFrame,
    strategy_generator,
    *,
    candle_interval,
    train_fraction: float = 0.70,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
) -> dict:
    """Evaluate independent chronological IS/OOS cold starts with equal settings.

    Each segment uses the same configured initial capital and strategy/cost/
    sizing assumptions. Carry no capital, positions, signals, or trades across
    the split. Return boundary metadata and the two segment results, without
    source candles or a continuous stitched portfolio.
    """
    in_sample, out_of_sample = chronological_split(candles, train_fraction)
    parameters = dict(
        candle_interval=candle_interval,
        strategy_kwargs=strategy_kwargs,
        initial_capital=initial_capital,
        fee_rate=fee_rate,
        slippage_rate=slippage_rate,
        position_fraction=position_fraction,
    )
    in_sample_result = evaluate_strategy_segment(in_sample, strategy_generator, **parameters)
    out_of_sample_result = evaluate_strategy_segment(out_of_sample, strategy_generator, **parameters)
    return {
        "split_index": len(in_sample),
        "split_timestamp": out_of_sample["timestamp"].iloc[0],
        "in_sample": in_sample_result,
        "out_of_sample": out_of_sample_result,
    }
