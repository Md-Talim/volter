from typing import Callable, Protocol, final, override

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp


class _Limiter(Protocol):
    def allow(self, key: str, tokens_requested: float = 1.0) -> bool: ...


def _default_key_func(request: Request) -> str:
    client = request.client
    return client.host if client else "unknown"


@final
class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(
        self,
        app: ASGIApp,
        limiter: _Limiter,
        key_func: Callable[[Request], str] = _default_key_func,
        tokens_requested: float = 1.0,
    ):
        super().__init__(app)
        self.limiter = limiter
        self.key_func = key_func
        self.tokens_requested = tokens_requested

    @override
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        key = self.key_func(request)

        if not self.limiter.allow(key, self.tokens_requested):
            return Response(
                content='{"detail": "Rate limit exceeded"}',
                status_code=429,
                media_type="application/json",
                headers={"Retry-After": "1"},
            )

        return await call_next(request)
