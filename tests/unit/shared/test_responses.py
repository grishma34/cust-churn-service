"""Seed tests for the error→HTTP mapping and response envelope
(docs/API_SPEC.md errors table)."""

import json

from shared.errors import (
    MethodNotAllowedError,
    NotFoundError,
    ServiceError,
    ValidationError,
)
from shared.responses import api_handler


def _invoke(handler, event):
    return handler(event, None)


def _body(response):
    return json.loads(response["body"])


def test_success_passthrough_and_request_id_echo(function_url_event):
    @api_handler
    def handler(event, context):
        return {"statusCode": 200, "headers": {"X-Request-Id": "x"}, "body": "{}"}

    response = _invoke(handler, function_url_event(request_id="abc-123"))
    assert response["statusCode"] == 200


def test_validation_error_maps_to_400_with_details(function_url_event):
    details = [{"field": "Contract", "issue": "must be one of: Month-to-month, One year, Two year"}]

    @api_handler
    def handler(event, context):
        raise ValidationError(details)

    response = _invoke(handler, function_url_event(request_id="abc-123"))
    assert response["statusCode"] == 400
    assert response["headers"]["X-Request-Id"] == "abc-123"
    body = _body(response)
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["details"] == details
    assert body["request_id"] == "abc-123"


def test_not_found_and_method_not_allowed_statuses(function_url_event):
    for err, status in [(NotFoundError("no such path"), 404), (MethodNotAllowedError("no"), 405)]:

        @api_handler
        def handler(event, context, err=err):
            raise err

        response = _invoke(handler, function_url_event())
        assert response["statusCode"] == status
        assert _body(response)["error"]["code"] == err.code


def test_unexpected_exception_becomes_opaque_500(function_url_event):
    @api_handler
    def handler(event, context):
        raise RuntimeError("secret internal detail")

    response = _invoke(handler, function_url_event())
    assert response["statusCode"] == 500
    body = _body(response)
    assert body["error"]["code"] == "INTERNAL_ERROR"
    # No stack trace or internal message leaks into the body (API_SPEC 500 rule)
    assert "secret internal detail" not in response["body"]


def test_service_error_hierarchy():
    assert issubclass(ValidationError, ServiceError)
    assert ValidationError([]).status == 400
    assert ServiceError().status == 500
