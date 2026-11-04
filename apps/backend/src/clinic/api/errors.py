"""The error envelope (docs/api/staff-api.md): `{"error": {code, message, request_id, details?}}`."""

from typing import Any

from fastapi import Request, Response
from fastapi.responses import JSONResponse

from clinic.domain.results import ResultCode
from clinic.observability import request_id_var
from clinic.services.staff_ops import OperationRefusedError

STATUS_FOR_CODE = {
    ResultCode.VALIDATION_ERROR: 422,
    ResultCode.UNAUTHENTICATED: 401,
    ResultCode.FORBIDDEN: 403,
    ResultCode.NOT_FOUND: 404,
    ResultCode.SLOT_TAKEN: 409,
    ResultCode.SLOT_UNAVAILABLE: 409,
    ResultCode.LIMIT_REACHED: 409,
    ResultCode.ALREADY_CANCELLED: 409,
    "CONFLICT": 409,
    ResultCode.ACCOUNT_LOCKED: 423,
    ResultCode.RATE_LIMITED: 429,
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, str(code), message, details or {}


def error_response(
    status: int, code: str, message: str, details: dict[str, Any] | None = None
) -> JSONResponse:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id_var.get()}
    if details:
        body["details"] = details
    return JSONResponse({"error": body}, status_code=status)


async def api_error_handler(_: Request, exc: Exception) -> Response:
    if not isinstance(exc, ApiError):
        raise exc
    return error_response(exc.status, exc.code, exc.message, exc.details)


async def refused_handler(_: Request, exc: Exception) -> Response:
    if not isinstance(exc, OperationRefusedError):
        raise exc
    return error_response(STATUS_FOR_CODE.get(exc.code, 409), exc.code, exc.message, exc.details)
