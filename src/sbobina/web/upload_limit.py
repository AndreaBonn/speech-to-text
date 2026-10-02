from collections.abc import Mapping

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LIMITED_METHOD = "POST"
BYTES_PER_MB = 1024 * 1024
# Multipart boundaries and the config fields travel with the file.
FORM_OVERHEAD_BYTES = BYTES_PER_MB


def upload_limit_bytes(max_upload_mb: int) -> int:
    """Whole-request cap for an audio file of at most ``max_upload_mb``."""
    return max_upload_mb * BYTES_PER_MB + FORM_OVERHEAD_BYTES


class UploadLimitMiddleware:
    """Reject oversized uploads from ``Content-Length`` before the body is read.

    Starlette's form parser spools a whole file part to a temporary file with no
    size cap, so a check inside the endpoint runs only after the full upload has
    hit the disk. Browsers always send ``Content-Length`` for form uploads; a
    request without it is refused instead of being trusted.
    """

    def __init__(
        self,
        app: ASGIApp,
        limits: Mapping[str, int],
        suffix_limits: Mapping[str, int] | None = None,
    ) -> None:
        self.app = app
        # Every multipart endpoint needs its own cap: path -> max request bytes.
        self.limits = dict(limits)
        # For routes with a path parameter (course key), matched by suffix instead.
        self.suffix_limits = dict(suffix_limits) if suffix_limits is not None else {}

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        rejection = self._rejection(scope=scope)
        if rejection is None:
            await self.app(scope, receive, send)
            return
        await rejection(scope, receive, send)

    def _max_bytes(self, path: str) -> int | None:
        exact = self.limits.get(path)
        if exact is not None:
            return exact
        return next(
            (
                limit
                for suffix, limit in self.suffix_limits.items()
                if path.endswith(suffix)
            ),
            None,
        )

    def _rejection(self, scope: Scope) -> JSONResponse | None:
        if scope["type"] != "http" or scope["method"] != LIMITED_METHOD:
            return None
        max_bytes = self._max_bytes(path=scope["path"].rstrip("/"))
        if max_bytes is None:
            return None
        headers = dict(scope["headers"])
        length = headers.get(b"content-length", b"").decode("latin-1")
        if not length.isdecimal():
            return _error(
                status_code=411,
                code="LENGTH_REQUIRED",
                message="Dimensione del file non dichiarata dal browser",
            )
        if int(length) > max_bytes:
            return _error(
                status_code=413,
                code="PAYLOAD_TOO_LARGE",
                message="Il file supera il limite consentito",
            )
        return None


def _error(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        content={"error": {"code": code, "message": message}},
        status_code=status_code,
    )
