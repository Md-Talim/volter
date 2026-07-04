# throttler

A fast, thread-safe, and zero-dependency Python rate limiting library featuring highly optimized in-memory limiters.

`throttler` is designed from the ground up for concurrent Python applications. It provides precise, thread-safe rate limiting with a clean API, minimal overhead, and smart algorithmic optimizations.

## Features

- **Thread-Safe by Design**: Both limiters share a consistent, high-concurrency locking strategy. Instead of locking the entire limiter registry, `throttler` uses fine-grained, per-key locks. This ensures threads checking different keys never block each other.
- **Amortized $O(1)$ Sliding Window Log**: The naive sliding window log algorithm checks and prunes the entire request log on every request, resulting in $O(N)$ overhead. `throttler` optimizes this to an **amortized $O(1)$** complexity by maintaining a running sum of active token weights and only popping expired entries from the left of a double-ended queue (`deque`).
- **Zero Dependencies**: Built entirely using Python's standard library (`threading`, `collections.deque`, `time`).
- **Fully Typed**: Includes a `py.typed` marker file, making it fully compatible with PEP 561 and modern type checkers like Pyright and Mypy.

## Installation

_(Note: Currently in active development. Local development setup instructions below.)_

To install locally in editable mode for your project:

```bash
uv pip install -e .
# or using standard pip
pip install -e .
```

## Quick Start

### 1. Token Bucket Limiter

Best for smooth traffic control with support for brief bursts.

```python
from throttler import TokenBucketLimiter

# Capacity of 5 tokens, refills at a rate of 1.0 token per second
limiter = TokenBucketLimiter(capacity=5, refill_rate=1.0)

# Allow a single request for user "user_123"
if limiter.allow("user_123"):
    print("Request allowed!")
else:
    print("Rate limit exceeded!")
```

### 2. Sliding Window Log Limiter

Best for strict window-based limiting (e.g., max 10 requests per minute) with fractional weight support.

```python
from throttler import SlidingWindowLimiter

# Capacity of 10 requests/tokens per a 60-second window
limiter = SlidingWindowLimiter(capacity=10, window_size=60.0)

# Request with a custom token weight (defaults to 1.0)
if limiter.allow("api_client_456", tokens_requested=2.0):
    print("Heavy request allowed!")
else:
    print("Rate limit exceeded!")
```

## Deep Dive: How it Works

### Thread-Safety & Locking Strategy

Both `TokenBucketLimiter` and `SlidingWindowLimiter` use a two-tier locking pattern:

1. A global lock (`_buckets_lock` / `_logs_lock`) is used **only** when instantiating a new tracking bucket/log for a key that hasn't been seen before.
2. Once the tracker is retrieved (which is an $O(1)$ dictionary lookup), thread-safe operations are guaranteed by acquiring a dedicated, per-key lock (`bucket.lock` / `log.lock`).

This means traffic for `user_a` will never slow down or block traffic for `user_b`.

### Amortized $O(1)$ Sliding Window Log Optimization

A naive sliding window log stores every request timestamp and iterates through the entire log to sum active requests on every check.

`throttler` solves this by keeping a running counter (`current_sum`) of the weights currently inside the active window. When a new request arrives:

1. It pops expired timestamps from the left of the `deque` and subtracts their weights from `current_sum` (an efficient $O(1)$ operation per expired element).
2. It checks if `current_sum + tokens_requested` fits within the capacity.
3. If it fits, it appends the new request to the right of the `deque` and adds its weight to `current_sum`.

Because each request is appended once and popped at most once, the complexity of managing the window scale is amortized to $O(1)$ per check.

## Known Limitations

- **Memory Eviction**: Currently, keys that are no longer active remain in the internal dictionary registry. A natural next step and planned extension for the in-memory backend is implementing a TTL-based eviction or LRU cache mechanism to automatically clean up stale keys and prevent memory growth over long periods.

## What's Next

- **Redis-Backed Backend**: Distribute rate limiting state across multiple application instances.
- **FastAPI Middleware**: Out-of-the-box decorator and middleware support for fast FastAPI integration.
- **PyPI Package**: Making the project fully pip-installable directly from PyPI.
