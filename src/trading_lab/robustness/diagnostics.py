"""Descriptive tables from precomputed, independent robustness evaluations."""

from collections.abc import Mapping
from datetime import datetime
from numbers import Integral

import numpy as np
import pandas as pd

from trading_lab.analytics.portfolio_drawdown import (
    summarize_gross_portfolio_drawdown,
    summarize_net_portfolio_drawdown,
)
from trading_lab.analytics.risk_adjusted import summarize_risk_adjusted_performance
from trading_lab.analytics.trade_time import summarize_trade_time_metrics


_SEGMENT_KEYS = (
    "strategy_output", "execution", "trades", "gross_results", "net_results",
    "gross_equity", "net_equity",
)
_METRICS = (
    "trade_count", "closed_trade_count", "exposure_ratio", "initial_equity",
    "gross_final_equity", "net_final_equity", "gross_total_return", "net_total_return",
    "gross_max_portfolio_drawdown", "net_max_portfolio_drawdown",
    "gross_sharpe", "gross_sortino", "net_sharpe", "net_sortino",
)
_COMPARABLE = tuple(name for name in _METRICS if name != "initial_equity")
_COUNTS = ("trade_count", "closed_trade_count")
_METADATA = (
    "window_id", "train_rows", "test_rows", "train_start_timestamp",
    "train_last_timestamp", "test_start_timestamp", "test_last_timestamp",
)


def _require_mapping(value, keys, label):
    if not isinstance(value, Mapping) or any(key not in value for key in keys):
        raise ValueError(f"{label} must be a mapping containing the canonical fields.")


def _require_integer(value, label, minimum=1):
    if (
        not isinstance(value, Integral) or isinstance(value, (bool, np.bool_))
        or not minimum <= int(value) <= np.iinfo(np.int64).max
    ):
        raise ValueError(f"{label} must be an int64-representable integer >= {minimum}.")


def _segment_metrics(segment, risk_kwargs):
    """Delegate financial validation/calculations; retain final OPEN marks."""
    _require_mapping(segment, _SEGMENT_KEYS, "segment")
    if any(not isinstance(segment[key], pd.DataFrame) for key in _SEGMENT_KEYS):
        raise ValueError("Canonical segment fields must be pandas DataFrames.")
    trades = segment["trades"]
    gross, net = segment["gross_equity"], segment["net_equity"]
    gross_dd = summarize_gross_portfolio_drawdown(gross).iloc[0]
    net_dd = summarize_net_portfolio_drawdown(net).iloc[0]
    gross_initial, net_initial = gross["equity"].iloc[0], net["equity"].iloc[0]
    if gross_initial != net_initial:
        raise ValueError("GROSS and NET initial equity must match exactly.")
    initial = float(gross_initial)
    gross_final, net_final = float(gross["equity"].iloc[-1]), float(net["equity"].iloc[-1])
    time = summarize_trade_time_metrics(
        trades, gross["valuation_time"].iloc[0], gross["valuation_time"].iloc[-1],
    ).iloc[0]
    gross_risk = summarize_risk_adjusted_performance(gross, **risk_kwargs).iloc[0]
    net_risk = summarize_risk_adjusted_performance(net, **risk_kwargs).iloc[0]
    return {
        "trade_count": len(trades),
        "closed_trade_count": int(trades["status"].eq("CLOSED").sum()),
        "exposure_ratio": time["exposure_ratio"],
        "initial_equity": initial,
        "gross_final_equity": gross_final,
        "net_final_equity": net_final,
        "gross_total_return": gross_final / initial - 1,
        "net_total_return": net_final / initial - 1,
        "gross_max_portfolio_drawdown": gross_dd["max_portfolio_drawdown"],
        "net_max_portfolio_drawdown": net_dd["max_portfolio_drawdown"],
        "gross_sharpe": gross_risk["sharpe_ratio"],
        "gross_sortino": gross_risk["sortino_ratio"],
        "net_sharpe": net_risk["sharpe_ratio"],
        "net_sortino": net_risk["sortino_ratio"],
    }


