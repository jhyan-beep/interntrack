import hashlib
import logging
import math
import re
import time
from dataclasses import dataclass
from threading import Lock
from uuid import uuid4

from fastapi import HTTPException, Request, status
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse, Response

from app.database import Settings, get_settings
from app.observability import reset_request_id, set_request_id


logger = logging.getLogger("interntrack.requests")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS", "TRACE"}
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


@dataclass
class _RateLimitBucket:
    started_at: float
    count: int


class FixedWindowRateLimiter:
    """Small, dependency-free limiter for a single application process."""

    def __init__(self) -> None:
        self._buckets: dict[str, _RateLimitBucket] = {}
        self._lock = Lock()

    def hit(self, key: str, limit: int, window_seconds: int) -> int | None:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None or now - bucket.started_at >= window_seconds:
                self._buckets[key] = _RateLimitBucket(started_at=now, count=1)
                self._discard_expired(now, window_seconds)
                return None

            bucket.count += 1
            if bucket.count <= limit:
                return None

            return max(1, math.ceil(window_seconds - (now - bucket.started_at)))

    def reset(self) -> None:
        with self._lock:
            self._buckets.clear()

    def _discard_expired(self, now: float, window_seconds: int) -> None:
        if len(self._buckets) < 5_000:
            return
        expired = [
            key
            for key, bucket in self._buckets.items()
            if now - bucket.started_at >= window_seconds
        ]
        for key in expired:
            self._buckets.pop(key, None)


auth_rate_limiter = FixedWindowRateLimiter()


def enforce_auth_rate_limit(
    request: Request,
    action: str,
    identity: str,
) -> None:
    settings = get_settings()
    client_ip = request.client.host if request.client is not None else "unknown"
    identity_digest = hashlib.sha256(identity.strip().lower().encode("utf-8")).hexdigest()
    rules = (
        (f"auth:{action}:ip:{client_ip}", settings.auth_rate_limit_per_ip),
        (f"auth:{action}:identity:{identity_digest}", settings.auth_rate_limit_per_identity),
    )

    for key, limit in rules:
        retry_after = auth_rate_limiter.hit(
            key,
            limit=limit,
            window_seconds=settings.auth_rate_limit_window_seconds,
        )
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many authentication attempts. Please try again later.",
                headers={"Retry-After": str(retry_after)},
            )


class OriginProtectionMiddleware(BaseHTTPMiddleware):
    """Reject cross-origin state changes to protect cookie-authenticated routes."""

    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.environment = settings.environment
        self.allowed_origins = set(settings.cors_origin_list)

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        if request.method in SAFE_METHODS:
            return await call_next(request)

        origin = request.headers.get("origin")
        if origin is not None and origin not in self.allowed_origins:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Untrusted request origin"},
            )

        if self.environment == "production" and origin is None:
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={"detail": "Origin header required"},
            )

        return await call_next(request)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings) -> None:
        super().__init__(app)
        self.environment = settings.environment

    async def dispatch(
        self,
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        supplied_request_id = request.headers.get("x-request-id", "")
        request_id = (
            supplied_request_id
            if REQUEST_ID_PATTERN.fullmatch(supplied_request_id)
            else str(uuid4())
        )
        request_id_token = set_request_id(request_id)
        started_at = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started_at) * 1_000
            logger.exception(
                "Request failed",
                extra={
                    "event": "http_request_failed",
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round(duration_ms, 1),
                },
            )
            raise
        finally:
            reset_request_id(request_id_token)

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"

        if request.url.path not in {"/docs", "/redoc", "/openapi.json"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; "
                "script-src 'self'; "
                "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
                "font-src 'self' https://fonts.gstatic.com; "
                "img-src 'self' data:; "
                "connect-src 'self'; "
                "frame-ancestors 'none'; "
                "base-uri 'self'; "
                "form-action 'self'"
            )

        if request.url.path.startswith("/auth"):
            response.headers["Cache-Control"] = "no-store"

        if self.environment == "production":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )

        duration_ms = (time.perf_counter() - started_at) * 1_000
        logger.info(
            "Request completed",
            extra={
                "event": "http_request",
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round(duration_ms, 1),
            },
        )
        return response


def sanitize_csv_cell(value: object) -> object:
    """Prevent spreadsheet programs from evaluating user-controlled cells."""

    if not isinstance(value, str):
        return value
    dangerous_prefix = value.startswith(("\t", "\r")) or value.lstrip().startswith(
        ("=", "+", "-", "@")
    )
    return f"'{value}" if dangerous_prefix else value
