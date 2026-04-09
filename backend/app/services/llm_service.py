import logging
import time
import httpx
from app.utils.concurrency import get_model_limiter
from app.utils.model_monitor import record_model_request_sync
from app.utils.http_clients import build_sync_httpx_client

logger = logging.getLogger(__name__)

CHAT_CONNECT_TIMEOUT = 10.0
CHAT_READ_TIMEOUT = 300.0
CHAT_WRITE_TIMEOUT = 30.0
CHAT_POOL_TIMEOUT = 30.0
CHAT_MAX_ATTEMPTS = 3


def _is_retryable_llm_error(exc: Exception) -> bool:
    if isinstance(exc, (httpx.TimeoutException, httpx.NetworkError, httpx.RemoteProtocolError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status_code = exc.response.status_code
        return status_code == 429 or 500 <= status_code < 600
    return False


def call_llm_sync(
    api_url: str, api_key: str, model_name: str,
    prompt: str, system_prompt: str = "",
    max_tokens: int = 4096, model_limit: int = 64,
    user_id: str | None = None,
) -> str:
    """Synchronous LLM call for Celery tasks. OpenAI-compatible format."""
    limiter = get_model_limiter(model_name, model_limit)
    limiter.acquire_sync(wait=True)
    success = False
    try:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        url = api_url.rstrip("/")
        if not url.endswith("/chat/completions"):
            url += "/chat/completions"

        timeout = httpx.Timeout(
            connect=CHAT_CONNECT_TIMEOUT,
            read=CHAT_READ_TIMEOUT,
            write=CHAT_WRITE_TIMEOUT,
            pool=CHAT_POOL_TIMEOUT,
        )
        with build_sync_httpx_client(timeout=timeout) as client:
            for attempt in range(1, CHAT_MAX_ATTEMPTS + 1):
                try:
                    resp = client.post(
                        url,
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={"model": model_name, "messages": messages, "max_tokens": max_tokens},
                    )
                    resp.raise_for_status()
                    data = resp.json()
                    success = True
                    return data["choices"][0]["message"]["content"]
                except Exception as exc:
                    if attempt >= CHAT_MAX_ATTEMPTS or not _is_retryable_llm_error(exc):
                        raise
                    delay_s = min(2 ** (attempt - 1), 8)
                    logger.warning(
                        f"LLM request failed for model {model_name} (attempt {attempt}/{CHAT_MAX_ATTEMPTS}): "
                        f"{exc}; retry in {delay_s}s"
                    )
                    time.sleep(delay_s)
    finally:
        record_model_request_sync("chat", model_name, user_id=user_id, success=success)
        limiter.safe_release_sync()


def get_model_config_sync() -> dict:
    """Get model configs from DB synchronously for Celery tasks."""
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
    return configs


def get_chat_model_config(configs: dict) -> tuple[str, str, str]:
    """Return (api_url, api_key, model_name) for default chat model."""
    return (
        configs.get("chat_api_url", ""),
        configs.get("chat_api_key", ""),
        configs.get("chat_model_name", ""),
    )


def get_user_chat_model(user_id: str) -> tuple[str, str, str] | None:
    """Get user's custom chat model config. Returns None if not configured."""
    from sqlalchemy import create_engine, text
    from app.config import get_settings
    settings = get_settings()
    engine = create_engine(settings.SYNC_DATABASE_URL)
    with engine.connect() as conn:
        row = conn.execute(
            text("SELECT custom_chat_api_url, custom_chat_api_key, custom_chat_model_name FROM users WHERE id = :uid"),
            {"uid": user_id},
        ).fetchone()
    engine.dispose()
    if row and row[0] and row[1] and row[2]:
        return (row[0], row[1], row[2])
    return None
