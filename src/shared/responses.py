"""HTTP response building for the Lambda Function URL handler.

One decorator (`api_handler`) owns the error→HTTP mapping (docs/API_SPEC.md
errors table), the JSON access log, and the X-Request-Id echo. Handlers return
plain dicts; services raise typed errors from shared/errors.py.
"""

import json
import uuid
from collections.abc import Callable
from typing import Any

from shared.errors import ServiceError, ValidationError
from shared.logging import get_logger, set_request_id

logger = get_logger("api")


def json_response(status: int, body: dict[str, Any], request_id: str) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
        },
        "body": json.dumps(body, default=str),
    }


def error_response(err: ServiceError, request_id: str) -> dict[str, Any]:
    error: dict[str, Any] = {"code": err.code, "message": err.message}
    if isinstance(err, ValidationError):
        error["details"] = err.details
    return json_response(err.status, {"error": error, "request_id": request_id}, request_id)


def _extract_request_id(event: dict[str, Any]) -> str:
    return event.get("requestContext", {}).get("requestId") or str(uuid.uuid4())


def api_handler(fn: Callable[[dict[str, Any], Any], dict[str, Any]]) -> Callable:
    """Wrap a handler: set request ID, map typed errors to HTTP, log one
    access line per request (success or failure), echo X-Request-Id."""

    def wrapper(event: dict[str, Any], context: Any) -> dict[str, Any]:
        request_id = _extract_request_id(event)
        set_request_id(request_id)
        http = event.get("requestContext", {}).get("http", {})
        try:
            response = fn(event, context)
        except ServiceError as err:
            response = error_response(err, request_id)
        except Exception:
            logger.exception("unhandled error")
            response = error_response(ServiceError("Internal error"), request_id)
        logger.info(
            "access",
            extra={
                "extra_fields": {
                    "method": http.get("method"),
                    "path": http.get("path"),
                    "status": response["statusCode"],
                }
            },
        )
        return response

    return wrapper
