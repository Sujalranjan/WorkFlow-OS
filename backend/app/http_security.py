"""HTTP hardening for every API response, and a request size limit.

- Security headers: no MIME sniffing, no framing, no referrer, no caching of API responses (they
  carry personal data), a strict Content-Security-Policy for JSON, and HSTS when served over HTTPS
  (COOKIE_SECURE=true means the site is HTTPS-only). The interactive API docs get a CSP that allows
  the assets they load; they can be switched off entirely with API_DOCS_ENABLED=false.
- Requests larger than MAX_REQUEST_BYTES are refused before the body is read (413), so a client
  cannot make the API buffer arbitrarily large uploads.
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app import config

_API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI / ReDoc load their scripts and styles from a CDN.
_DOCS_CSP = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; img-src 'self' data: https://fastapi.tiangolo.com; "
    "frame-ancestors 'none'; base-uri 'none'"
)
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        length = request.headers.get("content-length")
        if length is not None:
            try:
                too_big = int(length) > config.MAX_REQUEST_BYTES
            except ValueError:
                return JSONResponse({"detail": "Invalid Content-Length."}, status_code=400)
            if too_big:
                return JSONResponse({"detail": "Request too large."}, status_code=413)

        response = await call_next(request)
        headers = response.headers
        headers.setdefault("X-Content-Type-Options", "nosniff")
        headers.setdefault("X-Frame-Options", "DENY")
        headers.setdefault("Referrer-Policy", "no-referrer")
        headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        docs = request.url.path.startswith(_DOCS_PATHS)
        headers.setdefault("Content-Security-Policy", _DOCS_CSP if docs else _API_CSP)
        if request.url.path.startswith("/api/"):
            headers.setdefault("Cache-Control", "no-store")
        if config.COOKIE_SECURE:
            headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response
