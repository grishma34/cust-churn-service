"""Artifact packaging (REQ-0007): model.joblib + model_meta.json.

model_meta.json is the contract between training and serving: the server
reads model_version and threshold from it (never hardcodes them, REQ-0010),
and the drift report (REQ-0015) compares live traffic against the baseline
distributions recorded here — computed on the TRAINING split, i.e. the data
the model actually saw.
"""

import hashlib
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np

from training import config
from training.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS

_QUANTILES = {"p10": 0.10, "p25": 0.25, "p50": 0.50, "p75": 0.75, "p90": 0.90}


def dataset_sha256(csv_path: Path) -> str:
    return hashlib.sha256(csv_path.read_bytes()).hexdigest()


def git_sha7() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short=7", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        )
        return out.stdout.strip()
    except subprocess.CalledProcessError, FileNotFoundError:
        return "nogit00"


def model_version() -> str:
    return f"{config.MODEL_SEMVER}+{git_sha7()}"


def _numeric_baseline(values: np.ndarray) -> dict[str, Any]:
    as_float = np.array([np.nan if v is None else float(v) for v in values])
    finite = as_float[~np.isnan(as_float)]
    return {
        "type": "numeric",
        "mean": float(finite.mean()),
        "std": float(finite.std()),
        "quantiles": {name: float(np.quantile(finite, q)) for name, q in _QUANTILES.items()},
        "missing_rate": float(np.isnan(as_float).mean()),
    }


def _categorical_baseline(values: np.ndarray) -> dict[str, Any]:
    labels, counts = np.unique([str(v) for v in values], return_counts=True)
    return {
        "type": "categorical",
        "frequencies": {
            label: float(count / values.size) for label, count in zip(labels, counts, strict=True)
        },
    }


def build_baselines(x_train: np.ndarray) -> dict[str, dict[str, Any]]:
    """Per-feature training-data distributions, keyed by feature name, in
    FEATURE_COLUMNS positional order (the array has no column labels)."""
    baselines = {}
    for position, name in enumerate(FEATURE_COLUMNS):
        column = x_train[:, position]
        if name in CATEGORICAL_COLUMNS:
            baselines[name] = _categorical_baseline(column)
        else:
            baselines[name] = _numeric_baseline(column)
    return baselines


def build_metadata(result, threshold_result, test_metrics: dict, data_path: Path) -> dict[str, Any]:
    return {
        "model_version": model_version(),
        "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "model": {"name": result.model_name, "calibrated": result.calibrated},
        "dataset": {
            "file": data_path.name,
            "sha256": dataset_sha256(data_path),
            "n_records": int(
                len(result.splits.y_train) + len(result.splits.y_val) + len(result.splits.y_test)
            ),
        },
        "threshold": threshold_result.threshold,
        "threshold_analytic_optimum": threshold_result.analytic_optimum,
        "costs": {
            "false_positive": config.COST_FALSE_POSITIVE,
            "false_negative": config.COST_FALSE_NEGATIVE,
        },
        "metrics": {
            "cv_roc_auc": result.cv_auc,
            "validation": result.val_metrics
            | {"cost_per_customer": threshold_result.cost_per_customer},
            "test": test_metrics,
        },
        "baselines": build_baselines(result.splits.X_train),
    }


def write_artifact(pipeline, metadata: dict[str, Any], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    model_path = output_dir / "model.joblib"
    meta_path = output_dir / "model_meta.json"
    joblib.dump(pipeline, model_path)
    meta_path.write_text(json.dumps(metadata, indent=2) + "\n")
    return model_path, meta_path
