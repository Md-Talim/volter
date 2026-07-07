import redis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from volter.fastapi_middleware import RateLimitMiddleware
from volter.redis_token_bucket import RedisTokenBucketLimiter


def test_redis_backed_limiter_through_middleware():
    client_redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
    _ = client_redis.delete("volter:tb:testclient")

    limiter = RedisTokenBucketLimiter(client_redis, capacity=3, refill_rate=0)

    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, limiter=limiter)

    @app.get("/ping")
    def ping():
        return {"message": "pong"}

    http_client = TestClient(app)

    for _ in range(3):
        assert http_client.get("/ping").status_code == 200

    response = http_client.get("/ping")
    assert response.status_code == 429


def test_redis_state_persists_across_separate_app_instances():
    """The whole point of the Redis backend: two independent app instances
    (simulated by two separate limiter objects, same Redis) share rate-limit state."""
    client_redis = redis.Redis(host="localhost", port=6379, decode_responses=True)
    _ = client_redis.delete("volter:tb:shared-instance-test")

    limiter_instance_a = RedisTokenBucketLimiter(
        client_redis, capacity=2, refill_rate=0
    )
    limiter_instance_b = RedisTokenBucketLimiter(
        client_redis, capacity=2, refill_rate=0
    )

    assert limiter_instance_a.allow("shared-instance-test") is True
    assert limiter_instance_b.allow("shared-instance-test") is True
    # capacity is now exhausted from instance A's perspective, even though
    # only instance B made the second call -- proves shared state, not per-object state
    assert limiter_instance_a.allow("shared-instance-test") is False
