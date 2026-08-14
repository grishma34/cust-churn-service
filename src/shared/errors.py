"""Typed exceptions raised by services; mapped to HTTP responses in one place
(shared/responses.py). Handlers and services never build HTTP responses from
scratch."""


class ServiceError(Exception):
    """Base for all errors the API knows how to present."""

    code = "INTERNAL_ERROR"
    status = 500

    def __init__(self, message: str = "Internal error"):
        super().__init__(message)
        self.message = message


class ValidationError(ServiceError):
    """Input failed validation (REQ-0013). `details` lists per-field issues:
    [{"field": ..., "issue": ...}, ...]."""

    code = "VALIDATION_ERROR"
    status = 400

    def __init__(self, details: list[dict[str, str]], message: str = "Invalid input"):
        super().__init__(message)
        self.details = details


class NotFoundError(ServiceError):
    code = "NOT_FOUND"
    status = 404


class MethodNotAllowedError(ServiceError):
    code = "METHOD_NOT_ALLOWED"
    status = 405


class ArtifactError(ServiceError):
    """Model artifact missing or corrupt. Raised at container init — a Lambda
    that cannot load its model must fail to start, not serve (REQ-0012)."""

    code = "ARTIFACT_ERROR"
    status = 500
