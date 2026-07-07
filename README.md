# volter

A rate limiting library for Python, implementing **token bucket** and **sliding window log** algorithms, each with an in-memory backend and a Redis-backed backend for multi-process correctness. Ships with FastAPI middleware for drop-in use.

```python
from volter import TokenBucketLimiter

limiter = TokenBucketLimiter(capacity=10, refill_rate=1)  # 10 requests, refills 1/sec

if limiter.allow("user:123"):
    process_request()
else:
    reject_with_429()
```

## Why this exists

Most rate limiter examples online implement one algorithm, in memory, in a single file, and stop there. That's fine for a demo but doesn't reflect how rate limiting actually gets used in production: behind a load balancer, across multiple app instances, sharing state that has to stay correct under concurrent access. This project implements two different algorithms with genuinely different tradeoffs, and takes each one from "correct in a single process" to "correct across N processes sharing Redis" — including the concurrency bugs that show up at each step and how they were fixed.

## Installation

```bash
pip install volter              # core only — in-memory limiters, zero dependencies
pip install volter[redis]       # + Redis-backed limiters
pip install volter[fastapi]     # + FastAPI middleware
pip install volter[redis,fastapi]  # everything
```

The core package (`TokenBucketLimiter`, `SlidingWindowLimiter`) has **no third-party dependencies**. `redis` and `fastapi` are only imported inside their own modules (`redis_token_bucket.py`, `redis_sliding_window.py`, `fastapi_middleware.py`), so installing the bare package never forces you to pull in libraries you don't need. Importing one of those modules without installing its extra fails with a plain `ModuleNotFoundError` — that's expected, not a bug.

## The two algorithms, and why both exist

|                    | Token Bucket                                                                     | Sliding Window Log                                                      |
| ------------------ | -------------------------------------------------------------------------------- | ----------------------------------------------------------------------- |
| **Memory per key** | O(1) — two numbers (`tokens`, `last_refill`)                                     | O(requests in window) — one entry per allowed request until it ages out |
| **Precision**      | Approximate, allows short bursts up to `capacity`, then smooths to `refill_rate` | Exact count over the exact window, no averaging                         |
| **Best for**       | APIs that tolerate bursty-then-steady traffic (most APIs)                        | Cases where an exact count matters more than memory cost                |

Neither algorithm is strictly better — this is a genuine engineering tradeoff, not a "pick the fancier one" situation. Token bucket's O(1) memory comes at the cost of not tracking individual requests, which is exactly what gives it burst tolerance. Sliding window log's exact precision comes at the cost of storing a timestamp per request, which is exactly what gives it precision.

## Design decisions

### Per-key locking, not one global lock

Every in-memory limiter manages many independent buckets/logs — one per key (e.g. per user, per IP). Concurrency safety is implemented at **two levels**:

- An outer lock (`_buckets_lock` / `_logs_lock`) guards only the _creation_ of a new key's state, held very briefly.
- A per-key lock guards the actual read-compute-write logic for that one key.

This means a request for `user:123` never blocks a concurrent request for `user:456` — they hold different locks entirely. A single global lock would serialize _all_ traffic regardless of key, which defeats much of the point under real concurrent load.

**Double-checked locking** is used for bucket/log creation: the common path (key already exists) reads the dict without taking any lock at all; the outer lock is only paid once, the first time a new key appears.

### `time.monotonic()`, not `time.time()`

Elapsed-time calculations (used in token bucket's refill and sliding window's cutoff) use `time.monotonic()` deliberately. `time.time()` is wall-clock time and can jump backward — NTP sync, manual clock changes, VM pause/resume — which would make `elapsed` negative and corrupt the refill/eviction math. `time.monotonic()` is guaranteed never to go backward within a process.

### `current_sum` running total instead of summing on every call (sliding window)

A naive sliding window log recomputes its count by iterating every entry in the window on each call — O(n) per request. This implementation instead maintains a running total (`current_sum`) that's only adjusted as entries are evicted or added, making each call O(k) where k is just the number of _expired_ entries evicted that round — amortized O(1), not O(n).

### Weighted requests (`tokens_requested`)

Both in-memory limiters accept an optional `tokens_requested` parameter (default `1`), so a single call can represent a variable-cost request — e.g. a search endpoint costing 1 unit vs. a bulk export costing 20, the same pattern used by GitHub's and Stripe's own rate limiters. Callers who don't need this never have to think about it; the default keeps the simple case simple.

**This is dropped in the Redis-backed MVP** — see below.

## Redis-backed limiters: why Lua, and what it's doing

### The problem

The in-memory implementation protects its read-compute-write sequence with a `threading.Lock`. That works because all callers share one process's memory. Across multiple app server processes, there's no shared memory to hold a lock in — and Redis itself doesn't give you multi-command atomicity for free: `HMGET` → compute → `HSET` is three separate round trips, and another process can read the same stale value in between, causing both to compute independently off the same starting point (the same check-then-act race the in-process lock was preventing, just relocated).

Redis is single-threaded: any _single_ command is atomic with respect to every other client, because the event loop never interleaves commands. A Lua script sent via `EVAL`/`EVALSHA` runs as **one command** from the event loop's perspective — nothing else executes while it runs. The script becomes the critical section: the same role `bucket.lock` played in-process, just relocated into Redis's own execution model instead of a Python-level mutex.

`MULTI`/`EXEC` was considered and rejected for this: it queues commands atomically but doesn't let you branch on a value read _inside_ the transaction without an additional `WATCH` + optimistic-retry dance. A Lua script can read, branch, and write in one indivisible step, which maps directly onto this algorithm's logic.

### Token bucket (Redis)

