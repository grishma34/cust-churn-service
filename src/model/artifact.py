"""Load the trained artifact (model.joblib + model_meta.json) once per
container (NFR-0006). A container that cannot load its model must fail at
init, not serve (REQ-0012) — hence loud ArtifactError on anything missing,
corrupt, or structurally wrong.

The artifact directory is baked into the image at docker build; ARTIFACT_DIR
overrides it for tests.
"""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import joblib

from shared.errors import ArtifactError

_REQUIRED_META_KEYS = ("model_version", "threshold", "costs", "metrics", "baselines")


@dataclass(frozen=True)
class ModelArtifact:
    pipeline: Any
    meta: dict[str, Any]

    @property
    def model_version(self) -> str:
        return self.meta["model_version"]

    @property
    def threshold(self) -> float:
        return float(self.meta["threshold"])


def load_artifact(artifact_dir: Path | None = None) -> ModelArtifact:
    directory = artifact_dir or Path(os.environ.get("ARTIFACT_DIR", "artifacts"))
    model_path = directory / "model.joblib"
    meta_path = directory / "model_meta.json"
    for path in (model_path, meta_path):
        if not path.exists():
            raise ArtifactError(f"artifact file missing: {path}")
    try:
        pipeline = joblib.load(model_path)
        meta = json.loads(meta_path.read_text())
    except Exception as exc:
        raise ArtifactError(f"artifact corrupt: {exc}") from exc
    missing = [key for key in _REQUIRED_META_KEYS if key not in meta]
    if missing:
        raise ArtifactError(f"model_meta.json missing keys: {missing}")
    if not hasattr(pipeline, "predict_proba"):
        raise ArtifactError("model.joblib does not provide predict_proba")
    return ModelArtifact(pipeline=pipeline, meta=meta)


_instance: ModelArtifact | None = None


def get_artifact() -> ModelArtifact:
    """Process-wide singleton: deserialize once at cold start, reuse warm."""
    global _instance
    if _instance is None:
        _instance = load_artifact()
    return _instance


def reset() -> None:
    """Test hook: force the next get_artifact() to reload."""
    global _instance
    _instance = None
