"""End-to-end training runs on the fixture: reproducibility (NFR-0003),
split integrity, and the summary contract."""

import json

from tests.conftest import FIXTURE_CSV
from training import config, train


def test_run_end_to_end_and_summary_contract(capsys, tmp_path):
    train.main(["--data", str(FIXTURE_CSV), "--out", str(tmp_path)])
    summary = json.loads(capsys.readouterr().out)
    assert summary["model"] in {"logistic_regression", "hist_gradient_boosting"}
    assert set(summary["cv_roc_auc"]) == {"logistic_regression", "hist_gradient_boosting"}
    for auc in summary["cv_roc_auc"].values():
        assert 0.0 <= auc <= 1.0
    assert set(summary["validation"]) == {"roc_auc", "brier", "ece"}
    assert isinstance(summary["calibrated"], bool)
    assert 0.0 < summary["threshold"]["value"] < 1.0
    assert set(summary["test"]) >= {"roc_auc", "pr_auc", "confusion_at_threshold"}
    # the full artifact lands on disk (REQ-0007)
    assert (tmp_path / "model.joblib").exists()
    assert (tmp_path / "model_meta.json").exists()
    for plot in ("cost_curve", "reliability_curve", "roc_curve"):
        assert (tmp_path / "plots" / f"{plot}.png").exists()


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
    assert first.threshold.threshold == second.threshold.threshold
    assert first.test_metrics == second.test_metrics
