import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import final


@dataclass
class _Log:
    # A queue storing (timestamp, weight) tuples of allowed requests
    entries: deque[tuple[float, float]] = field(default_factory=deque)
    # Total weight (sum of tokens/requests) currently in the queue
    current_sum: float = 0.0
    last_access: float = 0.0
    lock: threading.Lock = field(default_factory=threading.Lock)


@final
class SlidingWindowLimiter:
    def __init__(
        self,
        capacity: int,
        window_size: float,
        max_idle: float = 0.0,
        evict_every: int = 128,
        evict_interval: float = 0.0,
    ):
        self.capacity = capacity
        self.window_size = window_size
        self.max_idle = max_idle or window_size * 2
        self.evict_every = 128
        self.evict_interval = evict_interval or self.max_idle / 4
        self._call_count = 0
        self._last_sweep = time.monotonic()
        self._logs: dict[str, _Log] = {}
        self._logs_lock = threading.Lock()

    def _get_log(self, key: str) -> _Log:
        log = self._logs.get(key)
        if log is not None:
            return log

        with self._logs_lock:
            log = self._logs.get(key)
            if log is None:
                log = _Log()
                self._logs[key] = log
            return log

    def _evict_stale(self, now: float) -> None:
        with self._logs_lock:
            stale = [
                k
                for k, log in self._logs.items()
                if now - log.last_access > self.max_idle
            ]
            for k in stale:
                del self._logs[k]

    def _evict_maybe(self, now: float) -> None:
        self._call_count += 1
        due_by_count = self._call_count >= self.evict_every
        due_by_time = (now - self._last_sweep) >= self.evict_interval
        if due_by_count or due_by_time:
            self._last_sweep = now
            self._call_count = 0
            self._evict_stale(now)

    def allow(self, key: str, tokens_requested: float = 1.0) -> bool:
        log = self._get_log(key)

        with log.lock:
            now = time.monotonic()
            cutoff = now - self.window_size
            log.last_access = now

            while log.entries and log.entries[0][0] <= cutoff:
                _, weight = log.entries.popleft()
                log.current_sum -= weight

            if log.current_sum + tokens_requested <= self.capacity:
                log.entries.append((now, tokens_requested))
                log.current_sum += tokens_requested
                allowed = True
            else:
                allowed = False

        self._evict_maybe(now)
        return allowed
