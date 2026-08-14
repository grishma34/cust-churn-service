"""Handler contract tests (REQ-0008/0012/0013) against the real fixture
artifact on moto."""

import importlib
import json

import pytest

from shared.errors import ArtifactError


def _body(response):
    return json.loads(response["body"])


def test_predict_happy_path_full_contract(predict_handler, function_url_event, valid_payload):
    response = predict_handler.handler(
        function_url_event(body=valid_payload, request_id="req-42"), None
    )
    assert response["statusCode"] == 200
    assert response["headers"]["X-Request-Id"] == "req-42"
    assert response["headers"]["Content-Type"] == "application/json"
    body = _body(response)
    assert set(body) == {
        "prediction_id",
        "churn_probability",
        "churn_predicted",
        "threshold",
        "model_version",
        "timestamp",
    }
    assert 0.0 <= body["churn_probability"] <= 1.0
    assert body["churn_predicted"] == (body["churn_probability"] >= body["threshold"])


def test_invalid_input_400_and_model_not_invoked(
    predict_handler, function_url_event, valid_payload, monkeypatch
):
    def explode(*args, **kwargs):
        raise AssertionError("model called on unvalidated input")

    monkeypatch.setattr(predict_handler._ARTIFACT.pipeline, "predict_proba", explode)
    response = predict_handler.handler(
        function_url_event(body=valid_payload | {"Contract": "Fortnightly"}), None
    )
    assert response["statusCode"] == 400
    error = _body(response)["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["details"][0]["field"] == "Contract"
    assert "One year" in error["details"][0]["issue"]


def test_base64_encoded_body_is_decoded(predict_handler, function_url_event, valid_payload):
    """Function URLs deliver some request bodies base64-encoded."""
    import base64

    event = function_url_event()
    event["body"] = base64.b64encode(json.dumps(valid_payload).encode()).decode()
    event["isBase64Encoded"] = True
    assert predict_handler.handler(event, None)["statusCode"] == 200


def test_malformed_json_body_is_400(predict_handler, function_url_event):
    event = function_url_event()
    event["body"] = "{not json"
    assert predict_handler.handler(event, None)["statusCode"] == 400


def test_missing_body_is_400(predict_handler, function_url_event):
    assert predict_handler.handler(function_url_event(body=None), None)["statusCode"] == 400


def test_get_model_returns_metadata_without_baselines(predict_handler, function_url_event):
    response = predict_handler.handler(function_url_event(method="GET", path="/model"), None)
    assert response["statusCode"] == 200
    body = _body(response)
    assert "baselines" not in body
    assert body["threshold"] == predict_handler._ARTIFACT.threshold
    assert body["model_version"] == predict_handler._ARTIFACT.model_version
    assert body["costs"] == {"false_positive": 50.0, "false_negative": 450.0}


def test_health(predict_handler, function_url_event):
    response = predict_handler.handler(function_url_event(method="GET", path="/health"), None)
    assert response["statusCode"] == 200
    assert _body(response) == {
        "status": "ok",
        "model_version": predict_handler._ARTIFACT.model_version,
    }


@pytest.mark.parametrize(
    ("method", "path", "status"),
    [
        ("GET", "/predict", 405),
        ("POST", "/health", 405),
        ("POST", "/model", 405),
        ("GET", "/nope", 404),
    ],
)
def test_routing_errors(predict_handler, function_url_event, method, path, status):
    response = predict_handler.handler(function_url_event(method=method, path=path), None)
    assert response["statusCode"] == status


def test_artifact_load_failure_fails_at_init_not_at_serve(serving_env, tmp_path, monkeypatch):
    """REQ-0012: a container without a loadable model must die at import."""
    from model import artifact

    monkeypatch.setenv("ARTIFACT_DIR", str(tmp_path))  # empty dir
    artifact.reset()
    import handlers.predict as handler_module

    with pytest.raises(ArtifactError, match="missing"):
        importlib.reload(handler_module)
