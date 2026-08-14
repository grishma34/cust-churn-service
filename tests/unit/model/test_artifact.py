"""Artifact loader tests (REQ-0009/0012): loads the real fixture artifact,
fails loudly on every broken variant, caches per process."""

import json
import shutil

import joblib
import pytest

from model import artifact
from shared.errors import ArtifactError


def test_loads_the_fixture_artifact(artifact_dir):
    loaded = artifact.load_artifact(artifact_dir)
    assert loaded.model_version.startswith("1.0.0+")
    assert 0.0 < loaded.threshold < 1.0
    assert hasattr(loaded.pipeline, "predict_proba")


def test_missing_files_fail_loudly(tmp_path):
    with pytest.raises(ArtifactError, match="missing"):
        artifact.load_artifact(tmp_path)


def test_corrupt_model_fails_loudly(artifact_dir, tmp_path):
    broken = tmp_path / "broken"
    shutil.copytree(artifact_dir, broken)
    (broken / "model.joblib").write_bytes(b"this is not a pickle")
    with pytest.raises(ArtifactError, match="corrupt"):
        artifact.load_artifact(broken)


def test_metadata_missing_required_keys_fails_loudly(artifact_dir, tmp_path):
    broken = tmp_path / "broken"
    shutil.copytree(artifact_dir, broken)
    meta = json.loads((broken / "model_meta.json").read_text())
    del meta["threshold"]
    (broken / "model_meta.json").write_text(json.dumps(meta))
    with pytest.raises(ArtifactError, match="threshold"):
        artifact.load_artifact(broken)


def test_model_without_predict_proba_fails_loudly(artifact_dir, tmp_path):
    broken = tmp_path / "broken"
    shutil.copytree(artifact_dir, broken)
    joblib.dump({"not": "a model"}, broken / "model.joblib")
    with pytest.raises(ArtifactError, match="predict_proba"):
        artifact.load_artifact(broken)


def test_singleton_caches_until_reset(serving_env):
    first = artifact.get_artifact()
    assert artifact.get_artifact() is first
    artifact.reset()
    assert artifact.get_artifact() is not first
