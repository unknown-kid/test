import logging
import re
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, unquote

from app.config import get_settings
from app.utils.redis_client import redis_client

logger = logging.getLogger(__name__)
settings = get_settings()

METRIC_TTL_SECONDS = 8 * 24 * 3600
MODEL_SET_KEY = "monitoring:model_refs"
USER_MODEL_SET_KEY = "monitoring:user_model_refs"


def _get_sync_redis():
    import redis as sync_redis
    return sync_redis.from_url(settings.REDIS_URL, decode_responses=True)


def normalize_model_type(model_type: str | None) -> str:
    raw = (model_type or "unknown").strip().lower()
    if not raw:
        raw = "unknown"
    # Keep keys readable and stable.
    return re.sub(r"[^a-z0-9_]+", "_", raw)[:50] or "unknown"


def encode_model_name(model_name: str | None) -> str:
    name = (model_name or "").strip()
    if not name:
        name = "unknown"
    return quote(name, safe="")


def decode_model_name(encoded_model_name: str) -> str:
    return unquote(encoded_model_name or "")


def recent_hour_buckets(hours: int = 24) -> list[str]:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return [
        (now - timedelta(hours=i)).strftime("%Y%m%d%H")
        for i in range(max(1, hours))
    ]


def _model_total_key(model_type: str, encoded_model_name: str, bucket: str) -> str:
    return f"monitoring:model:{model_type}:{encoded_model_name}:total:{bucket}"


def _model_fail_key(model_type: str, encoded_model_name: str, bucket: str) -> str:
    return f"monitoring:model:{model_type}:{encoded_model_name}:fail:{bucket}"


def _user_model_total_key(user_id: str, model_type: str, encoded_model_name: str, bucket: str) -> str:
    return f"monitoring:user:{user_id}:{model_type}:{encoded_model_name}:total:{bucket}"


def _user_model_fail_key(user_id: str, model_type: str, encoded_model_name: str, bucket: str) -> str:
    return f"monitoring:user:{user_id}:{model_type}:{encoded_model_name}:fail:{bucket}"


def record_model_request_sync(
    model_type: str,
    model_name: str | None,
    *,
    user_id: str | None = None,
    success: bool = True,
):
    model_type_norm = normalize_model_type(model_type)
    model_name_encoded = encode_model_name(model_name)
    model_ref = f"{model_type_norm}:{model_name_encoded}"
    bucket = recent_hour_buckets(1)[0]

    r = None
    try:
        r = _get_sync_redis()
        pipe = r.pipeline(transaction=False)
        total_key = _model_total_key(model_type_norm, model_name_encoded, bucket)
        pipe.incr(total_key)
        pipe.expire(total_key, METRIC_TTL_SECONDS)

        if not success:
            fail_key = _model_fail_key(model_type_norm, model_name_encoded, bucket)
            pipe.incr(fail_key)
            pipe.expire(fail_key, METRIC_TTL_SECONDS)

        pipe.sadd(MODEL_SET_KEY, model_ref)

        if user_id:
            user_ref = f"{user_id}:{model_type_norm}:{model_name_encoded}"
            user_total_key = _user_model_total_key(user_id, model_type_norm, model_name_encoded, bucket)
            pipe.sadd(USER_MODEL_SET_KEY, user_ref)
            pipe.incr(user_total_key)
            pipe.expire(user_total_key, METRIC_TTL_SECONDS)
            if not success:
                user_fail_key = _user_model_fail_key(user_id, model_type_norm, model_name_encoded, bucket)
                pipe.incr(user_fail_key)
                pipe.expire(user_fail_key, METRIC_TTL_SECONDS)

        pipe.execute()
    except Exception as e:
        logger.warning(f"record_model_request_sync failed: {e}")
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


