"""The traceability test (REQ-0010/0011) — the other test that IS a resume
claim: any prediction anyone has seen maps back to the exact model that
produced it, through three independent copies of the version string."""

import importlib
import json
import shutil

from data.prediction_repository import PredictionRepository


def _body(response):
    return json.loads(response["body"])


def test_prediction_traceable_end_to_end(
    predict_handler, function_url_event, valid_payload, artifact_dir
):
    response = predict_handler.handler(function_url_event(body=valid_payload), None)
    assert response["statusCode"] == 200
    body = _body(response)

    meta_version = json.loads((artifact_dir / "model_meta.json").read_text())["model_version"]
    item = PredictionRepository().get_prediction(body["prediction_id"])

    # HTTP response == DynamoDB audit item == artifact metadata
    assert body["model_version"] == meta_version
    assert item["modelVersion"] == meta_version
    assert float(item["churnProbability"]) == body["churn_probability"]
    assert item["features"]["Contract"] == valid_payload["Contract"]


def test_version_is_read_from_the_artifact_not_a_constant(
    serving_env,
    predictions_table,
    function_url_event,
    valid_payload,
    artifact_dir,
    tmp_path,
    monkeypatch,
):
    """Mutate the metadata, reload, and the served version must follow —
    proving no copy of the version string lives in src/ (REQ-0010)."""
    mutated_dir = tmp_path / "mutated"
    shutil.copytree(artifact_dir, mutated_dir)
    meta_path = mutated_dir / "model_meta.json"
    meta = json.loads(meta_path.read_text())
    meta["model_version"] = "2.0.0+mutated"
    meta_path.write_text(json.dumps(meta))

    from model import artifact

    monkeypatch.setenv("ARTIFACT_DIR", str(mutated_dir))
    artifact.reset()
    import handlers.predict as handler_module

    importlib.reload(handler_module)

    response = handler_module.handler(function_url_event(body=valid_payload), None)
    assert _body(response)["model_version"] == "2.0.0+mutated"
    item = PredictionRepository().get_prediction(_body(response)["prediction_id"])
    assert item["modelVersion"] == "2.0.0+mutated"
