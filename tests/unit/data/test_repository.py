"""Repository tests on moto: exact item shape per docs/DYNAMODB_DESIGN.md,
the three access patterns, pagination, duplicate protection — and the no-Scan
assertions (REQ-0011/0012 of the design doc)."""

import re
from decimal import Decimal
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from data.prediction_repository import PredictionRepository

REPO_ROOT = Path(__file__).resolve().parents[3]


def _record(
    prediction_id="01JTESTULID000000000000000",
    ts="2026-08-14T10:00:00Z",
    version="1.0.0+abc1234",
):
    return {
        "prediction_id": prediction_id,
        "churn_probability": 0.72,
        "churn_predicted": True,
        "threshold": 0.065,
        "model_version": version,
        "timestamp": ts,
        "features": {
            "tenure": 5,
            "MonthlyCharges": 85.7,
            "TotalCharges": None,
            "Contract": "Month-to-month",
        },
    }


@pytest.fixture
def repo(serving_env, predictions_table):
    """Repository on a moto-backed resource whose botocore event stream is
    recorded — the raw material for the no-Scan assertion."""
    import boto3

    recorded: list[str] = []
    resource = boto3.resource("dynamodb", region_name="us-east-1")
    resource.meta.client.meta.events.register(
        "provide-client-params.dynamodb.*",
        lambda params, model, **kwargs: recorded.append(model.name),
    )
    repository = PredictionRepository(resource=resource)
    repository.operations = recorded
    return repository


def test_item_shape_matches_the_design_doc(repo, predictions_table):
    repo.put_prediction(_record())
    item = predictions_table.get_item(Key={"PK": "PRED#01JTESTULID000000000000000", "SK": "META"})[
        "Item"
    ]
    assert item["SK"] == "META"
    assert item["entityType"] == "Prediction"
    assert item["modelVersion"] == "1.0.0+abc1234"
    assert item["churnProbability"] == Decimal("0.72")
    assert item["churnPredicted"] is True
    assert item["threshold"] == Decimal("0.065")
    assert item["features"]["MonthlyCharges"] == Decimal("85.7")
    assert item["features"]["TotalCharges"] is None
    assert item["GSI1PK"] == "MODEL#1.0.0+abc1234"
    assert item["GSI1SK"] == "TS#2026-08-14T10:00:00Z#01JTESTULID000000000000000"
    assert item["GSI2PK"] == "DAY#2026-08-14"
    assert item["createdAt"] == "2026-08-14T10:00:00Z"
    assert int(item["expiresAt"]) > 0  # TTL set (90 days)


def test_ap1_get_prediction(repo):
    repo.put_prediction(_record())
    item = repo.get_prediction("01JTESTULID000000000000000")
    assert item["predictionId"] == "01JTESTULID000000000000000"
    assert repo.get_prediction("01JNOSUCHID00000000000000") is None


def test_ap2_by_model_version_newest_first(repo):
    for i in (1, 2, 3):
        repo.put_prediction(
            _record(prediction_id=f"01JTESTULID00000000000000{i}", ts=f"2026-08-14T10:00:0{i}Z")
        )
    repo.put_prediction(_record(prediction_id="01JOTHERVERSION0000000001", version="2.0.0+def5678"))
    items, cursor = repo.list_by_model_version("1.0.0+abc1234")
    assert [i["GSI1SK"][-1] for i in items] == ["3", "2", "1"]  # newest first
    assert cursor is None


def test_ap3_by_day_with_pagination_roundtrip(repo):
    for i in (1, 2, 3):
        repo.put_prediction(
            _record(prediction_id=f"01JTESTULID00000000000000{i}", ts=f"2026-08-14T10:00:0{i}Z")
        )
    seen, cursor, pages = [], None, 0
    while True:
        items, cursor = repo.list_by_day("2026-08-14", limit=1, cursor=cursor)
        # GSI2 projects KEYS_ONLY + INCLUDE (see docs/DYNAMODB_DESIGN.md), so
        # the id comes from the projected table key, not predictionId
        seen += [i["PK"].removeprefix("PRED#") for i in items]
        pages += 1
        if cursor is None:
            break
    assert pages >= 3
    assert len(seen) == len(set(seen)) == 3  # every item exactly once


def test_duplicate_prediction_id_is_rejected(repo):
    repo.put_prediction(_record())
    with pytest.raises(ClientError) as excinfo:
        repo.put_prediction(_record())
    assert excinfo.value.response["Error"]["Code"] == "ConditionalCheckFailedException"


def test_no_scan_ever(repo):
    """Dynamic: exercise every repository operation and assert the botocore
    call log contains no Scan. Static: the word never appears in src/."""
    repo.put_prediction(_record())
    repo.get_prediction("01JTESTULID000000000000000")
    repo.list_by_model_version("1.0.0+abc1234")
    repo.list_by_day("2026-08-14")
    assert repo.operations  # the recorder actually saw traffic
    assert "Scan" not in repo.operations
    for path in (REPO_ROOT / "src").rglob("*.py"):
        assert not re.search(r"\.scan\s*\(", path.read_text(), re.IGNORECASE), path
