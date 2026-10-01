from fastapi import status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from sbobina.settings import Settings
from sbobina.web.responses import error_response

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def web_origin(settings: Settings) -> str:
    host = settings.web_host
    url_host = f"[{host}]" if ":" in host else host
    return f"http://{url_host}:{settings.web_port}"


class OriginMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: ASGIApp, origin: str) -> None:
        super().__init__(app=app)
        self.origin = origin

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        origin = request.headers.get("origin")
        if (
            request.method in MUTATING_METHODS
            and origin is not None
            and origin != self.origin
        ):
            return error_response(
                code="FORBIDDEN",
                message="Origine della richiesta non consentita",
                status_code=status.HTTP_403_FORBIDDEN,
            )
        return await call_next(request)
