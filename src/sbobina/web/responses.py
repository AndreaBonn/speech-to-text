import logging
from http import HTTPStatus
from typing import Any

from fastapi import status
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse

from sbobina.web.errors import (
    AppError,
    ConflictError,
    GatewayTimeoutError,
    NotFoundError,
    ServiceUnavailableError,
    ValidationError,
)
from sbobina.web.gpu_lock import GpuBusyError
from sbobina.web.search_index import SearchCorruptError, SearchUnavailableError

logger = logging.getLogger(__name__)


def error_response(
    code: str,
    message: str,
    status_code: int,
    details: list[dict[str, str]] | None = None,
) -> JSONResponse:
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return JSONResponse(content={"error": error}, status_code=status_code)


async def request_validation_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {"field": ".".join(str(part) for part in error["loc"]), "message": error["msg"]}
        for error in exc.errors()
    ]
    return error_response(
        code="VALIDATION_ERROR",
        message="Dati della richiesta non validi",
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        details=details,
    )


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    if isinstance(exc, NotFoundError):
        return error_response(
            code=exc.code, message=exc.message, status_code=status.HTTP_404_NOT_FOUND
        )
    if isinstance(exc, GpuBusyError):
        return _build_gpu_busy_response(exc=exc)
    if isinstance(exc, ConflictError):
        return error_response(
            code=exc.code, message=exc.message, status_code=status.HTTP_409_CONFLICT
        )
    if isinstance(exc, ValidationError):
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )
    return _build_service_error_response(exc=exc)


def _build_gpu_busy_response(exc: GpuBusyError) -> JSONResponse:
    return error_response(
        code=exc.code,
        message=exc.message,
        status_code=status.HTTP_409_CONFLICT,
        details=[{"field": "stage", "message": exc.stage}]
        + (
            []
            if exc.estimate_s is None
            else [{"field": "estimate_s", "message": str(exc.estimate_s)}]
        ),
    )


def _build_service_error_response(exc: AppError) -> JSONResponse:
    if isinstance(
        exc, (SearchUnavailableError, SearchCorruptError, ServiceUnavailableError)
    ):
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    if isinstance(exc, GatewayTimeoutError):
        return error_response(
            code=exc.code,
            message=exc.message,
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        )
    logger.error("Web application failure", exc_info=exc)
    return error_response(
        code=exc.code,
        message="Errore interno del server",
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
    )


async def http_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Wrap Starlette's 404/405 and friends in the API error envelope."""
    assert isinstance(exc, HTTPException)
    code = HTTPStatus(exc.status_code).name
    return error_response(
        code=code, message=str(exc.detail), status_code=exc.status_code
    )
