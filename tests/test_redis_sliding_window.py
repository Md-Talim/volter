import multiprocessing

import redis

from throttler.redis_sliding_window import RedisSlidingWindowLimiter


def _worker(results_queue: multiprocessing.Queue) -> None:
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    limiter = RedisSlidingWindowLimiter(client, capacity=10, window_size=5.0)
    results_queue.put(limiter.allow("shared-key"))


def test_atomic_across_processes():
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    _ = client.delete("throttler:sw:shared-key")

    results_queue = multiprocessing.Queue()
    processes = [
        multiprocessing.Process(target=_worker, args=(results_queue,))
        for _ in range(20)
    ]

    for p in processes:
        p.start()
    for p in processes:
        p.join()

    results = [results_queue.get() for _ in processes]
    assert sum(results) == 10


def test_expired_entries_free_up_capacity():
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    _ = client.delete("throttler:sw:shared-key")

    limiter = RedisSlidingWindowLimiter(client, capacity=1, window_size=0.2)
    assert limiter.allow("expiry-test") is True
    assert limiter.allow("expiry-test") is False

    import time

    time.sleep(0.25)
    assert limiter.allow("expiry-test") is True


def test_zset_member_uniqueness_under_same_timestamp(monkeypatch):
    """Regression test for the member-id collision, if two requests landed at the exact
    same score without unique members, ZADD would silently overwrite instead of adding
    a second entry."""
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    _ = client.delete("throttler:sw:shared-key")

    limiter = RedisSlidingWindowLimiter(client, capacity=2, window_size=5.0)

    assert limiter.allow("collision-test") is True
    assert limiter.allow("collision-test") is True
    assert client.zcard("throttler:sw:collision-test") == 2
