"""The leakage guard (REQ-0006) — the test that IS the resume claim.

Dynamic guard: spy on Pipeline.fit across a full training run and assert no
validation or test row was ever in a fitted X. Static guard: serving code
never calls fit at all.
"""

import re
from pathlib import Path

import numpy as np
import pytest
from sklearn.pipeline import Pipeline

from tests.conftest import FIXTURE_CSV
from training import train

REPO_ROOT = Path(__file__).resolve().parents[2]


def _row_keys(X: np.ndarray) -> set[tuple[str, ...]]:
    return {tuple(str(v) for v in row) for row in np.asarray(X, dtype=object)}


def test_nothing_fit_outside_train_split(monkeypatch):
    """Run the REAL entrypoint end-to-end; every X passed to any Pipeline.fit
    (final fits, every CV clone, the calibration refit) must be a subset of
    the training split — zero rows from validation or test."""
    fitted: list[np.ndarray] = []
    original_fit = Pipeline.fit

    def spying_fit(self, X, y=None, **kwargs):
        fitted.append(np.asarray(X, dtype=object))
        return original_fit(self, X, y, **kwargs)

    monkeypatch.setattr(Pipeline, "fit", spying_fit)
    result = train.run(FIXTURE_CSV)

    assert len(fitted) >= train.config.CV_FOLDS * 2, "spy did not capture the CV fits"
    train_keys = _row_keys(result.splits.X_train)
    forbidden = _row_keys(result.splits.X_val) | _row_keys(result.splits.X_test)
    # fixture rows are distinct customers, so row-content keys are unambiguous
    assert not (train_keys & forbidden)
    for X in fitted:
        leaked = _row_keys(X) & forbidden
        assert not leaked, f"fit() saw {len(leaked)} validation/test rows"


def test_test_split_is_scored_only_in_evaluate_final():
    """REQ-0002: the test split is touched exactly once. Statically: the only
    top-level definitions allowed to reference X_test/y_test are the split
    itself, the container dataclasses, and evaluate_final — and evaluate_final
    is called from exactly one site."""
    import ast

    source = (REPO_ROOT / "training" / "train.py").read_text()
    allowed = {"split_dataset", "evaluate_final", "Splits", "TrainingResult"}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            body = ast.unparse(node)
            if "X_test" in body or "y_test" in body:
                assert node.name in allowed, f"{node.name} touches the test split"
    # one definition + one call site, nothing more
    assert source.count("evaluate_final(") == 2


def test_serving_code_never_fits():
    """Static half of the guard: `fit(` must not appear anywhere in src/ —
    serving may only predict/predict_proba/transform (claude.md rule 2)."""
    offenders = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), start=1):
            if re.search(r"\bfit(_transform)?\s*\(", line):
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")
    assert not offenders, f"fit() calls in serving code: {offenders}"


def test_model_selection_cross_validates_the_whole_pipeline():
    """CV must clone preprocessing+estimator together (per-fold refit of
    imputers/scalers/encoders) — i.e. cross_val_score receives build_pipeline's
    output, not a bare estimator (docs/TEST_STRATEGY.md 'CV integrity')."""
    source = (REPO_ROOT / "training" / "train.py").read_text()
    call = re.search(r"cross_val_score\(\s*([^,]+),", source)
    assert call, "model selection no longer uses cross_val_score"
    assert "build_pipeline(" in call.group(1)


@pytest.mark.parametrize("module", ["train", "features", "config", "threshold", "metadata"])
def test_training_never_imports_serving(module):
    """claude.md rule 4: the artifact contract is the only interface."""
    source = (REPO_ROOT / "training" / f"{module}.py").read_text()
    assert not re.search(r"^\s*(from|import)\s+(src|shared|handlers|services)\b", source, re.M)