def summarize_train_test_diagnostics(
    train_test_result,
    *,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict:
    """Summarize precomputed independent IS/OOS results through existing analytics.

    Report neutral OOS-minus-IS changes without rerunning a strategy/backtest
    or classifying robustness. Preserve inputs and undefined analytics.
    """
    _require_mapping(
        train_test_result, ("split_index", "split_timestamp", "in_sample", "out_of_sample"),
        "train_test_result",
    )
    _require_integer(train_test_result["split_index"], "split_index")
    stamp = train_test_result["split_timestamp"]
    if not isinstance(stamp, (datetime, np.datetime64)) or pd.isna(stamp):
        raise ValueError("split_timestamp must be a non-missing datetime scalar.")
    risk_kwargs = dict(
        periods_per_year=periods_per_year,
        risk_free_return_per_period=risk_free_return_per_period,
        minimum_acceptable_return_per_period=minimum_acceptable_return_per_period,
    )
    rows = [
        {"segment": label, **_segment_metrics(train_test_result[key], risk_kwargs)}
        for label, key in (("IN_SAMPLE", "in_sample"), ("OUT_OF_SAMPLE", "out_of_sample"))
    ]
    metrics = pd.DataFrame(rows, columns=("segment", *_METRICS))
    for name in _METRICS:
        metrics[name] = metrics[name].astype("int64" if name in _COUNTS else "float64")
    comparison = pd.DataFrame([
        [name, float(rows[0][name]), float(rows[1][name]),
         float(rows[1][name]) - float(rows[0][name])]
        for name in _COMPARABLE
    ], columns=("metric", "in_sample_value", "out_of_sample_value", "oos_minus_is"))
    return {
        "split_index": train_test_result["split_index"],
        "split_timestamp": stamp,
        "segment_metrics": metrics,
        "comparison": comparison,
    }


def summarize_walk_forward_diagnostics(
    walk_forward_result,
    *,
    periods_per_year: float = 8760.0,
    risk_free_return_per_period: float = 0.0,
    minimum_acceptable_return_per_period: float = 0.0,
) -> dict:
    """Describe precomputed independent walk-forward train/test windows.

    Return per-window metrics, neutral differences, and finite-only test-window
    statistics. Never compound/stitch windows, rerun research, or score/classify
    robustness. Preserve raw NaN/infinities and caller-owned objects.
    """
    _require_mapping(
        walk_forward_result, ("window_definitions", "unused_tail_rows", "windows"),
        "walk_forward_result",
    )
    definitions, windows = walk_forward_result["window_definitions"], walk_forward_result["windows"]
    if not isinstance(definitions, pd.DataFrame) or definitions.empty:
        raise ValueError("window_definitions must be a non-empty pandas DataFrame.")
    if not definitions.columns.is_unique or any(name not in definitions for name in _METADATA):
        raise ValueError("window_definitions must have unique columns and canonical metadata.")
    if not isinstance(windows, tuple) or len(windows) != len(definitions):
        raise ValueError("windows must be a tuple matching the number of definition rows.")
    _require_integer(walk_forward_result["unused_tail_rows"], "unused_tail_rows", minimum=0)
    for name in _METADATA[:3]:
        for value in definitions[name]:
            _require_integer(value, name)
    if not definitions["window_id"].is_unique:
        raise ValueError("window IDs must be unique.")
    for name in _METADATA[3:]:
        if not pd.api.types.is_datetime64_any_dtype(definitions[name].dtype) or definitions[name].isna().any():
            raise ValueError("Window timestamps must be non-missing datetime columns.")
    for window_id, window in zip(definitions["window_id"], windows):
        _require_mapping(window, ("window_id", "train", "test"), "window")
        _require_integer(window["window_id"], "window_id")
        if window["window_id"] != window_id:
            raise ValueError("Window IDs must reconcile exactly in supplied definition order.")

    risk_kwargs = dict(
        periods_per_year=periods_per_year,
        risk_free_return_per_period=risk_free_return_per_period,
        minimum_acceptable_return_per_period=minimum_acceptable_return_per_period,
    )
    metric_rows, comparison_rows = [], []
    for window in windows:
        train, test = (_segment_metrics(window[label], risk_kwargs) for label in ("train", "test"))
        metric_rows.append({
            **{f"train_{name}": train[name] for name in _METRICS},
            **{f"test_{name}": test[name] for name in _METRICS},
        })
        comparison_rows.extend([
            [window["window_id"], name, float(train[name]), float(test[name]),
             float(test[name]) - float(train[name])]
            for name in _COMPARABLE
        ])
    columns = [f"{prefix}_{name}" for prefix in ("train", "test") for name in _METRICS]
    metrics = pd.concat([
        definitions[list(_METADATA)].copy(deep=True).reset_index(drop=True),
        pd.DataFrame(metric_rows, columns=columns),
    ], axis=1)
    for name in _METADATA[:3]:
        metrics[name] = metrics[name].astype("int64")
    for prefix in ("train", "test"):
        for name in _METRICS:
            metrics[f"{prefix}_{name}"] = metrics[f"{prefix}_{name}"].astype(
                "int64" if name in _COUNTS else "float64",
            )
    comparison = pd.DataFrame(comparison_rows, columns=(
        "window_id", "metric", "train_value", "test_value", "test_minus_train",
    ))
    comparison["window_id"] = comparison["window_id"].astype("int64")
    summary_rows = []
    for name in _COMPARABLE:
        values = metrics[f"test_{name}"].to_numpy(dtype="float64", copy=True)
        finite = values[np.isfinite(values)]
        # These statistics describe separate evaluations, not a compounded
        # portfolio. Exclude non-finite values only here, never from raw tables.
        statistics = (
            [float(np.mean(finite)), float(np.median(finite)), float(np.min(finite)), float(np.max(finite))]
            if len(finite) else [float("nan")] * 4
        )
        summary_rows.append([name, len(finite), *statistics])
    summary = pd.DataFrame(summary_rows, columns=("metric", "finite_count", "mean", "median", "minimum", "maximum"))
    summary["finite_count"] = summary["finite_count"].astype("int64")
    return {
        "unused_tail_rows": walk_forward_result["unused_tail_rows"],
        "window_metrics": metrics,
        "window_comparison": comparison,
        "test_metric_summary": summary,
    }
