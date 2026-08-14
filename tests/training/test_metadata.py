"""Artifact contract tests (REQ-0007): metadata shape, baselines, and an
artifact that round-trips without the training package."""

import hashlib
import json
import re

import joblib
import numpy as np
import pytest
from training.features import CATEGORICAL_COLUMNS, FEATURE_COLUMNS, NUMERIC_COLUMNS
from training.metadata import build_metadata, write_artifact

from tests.conftest import FIXTURE_CSV
from training import config, train

VERSION_PATTERN = r"^\d+\.\d+\.\d+\+[0-9a-f]{7,}$"


@pytest.fixture(scope="module")
def result():
    return train.run(FIXTURE_CSV)


@pytest.fixture(scope="module")
def meta(result):
    return build_metadata(result, result.threshold, result.test_metrics, FIXTURE_CSV)


def test_metadata_contract(meta):
    assert re.match(VERSION_PATTERN, meta["model_version"])
    assert meta["dataset"]["sha256"] == hashlib.sha256(FIXTURE_CSV.read_bytes()).hexdigest()
    assert meta["dataset"]["n_records"] == 60
    assert 0.0 < meta["threshold"] < 1.0
    assert meta["threshold_analytic_optimum"] == pytest.approx(
        config.COST_FALSE_POSITIVE / (config.COST_FALSE_POSITIVE + config.COST_FALSE_NEGATIVE)
    )
    assert meta["costs"] == {
        "false_positive": config.COST_FALSE_POSITIVE,
        "false_negative": config.COST_FALSE_NEGATIVE,
    }
    test_metrics = meta["metrics"]["test"]
    assert set(test_metrics["confusion_at_threshold"]) == {"tp", "fp", "fn", "tn"}
    n_test = round(meta["dataset"]["n_records"] * config.TEST_FRACTION)
    assert sum(test_metrics["confusion_at_threshold"].values()) == n_test


def test_baselines_cover_every_feature(meta):
    baselines = meta["baselines"]
    assert set(baselines) == set(FEATURE_COLUMNS)
    for name in NUMERIC_COLUMNS:
        b = baselines[name]
        assert b["type"] == "numeric"
        assert set(b) == {"type", "mean", "std", "quantiles", "missing_rate"}
        assert set(b["quantiles"]) == {"p10", "p25", "p50", "p75", "p90"}
    for name in CATEGORICAL_COLUMNS:
        freqs = baselines[name]["frequencies"]
        assert sum(freqs.values()) == pytest.approx(1.0)
        assert len(freqs) >= 1
    # the fixture deliberately contains blank TotalCharges rows
    assert baselines["TotalCharges"]["missing_rate"] > 0


def test_artifact_roundtrip_and_serving_shaped_predict(result, meta, tmp_path):
    model_path, meta_path = write_artifact(result.pipeline, meta, tmp_path)
    assert json.loads(meta_path.read_text())["model_version"] == meta["model_version"]

    loaded = joblib.load(model_path)
    raw_row = np.array(
        [[1, 85.7, None] + ["Male", 0] + ["No"] * 12 + ["Month-to-month", "Electronic check"]],
        dtype=object,
    )
    proba = loaded.predict_proba(raw_row)[:, 1]
    assert 0.0 <= proba[0] <= 1.0


def test_artifact_has_no_dependency_on_the_training_package(result, tmp_path):
    """The inference image cannot import `training` — if any custom class or
    function leaked into the Pipeline, its module path would be pickled into
    the artifact (claude.md rule 4 / features.py docstring)."""
    path = tmp_path / "model.joblib"
    joblib.dump(result.pipeline, path)
    payload = path.read_bytes()
    for module in (b"training.features", b"training.train", b"training.threshold"):
        assert module not in payload
