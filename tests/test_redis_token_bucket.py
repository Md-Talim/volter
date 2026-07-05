import multiprocessing

import redis

from throttler.redis_token_bucket import RedisTokenBucketLimiter


def _worker(results_queue: multiprocessing.Queue) -> None:
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    limiter = RedisTokenBucketLimiter(client, capacity=10, refill_rate=0)
    results_queue.put(limiter.allow("shared-key"))


def test_atomic_across_processes():
    client = redis.Redis(host="localhost", port=6379, decode_responses=True)
    _ = client.delete("throttler:tb:shared-key")  # clean slate

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
