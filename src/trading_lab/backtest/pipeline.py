"""Compose strategy intent and next-open execution without financial fields."""

import pandas as pd

from trading_lab.backtest.execution import apply_next_open_execution
from trading_lab.backtest.strategy_validation import validate_strategy_output
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


def run_execution_pipeline(
    candles: pd.DataFrame,
    strategy_output: pd.DataFrame,
) -> pd.DataFrame:
    """Validate supplied strategy intent and return next-OPEN execution only.

    Decision 010 validation owns canonical fields, alignment, availability,
    and desired state. The existing execution helper owns continuous hourly
    timing, fill OPEN validation, executed state, and final-row no-fill rules.
    Candles need timestamp/open; no close, indicators, or warm-up are required.

    Return the helper's exact timestamp, open, signal, execution_time,
    execution_price, executed_position schema with its dtypes and index.
    Market OPEN always comes from candles. Only the validated strategy signal
    is transferred; arbitrary diagnostics stay in the separate strategy frame.
    Preserve both inputs and replace any candle signal only on a local copy.
    No strategy generation, trade ledger, or financial calculation occurs.
    """
    validated = validate_strategy_output(candles, strategy_output)

    # Keep market data authoritative, including when a strategy diagnostic is
    # also named open. Missing OPEN is left to the execution helper to reject.
    execution_input = candles.copy(deep=True)
    execution_input["signal"] = validated["signal"]
    execution = apply_next_open_execution(execution_input)

    _check_alignment(candles, execution, "Execution")
    if not execution["signal"].equals(validated["signal"]):
        raise ValueError("Execution output changed strategy signals.")
    if not execution["open"].equals(candles["open"]):
        raise ValueError("Execution output changed market OPEN values.")
    return execution


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
