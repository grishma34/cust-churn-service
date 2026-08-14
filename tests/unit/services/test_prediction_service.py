"""Service behavior with fakes (no boto3, no moto): decision boundary from
metadata threshold, record contract, best-effort logging (REQ-0008/0011)."""

import re

import pytest

from services.prediction_service import PredictionService


class FakePipeline:
    def __init__(self, probability: float):
        self.probability = probability

    def predict_proba(self, rows):
        import numpy as np

        return np.array([[1 - self.probability, self.probability]] * len(rows))


class FakeArtifact:
    def __init__(self, probability: float, threshold: float = 0.10):
        self.pipeline = FakePipeline(probability)
        self.meta = {"model_version": "9.9.9+fake0000", "threshold": threshold}
        self.model_version = "9.9.9+fake0000"
        self.threshold = threshold


class RecordingRepo:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.records = []

    def put_prediction(self, record):
        if self.fail:
            raise RuntimeError("dynamo down")
        self.records.append(record)


class RecordingEmitter:
    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = []

    def emit(self, features, probability, predicted, model_version):
        if self.fail:
            raise RuntimeError("stdout on fire")
        self.calls.append((features, probability, predicted, model_version))


def _service(probability, threshold=0.10, repo=None, emitter=None):
    return PredictionService(
        FakeArtifact(probability, threshold), repo or RecordingRepo(), emitter or RecordingEmitter()
    )


@pytest.mark.parametrize(
    ("probability", "threshold", "expected"),
    [
        (0.099, 0.10, False),  # just below
        (0.100, 0.10, True),  # at the threshold: flag (>= per API_SPEC)
        (0.101, 0.10, True),  # just above
        (0.499, 0.50, False),  # threshold comes from metadata, not a constant
        (0.500, 0.50, True),
    ],
)
def test_decision_boundary_uses_metadata_threshold(valid_payload, probability, threshold, expected):
    result = _service(probability, threshold).predict(valid_payload)
    assert result["churn_predicted"] is expected
    assert result["threshold"] == threshold


def test_response_contract(valid_payload):
    result = _service(0.42).predict(valid_payload)
    assert set(result) == {
        "prediction_id",
        "churn_probability",
        "churn_predicted",
        "threshold",
        "model_version",
        "timestamp",
    }
    assert re.fullmatch(r"[0-9A-HJKMNP-TV-Z]{26}", result["prediction_id"])  # ULID
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", result["timestamp"])
    assert result["model_version"] == "9.9.9+fake0000"
    assert result["churn_probability"] == pytest.approx(0.42)


def test_audit_record_includes_features(valid_payload):
    repo = RecordingRepo()
    _service(0.42, repo=repo).predict(valid_payload)
    [record] = repo.records
    assert record["features"] == valid_payload
    assert record["model_version"] == "9.9.9+fake0000"


def test_repo_failure_does_not_fail_the_prediction(valid_payload):
    emitter = RecordingEmitter()
    result = _service(0.42, repo=RecordingRepo(fail=True), emitter=emitter).predict(valid_payload)
    assert result["churn_probability"] == pytest.approx(0.42)
    assert emitter.calls  # metrics still emitted after the audit failure


def test_emitter_failure_does_not_fail_the_prediction(valid_payload):
    repo = RecordingRepo()
    result = _service(0.42, repo=repo, emitter=RecordingEmitter(fail=True)).predict(valid_payload)
    assert result["churn_probability"] == pytest.approx(0.42)
    assert repo.records  # audit still written


def test_invalid_input_never_reaches_the_model(valid_payload):
    class ExplodingPipeline:
        def predict_proba(self, rows):
            raise AssertionError("model called on unvalidated input")

    artifact = FakeArtifact(0.5)
    artifact.pipeline = ExplodingPipeline()
    service = PredictionService(artifact, RecordingRepo(), RecordingEmitter())
    from shared.errors import ValidationError

    with pytest.raises(ValidationError):
        service.predict(valid_payload | {"Contract": "Fortnightly"})
