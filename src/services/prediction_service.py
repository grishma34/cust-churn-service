"""Prediction service (REQ-0008/0011/0013): validate → predict → decide → log.

No boto3 here — the repository and metrics emitter are injected, so this
module is unit-testable with fakes. The decision threshold and model version
come from the artifact metadata, never from constants (claude.md rule 3).
"""

from datetime import UTC, datetime
from typing import Any, Protocol

import numpy as np
from ulid import ULID

from shared.errors import ValidationError
from shared.logging import get_logger
from shared.schema import CATEGORICAL_DOMAINS, FEATURE_FIELDS, NUMERIC_FIELDS

logger = get_logger("prediction")

# TotalCharges is blank in the source data for tenure-0 customers, so the API
# accepts null there (imputed inside the Pipeline); all other numerics required.
_NULLABLE_FIELDS = {"TotalCharges"}


class Repository(Protocol):
    def put_prediction(self, record: dict[str, Any]) -> None: ...


class Emitter(Protocol):
    def emit(self, features, probability, predicted, model_version) -> None: ...


def _check_numeric(field: str, value: Any, issues: list[dict[str, str]]) -> None:
    if value is None:
        if field not in _NULLABLE_FIELDS:
            issues.append({"field": field, "issue": "must be a number"})
        return
    if isinstance(value, bool) or not isinstance(value, int | float):
        issues.append({"field": field, "issue": "must be a number"})
    elif value < 0:
        issues.append({"field": field, "issue": "must be >= 0"})


def _check_categorical(field: str, value: Any, issues: list[dict[str, str]]) -> None:
    domain = CATEGORICAL_DOMAINS[field]
    if isinstance(value, bool) or value not in domain:
        allowed = ", ".join(str(v) for v in domain)
        issues.append({"field": field, "issue": f"must be one of: {allowed}"})


def validate_features(payload: Any) -> dict[str, Any]:
    """REQ-0013: every problem reported at once; the model never sees
    unvalidated input."""
    if not isinstance(payload, dict):
        raise ValidationError([{"field": "body", "issue": "must be a JSON object"}])
    issues: list[dict[str, str]] = []
    for field in sorted(set(payload) - set(FEATURE_FIELDS)):
        issues.append({"field": field, "issue": "unknown field"})
    for field in FEATURE_FIELDS:
        if field not in payload:
            issues.append({"field": field, "issue": "required"})
        elif field in NUMERIC_FIELDS:
            _check_numeric(field, payload[field], issues)
        else:
            _check_categorical(field, payload[field], issues)
    if issues:
        raise ValidationError(issues)
    return {field: payload[field] for field in FEATURE_FIELDS}


def _to_row(features: dict[str, Any]) -> np.ndarray:
    """Assemble the positional object-array the Pipeline was fitted on —
    FEATURE_FIELDS order, no pandas (see training/features.py docstring)."""
    return np.array([[features[field] for field in FEATURE_FIELDS]], dtype=object)


class PredictionService:
    def __init__(self, artifact, repository: Repository, emitter: Emitter):
        self._artifact = artifact
        self._repository = repository
        self._emitter = emitter

    def predict(self, payload: Any) -> dict[str, Any]:
        features = validate_features(payload)
        probability = float(self._artifact.pipeline.predict_proba(_to_row(features))[:, 1][0])
        threshold = self._artifact.threshold
        predicted = probability >= threshold
        record = {
            "prediction_id": str(ULID()),
            "churn_probability": probability,
            "churn_predicted": predicted,
            "threshold": threshold,
            "model_version": self._artifact.model_version,
            "timestamp": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

        # Best-effort observability (REQ-0011/0014): an audit or metrics
        # failure is logged, never surfaced as a prediction failure.
        try:
            self._repository.put_prediction(record | {"features": features})
        except Exception:
            logger.exception("audit write failed", extra={"extra_fields": record})
        try:
            self._emitter.emit(features, probability, predicted, record["model_version"])
        except Exception:
            logger.exception("metrics emit failed")

        return record
