"""The artifact is fitted under training's sklearn and deserialized under
serving's sklearn — the pins must be identical or the Pipeline may not load
(PLAN.md risk table). joblib (the serialization layer) gets the same treatment."""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def _pins(requirements_path: Path) -> dict[str, str]:
    pins = {}
    for line in requirements_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "-r")):
            continue
        match = re.fullmatch(r"([A-Za-z0-9_.\[\]-]+)==([^\s;#]+).*", line)
        assert match, f"unpinned requirement in {requirements_path.name}: {line!r}"
        name = match.group(1).split("[")[0].lower()
        pins[name] = match.group(2)
    return pins


def test_every_requirement_is_pinned_and_sklearn_matches():
    src = _pins(REPO_ROOT / "src" / "requirements.txt")
    training = _pins(REPO_ROOT / "training" / "requirements.txt")
    _pins(REPO_ROOT / "requirements-dev.txt")  # asserts pinning as a side effect
    for package in ("scikit-learn", "joblib"):
        assert src[package] == training[package], (
            f"{package} pinned differently: src={src[package]} training={training[package]}"
        )


def test_training_only_deps_stay_out_of_inference_image():
    """claude.md rule 4: pandas/matplotlib must never appear in src/requirements.txt."""
    src = _pins(REPO_ROOT / "src" / "requirements.txt")
    assert "pandas" not in src
    assert "matplotlib" not in src