Implemented as a Lua script operating on a Redis hash (`tokens`, `last_refill` fields):

1. Read current `tokens` / `last_refill` from the hash (or treat as a fresh bucket if the key doesn't exist).
2. Compute elapsed time using Redis's own `TIME` command — **not** a timestamp passed in from Python — so there's no clock-skew risk between different app servers with slightly different clocks.
3. Refill, check against capacity, decrement if allowed, write back with `HSET`.
4. `EXPIRE` the key with a configurable TTL.

`register_script()` (via `redis-py`) handles caching the script server-side and automatically falls back from `EVALSHA` to a full `EVAL` if Redis responds `NOSCRIPT` (e.g. after a restart or `SCRIPT FLUSH`) — no manual `SCRIPT LOAD` management needed.

### Sliding window log (Redis)

Implemented using a Redis **sorted set** (ZSET) — score = timestamp, member = a unique ID per request:

1. `ZREMRANGEBYSCORE key -inf cutoff` — evict every member scored at or below the cutoff. This is the direct Redis-native equivalent of the in-memory version's `while entries[0][0] <= cutoff: popleft()` loop, and it's cheap for the same reason: a sorted set is backed by a skip list, so eviction walks from the low end and stops as soon as it clears the cutoff, rather than scanning every member.
2. `ZCARD key` — count remaining members. This plays the same role `current_sum` played in-process.
3. If under capacity, `ZADD key now member_id` and `EXPIRE`.

**Why a unique member ID, not the timestamp as the member:** a sorted set's members are unique — adding the same member twice just updates its score rather than creating a second entry. If the timestamp itself were used as the member, two requests landing at the same microsecond (plausible under real load, since Redis's `TIME` has microsecond resolution) would collide, and the second `ZADD` would silently overwrite the first instead of adding a new entry — undercounting real traffic and letting more requests through than the configured capacity. A `uuid4` generated per request guarantees two simultaneous requests still occupy two distinct ZSET entries. The score does the "when" work; the member does the "this is one distinct, countable event" work — deliberately decoupled.

**Why the UUID is generated in Python, not inside the Lua script:** Redis requires scripts to be deterministic, since their effects (not the script itself) get replicated to replicas — calls to random number generators or non-`TIME` clock reads aren't available inside a script for this reason. Randomness has to be manufactured outside the script and passed in as an argument.

### Advantage of the Redis-backed version: expiry is built in

The in-memory limiters have a known, documented limitation (see below): their internal dict of per-key state grows forever, since nothing ever removes an entry once a key has been seen. The Redis-backed versions don't have this problem — every write is paired with an `EXPIRE`, so idle keys clean themselves up naturally as part of Redis's own key expiry mechanism. No manual cleanup logic was needed to get this for free.

### Dropped from the Redis MVP: weighted `tokens_requested`

The in-memory limiters support a variable request cost via `tokens_requested`. This is intentionally **not** carried over to the Redis-backed sliding window implementation in this MVP — supporting it would mean encoding a weight into each ZSET member and summing weights on read instead of a plain `ZCARD` count, adding real complexity for a feature not yet exercised elsewhere in the project. This is a deliberate scope cut, not an oversight; extending it is a natural next step (see below).

### Verifying atomicity: multi-process tests, not multi-thread

The in-memory limiters' concurrency tests use `ThreadPoolExecutor` — sufficient there because threads share process memory, so it genuinely exercises the `threading.Lock`. That same approach would prove nothing for the Redis-backed versions, since the whole point is correctness **across separate processes** that share no memory at all. Their tests instead spin up real OS processes (`multiprocessing.Process`), each with its own Redis client, all hammering the same key concurrently, and assert that exactly `capacity` requests succeed — no over-admission, despite zero shared process state.

## FastAPI middleware

```python
from fastapi import FastAPI
from volter.token_bucket import TokenBucketLimiter
from volter.fastapi_middleware import RateLimitMiddleware

app = FastAPI()
limiter = TokenBucketLimiter(capacity=5, refill_rate=1)
app.add_middleware(RateLimitMiddleware, limiter=limiter)
```

Rejected requests get a `429` with a `Retry-After` header. The middleware is written against a `Protocol` (anything with `.allow(key, tokens_requested) -> bool`), not a concrete class — it works unmodified with any of the four limiter implementations, which is a direct payoff of keeping all four classes' interfaces identical from the start. The rate-limit key defaults to client IP but accepts a custom `key_func`, e.g. to key by API key or authenticated user ID instead.

## Known limitations / natural next steps

- **In-memory dict growth**: `_buckets` / `_logs` never evict entries for keys that stop being used — every key ever seen stays in memory for the process lifetime. A TTL-based eviction (e.g. a background sweep, or lazy eviction on access) would be the natural fix. The Redis-backed versions don't share this problem, since `EXPIRE` handles it natively.
- **Weighted requests on the Redis sliding window**: dropped from this MVP, as explained above — implementable by encoding weight into ZSET members and summing instead of counting.
- **`Retry-After` is currently a fixed placeholder**, not computed from actual time-until-next-allowed-request. Each algorithm could expose a `retry_after(key) -> float` method (token bucket: time until enough tokens accumulate; sliding window: time until the oldest entry expires) for the middleware to report precisely instead of a constant.

## Development

```bash
uv sync --all-extras       # install everything, including redis/fastapi extras and dev deps
uv run pytest              # run the full test suite
uv run pytest -v tests/test_redis_token_bucket.py   # requires a local Redis (see below)
```

Redis-backed tests need a running Redis instance:

```bash
docker run -d --name volter-redis -p 6379:6379 redis:7-alpine
```
