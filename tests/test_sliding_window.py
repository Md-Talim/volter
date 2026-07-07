import time
from concurrent.futures.thread import ThreadPoolExecutor

from volter.sliding_window import SlidingWindowLimiter


def test_burst_up_to_capacity_succeeds():
    limiter = SlidingWindowLimiter(capacity=5, window_size=1.0)
    results = [limiter.allow("k") for _ in range(5)]
    assert all(results)
    assert limiter.allow("k") is False  # 6th request in the same instant should fail


def test_entries_expire_after_window():
    limiter = SlidingWindowLimiter(capacity=1, window_size=0.1)
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
    time.sleep(0.15)
    assert limiter.allow("k") is True  # window has passed, slot freed up


def test_weighted_requests_consume_proportional_capacity():
    limiter = SlidingWindowLimiter(capacity=10, window_size=1.0)
    assert limiter.allow("k", tokens_requested=7) is True
    assert limiter.allow("k", tokens_requested=4) is False  # 7+4 > 10
    assert limiter.allow("k", tokens_requested=3) is True


def test_concurrent_request_capacity():
    limiter = SlidingWindowLimiter(capacity=10, window_size=5.0)
    with ThreadPoolExecutor(max_workers=20) as pool:

        def allow_request(_: int) -> bool:
            return limiter.allow("k")

        results = list(pool.map(allow_request, range(20)))
    assert sum(results) == 10