async def record_model_request(
    model_type: str,
    model_name: str | None,
    *,
    user_id: str | None = None,
    success: bool = True,
):
    model_type_norm = normalize_model_type(model_type)
    model_name_encoded = encode_model_name(model_name)
    model_ref = f"{model_type_norm}:{model_name_encoded}"
    bucket = recent_hour_buckets(1)[0]
    try:
        pipe = redis_client.pipeline(transaction=False)
        total_key = _model_total_key(model_type_norm, model_name_encoded, bucket)
        pipe.incr(total_key)
        pipe.expire(total_key, METRIC_TTL_SECONDS)

        if not success:
            fail_key = _model_fail_key(model_type_norm, model_name_encoded, bucket)
            pipe.incr(fail_key)
            pipe.expire(fail_key, METRIC_TTL_SECONDS)

        pipe.sadd(MODEL_SET_KEY, model_ref)

        if user_id:
            user_ref = f"{user_id}:{model_type_norm}:{model_name_encoded}"
            user_total_key = _user_model_total_key(user_id, model_type_norm, model_name_encoded, bucket)
            pipe.sadd(USER_MODEL_SET_KEY, user_ref)
            pipe.incr(user_total_key)
            pipe.expire(user_total_key, METRIC_TTL_SECONDS)
            if not success:
                user_fail_key = _user_model_fail_key(user_id, model_type_norm, model_name_encoded, bucket)
                pipe.incr(user_fail_key)
                pipe.expire(user_fail_key, METRIC_TTL_SECONDS)

        await pipe.execute()
    except Exception as e:
        logger.warning(f"record_model_request failed: {e}")


async def _sum_keys(keys: list[str]) -> int:
    if not keys:
        return 0
    values = await redis_client.mget(keys)
    total = 0
    for v in values:
        try:
            total += int(v or 0)
        except Exception:
            continue
    return total


async def get_model_usage_snapshot(hours: int = 24, max_user_rows: int = 200) -> dict:
    buckets = recent_hour_buckets(hours)
    model_usage_rows: list[dict] = []
    user_model_usage_rows: list[dict] = []

    model_refs = await redis_client.smembers(MODEL_SET_KEY)
    for ref in model_refs:
        parts = ref.split(":", 1)
        if len(parts) != 2:
            continue
        model_type, encoded_model_name = parts
        total_keys = [_model_total_key(model_type, encoded_model_name, b) for b in buckets]
        fail_keys = [_model_fail_key(model_type, encoded_model_name, b) for b in buckets]
        requests_24h = await _sum_keys(total_keys)
        failed_24h = await _sum_keys(fail_keys)
        if requests_24h <= 0 and failed_24h <= 0:
            continue
        model_usage_rows.append({
            "model_type": model_type,
            "model_name": decode_model_name(encoded_model_name) or "unknown",
            "requests_24h": requests_24h,
            "failed_24h": failed_24h,
            "success_rate_24h": round(
                ((requests_24h - failed_24h) / requests_24h) * 100, 2
            ) if requests_24h > 0 else None,
        })

    model_usage_rows.sort(key=lambda x: x["requests_24h"], reverse=True)

    user_refs = await redis_client.smembers(USER_MODEL_SET_KEY)
    for ref in user_refs:
        parts = ref.split(":", 2)
        if len(parts) != 3:
            continue
        user_id, model_type, encoded_model_name = parts
        total_keys = [_user_model_total_key(user_id, model_type, encoded_model_name, b) for b in buckets]
        fail_keys = [_user_model_fail_key(user_id, model_type, encoded_model_name, b) for b in buckets]
        requests_24h = await _sum_keys(total_keys)
        failed_24h = await _sum_keys(fail_keys)
        if requests_24h <= 0 and failed_24h <= 0:
            continue
        user_model_usage_rows.append({
            "user_id": user_id,
            "model_type": model_type,
            "model_name": decode_model_name(encoded_model_name) or "unknown",
            "requests_24h": requests_24h,
            "failed_24h": failed_24h,
            "success_rate_24h": round(
                ((requests_24h - failed_24h) / requests_24h) * 100, 2
            ) if requests_24h > 0 else None,
        })

    user_model_usage_rows.sort(key=lambda x: x["requests_24h"], reverse=True)
    if max_user_rows > 0:
        user_model_usage_rows = user_model_usage_rows[:max_user_rows]

    return {
        "model_usage_24h": model_usage_rows,
        "user_model_usage_24h": user_model_usage_rows,
    }
