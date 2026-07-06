import uuid
from typing import final

import redis

_SLIDING_WINDOW_SCRIPT = """
-- KEYS[1] = zset key
-- ARGV[1] = capacity
-- ARGV[2] = window_size (seconds)
-- ARGV[3] = ttl seconds
-- ARGV[4] = unique member id

local capacity = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local ttl = tonumber(ARGV[3])
local member_id = ARGV[4]

local time_result = redis.call('TIME')
local now = tonumber(time_result[1]) + tonumber(time_result[2]) / 1000000
local cutoff = now - window

redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', cutoff)

local count = redis.call('ZCARD', KEYS[1])

local allowed = 0
if count < capacity then
    redis.call('ZADD', KEYS[1], now, member_id)
    redis.call('EXPIRE', KEYS[1], ttl)
    allowed = 1
end

return allowed
"""


@final
class RedisSlidingWindowLimiter:
    def __init__(
        self,
        redis_client: redis.Redis,
        capacity: int,
        window_size: float,
        ttl: int | None = None,
        key_prefix: str = "throttler:sw",
    ):
        self.capacity = capacity
        self.window_size = window_size
        self.ttl = ttl if ttl is not None else int(window_size) + 1
        self.key_prefix = key_prefix
        self._redis = redis_client
        self._script = redis_client.register_script(_SLIDING_WINDOW_SCRIPT)

    def allow(self, key: str) -> bool:
        full_key = f"{self.key_prefix}:{key}"
        member_id = uuid.uuid4().hex
        result = self._script(
            keys=[full_key], args=[self.capacity, self.window_size, self.ttl, member_id]
        )
        return bool(result)
