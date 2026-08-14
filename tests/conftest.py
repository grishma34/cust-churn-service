"""Shared fixtures: Function URL event factory and the moto DynamoDB table.

Phase 3 adds the session-scoped fixture model artifact (a real tiny Pipeline
fitted on data/fixtures/telco_60.csv) — see docs/TEST_STRATEGY.md.
"""

import csv
import json
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CSV = REPO_ROOT / "data" / "fixtures" / "telco_60.csv"

TABLE_NAME = "churn-predictions"


@pytest.fixture
def function_url_event():
    """Factory for Lambda Function URL events (API GW payload format 2.0)."""

    def _event(
        method: str = "POST",
        path: str = "/predict",
        body: dict[str, Any] | None = None,
        request_id: str = "test-request-id",
    ) -> dict[str, Any]:
        return {
            "version": "2.0",
            "rawPath": path,
            "headers": {"content-type": "application/json"},
            "requestContext": {
                "requestId": request_id,
                "http": {"method": method, "path": path},
            },
            "body": json.dumps(body) if body is not None else None,
            "isBase64Encoded": False,
        }

    return _event


@pytest.fixture
def fixture_rows() -> list[dict[str, str]]:
    """The committed 60-row Telco sample as raw dicts."""
    with FIXTURE_CSV.open(newline="") as f:
        return list(csv.DictReader(f))


@pytest.fixture
def predictions_table():
    """moto-backed churn-predictions table per docs/DYNAMODB_DESIGN.md.

    Phase 4 replaces the inline schema with one parsed from template.yaml so
    infra and tests cannot drift.
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[
                {"AttributeName": "PK", "AttributeType": "S"},
                {"AttributeName": "SK", "AttributeType": "S"},
                {"AttributeName": "GSI1PK", "AttributeType": "S"},
                {"AttributeName": "GSI1SK", "AttributeType": "S"},
                {"AttributeName": "GSI2PK", "AttributeType": "S"},
                {"AttributeName": "GSI2SK", "AttributeType": "S"},
            ],
            KeySchema=[
                {"AttributeName": "PK", "KeyType": "HASH"},
                {"AttributeName": "SK", "KeyType": "RANGE"},
            ],
            GlobalSecondaryIndexes=[
                {
                    "IndexName": "GSI1",
                    "KeySchema": [
                        {"AttributeName": "GSI1PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI1SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {
                        "ProjectionType": "INCLUDE",
                        "NonKeyAttributes": ["churnProbability", "churnPredicted", "modelVersion"],
                    },
                },
                {
                    "IndexName": "GSI2",
                    "KeySchema": [
                        {"AttributeName": "GSI2PK", "KeyType": "HASH"},
                        {"AttributeName": "GSI2SK", "KeyType": "RANGE"},
                    ],
                    "Projection": {
                        "ProjectionType": "INCLUDE",
                        "NonKeyAttributes": ["churnProbability", "churnPredicted", "modelVersion"],
                    },
                },
            ],
        )
        client.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={"Enabled": True, "AttributeName": "expiresAt"},
        )
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
