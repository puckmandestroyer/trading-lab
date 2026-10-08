"""Descriptive parameter-grid research through the existing IS/OOS engine."""

from collections.abc import Mapping, Sequence
from copy import deepcopy
from itertools import product

import pandas as pd

from trading_lab.analytics.portfolio_drawdown import (
    summarize_gross_portfolio_drawdown,
    summarize_net_portfolio_drawdown,
)
from trading_lab.analytics.risk_adjusted import summarize_risk_adjusted_performance
from trading_lab.analytics.trade_time import summarize_trade_time_metrics
from trading_lab.robustness.evaluation import evaluate_train_test_split


_SEGMENT_METRICS = (
    "trade_count", "closed_trade_count", "exposure_ratio",
    "gross_final_equity", "net_final_equity",
    "gross_max_portfolio_drawdown", "net_max_portfolio_drawdown",
    "gross_sharpe", "gross_sortino", "net_sharpe", "net_sortino",
)
_METRIC_COLUMNS = tuple(
    f"{prefix}_{metric}" for prefix in ("is", "oos") for metric in _SEGMENT_METRICS
)


def _validated_grid(parameter_grid, strategy_kwargs):
    if not isinstance(parameter_grid, Mapping) or not parameter_grid:
        raise ValueError("parameter_grid must be a non-empty mapping.")
    if strategy_kwargs is not None and not isinstance(strategy_kwargs, Mapping):
        raise ValueError("strategy_kwargs must be a mapping or None.")
    common_kwargs = {} if strategy_kwargs is None else dict(strategy_kwargs)
    if any(not isinstance(key, str) for key in common_kwargs):
        raise ValueError("strategy_kwargs keys must be strings.")

    names, candidates = [], []
    for name, values in parameter_grid.items():
        if not isinstance(name, str) or not name:
            raise ValueError("parameter_grid keys must be non-empty strings.")
        if name in _METRIC_COLUMNS:
            raise ValueError("Parameter names must not collide with fixed metric columns.")
        if name in common_kwargs:
            raise ValueError("parameter_grid and strategy_kwargs keys must not overlap.")
        if (
            isinstance(values, (str, bytes, Mapping))
            or not isinstance(values, Sequence)
            or len(values) == 0
        ):
            raise ValueError("Grid candidates must be non-empty ordered sequences.")
        names.append(name)
        candidates.append(tuple(values))
    return tuple(names), candidates, common_kwargs


def _segment_metrics(segment, risk_kwargs):
    """Extract existing summaries; keep the canonical OPEN-position marks."""
    trades = segment["trades"]
    gross, net = segment["gross_equity"], segment["net_equity"]
    time = summarize_trade_time_metrics(
        trades, gross["valuation_time"].iloc[0], gross["valuation_time"].iloc[-1],
    ).iloc[0]
    gross_drawdown = summarize_gross_portfolio_drawdown(gross).iloc[0]
    net_drawdown = summarize_net_portfolio_drawdown(net).iloc[0]
    gross_risk = summarize_risk_adjusted_performance(gross, **risk_kwargs).iloc[0]
    net_risk = summarize_risk_adjusted_performance(net, **risk_kwargs).iloc[0]
    return {
        "trade_count": len(trades),
        "closed_trade_count": int(trades["status"].eq("CLOSED").sum()),
        "exposure_ratio": time["exposure_ratio"],
        "gross_final_equity": gross["equity"].iloc[-1],
        "net_final_equity": net["equity"].iloc[-1],
        "gross_max_portfolio_drawdown": gross_drawdown["max_portfolio_drawdown"],
        "net_max_portfolio_drawdown": net_drawdown["max_portfolio_drawdown"],
        "gross_sharpe": gross_risk["sharpe_ratio"],
        "gross_sortino": gross_risk["sortino_ratio"],
        "net_sharpe": net_risk["sharpe_ratio"],
        "net_sortino": net_risk["sortino_ratio"],
    }


def evaluate_parameter_sensitivity(
    candles: pd.DataFrame,
    strategy_generator,
    parameter_grid,
    *,
    candle_interval,
    train_fraction: float = 0.70,
    strategy_kwargs=None,
    initial_capital: float = 10_000.0,
    fee_rate: float = 0.0,
    slippage_rate: float = 0.0,
    position_fraction=1.0,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict:
    """Evaluate a predefined deterministic Cartesian grid in supplied order.

    Reuse independent cold-start IS/OOS evaluation and existing descriptive
    analytics. Preserve undefined analytics values and inputs. Do not rank,
    select, or optimize parameters; strategy validation/errors propagate.
    """
    names, candidates, common_kwargs = _validated_grid(parameter_grid, strategy_kwargs)
    risk_kwargs = dict(
        periods_per_year=periods_per_year,
        risk_free_return_per_period=risk_free_return_per_period,
        minimum_acceptable_return_per_period=minimum_acceptable_return_per_period,
    )
    rows = []
    split_index, split_timestamp = None, None
    for values in product(*candidates):
        parameters = dict(zip(names, values))
        # A strategy may mutate mutable keyword values; isolate each run from
        # the caller's grid/common settings and from later combinations.
        combined_kwargs = deepcopy({**common_kwargs, **parameters})
        evaluation = evaluate_train_test_split(
            candles, strategy_generator,
            candle_interval=candle_interval, train_fraction=train_fraction,
            strategy_kwargs=combined_kwargs, initial_capital=initial_capital,
            fee_rate=fee_rate, slippage_rate=slippage_rate,
            position_fraction=position_fraction,
        )
        if split_index is None:
            split_index = evaluation["split_index"]
            split_timestamp = evaluation["split_timestamp"]
        elif (
            evaluation["split_index"] != split_index
            or evaluation["split_timestamp"] != split_timestamp
        ):
            raise RuntimeError("Parameter combinations returned inconsistent split metadata.")

        row = parameters.copy()
        for prefix, key in (("is", "in_sample"), ("oos", "out_of_sample")):
            metrics = _segment_metrics(evaluation[key], risk_kwargs)
            row.update({f"{prefix}_{name}": value for name, value in metrics.items()})
        rows.append(row)

    results = pd.DataFrame(rows, columns=[*names, *_METRIC_COLUMNS])
    # Explicit metric dtypes also preserve NaN and signed infinities. Leave
    # strategy parameter columns to pandas' ordinary scalar inference.
    for column in _METRIC_COLUMNS:
        dtype = "int64" if column.endswith("trade_count") else "float64"
        results[column] = results[column].astype(dtype)
    return {
        "split_index": split_index,
        "split_timestamp": split_timestamp,
        "parameter_names": names,
        "results": results,
    }
