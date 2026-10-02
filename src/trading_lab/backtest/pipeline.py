"""Compose EMA strategy intent and next-open execution without financial fields."""

import pandas as pd

from trading_lab.backtest.execution import apply_next_open_execution
from trading_lab.strategies.ema_trend import generate_ema_signals


def _check_alignment(candles: pd.DataFrame, result: pd.DataFrame, layer: str) -> None:
    """Reject changed rows before pandas could align them silently by index."""
    if len(result) != len(candles):
        raise ValueError(f"{layer} output alignment error: row count differs from input.")
    if not result.index.equals(candles.index):
        raise ValueError(f"{layer} output alignment error: index differs from input.")
    if not result["timestamp"].equals(candles["timestamp"]):
        raise ValueError(f"{layer} output alignment error: timestamps differ from input.")
    if not result["timestamp"].is_monotonic_increasing:
        raise ValueError(f"{layer} output alignment error: timestamps must be chronological.")


def run_ema_execution_pipeline(
    candles: pd.DataFrame,
    fast_span: int = 20,
    slow_span: int = 50,
    warmup_candles: int = 50,
) -> pd.DataFrame:
    """Combine independently generated strategy and execution outputs.

    Require timestamp, open, close; expect validated continuous hourly candles.
    Component functions validate prices, timestamps, parameters, and transitions.
    Do not sort, reset indexes, repair signals, load files, or modify input.

    Return exactly timestamp, open, close, ema_{fast_span}, ema_{slow_span},
    warmup_complete, bullish_cross, bearish_cross, signal, desired_position,
    signal_time, execution_time, execution_price, executed_position. Defaults
    retain ema_20/ema_50. Optional market-context columns are omitted.

    On row N, desired_position is intent after N completes; executed_position
    is state during N after any preceding signal fills at N's OPEN. N's own
    execution metadata describes its fill at N+1 OPEN. No signal is shifted here.
    A final-row signal has no fill. Appending its next candle may legitimately
    populate that signal row's execution metadata, without changing its intent
    or executed state during that row. No PnL or trade ledger is calculated.
    """
    if not isinstance(candles, pd.DataFrame):
        raise ValueError("candles must be a pandas DataFrame.")
    if not candles.columns.is_unique:
        raise ValueError("Input column names must be unique.")
    missing = [column for column in ("timestamp", "open", "close") if column not in candles.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}.")

    strategy_df = generate_ema_signals(candles, fast_span, slow_span, warmup_candles)
    _check_alignment(candles, strategy_df, "Strategy")

    execution_input = candles[["timestamp", "open"]].copy()
    execution_input["signal"] = strategy_df["signal"]
    execution_df = apply_next_open_execution(execution_input)
    _check_alignment(candles, execution_df, "Execution")
    if not execution_df["signal"].equals(strategy_df["signal"]):
        raise ValueError("Execution output changed strategy signals.")

    # Alignment is checked before assigning any columns; keep one signal column.
    result = strategy_df.copy()
    result.insert(1, "open", candles["open"])
    for column in ("execution_time", "execution_price", "executed_position"):
        result[column] = execution_df[column]
    return result
