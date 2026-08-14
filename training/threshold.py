"""Cost-based decision threshold (REQ-0003).

The threshold is not a modeling choice, it's a business choice: sweep t over
the VALIDATION split and minimize C_FP·FP(t) + C_FN·FN(t). With calibrated
probabilities the analytic optimum is C_FP/(C_FP+C_FN); the empirical curve is
kept for the cost plot and recorded alongside the choice.
"""

from dataclasses import dataclass

import numpy as np

from training import config


@dataclass(frozen=True)
class ThresholdResult:
    threshold: float
    expected_cost: float
    cost_per_customer: float
    analytic_optimum: float
    grid: tuple[float, ...]
    costs: tuple[float, ...]


def expected_cost(
    y_true: np.ndarray,
    proba: np.ndarray,
    threshold: float,
    cost_fp: float,
    cost_fn: float,
) -> float:
    """Total misclassification cost of deciding `proba >= threshold`."""
    y = np.asarray(y_true)
    predicted = np.asarray(proba) >= threshold
    false_positives = int(((y == 0) & predicted).sum())
    false_negatives = int(((y == 1) & ~predicted).sum())
    return cost_fp * false_positives + cost_fn * false_negatives


def select_threshold(
    y_true: np.ndarray,
    proba: np.ndarray,
    cost_fp: float = config.COST_FALSE_POSITIVE,
    cost_fn: float = config.COST_FALSE_NEGATIVE,
) -> ThresholdResult:
    y = np.asarray(y_true)
    if np.unique(y).size < 2:
        # A one-class validation split can't price both error types; a silent
        # 0.5 fallback here would be exactly the default this project rejects.
        raise ValueError("threshold selection requires both classes in the validation split")

    grid = np.round(np.arange(0.01, 0.9951, 0.005), 3)
    costs = np.array([expected_cost(y, proba, t, cost_fp, cost_fn) for t in grid])
    best = int(np.argmin(costs))  # deterministic: first minimum wins ties
    return ThresholdResult(
        threshold=float(grid[best]),
        expected_cost=float(costs[best]),
        cost_per_customer=float(costs[best] / y.size),
        analytic_optimum=cost_fp / (cost_fp + cost_fn),
        grid=tuple(grid.tolist()),
        costs=tuple(costs.tolist()),
    )
