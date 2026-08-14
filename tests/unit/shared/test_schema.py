"""Drift guards between the schema stub, the API spec, and the fixture data.

These are Phase 0 seed tests, but they are real: if the documented request
example, the dataset columns, and src/shared/schema.py disagree, something is
already wrong.
"""

import json
import re
from pathlib import Path

from shared.schema import CATEGORICAL_FIELDS, FEATURE_FIELDS, NUMERIC_FIELDS

REPO_ROOT = Path(__file__).resolve().parents[3]


def test_feature_fields_are_19_and_disjoint():
    assert len(FEATURE_FIELDS) == 19
    assert set(NUMERIC_FIELDS).isdisjoint(CATEGORICAL_FIELDS)
    assert set(FEATURE_FIELDS) == set(NUMERIC_FIELDS) | set(CATEGORICAL_FIELDS)


def test_schema_matches_api_spec_request_example():
    """The first JSON block in docs/API_SPEC.md is the /predict request example;
    its keys must be exactly the schema's feature fields."""
    spec = (REPO_ROOT / "docs" / "API_SPEC.md").read_text()
    match = re.search(r"```json\n(.*?)```", spec, re.DOTALL)
    assert match, "API_SPEC.md no longer contains a JSON request example"
    example = json.loads(match.group(1))
    assert set(example) == set(FEATURE_FIELDS)


def test_schema_matches_fixture_columns(fixture_rows):
    """Fixture CSV columns = customerID + features + Churn, nothing else."""
    columns = set(fixture_rows[0])
    assert columns == set(FEATURE_FIELDS) | {"customerID", "Churn"}


def test_fixture_composition(fixture_rows):
    """The fixture stays useful: 60 rows, both classes present at roughly the
    real churn rate, and blank-TotalCharges rows kept for the coercion path."""
    assert len(fixture_rows) == 60
    churners = sum(row["Churn"] == "Yes" for row in fixture_rows)
    assert 10 <= churners <= 25
    blanks = sum(row["TotalCharges"].strip() == "" for row in fixture_rows)
    assert blanks >= 2
