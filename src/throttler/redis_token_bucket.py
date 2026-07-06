from typing import final

import redis

_TOKEN_BUCKET_SCRIPT = """
-- KEYS[1] = bucket key
-- ARGV[1] = capacity
-- ARGV[2] = refill rate (tokens per second)
-- ARGV[3] = tokens requested
-- ARGV[4] = ttl seconds (so idle keys clean themselves up)

local capacity = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])
local requested = tonumber(ARGV[3])
local ttl = tonumber(ARGV[4])

local time_result = redis.call('TIME')
local now = tonumber(time_result[1]) + tonumber(time_result[2]) / 1000000

local bucket = redis.call('HMGET', KEYS[1], 'tokens', 'last_refill')
local tokens = tonumber(bucket[1])
local last_refill = tonumber(bucket[2])

if tokens == nil then
    tokens = capacity
    last_refill = now
end

local elapsed = now - last_refill
if elapsed < 0 then elapsed = 0 end
tokens = math.min(capacity, tokens + elapsed * refill_rate)

local allowed = 0
if tokens >= requested then
    tokens = tokens - requested
    allowed = 1
end

redis.call('HSET', KEYS[1], 'tokens', tokens, 'last_refill', now)
redis.call('EXPIRE', KEYS[1], ttl)

return allowed
"""


@final
class RedisTokenBucketLimiter:
    def __init__(
        self,
        redis_client: redis.Redis,
        capacity: int,
        refill_rate: float,
        ttl: int = 3600,
        key_prefix: str = "throttler:tb",
    ):
        self.capacity = capacity
        self.refill_rate = refill_rate
        self.ttl = ttl
        self.key_prefix = key_prefix
        self._redis = redis_client
        self._script = redis_client.register_script(_TOKEN_BUCKET_SCRIPT)

    def allow(self, key: str, tokens_requested: float = 1.0) -> bool:
        full_key = f"{self.key_prefix}:{key}"
        result = self._script(
            keys=[full_key],
            args=[self.capacity, self.refill_rate, tokens_requested, self.ttl],
        )
        return bool(result)
