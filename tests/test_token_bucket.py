from concurrent.futures import ThreadPoolExecutor

from throttler import TokenBucketLimiter


def test_concurrent_requests_respect_capacity():
    limiter = TokenBucketLimiter(capacity=10, refill_rate=0)
    key = "test-key"

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: limiter.allow(key), range(20)))

    assert sum(results) == 10
