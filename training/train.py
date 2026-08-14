"""Training entrypoint (REQ-0001/0002/0004): load → split → select → calibrate.

Phase 1 scope: fit and honestly evaluate. The test split is created here but
NOT evaluated — Phase 2 (threshold + artifact) touches it exactly once.

Usage: python -m training.train --data data/telco.csv
"""

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

from training import config
from training.features import (
    FEATURE_COLUMNS,
    POSITIVE_LABEL,
    TARGET_COLUMN,
    build_pipeline,
)


def candidate_estimators() -> dict[str, object]:
    return {
        "logistic_regression": LogisticRegression(max_iter=2000, random_state=config.RANDOM_SEED),
        "hist_gradient_boosting": HistGradientBoostingClassifier(random_state=config.RANDOM_SEED),
    }


def load_dataset(csv_path: Path) -> tuple[np.ndarray, np.ndarray]:
    """CSV → (X, y). X is an object-dtype array in FEATURE_COLUMNS order — the
    same shape serving assembles from JSON (see training/features.py docstring).

    The blank-string TotalCharges quirk is parsed to NaN here, at the I/O
    boundary (serving's equivalent is JSON `null`); the IMPUTATION of those
    NaNs is the Pipeline's job, so train and serve share it (REQ-0005).
    """
    df = pd.read_csv(csv_path, na_values=[" "])
    X = df[list(FEATURE_COLUMNS)].to_numpy(dtype=object)
    y = (df[TARGET_COLUMN] == POSITIVE_LABEL).to_numpy(dtype=int)
    return X, y


@dataclass
class Splits:
    X_train: np.ndarray
    X_val: np.ndarray
    X_test: np.ndarray
    y_train: np.ndarray
    y_val: np.ndarray
    y_test: np.ndarray


def split_dataset(X: np.ndarray, y: np.ndarray) -> Splits:
    """Stratified 60/20/20; seeds and fractions from config only (REQ-0006:
    the test split exists from the start and nothing is ever fitted on it)."""
    X_trainval, X_test, y_trainval, y_test = train_test_split(
        X,
        y,
        test_size=config.TEST_FRACTION,
        stratify=y,
        random_state=config.RANDOM_SEED,
    )
    val_share = config.VAL_FRACTION / (1.0 - config.TEST_FRACTION)
    X_train, X_val, y_train, y_val = train_test_split(
        X_trainval,
        y_trainval,
        test_size=val_share,
        stratify=y_trainval,
        random_state=config.RANDOM_SEED,
    )
    return Splits(X_train, X_val, X_test, y_train, y_val, y_test)


def select_model(X_train: np.ndarray, y_train: np.ndarray) -> tuple[str, dict[str, float]]:
    """Stratified K-fold CV ROC AUC per candidate, on the TRAINING split only.
    cross_val_score clones the whole Pipeline per fold, so preprocessing is
    re-fitted inside each fold — leakage-safe by construction (REQ-0002)."""
    cv = StratifiedKFold(n_splits=config.CV_FOLDS, shuffle=True, random_state=config.RANDOM_SEED)
    cv_auc: dict[str, float] = {}
    for name, estimator in candidate_estimators().items():
        scores = cross_val_score(
            build_pipeline(estimator), X_train, y_train, scoring="roc_auc", cv=cv
        )
        cv_auc[name] = float(scores.mean())
    winner = max(cv_auc, key=lambda name: cv_auc[name])
    return winner, cv_auc


def expected_calibration_error(
    y_true: np.ndarray, proba: np.ndarray, n_bins: int = config.CALIBRATION_BINS
) -> float:
    """Weighted mean |observed churn rate − mean predicted probability| over
    equal-width probability bins."""
    bins = np.clip((proba * n_bins).astype(int), 0, n_bins - 1)
    ece = 0.0
    for b in range(n_bins):
        mask = bins == b
        if mask.any():
            ece += (mask.mean()) * abs(y_true[mask].mean() - proba[mask].mean())
    return float(ece)


@dataclass
class TrainingResult:
    pipeline: Pipeline
    model_name: str
    calibrated: bool
    cv_auc: dict[str, float]
    val_metrics: dict[str, float]
    splits: Splits = field(repr=False)

    def summary(self) -> dict:
        return {
            "model": self.model_name,
            "calibrated": self.calibrated,
            "cv_roc_auc": self.cv_auc,
            "validation": self.val_metrics,
            "split_sizes": {
                "train": len(self.splits.y_train),
                "val": len(self.splits.y_val),
                "test": len(self.splits.y_test),
            },
        }


def run(csv_path: Path) -> TrainingResult:
    X, y = load_dataset(csv_path)
    splits = split_dataset(X, y)

    winner, cv_auc = select_model(splits.X_train, splits.y_train)
    pipeline = build_pipeline(candidate_estimators()[winner])
    pipeline.fit(splits.X_train, splits.y_train)

    # Calibration gate (REQ-0004): ECE measured on validation; the calibrator
    # itself is fitted via internal CV on the TRAINING split only.
    proba_val = pipeline.predict_proba(splits.X_val)[:, 1]
    ece = expected_calibration_error(splits.y_val, proba_val)
    calibrated = ece > config.CALIBRATION_MAX_ECE
    if calibrated:
        pipeline = build_pipeline(
            CalibratedClassifierCV(
                candidate_estimators()[winner], method="isotonic", cv=config.CV_FOLDS
            )
        )
        pipeline.fit(splits.X_train, splits.y_train)
        proba_val = pipeline.predict_proba(splits.X_val)[:, 1]
        ece = expected_calibration_error(splits.y_val, proba_val)

    val_metrics = {
        "roc_auc": float(roc_auc_score(splits.y_val, proba_val)),
        "brier": float(brier_score_loss(splits.y_val, proba_val)),
        "ece": ece,
    }
    return TrainingResult(pipeline, winner, calibrated, cv_auc, val_metrics, splits)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="path to the Telco CSV")
    args = parser.parse_args(argv)
    result = run(args.data)
    print(json.dumps(result.summary(), indent=2))


if __name__ == "__main__":
    main()
