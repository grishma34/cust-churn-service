"""Drift guards for the Streamlit UI (REQ-0016) — same idea as the sibling
project's frontend test: the UI's field spec must match the API schema
exactly, and the UI must stay a thin HTTP client.

The spec is extracted from app.py's AST rather than importing it, so the test
suite needs no streamlit installation (the app module executes st.* calls at
import time).
"""

import ast
import re
from pathlib import Path

from shared import schema

APP_PATH = Path(__file__).resolve().parents[3] / "streamlit_app" / "app.py"


def _literal_assignment(name: str):
    for node in ast.parse(APP_PATH.read_text()).body:
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == name for t in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(f"app.py no longer defines a literal {name}")


def test_numeric_fields_match_serving_schema():
    assert _literal_assignment("NUMERIC_FIELDS") == schema.NUMERIC_FIELDS


def test_categorical_domains_match_serving_schema_exactly():
    """Every field, every domain value, byte for byte — a UI dropdown offering
    a value the API rejects (or missing one it accepts) fails the build."""
    app_domains = _literal_assignment("CATEGORICAL_DOMAINS")
    assert set(app_domains) == set(schema.CATEGORICAL_FIELDS)
    for field, domain in app_domains.items():
        assert tuple(domain) == tuple(schema.CATEGORICAL_DOMAINS[field]), field


def test_every_field_appears_in_the_submitted_payload():
    """The payload dict in app.py must carry all 19 features — a field left
    out of the form would 400 on every submission."""
    source = APP_PATH.read_text()
    for field in schema.FEATURE_FIELDS:
        assert re.search(rf'"{field}":', source), f"{field} missing from the payload"


def test_ui_is_a_thin_http_client():
    """PROJECT_STRUCTURE.md boundary: no model, no AWS SDK, no imports from
    src/ or training/."""
    tree = ast.parse(APP_PATH.read_text())
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    forbidden = {"boto3", "sklearn", "joblib", "shared", "services", "data", "model", "training"}
    assert not (imported & forbidden), imported & forbidden
    assert "requests" in imported  # it talks HTTP and nothing else


def test_ui_requirements_stay_thin():
    lines = [
        line.strip()
        for line in (APP_PATH.parent / "requirements.txt").read_text().splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    packages = {re.split(r"[<>=\[]", line)[0] for line in lines}
    assert "streamlit" in packages
    assert not packages & {"boto3", "scikit-learn", "joblib", "pandas"}
