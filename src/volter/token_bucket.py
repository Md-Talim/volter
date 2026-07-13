import threading
import time
from dataclasses import dataclass, field
from typing import final


@dataclass
class _Bucket:
    tokens: float
    last_refill: float
    last_access: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


@final
class TokenBucketLimiter:
    def __init__(
        self,
        capacity: int,
        refill_rate: float,
        max_idle: float = 0.0,
        evict_every: int = 128,
        evict_interval: float = 0.0,
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.max_idle = (
            max_idle
            or (capacity / refill_rate if refill_rate > 0 else float("inf")) * 2
        )
        self.evict_every = 128
        self.evict_interval = evict_interval or self.max_idle / 4
        self._call_count = 0
        self._last_sweep = time.monotonic()
        self._buckets: dict[str, _Bucket] = {}
        self._buckets_lock = threading.Lock()

    def _get_bucket(self, key: str) -> _Bucket:
        bucket = self._buckets.get(key)
        if bucket is not None:
            return bucket

        with self._buckets_lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = _Bucket(tokens=self.capacity, last_refill=time.monotonic())
                self._buckets[key] = bucket
            return bucket

    def _evict_stale(self, now: float) -> None:
        with self._buckets_lock:
            stale = [
                key
                for key, bucket in self._buckets.items()
                if now - bucket.last_access > self.max_idle
            ]
            for k in stale:
                del self._buckets[k]

    def _evict_maybe(self, now: float) -> None:
        self._call_count += 1
        due_by_count = self._call_count >= self.evict_every
        due_by_time = (now - self._last_sweep) >= self.evict_interval
        if due_by_count or due_by_time:
            self._last_sweep = now
            self._call_count = 0
            self._evict_stale(now)

    def allow(self, key: str, tokens_requested: float = 1.0) -> bool:
        bucket = self._get_bucket(key)

        with bucket.lock:
            now = time.monotonic()
            elapsed = now - bucket.last_refill
            bucket.tokens = min(
                self.capacity, bucket.tokens + (elapsed * self.refill_rate)
            )
            bucket.last_refill = now
            bucket.last_access = now

            if bucket.tokens >= tokens_requested:
                bucket.tokens -= tokens_requested
                allowed = True
            else:
                allowed = False

        self._evict_maybe(now)
        return allowed
