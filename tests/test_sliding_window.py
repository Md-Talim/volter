import time
from concurrent.futures.thread import ThreadPoolExecutor
from unittest.mock import patch

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


def test_low_traffic_key_is_still_evicted_via_time_trigger():
    """
    Regression test: eviction must not depend only on call volume.
    A single stale key with almost no traffic should still be swept
    once evict_interval has elapsed, even though evict_every (128 default)
    is never reached.
    """

    limiter = SlidingWindowLimiter(capacity=10, window_size=1.0, max_idle=5)
    limiter.allow("only-key")
    assert "only-key" in limiter._logs
    assert limiter._call_count < limiter.evict_every

    with patch.object(time, "monotonic", return_value=time.monotonic() + 10):
        # same key touches itself; last_access updates but doesn't evict itself
        limiter.allow("only-key")

    # a *different* low-traffic key should trigger sweep via time, not count
    with patch.object(time, "monotonic", return_value=time.monotonic() + 20):
        limiter.allow("second-key")

    assert "second-key" in limiter._logs
    assert "only-key" not in limiter._logs


def test_eviction_sweep_runs_after_evict_every_calls():
    """Count trigger: the sweep must also fire after evict_every calls, even when
    no time-trigger interval has elapsed."""
    limiter = SlidingWindowLimiter(
        capacity=10, window_size=1.0, max_idle=5, evict_interval=float("inf")
    )

    limiter.allow("stale-key")
    assert "stale-key" in limiter._logs

    # Jump forward past max_idle so stale-key qualifies for eviction.
    # evict_interval=inf disables the time trigger, so only the call count
    # can fire the sweep (which happens on the 128th call overall).
    with patch.object(time, "monotonic", return_value=time.monotonic() + 10):
        for i in range(127):
            limiter.allow(f"warm-{i}")

    assert "stale-key" not in limiter._logs
    assert "warm-0" in limiter._logs


def test_evicted_key_starts_fresh_with_full_capacity():
    """After eviction, a key must come back as a brand-new log: full capacity
    available again. Safe by design because max_idle defaults to 2x window_size,
    so evicted entries would have expired naturally anyway."""
    limiter = SlidingWindowLimiter(capacity=3, window_size=1.0, max_idle=2)

    # Exhaust the key
    for _ in range(3):
        assert limiter.allow("k") is True
    assert limiter.allow("k") is False

    # Go idle past max_idle; a different key triggers the sweep
    with patch.object(time, "monotonic", return_value=time.monotonic() + 3):
        limiter.allow("trigger")

    assert "k" not in limiter._logs

    # Key returns fresh with full capacity
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is True
    assert limiter.allow("k") is False
