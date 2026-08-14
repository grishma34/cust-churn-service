"""Shared fixtures: Function URL event factory, the moto DynamoDB table, and
the session-scoped fixture model artifact (a REAL tiny artifact built by the
production training code on data/fixtures/telco_60.csv — a mocked Pipeline
would pass even if preprocessing were missing, see docs/TEST_STRATEGY.md).
"""

import csv
import importlib
import json
from pathlib import Path
from typing import Any

import boto3
import pytest
import yaml
from moto import mock_aws

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_CSV = REPO_ROOT / "data" / "fixtures" / "telco_60.csv"

TABLE_NAME = "churn-predictions"


class CfnLoader(yaml.SafeLoader):
    """SafeLoader that tolerates CloudFormation intrinsics (!Ref, !Sub,
    !GetAtt, ...) by constructing their plain values."""


def _construct_unknown(loader, tag_suffix, node):
    if isinstance(node, yaml.ScalarNode):
        return loader.construct_scalar(node)
    if isinstance(node, yaml.SequenceNode):
        return loader.construct_sequence(node)
    return loader.construct_mapping(node)


CfnLoader.add_multi_constructor("!", _construct_unknown)


def load_template() -> dict[str, Any]:
    return yaml.load((REPO_ROOT / "template.yaml").read_text(), Loader=CfnLoader)


def table_properties() -> dict[str, Any]:
    """The DynamoDB table as declared in template.yaml — the single source of
    truth for the moto fixture, so infra and tests cannot drift (PLAN Phase 4)."""
    resources = load_template()["Resources"]
    [table] = [r for r in resources.values() if r["Type"] == "AWS::DynamoDB::Table"]
    return table["Properties"]


@pytest.fixture(scope="session")
def artifact_dir(tmp_path_factory) -> Path:
    """model.joblib + model_meta.json produced by the real training entrypoint
    on the 60-row fixture — serialization, metadata schema, and raw-input
    prediction are all exercised for real."""
    from training import train

    out = tmp_path_factory.mktemp("artifact")
    result = train.run(FIXTURE_CSV)
    train.package(result, FIXTURE_CSV, out)
    return out


@pytest.fixture
def serving_env(artifact_dir, monkeypatch):
    """Environment the Lambda would see, pointed at the fixture artifact and
    moto-friendly fake credentials. Resets the artifact singleton around each
    test so env changes take effect."""
    from model import artifact

    monkeypatch.setenv("ARTIFACT_DIR", str(artifact_dir))
    monkeypatch.setenv("TABLE_NAME", TABLE_NAME)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    artifact.reset()
    yield
    artifact.reset()


@pytest.fixture
def predict_handler(serving_env, predictions_table):
    """The handler module, freshly imported under the serving env (its
    module-level artifact load is part of what's under test)."""
    import handlers.predict as handler_module

    importlib.reload(handler_module)
    return handler_module


@pytest.fixture
def valid_payload() -> dict[str, Any]:
    """The docs/API_SPEC.md request example (kept in sync by
    tests/unit/shared/test_schema.py)."""
    return {
        "gender": "Female",
        "SeniorCitizen": 0,
        "Partner": "Yes",
        "Dependents": "No",
        "tenure": 5,
        "PhoneService": "Yes",
        "MultipleLines": "No",
        "InternetService": "Fiber optic",
        "OnlineSecurity": "No",
        "OnlineBackup": "No",
        "DeviceProtection": "No",
        "TechSupport": "No",
        "StreamingTV": "Yes",
        "StreamingMovies": "No",
        "Contract": "Month-to-month",
        "PaperlessBilling": "Yes",
        "PaymentMethod": "Electronic check",
        "MonthlyCharges": 85.7,
        "TotalCharges": 420.35,
    }


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
    """moto-backed churn-predictions table built from the ACTUAL template.yaml
    schema — keys, GSIs, projections, and TTL all come from the template."""
    props = table_properties()
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=TABLE_NAME,
            BillingMode=props["BillingMode"],
            AttributeDefinitions=props["AttributeDefinitions"],
            KeySchema=props["KeySchema"],
            GlobalSecondaryIndexes=props["GlobalSecondaryIndexes"],
        )
        ttl = props["TimeToLiveSpecification"]
        client.update_time_to_live(
            TableName=TABLE_NAME,
            TimeToLiveSpecification={
                "Enabled": ttl["Enabled"],
                "AttributeName": ttl["AttributeName"],
            },
        )
        yield boto3.resource("dynamodb", region_name="us-east-1").Table(TABLE_NAME)
