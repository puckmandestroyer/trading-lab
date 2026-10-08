"""Chronological, cold-start strategy research using the existing backtest."""

from trading_lab.robustness.evaluation import (
    chronological_split,
    evaluate_strategy_segment,
    evaluate_train_test_split,
)
from trading_lab.robustness.sensitivity import evaluate_parameter_sensitivity

# Keep the existing wildcard exports stable; import sensitivity explicitly.
__all__ = [
    "chronological_split",
    "evaluate_strategy_segment",
    "evaluate_train_test_split",
]
