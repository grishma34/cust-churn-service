"""Template guards: least-privilege IAM (NFR-0004), the NFR-0008 cost caps,
and consistency with docs/DYNAMODB_DESIGN.md. `sam validate --lint` covers
syntax in CI; these tests pin the properties that carry requirements."""

from pathlib import Path

import pytest

from tests.conftest import load_template, table_properties

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture(scope="module")
def template():
    return load_template()


@pytest.fixture(scope="module")
def function(template):
    [fn] = [
        r["Properties"]
        for r in template["Resources"].values()
        if r["Type"] == "AWS::Serverless::Function"
    ]
    return fn


def test_iam_grants_putitem_and_nothing_else(function):
    """NFR-0004: the function can append to the audit log, never read or scan
    it — reads happen via operator credentials (docs/DYNAMODB_DESIGN.md)."""
    actions = [
        action
        for policy in function["Policies"]
        for statement in policy["Statement"]
        for action in (
            statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        )
    ]
    assert actions == ["dynamodb:PutItem"]


def test_function_shape(function):
    assert function["PackageType"] == "Image"
    assert function["FunctionUrlConfig"]["AuthType"] == "NONE"
    assert function["Environment"]["Variables"]["TABLE_NAME"] == "PredictionsTable"  # !Ref
    assert function["MemorySize"] >= 512  # sklearn + numpy need headroom (NFR-0006)
    assert function["Timeout"] <= 30


def test_log_retention_capped_at_30_days(template):
    """NFR-0008: log groups must not retain forever."""
    groups = [
        r["Properties"]
        for r in template["Resources"].values()
        if r["Type"] == "AWS::Logs::LogGroup"
    ]
    assert groups, "explicit log group missing — Lambda would create one with no retention"
    for group in groups:
        assert group["RetentionInDays"] <= 30


def test_table_matches_the_design_doc():
    props = table_properties()
    assert props["BillingMode"] == "PAY_PER_REQUEST"  # NFR-0008: no provisioned idle cost
    assert props["TimeToLiveSpecification"] == {"AttributeName": "expiresAt", "Enabled": True}
    keys = {k["AttributeName"]: k["KeyType"] for k in props["KeySchema"]}
    assert keys == {"PK": "HASH", "SK": "RANGE"}
    gsis = {g["IndexName"]: g for g in props["GlobalSecondaryIndexes"]}
    assert set(gsis) == {"GSI1", "GSI2"}
    for gsi in gsis.values():
        assert gsi["Projection"]["ProjectionType"] == "INCLUDE"
        assert set(gsi["Projection"]["NonKeyAttributes"]) == {
            "churnProbability",
            "churnPredicted",
            "modelVersion",
        }


def test_dockerfile_excludes_training(template):
    """claude.md rule 4 at the image boundary: only src/requirements.txt is
    installed and only src/ + artifacts/ are copied — no training deps."""
    dockerfile = (REPO_ROOT / "Dockerfile").read_text()
    assert "src/requirements.txt" in dockerfile
    assert "COPY training" not in dockerfile
    assert "training/requirements" not in dockerfile
    assert "pandas" not in dockerfile
    assert "artifacts/model.joblib" in dockerfile
    assert "artifacts/model_meta.json" in dockerfile
    assert 'CMD ["handlers.predict.handler"]' in dockerfile


def test_ci_validates_the_template():
    """Same drift-guard idea as the sibling project: the CI workflow must keep
    running sam validate --lint."""
    ci = (REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text()
    assert "sam validate --lint" in ci
