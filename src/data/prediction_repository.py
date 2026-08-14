"""DynamoDB prediction audit log (REQ-0011) — the only module holding boto3
for DynamoDB. Every query below maps to an access pattern in
docs/DYNAMODB_DESIGN.md; there is no Scan and there must never be one.
"""

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import boto3

TTL_DAYS = 90


def _to_dynamo(value: Any) -> Any:
    """DynamoDB rejects floats — store numbers as Decimal via str (exact)."""
    if isinstance(value, bool):
        return value
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: _to_dynamo(v) for k, v in value.items()}
    return value


class PredictionRepository:
    def __init__(self, table_name: str | None = None, resource: Any = None):
        resource = resource or boto3.resource("dynamodb")
        self._table = resource.Table(table_name or os.environ["TABLE_NAME"])

    def put_prediction(self, record: dict[str, Any]) -> None:
        """Single conditional PutItem per docs/DYNAMODB_DESIGN.md — a ULID
        collision should be impossible, so overwriting an audit record must
        error rather than pass silently."""
        prediction_id = record["prediction_id"]
        created_at = record["timestamp"]
        day = created_at[:10]
        expires_at = int((datetime.now(UTC) + timedelta(days=TTL_DAYS)).timestamp())
        item = {
            "PK": f"PRED#{prediction_id}",
            "SK": "META",
            "entityType": "Prediction",
            "predictionId": prediction_id,
            "modelVersion": record["model_version"],
            "churnProbability": record["churn_probability"],
            "churnPredicted": record["churn_predicted"],
            "threshold": record["threshold"],
            "features": record["features"],
            "createdAt": created_at,
            "expiresAt": expires_at,
            "GSI1PK": f"MODEL#{record['model_version']}",
            "GSI1SK": f"TS#{created_at}#{prediction_id}",
            "GSI2PK": f"DAY#{day}",
            "GSI2SK": f"TS#{created_at}#{prediction_id}",
        }
        self._table.put_item(
            Item=_to_dynamo(item),
            ConditionExpression="attribute_not_exists(PK)",
        )

    def get_prediction(self, prediction_id: str) -> dict[str, Any] | None:
        """AP1: point lookup."""
        response = self._table.get_item(Key={"PK": f"PRED#{prediction_id}", "SK": "META"})
        return response.get("Item")

    def list_by_model_version(
        self, model_version: str, limit: int = 50, cursor: dict | None = None
    ) -> tuple[list[dict[str, Any]], dict | None]:
        """AP2: predictions for one model version, newest first."""
        return self._query_index("GSI1", f"MODEL#{model_version}", limit, cursor)

    def list_by_day(
        self, day: str, limit: int = 50, cursor: dict | None = None
    ) -> tuple[list[dict[str, Any]], dict | None]:
        """AP3: predictions for one UTC day (YYYY-MM-DD), newest first."""
        return self._query_index("GSI2", f"DAY#{day}", limit, cursor)

    def _query_index(
        self, index: str, partition_key: str, limit: int, cursor: dict | None
    ) -> tuple[list[dict[str, Any]], dict | None]:
        kwargs: dict[str, Any] = {
            "IndexName": index,
            "KeyConditionExpression": f"{index}PK = :pk",
            "ExpressionAttributeValues": {":pk": partition_key},
            "ScanIndexForward": False,  # newest first
            "Limit": limit,
        }
        if cursor:
            kwargs["ExclusiveStartKey"] = cursor
        response = self._table.query(**kwargs)
        return response["Items"], response.get("LastEvaluatedKey")
