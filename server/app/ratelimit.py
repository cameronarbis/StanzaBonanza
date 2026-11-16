"""
Per-client token bucket, in process (docs/DESIGN.md §5.6).

A courtesy fence, not a security boundary: one Railway instance, so no
shared store. Keyed by client IP — behind the Railway proxy that is the
rightmost X-Forwarded-For hop (the one our proxy appended); the leftmost
entries are client-controlled and must not be trusted.
"""

import time

from starlette.responses import JSONResponse


class TokenBucket:
    def __init__(self, per_minute: int, burst: int):
        self.rate = per_minute / 60.0
        self.burst = burst
        self.buckets: dict[str, tuple[float, float]] = {}  # ip -> (tokens, last)

    def check(self, key: str, now: float | None = None) -> float:
        """Returns 0 if allowed, else seconds until a token is available."""
        now = time.monotonic() if now is None else now
        tokens, last = self.buckets.get(key, (float(self.burst), now))
        tokens = min(self.burst, tokens + (now - last) * self.rate)
        if tokens >= 1.0:
            self.buckets[key] = (tokens - 1.0, now)
            return 0.0
        self.buckets[key] = (tokens, now)
        return (1.0 - tokens) / self.rate

    def prune(self, now: float) -> None:
        # Full buckets carry no information; drop them so the dict stays
        # bounded on the free tier's small memory allowance.
        self.buckets = {
            k: (t, last)
            for k, (t, last) in self.buckets.items()
            if t + (now - last) * self.rate < self.burst
        }


def client_ip(scope) -> str:
    headers = {k.decode("latin-1"): v.decode("latin-1") for k, v in scope["headers"]}
    forwarded = headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    client = scope.get("client")
    return client[0] if client else "unknown"


class RateLimitMiddleware:
    """Pure ASGI: applies to /api/* except /api/health (Railway polls it)."""

    def __init__(self, app, per_minute: int, burst: int):
        self.app = app
        self.bucket = TokenBucket(per_minute, burst)
        self.requests_seen = 0

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "")
        if scope["type"] != "http" or not path.startswith("/api/") or path == "/api/health":
            return await self.app(scope, receive, send)

        self.requests_seen += 1
        if self.requests_seen % 1024 == 0:
            self.bucket.prune(time.monotonic())

        retry_after = self.bucket.check(client_ip(scope))
        if retry_after > 0:
            response = JSONResponse(
                {"error": "rate_limited",
                 "detail": "too many requests — the muse needs a moment",
                 "status": 429},
                status_code=429,
                headers={"Retry-After": str(max(1, round(retry_after)))},
            )
            return await response(scope, receive, send)
        return await self.app(scope, receive, send)
