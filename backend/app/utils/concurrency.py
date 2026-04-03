import asyncio
import logging
import time
from app.utils.redis_client import redis_client

logger = logging.getLogger(__name__)


def _get_sync_redis():
    import redis as sync_redis
    from app.config import get_settings
    settings = get_settings()
    return sync_redis.from_url(settings.REDIS_URL)


def _normalize_limit(limit: int, default: int) -> int:
    try:
        value = int(str(limit))
    except Exception:
        return default
    return value if value > 0 else default


class ConcurrencyLimiter:
    """Redis-based atomic concurrency limiter."""

    def __init__(self, key: str, limit: int, timeout: int = 3600):
        self.key = key
        self.limit = limit
        self.timeout = timeout

    async def acquire(self, wait: bool = True, poll_interval: float = 1.0) -> bool:
        while True:
            current = await redis_client.incr(self.key)
            # Always refresh TTL to prevent stale keys
            await redis_client.expire(self.key, self.timeout)
            if current <= self.limit:
                return True
            # Over limit, decrement and wait or fail
            await redis_client.decr(self.key)
            if not wait:
                return False
            await asyncio.sleep(poll_interval)

    async def release(self):
        try:
            val = await redis_client.decr(self.key)
            if val < 0:
                await redis_client.set(self.key, 0)
        except Exception as e:
            logger.error(f"Failed to release concurrency key {self.key}: {e}")

    def acquire_sync(self, wait: bool = True, poll_interval: float = 1.0) -> bool:
        """Synchronous version for Celery tasks."""
        r = _get_sync_redis()
        while True:
            current = r.incr(self.key)
            # Always refresh TTL to prevent stale keys
            r.expire(self.key, self.timeout)
            if current <= self.limit:
                return True
            r.decr(self.key)
            if not wait:
                return False
            time.sleep(poll_interval)

    def release_sync(self):
        """Release with retry. Raises on persistent failure."""
        max_retries = 3
        for attempt in range(max_retries):
            try:
                r = _get_sync_redis()
                val = r.decr(self.key)
                if val < 0:
                    r.set(self.key, 0)
                return
            except Exception as e:
                logger.warning(f"release_sync attempt {attempt + 1} failed for {self.key}: {e}")
                if attempt < max_retries - 1:
                    time.sleep(1 * (attempt + 1))
                else:
                    logger.error(f"release_sync gave up for {self.key} after {max_retries} attempts")
                    raise

    def safe_release_sync(self):
        """Release that never raises — for use in finally blocks."""
        try:
            self.release_sync()
        except Exception as e:
            logger.error(f"safe_release_sync failed for {self.key}, slot leaked: {e}")


def get_paper_limiter(limit: int = 10) -> ConcurrencyLimiter:
    return ConcurrencyLimiter("concurrency:paper", _normalize_limit(limit, 10))


def get_model_limiter(model_name: str = "default", limit: int = 64) -> ConcurrencyLimiter:
    safe_model_name = model_name or "default"
    return ConcurrencyLimiter(f"concurrency:model:{safe_model_name}", _normalize_limit(limit, 64))


def get_step_limiter(step: str, limit: int = 6) -> ConcurrencyLimiter:
    safe_step = step or "unknown"
    return ConcurrencyLimiter(f"concurrency:step:{safe_step}", _normalize_limit(limit, 6))


def get_worker_limiter(limit: int = 18) -> ConcurrencyLimiter:
    return ConcurrencyLimiter("concurrency:worker_total", _normalize_limit(limit, 18))
