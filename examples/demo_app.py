from fastapi import FastAPI

from throttler.fastapi_middleware import RateLimitMiddleware
from throttler.token_bucket import TokenBucketLimiter

app = FastAPI()
limiter = TokenBucketLimiter(capacity=5, refill_rate=1)

app.add_middleware(RateLimitMiddleware, limiter=limiter)


@app.get("/ping")
def ping():
    return {"message": "pong"}
