from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.middleware.trustedhost import TrustedHostMiddleware

from sbobina.settings import LOOPBACK_HOSTS, Settings
from sbobina.web.api_system import create_system_router
from sbobina.web.errors import AppError
from sbobina.web.job_store import JobStore
from sbobina.web.middleware import OriginMiddleware, web_origin
from sbobina.web.responses import (
    app_error_handler,
    http_error_handler,
    request_validation_handler,
)

# Starlette's TrustedHostMiddleware matches the Host header as parsed, which
# keeps brackets around IPv6 literals (RFC 3986 host rule): "::1" must be
# "[::1]" here or a request to http://[::1]:PORT/ gets a 400 before reaching
# OriginMiddleware. https://github.com/encode/starlette/blob/master/starlette/_utils.py
_TRUSTED_HOSTS = [f"[{host}]" if ":" in host else host for host in LOOPBACK_HOSTS]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    yield


def create_app(settings: Settings, data_dir: Path | None = None) -> FastAPI:
    app = FastAPI(lifespan=lifespan)
    app.state.settings = settings
    app.state.job_store = JobStore(
        data_dir=data_dir if data_dir is not None else settings.data_dir
    )
    app.add_middleware(OriginMiddleware, origin=web_origin(settings=settings))
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=_TRUSTED_HOSTS)
    app.add_exception_handler(RequestValidationError, request_validation_handler)
    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(HTTPException, http_error_handler)
    app.include_router(create_system_router(settings=settings))
    return app
