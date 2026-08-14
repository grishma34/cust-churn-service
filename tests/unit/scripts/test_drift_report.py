"""Drift-report math (REQ-0015): identical distributions score ~0, real shifts
cross the 0.2 flag. Pure functions only — no AWS (NFR-0002)."""

import numpy as np
from scripts.drift_report import build_report, categorical_psi, numeric_psi, psi

NUMERIC_BASELINE = {
    "type": "numeric",
    "mean": 30.0,
    "std": 20.0,
    "quantiles": {"p10": 5.0, "p25": 12.0, "p50": 29.0, "p75": 55.0, "p90": 69.0},
    "missing_rate": 0.0,
}
CATEGORICAL_BASELINE = {
    "type": "categorical",
    "frequencies": {"Month-to-month": 0.55, "One year": 0.21, "Two year": 0.24},
}


def test_psi_identical_is_near_zero():
    assert psi([0.1, 0.15, 0.25, 0.25, 0.15, 0.1], [0.1, 0.15, 0.25, 0.25, 0.15, 0.1]) < 1e-9


def test_numeric_matching_baseline_scores_low():
    rng = np.random.default_rng(7)
    # sample tenure-like values that roughly follow the baseline quantiles
    values = list(
        rng.choice([2, 8, 20, 40, 60, 72], p=[0.10, 0.15, 0.25, 0.25, 0.15, 0.10], size=2000)
    )
    assert numeric_psi(values, NUMERIC_BASELINE) < 0.05


def test_numeric_shift_is_flagged():
    # everyone suddenly a brand-new customer: mass collapses into the lowest bin
    assert numeric_psi([0, 1, 2, 3] * 100, NUMERIC_BASELINE) > 0.2


def test_categorical_matching_baseline_scores_low():
    counts = {"Month-to-month": 550, "One year": 210, "Two year": 240}
    assert categorical_psi(counts, CATEGORICAL_BASELINE) < 0.01


def test_categorical_shift_is_flagged():
    counts = {"Month-to-month": 990, "One year": 5, "Two year": 5}
    assert categorical_psi(counts, CATEGORICAL_BASELINE) > 0.2


def test_build_report_statuses_and_missing_data():
    baselines = {"tenure": NUMERIC_BASELINE, "Contract": CATEGORICAL_BASELINE, "gender": {
        "type": "categorical", "frequencies": {"Female": 0.5, "Male": 0.5}}}
    rows = [{"tenure": "1", "Contract": "Month-to-month"} for _ in range(50)]
    report = {r["feature"]: r for r in build_report(rows, baselines)}
    assert report["tenure"]["status"] == "DRIFT"  # all mass in one bin
    assert report["Contract"]["status"] == "DRIFT"  # single category
    assert report["gender"]["status"] == "no-data"  # never present in rows
    assert report["tenure"]["n"] == 50
