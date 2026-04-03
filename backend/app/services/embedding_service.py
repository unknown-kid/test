import logging
import time
import httpx
from app.utils.concurrency import get_model_limiter
from app.utils.model_monitor import record_model_request_sync

logger = logging.getLogger(__name__)

EMBED_CONNECT_TIMEOUT = 10.0
EMBED_READ_TIMEOUT = 180.0
EMBED_WRITE_TIMEOUT = 30.0
EMBED_POOL_TIMEOUT = 30.0
EMBED_MAX_ATTEMPTS = 3


def _is_retryable_embedding_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or 500 <= status_code < 600
    return False


def embed_text_sync(
    api_url: str, api_key: str, model_name: str,
    text: str, model_limit: int = 64,
    user_id: str | None = None,
) -> list[float]:
    """Synchronous embedding call for Celery tasks. OpenAI-compatible format."""
    limiter = get_model_limiter(model_name, model_limit)
    limiter.acquire_sync(wait=True)
    success = False
    try:
        url = api_url.rstrip("/")
        if not url.endswith("/embeddings"):
            url += "/embeddings"

        timeout = httpx.Timeout(
            connect=EMBED_CONNECT_TIMEOUT,
            read=EMBED_READ_TIMEOUT,
            write=EMBED_WRITE_TIMEOUT,
            pool=EMBED_POOL_TIMEOUT,
        )
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(1, EMBED_MAX_ATTEMPTS + 1):
                try:
                    resp = client.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": model_name, "input": text},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    success = True
                    return data["data"][0]["embedding"]
                except Exception as exc:
                    if attempt >= EMBED_MAX_ATTEMPTS or not _is_retryable_embedding_error(exc):
                        raise
                    delay_s = min(2 ** (attempt - 1), 8)
                    logger.warning(
                        f"Embedding request failed for model {model_name} (attempt {attempt}/{EMBED_MAX_ATTEMPTS}): "
                        f"{exc}; retry in {delay_s}s"
                    )
                    time.sleep(delay_s)
    finally:
        record_model_request_sync("embedding", model_name, user_id=user_id, success=success)
        limiter.safe_release_sync()


def embed_texts_batch_sync(
    api_url: str, api_key: str, model_name: str,
    texts: list[str], model_limit: int = 64,
    user_id: str | None = None,
) -> list[list[float]]:
    """Batch embedding for multiple texts."""
    limiter = get_model_limiter(model_name, model_limit)
    limiter.acquire_sync(wait=True)
    success = False
    try:
        url = api_url.rstrip("/")
        if not url.endswith("/embeddings"):
            url += "/embeddings"

        timeout = httpx.Timeout(
            connect=EMBED_CONNECT_TIMEOUT,
            read=EMBED_READ_TIMEOUT,
            write=EMBED_WRITE_TIMEOUT,
            pool=EMBED_POOL_TIMEOUT,
        )
        with httpx.Client(timeout=timeout) as client:
            for attempt in range(1, EMBED_MAX_ATTEMPTS + 1):
                try:
                    resp = client.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": model_name, "input": texts},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    success = True
                    return [item["embedding"] for item in sorted(data["data"], key=lambda x: x["index"])]
                except Exception as exc:
                    if attempt >= EMBED_MAX_ATTEMPTS or not _is_retryable_embedding_error(exc):
                        raise
                    delay_s = min(2 ** (attempt - 1), 8)
                    logger.warning(
                        f"Batch embedding request failed for model {model_name} (attempt {attempt}/{EMBED_MAX_ATTEMPTS}): "
                        f"{exc}; retry in {delay_s}s"
                    )
                    time.sleep(delay_s)
    finally:
        record_model_request_sync("embedding", model_name, user_id=user_id, success=success)
        limiter.safe_release_sync()


def get_embedding_config_sync() -> tuple[str, str, str]:
    """Get embedding model config from DB."""
    from sqlalchemy import create_engine, text
    from app.config import get_settings
    settings = get_settings()
    engine = create_engine(settings.SYNC_DATABASE_URL)
    configs = {}
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT key, value FROM system_config")).fetchall()
        for row in rows:
            configs[row[0]] = row[1]
    engine.dispose()
    return (
        configs.get("embedding_api_url", ""),
        configs.get("embedding_api_key", ""),
        configs.get("embedding_model_name", ""),
    )
