"""Training entrypoint: load → split → select → calibrate → threshold →
one-shot test evaluation → package (REQ-0001/0002/0003/0004/0007).

The test split is evaluated exactly once, inside `evaluate_final` — a test
enforces that no other function touches it.

Usage: python -m training.train --data data/telco.csv [--out artifacts]
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
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    roc_auc_score,
    roc_curve,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.pipeline import Pipeline

from training import config, metadata, plots
from training.features import (
    FEATURE_COLUMNS,
    POSITIVE_LABEL,
    TARGET_COLUMN,
    build_pipeline,
)
from training.threshold import ThresholdResult, select_threshold


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


def evaluate_final(
    pipeline: Pipeline, threshold: float, splits: Splits
) -> tuple[dict, tuple[list[float], list[float]]]:
    """The ONLY function allowed to score the test split (REQ-0002); called
    once per training run, after every model/threshold decision is final."""
    proba = pipeline.predict_proba(splits.X_test)[:, 1]
    y = splits.y_test
    predicted = proba >= threshold
    confusion = {
        "tp": int(((y == 1) & predicted).sum()),
        "fp": int(((y == 0) & predicted).sum()),
        "fn": int(((y == 1) & ~predicted).sum()),
        "tn": int(((y == 0) & ~predicted).sum()),
    }
    cost = (
        config.COST_FALSE_POSITIVE * confusion["fp"] + config.COST_FALSE_NEGATIVE * confusion["fn"]
    )
    metrics = {
        "roc_auc": float(roc_auc_score(y, proba)),
        "pr_auc": float(average_precision_score(y, proba)),
        "confusion_at_threshold": confusion,
        "expected_cost_per_customer": float(cost / y.size),
    }
    fpr, tpr, _ = roc_curve(y, proba)
    return metrics, (fpr.tolist(), tpr.tolist())


@dataclass
class TrainingResult:
    pipeline: Pipeline
    model_name: str
    calibrated: bool
    cv_auc: dict[str, float]
    val_metrics: dict[str, float]
    threshold: ThresholdResult
    test_metrics: dict
    roc_points: tuple[list[float], list[float]] = field(repr=False)
    splits: Splits = field(repr=False)

    def summary(self) -> dict:
        return {
            "model": self.model_name,
            "calibrated": self.calibrated,
            "cv_roc_auc": self.cv_auc,
            "validation": self.val_metrics,
            "threshold": {
                "value": self.threshold.threshold,
                "analytic_optimum": self.threshold.analytic_optimum,
                "val_cost_per_customer": self.threshold.cost_per_customer,
            },
            "test": self.test_metrics,
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

    # Business threshold from validation (REQ-0003), then the single test
    # evaluation now that every decision is final.
    threshold = select_threshold(splits.y_val, proba_val)
    test_metrics, roc_points = evaluate_final(pipeline, threshold.threshold, splits)

    return TrainingResult(
        pipeline,
        winner,
        calibrated,
        cv_auc,
        val_metrics,
        threshold,
        test_metrics,
        roc_points,
        splits,
    )


def package(result: TrainingResult, data_path: Path, output_dir: Path) -> dict:
    """Write model.joblib + model_meta.json + plots (REQ-0007)."""
    meta = metadata.build_metadata(result, result.threshold, result.test_metrics, data_path)
    metadata.write_artifact(result.pipeline, meta, output_dir)
    plots.write_plots(result, result.threshold, result.roc_points, output_dir)
    return meta


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True, help="path to the Telco CSV")
    parser.add_argument(
        "--out", type=Path, default=Path("artifacts"), help="artifact output directory"
    )
    args = parser.parse_args(argv)
    result = run(args.data)
    meta = package(result, args.data, args.out)
    print(
        json.dumps(
            result.summary() | {"model_version": meta["model_version"], "out": str(args.out)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
