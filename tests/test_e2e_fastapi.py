import time

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from volter.fastapi_middleware import RateLimitMiddleware
from volter.sliding_window import SlidingWindowLimiter
from volter.token_bucket import TokenBucketLimiter


def _build_app(limiter) -> TestClient:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    return TestClient(app)


def test_requests_within_capacity_all_succeed():
    limiter = TokenBucketLimiter(capacity=5, refill_rate=5)
    client = _build_app(limiter)

    for _ in range(5):
        response = client.get("/ping")
        assert response.status_code == 200
        assert response.json() == {"message": "pong"}


def test_requests_beyond_capacity_get_429_with_retry_after():
    limiter = TokenBucketLimiter(capacity=3, refill_rate=0)
    client = _build_app(limiter)

    for _ in range(3):
        assert client.get("/ping").status_code == 200

    response = client.get("/ping")
    assert response.status_code == 429
    assert "Retry-After" in response.headers
    assert response.json()["detail"] == "Rate limit exceeded"


def test_bucket_refills_over_time_allowing_new_requests():
    limiter = TokenBucketLimiter(
        capacity=1, refill_rate=10
    )  # fast refill for test speed
    client = _build_app(limiter)

    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429

    time.sleep(0.15)  # ~1.5 tokens refilled at rate=10/sec
    assert client.get("/ping").status_code == 200


def test_different_keys_are_rate_limited_independently():
    limiter = TokenBucketLimiter(capacity=1, refill_rate=0)
    app = FastAPI()
    app.add_middleware(
        RateLimitMiddleware,
        limiter=limiter,
        key_func=lambda request: request.headers.get("x-api-key", "anon"),
    )

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    client = TestClient(app)

    assert client.get("/ping", headers={"x-api-key": "tenant-a"}).status_code == 200
    assert client.get("/ping", headers={"x-api-key": "tenant-a"}).status_code == 429
    # tenant-b has its own bucket, unaffected by tenant-a exhausting theirs
    assert client.get("/ping", headers={"x-api-key": "tenant-b"}).status_code == 200


def test_sliding_window_limiter_works_through_middleware():
    """Confirms the middleware is genuinely algorithm-agnostic (Protocol-based),
    not accidentally coupled to TokenBucketLimiter specifically."""
    limiter = SlidingWindowLimiter(capacity=2, window_size=5.0)
    client = _build_app(limiter)

    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 200
    assert client.get("/ping").status_code == 429


@pytest.mark.parametrize(
    "limiter_factory",
    [
        lambda: TokenBucketLimiter(capacity=2, refill_rate=0),
        lambda: SlidingWindowLimiter(capacity=2, window_size=5.0),
    ],
    ids=["token_bucket", "sliding_window"],
)
def test_weighted_request_cost_through_middleware(limiter_factory):
    limiter = limiter_factory()
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter, tokens_requested=2)

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    client = TestClient(app)

    assert client.get("/ping").status_code == 200  # costs 2, capacity now 0
    assert client.get("/ping").status_code == 429  # no capacity left
