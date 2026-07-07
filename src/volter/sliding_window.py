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
    lock: threading.Lock = field(default_factory=threading.Lock)


@final
class SlidingWindowLimiter:
    def __init__(self, capacity: int, window_size: float):
        self.capacity = capacity
        self.window_size = window_size
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

    def allow(self, key: str, tokens_requested: float = 1.0) -> bool:
        log = self._get_log(key)

        with log.lock:
            now = time.monotonic()
            cutoff = now - self.window_size

            while log.entries and log.entries[0][0] <= cutoff:
                _, weight = log.entries.popleft()
                log.current_sum -= weight

            if log.current_sum + tokens_requested <= self.capacity:
                log.entries.append((now, tokens_requested))
                log.current_sum += tokens_requested
                return True

            return False
