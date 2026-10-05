from fastapi import status
from starlette.datastructures import MutableHeaders
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from sbobina.settings import Settings
from sbobina.web.responses import error_response

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
# Plan C4 (S4): defence in depth for formulas rendered by KaTeX. KaTeX sets
# styles through the CSSOM, which style-src does not govern.
CONTENT_SECURITY_POLICY = (
    "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
    "base-uri 'none'; frame-ancestors 'none'"
)


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


class ContentSecurityPolicyMiddleware:
    """Add the policy to HTML pages; JSON and files do not run scripts.

    Raw ASGI, not BaseHTTPMiddleware: it only rewrites the response start, so
    streamed exports and server-sent events pass through untouched.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_policy(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                if headers.get("content-type", "").startswith("text/html"):
                    headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
            await send(message)

        await self.app(scope, receive, send_with_policy)
