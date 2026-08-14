"""Lambda Function URL handler: /predict, /model, /health (REQ-0008/0012).

The artifact loads at import — a container that can't load its model fails
init instead of serving (REQ-0012). The service (which needs boto3/env) is
built lazily on first request so tests can stand up moto first.
"""

import base64
import json
from typing import Any

from data.metrics_emitter import MetricsEmitter
from data.prediction_repository import PredictionRepository
from model.artifact import get_artifact
from services.prediction_service import PredictionService
from shared.errors import MethodNotAllowedError, NotFoundError, ValidationError
from shared.logging import get_request_id
from shared.responses import api_handler, json_response

_ARTIFACT = get_artifact()

_service: PredictionService | None = None


def _get_service() -> PredictionService:
    global _service
    if _service is None:
        _service = PredictionService(_ARTIFACT, PredictionRepository(), MetricsEmitter())
    return _service


def _parse_body(event: dict[str, Any]) -> Any:
    raw = event.get("body")
    if raw is None:
        raise ValidationError([{"field": "body", "issue": "request body required"}])
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode()
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValidationError([{"field": "body", "issue": "must be valid JSON"}]) from exc


@api_handler
def handler(event: dict[str, Any], context: Any) -> dict[str, Any]:
    http = event.get("requestContext", {}).get("http", {})
    method, path = http.get("method"), http.get("path")
    request_id = get_request_id()

    match path:
        case "/predict":
            if method != "POST":
                raise MethodNotAllowedError(f"{method} not allowed on /predict")
            result = _get_service().predict(_parse_body(event))
            return json_response(200, result, request_id)
        case "/model":
            if method != "GET":
                raise MethodNotAllowedError(f"{method} not allowed on /model")
            # metadata verbatim minus the bulky baselines (docs/API_SPEC.md)
            meta = {k: v for k, v in _ARTIFACT.meta.items() if k != "baselines"}
            return json_response(200, meta, request_id)
        case "/health":
            if method != "GET":
                raise MethodNotAllowedError(f"{method} not allowed on /health")
            body = {"status": "ok", "model_version": _ARTIFACT.model_version}
            return json_response(200, body, request_id)
        case _:
            raise NotFoundError(f"no such path: {path}")
