"""End-to-end training runs on the fixture: reproducibility (NFR-0003),
split integrity, and the summary contract."""

import json

from tests.conftest import FIXTURE_CSV
from training import config, train


def test_run_end_to_end_and_summary_contract(capsys):
    train.main(["--data", str(FIXTURE_CSV)])
    summary = json.loads(capsys.readouterr().out)
    assert summary["model"] in {"logistic_regression", "hist_gradient_boosting"}
    assert set(summary["cv_roc_auc"]) == {"logistic_regression", "hist_gradient_boosting"}
    for auc in summary["cv_roc_auc"].values():
        assert 0.0 <= auc <= 1.0
    assert set(summary["validation"]) == {"roc_auc", "brier", "ece"}
    assert isinstance(summary["calibrated"], bool)


def test_split_is_stratified_60_20_20():
    X, y = train.load_dataset(FIXTURE_CSV)
    splits = train.split_dataset(X, y)
    n = len(y)
    assert len(splits.y_train) + len(splits.y_val) + len(splits.y_test) == n
    assert abs(len(splits.y_test) / n - config.TEST_FRACTION) < 0.05
    assert abs(len(splits.y_val) / n - config.VAL_FRACTION) < 0.05
    # stratification: churn rate within a few points of the overall rate
    overall = y.mean()
    for part in (splits.y_train, splits.y_val, splits.y_test):
        assert abs(part.mean() - overall) < 0.10


def test_training_is_reproducible():
    """Same data + same config ⇒ identical model choice and metrics (NFR-0003)."""
    first = train.run(FIXTURE_CSV)
    second = train.run(FIXTURE_CSV)
    assert first.model_name == second.model_name
    assert first.calibrated == second.calibrated
    assert first.cv_auc == second.cv_auc
    assert first.val_metrics == second.val_metrics
