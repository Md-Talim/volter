# volter

A rate-limiting engine and service in Go, with Redis-backed distributed state and a Python client.

> **Status:** v1 Go rewrite in progress.
>
> The previous Python implementation is frozen at [v0.1.2](https://pypi.org/project/volter/0.1.2/)
> and preserved on the [`legacy/python`](https://github.com/Md-Talim/volter/tree/legacy/python) branch.

## Planned

- **Go library:** token bucket, sliding window log, and GCRA; in-memory and Redis backends.
- **`volterd`:** HTTP service with YAML limits, hot reload, metrics, and graceful shutdown.
- **Python client:** `pip install volter` (v1), a thin async client and FastAPI middleware.

## Why

Most rate limiters are either a single-process library or a full API gateway.
Volter is the focused middle: one Go engine, usable embedded or as a small service,
with a stable HTTP contract for other languages.
