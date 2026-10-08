"""Chronological, cold-start strategy research using the existing backtest."""

from trading_lab.robustness.evaluation import (
    chronological_split,
    evaluate_strategy_segment,
    evaluate_train_test_split,
)
from trading_lab.robustness.sensitivity import evaluate_parameter_sensitivity
from trading_lab.robustness.stability import analyze_parameter_stability
from trading_lab.robustness.walk_forward import (
    evaluate_expanding_walk_forward,
    generate_expanding_walk_forward_windows,
)

# Keep the existing wildcard exports stable; import research analyses explicitly.
__all__ = [
    "chronological_split",
    "evaluate_strategy_segment",
    "evaluate_train_test_split",
]
