from unittest.mock import patch
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


def test_stale_logs_are_evicted():
    limiter = SlidingWindowLimiter(capacity=5, window_size=1.0, max_idle=5)

    limiter.allow("stale-key")
    assert "stale-key" in limiter._logs

    # Jump forward past max_idle
    with patch.object(time, "monotonic", return_value=time.monotonic() + 10):
        limiter.allow("fresh-key")

    assert "stale-key" not in limiter._logs
    assert "fresh-key" in limiter._logs

def test_active_logs_survive_eviction():
    limiter = SlidingWindowLimiter(capacity=5, window_size=1.0, max_idle=5)

    limiter.allow("active-key")
    limiter.allow("idle-key")

    # Jump forward 3s (under max_idle), touch only active-key
    t = time.monotonic() + 3
    with patch.object(time, "monotonic", return_value=t):
        limiter.allow("active-key")

    # Jump forward another 3s (total 6s for idle-key, 3s for active-key)
    t2 = t + 3
    with patch.object(time, "monotonic", return_value=t2):
        limiter.allow("trigger-key")

    assert "active-key" in limiter._logs
    assert "idle-key" not in limiter._logs

    