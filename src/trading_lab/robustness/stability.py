"""Local variation diagnostics on an existing two-dimensional research grid."""

from collections.abc import Mapping

import numpy as np
import pandas as pd


_DIAGNOSTICS = (
    "metric_value", "neighbor_count", "finite_neighbor_count",
    "neighbor_mean", "neighbor_std", "neighbor_min", "neighbor_max",
    "mean_absolute_delta", "max_absolute_delta",
    "local_min", "local_max", "local_range",
)


def _validated_surface(sensitivity_result, metric):
    required = ("split_index", "split_timestamp", "parameter_names", "results")
    if not isinstance(sensitivity_result, Mapping) or any(
        key not in sensitivity_result for key in required
    ):
        raise ValueError("sensitivity_result must be a mapping containing the canonical fields.")
    names = sensitivity_result["parameter_names"]
    if (
        not isinstance(names, tuple) or len(names) != 2
        or any(not isinstance(name, str) or not name for name in names)
        or names[0] == names[1]
    ):
        raise ValueError("parameter_names must be a tuple of two distinct non-empty strings.")
    if any(name in _DIAGNOSTICS for name in names):
        raise ValueError("Parameter names must not collide with diagnostic columns.")
    results = sensitivity_result["results"]
    if not isinstance(results, pd.DataFrame) or results.empty:
        raise ValueError("results must be a non-empty pandas DataFrame.")
    if not results.columns.is_unique:
        raise ValueError("results column names must be unique.")
    if not isinstance(results.index, pd.RangeIndex) or not results.index.equals(pd.RangeIndex(len(results))):
        raise ValueError("results must use RangeIndex 0..N-1.")
    if any(name not in results for name in names):
        raise ValueError("results must contain both parameter columns.")
    if not isinstance(metric, str) or not metric or metric not in results or metric in names:
        raise ValueError("metric must name an existing non-parameter numeric column.")
    dtype = results[metric].dtype
    if (
        not pd.api.types.is_numeric_dtype(dtype)
        or pd.api.types.is_bool_dtype(dtype)
        or pd.api.types.is_complex_dtype(dtype)
    ):
        raise ValueError("metric must have a real numeric dtype.")

    levels, codes = {}, []
    for name in names:
        try:
            positions, labels = pd.factorize(results[name], sort=False)
        except TypeError as error:
            raise ValueError("Parameter values must be hashable labels.") from error
        if (positions < 0).any():
            raise ValueError("Parameter labels must not be missing.")
        levels[name] = tuple(labels)
        codes.append(positions)
    pairs = list(zip(*codes))
    if len(set(pairs)) != len(pairs):
        raise ValueError("Duplicate parameter pairs are not allowed.")
    if len(results) != len(levels[names[0]]) * len(levels[names[1]]):
        raise ValueError("results must form a complete rectangular Cartesian grid.")

    surface = results[[*names, metric]].copy(deep=True).reset_index(drop=True)
    values = results[metric].to_numpy(dtype="float64", na_value=np.nan, copy=True)
    return names, levels, pairs, surface, values


def _local_diagnostics(center, neighbors):
    finite = neighbors[np.isfinite(neighbors)]
    count = len(finite)
    nan = float("nan")
    if count:
        mean = float(np.mean(finite))
        std = float(np.std(finite, ddof=1)) if count > 1 else nan
        minimum, maximum = float(np.min(finite)), float(np.max(finite))
    else:
        mean, std, minimum, maximum = nan, nan, nan, nan
    if np.isfinite(center) and count:
        deltas = np.abs(finite - center)
        mean_delta, max_delta = float(np.mean(deltas)), float(np.max(deltas))
    else:
        mean_delta, max_delta = nan, nan

    # Neighbor summaries exclude the center. The local region includes it
    # when finite, even when it is the region's only finite observation.
    local = np.append(finite, center) if np.isfinite(center) else finite
    if len(local):
        local_min, local_max = float(np.min(local)), float(np.max(local))
        local_range = local_max - local_min
    else:
        local_min, local_max, local_range = nan, nan, nan
    return {
        "metric_value": center,
        "neighbor_count": len(neighbors),
        "finite_neighbor_count": count,
        "neighbor_mean": mean,
        "neighbor_std": std,
        "neighbor_min": minimum,
        "neighbor_max": maximum,
        "mean_absolute_delta": mean_delta,
        "max_absolute_delta": max_delta,
        "local_min": local_min,
        "local_max": local_max,
        "local_range": local_range,
    }


def analyze_parameter_stability(sensitivity_result, metric: str) -> dict:
    """Analyze local variation in an existing two-parameter sensitivity result.

    Use radius-one Moore adjacency in supplied level order, preserving surface
    values and row order. Exclude non-finite values only from finite local
    statistics. Return descriptive diagnostics without ranking or classifying
    parameters; never rerun a backtest.
    """
    names, levels, pairs, surface, values = _validated_surface(sensitivity_result, metric)
    cells = dict(zip(pairs, values))
    height, width = len(levels[names[0]]), len(levels[names[1]])
    rows = []
    for (i, j), center in zip(pairs, values):
        # Clip at the grid boundary; adjacency uses positions, not distances
        # between numeric labels. Diagonals count and the center does not.
        neighbors = np.asarray([
            cells[(row, column)]
            for row in range(max(0, i - 1), min(height, i + 2))
            for column in range(max(0, j - 1), min(width, j + 2))
            if (row, column) != (i, j)
        ], dtype="float64")
        rows.append(_local_diagnostics(center, neighbors))

    diagnostics = pd.DataFrame(rows, columns=_DIAGNOSTICS)
    for column in _DIAGNOSTICS:
        dtype = "int64" if column in ("neighbor_count", "finite_neighbor_count") else "float64"
        diagnostics[column] = diagnostics[column].astype(dtype)
    local_stability = pd.concat([surface[list(names)].copy(deep=True), diagnostics], axis=1)
    return {
        "parameter_names": names,
        "metric": metric,
        "parameter_levels": levels,
        "surface": surface,
        "local_stability": local_stability,
    }
