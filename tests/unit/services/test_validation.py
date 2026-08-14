"""Validation matrix (REQ-0013), parametrized per docs/TEST_STRATEGY.md."""

import pytest

from services.prediction_service import validate_features
from shared.errors import ValidationError
from shared.schema import FEATURE_FIELDS


def _issues_for(payload) -> dict[str, str]:
    with pytest.raises(ValidationError) as excinfo:
        validate_features(payload)
    return {d["field"]: d["issue"] for d in excinfo.value.details}


def test_valid_payload_passes_and_is_ordered(valid_payload):
    features = validate_features(valid_payload)
    assert list(features) == list(FEATURE_FIELDS)


def test_null_totalcharges_is_allowed(valid_payload):
    features = validate_features(valid_payload | {"TotalCharges": None})
    assert features["TotalCharges"] is None


@pytest.mark.parametrize("field", FEATURE_FIELDS)
def test_each_missing_field_is_reported(valid_payload, field):
    payload = {k: v for k, v in valid_payload.items() if k != field}
    assert _issues_for(payload)[field] == "required"


@pytest.mark.parametrize(
    ("field", "value", "issue_fragment"),
    [
        ("Contract", "Fortnightly", "must be one of"),
        ("gender", 3, "must be one of"),
        ("SeniorCitizen", 2, "must be one of"),
        ("SeniorCitizen", True, "must be one of"),  # bool is not the int 1 here
        ("tenure", -1, ">= 0"),
        ("tenure", None, "must be a number"),
        ("tenure", "five", "must be a number"),
        ("MonthlyCharges", True, "must be a number"),
        ("TotalCharges", "lots", "must be a number"),
    ],
)
def test_bad_values_are_reported(valid_payload, field, value, issue_fragment):
    assert issue_fragment in _issues_for(valid_payload | {field: value})[field]


def test_unknown_field_rejected(valid_payload):
    assert _issues_for(valid_payload | {"customerID": "x"})["customerID"] == "unknown field"


def test_all_problems_reported_at_once(valid_payload):
    payload = dict(valid_payload)
    del payload["gender"]
    payload["tenure"] = -3
    payload["extra"] = 1
    issues = _issues_for(payload)
    assert set(issues) == {"gender", "tenure", "extra"}


def test_non_object_body_rejected():
    assert _issues_for(["not", "a", "dict"])["body"] == "must be a JSON object"
