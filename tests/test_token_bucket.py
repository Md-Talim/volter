import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from volter import TokenBucketLimiter


def test_concurrent_requests_respect_capacity():
    limiter = TokenBucketLimiter(capacity=10, refill_rate=1)
    key = "test-key"

    with ThreadPoolExecutor(max_workers=20) as pool:
        results = list(pool.map(lambda _: limiter.allow(key), range(20)))

    assert sum(results) == 10


def test_stale_buckets_are_evicted():
    limiter = TokenBucketLimiter(capacity=10, refill_rate=1, max_idle=5)

    limiter.allow("stale-key")
    assert "stale-key" in limiter._buckets

    # Jump forward past max_idle
    with patch.object(time, "monotonic", return_value=time.monotonic() + 10):
        limiter.allow("fresh-key")

    # stale-key should be evicted, fresh-key should remain
    assert "stale-key" not in limiter._buckets
    assert "fresh-key" in limiter._buckets


def test_active_bucket_survive_eviction():
    limiter = TokenBucketLimiter(capacity=10, refill_rate=1, max_idle=5)

    limiter.allow("active-key")
    limiter.allow("idle-key")

    # Jump forward 3s (under max_idle), touch only active-key
    t = time.monotonic() + 3
    with patch.object(time, "monotonic", return_value=t):
        limiter.allow("active-key")

    # Jump forward another 3s (total 6x for idle-key, 3s for active-key), touch only active-key
    t2 = t + 3
    with patch.object(time, "monotonic", return_value=t2):
        limiter.allow("trigger-key")

    assert "active-key" in limiter._buckets
    assert "idle-key" not in limiter._buckets


def test_low_traffic_key_is_still_evicted_via_time_trigger():
    """
    Regression test: eviction must not depend only solely on call volume.
    A single stale key with almost no traffic should still be swept
    once evict_interval has elapsed, even though evict_every (128 default)
    is never reached.
    """

    limiter = TokenBucketLimiter(capacity=10, refill_rate=1, max_idle=5)

    limiter.allow("only-key")
    assert "only-key" in limiter._buckets
    assert limiter._call_count < limiter.evict_every

    with patch.object(time, "monotonic", return_value=time.monotonic() + 10):
        # same key touches itself; last_access updates but doesn't evict itself
        limiter.allow("only-key")

    # a *different* low-traffic key should trigger sweep via time, not count
    with patch.object(time, "monotonic", return_value=time.monotonic() + 20):
        limiter.allow("second-key")

    assert "only-key" not in limiter._buckets
    assert "second-key" in limiter._buckets
