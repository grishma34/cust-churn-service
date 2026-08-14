"""Threshold selection tests (REQ-0003): hand-checked cost math, a known
minimum, the analytic-optimum sanity check, and loud failure on degenerate
input (docs/TEST_STRATEGY.md)."""

import numpy as np
import pytest
from training.threshold import expected_cost, select_threshold

Y = np.array([0, 0, 1, 1])
P = np.array([0.2, 0.4, 0.6, 0.8])


def test_cost_math_by_hand():
    """4-cell confusion computed on paper: at t=0.5 both errors are zero; at
    t=0.3 one stayer (p=0.4) is flagged (1 FP); at t=0.7 one churner (p=0.6)
    is missed (1 FN)."""
    assert expected_cost(Y, P, 0.5, cost_fp=50, cost_fn=450) == 0
    assert expected_cost(Y, P, 0.3, cost_fp=50, cost_fn=450) == 50
    assert expected_cost(Y, P, 0.7, cost_fp=50, cost_fn=450) == 450
    # everyone flagged: 2 FP; no one flagged: 2 FN
    assert expected_cost(Y, P, 0.0, cost_fp=50, cost_fn=450) == 100
    assert expected_cost(Y, P, 1.0, cost_fp=50, cost_fn=450) == 900


def test_optimizer_finds_the_known_minimum():
    """Perfect separation: any t in (0.4, 0.6] costs zero — the sweep must
    land inside that window."""
    result = select_threshold(Y, P, cost_fp=50, cost_fn=450)
    assert 0.4 < result.threshold <= 0.6
    assert result.expected_cost == 0
    assert len(result.grid) == len(result.costs)


def test_calibrated_probabilities_land_near_the_analytic_optimum():
    """On a perfectly calibrated sample, the empirical sweep should agree with
    t* = C_FP/(C_FP+C_FN) = 0.10 — and be nowhere near the 0.5 default."""
    proba, y = [], []
    for p in np.linspace(0.025, 0.975, 39):
        block = 200
        positives = round(block * p)
        proba += [p] * block
        y += [1] * positives + [0] * (block - positives)
    result = select_threshold(np.array(y), np.array(proba), cost_fp=50, cost_fn=450)
    assert result.analytic_optimum == pytest.approx(0.10)
    assert abs(result.threshold - 0.10) <= 0.03
    assert result.threshold < 0.3  # far from the rejected 0.5 default


def test_one_class_validation_split_fails_loudly():
    with pytest.raises(ValueError, match="both classes"):
        select_threshold(np.zeros(10, dtype=int), np.linspace(0, 1, 10))
