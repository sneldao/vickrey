"""Small, stable error types translated by the HTTP layer."""

from __future__ import annotations


class ServiceError(Exception):
    status_code = 500
    code = "internal_error"

    def __init__(self, detail: str, *, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        if status_code is not None:
            self.status_code = status_code


class NotFound(ServiceError):
    status_code = 404
    code = "not_found"


class Conflict(ServiceError):
    status_code = 409
    code = "conflict"


class Gone(ServiceError):
    status_code = 410
    code = "expired"


class Forbidden(ServiceError):
    status_code = 403
    code = "forbidden"


class IdempotencyConflict(Conflict):
    code = "idempotency_conflict"


class InvalidSignature(ServiceError):
    status_code = 422
    code = "invalid_verifier_signature"


class QuotaExceeded(ServiceError):
    status_code = 429
    code = "quota_exceeded"

    def __init__(self, retry_after: int) -> None:
        super().__init__("hourly mutation quota exceeded")
        self.retry_after = max(1, retry_after)
