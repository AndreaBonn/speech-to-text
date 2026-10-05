from collections.abc import Mapping

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

LIMITED_METHODS = frozenset({"POST", "PATCH"})
BYTES_PER_MB = 1024 * 1024
# Multipart boundaries and the config fields travel with the file.
FORM_OVERHEAD_BYTES = BYTES_PER_MB
# Card front/back (MAX_CARD_TEXT_LENGTH) and a citation quote (MAX_QUOTE_CHARS)
# are each capped at 2000 chars; 64 KiB is generous headroom over that JSON.
CARD_JSON_LIMIT_BYTES = 64 * 1024


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
        direct = self._suffix_limit(path=path)
        if direct is not None:
            return direct
        # A trailing variable id segment (.../cards/{card_id}) has no fixed
        # suffix of its own: retry once against the path with that segment
        # removed, so a PATCH on a specific resource inherits its collection
        # limit without a per-id entry.
        parent, separator, segment = path.rpartition("/")
        if not separator or not segment:
            return None
        return self._suffix_limit(path=parent)

    def _suffix_limit(self, path: str) -> int | None:
        return next(
            (
                limit
                for suffix, limit in self.suffix_limits.items()
                if path.endswith(suffix)
            ),
            None,
        )

    def _rejection(self, scope: Scope) -> JSONResponse | None:
        if scope["type"] != "http" or scope["method"] not in LIMITED_METHODS:
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
        content={"error": {"code": code, "message": message, "details": []}},
        status_code=status_code,
    )
