"""Pipeline shape and contract tests (REQ-0005) on the 60-row fixture."""

import numpy as np
import pytest
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LogisticRegression
from src.shared import schema
from training.features import FEATURE_COLUMNS, build_pipeline
from training.train import load_dataset

from tests.conftest import FIXTURE_CSV
from training import features


@pytest.fixture(scope="module")
def fixture_data():
    return load_dataset(FIXTURE_CSV)


def test_preprocessing_is_the_first_step_inside_the_pipeline():
    """The artifact IS the preprocessing: first step a ColumnTransformer
    covering every feature column, estimator last (REQ-0005)."""
    pipeline = build_pipeline(LogisticRegression())
    first_name, first_step = pipeline.steps[0]
    assert isinstance(first_step, ColumnTransformer)
    covered = sorted(pos for _, _, positions in first_step.transformers for pos in positions)
    assert covered == list(range(len(FEATURE_COLUMNS)))
    assert pipeline.steps[-1][0] == "classifier"


def test_columns_match_serving_schema_exactly():
    """training/features.py and src/shared/schema.py cannot import each other
    (claude.md rule 4), so this test is the bridge: same fields, same order —
    serving assembles arrays positionally (see features.py docstring)."""
    assert features.NUMERIC_COLUMNS == schema.NUMERIC_FIELDS
    assert features.CATEGORICAL_COLUMNS == schema.CATEGORICAL_FIELDS
    assert features.FEATURE_COLUMNS == schema.FEATURE_FIELDS


def test_fitted_pipeline_predicts_on_raw_serving_shaped_input(fixture_data):
    """A row assembled the way serving will assemble it — object array, JSON
    types, missing TotalCharges as None — predicts without pandas and without
    any preprocessing outside the pipeline."""
    X, y = fixture_data
    pipeline = build_pipeline(LogisticRegression(max_iter=2000))
    pipeline.fit(X, y)

    raw_row = np.array(
        [[1, 85.7, None] + ["Male", 0] + ["No"] * 12 + ["Month-to-month", "Electronic check"]],
        dtype=object,
    )
    # sanity: row built in FEATURE_COLUMNS order (3 numerics then 16 categoricals)
    assert raw_row.shape == (1, len(FEATURE_COLUMNS))
    proba = pipeline.predict_proba(raw_row)[:, 1]
    assert 0.0 <= proba[0] <= 1.0


def test_pipeline_handles_blank_totalcharges_rows(fixture_data):
    """The fixture's 2 NaN TotalCharges rows flow through fit and predict —
    imputation happens inside the pipeline (data/README.md quirk)."""
    X, y = fixture_data
    nan_mask = np.array([x is None or (isinstance(x, float) and np.isnan(x)) for x in X[:, 2]])
    assert nan_mask.sum() >= 2
    pipeline = build_pipeline(LogisticRegression(max_iter=2000))
    pipeline.fit(X, y)
    proba = pipeline.predict_proba(X[nan_mask])[:, 1]
    assert np.all((proba >= 0) & (proba <= 1))
