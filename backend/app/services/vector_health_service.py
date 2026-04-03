import json
import logging
from typing import Any

import redis as sync_redis
from pymilvus import Collection, utility

from app.config import get_settings
from app.services.embedding_service import get_embedding_config_sync
from app.services.milvus_service import ensure_milvus_connection

logger = logging.getLogger(__name__)
settings = get_settings()

_REPAIR_LOCK_TTL_SECONDS = 30 * 60


def _get_sync_redis():
    return sync_redis.from_url(settings.REDIS_URL, decode_responses=True)


def normalize_step_status_map(raw_step_map: Any) -> dict[str, str]:
    if isinstance(raw_step_map, str):
        try:
            raw_step_map = json.loads(raw_step_map)
        except Exception:
            raw_step_map = {}
    src = raw_step_map if isinstance(raw_step_map, dict) else {}
    return {
        "chunking": str(src.get("chunking") or "pending").lower(),
        "title": str(src.get("title") or "pending").lower(),
        "abstract": str(src.get("abstract") or "pending").lower(),
        "keywords": str(src.get("keywords") or "pending").lower(),
        "report": str(src.get("report") or "pending").lower(),
    }


def get_paper_vector_presence_sync(paper_id: str) -> dict[str, bool]:
    present = {"chunking": False, "abstract": False}
    try:
        ensure_milvus_connection(max_attempts=1, base_delay=0.1)
        if utility.has_collection("paper_chunks"):
            col = Collection("paper_chunks")
            rows = col.query(
                expr=f'paper_id == "{paper_id}"',
                output_fields=["paper_id"],
                limit=1,
            )
            present["chunking"] = bool(rows)
        if utility.has_collection("paper_abstracts"):
            col = Collection("paper_abstracts")
            rows = col.query(
                expr=f'paper_id == "{paper_id}"',
                output_fields=["paper_id"],
                limit=1,
            )
            present["abstract"] = bool(rows)
    except Exception as e:
        logger.warning(f"Vector presence probe failed for {paper_id}: {e}")
    return present


def queue_paper_vector_repair_sync(
    paper_id: str,
    user_id: str | None = None,
    reason: str | None = None,
) -> bool:
    emb_url, emb_key, _ = get_embedding_config_sync()
    if not emb_url or not emb_key:
        return False

    lock_key = f"paper_vector_repair:{paper_id}"
    r = None
    try:
        r = _get_sync_redis()
        acquired = bool(r.set(lock_key, "1", ex=_REPAIR_LOCK_TTL_SECONDS, nx=True))
        if not acquired:
            return False

        from app.tasks.vector_health import task_repair_paper_vectors

        kwargs = {}
        if user_id:
            kwargs["user_id"] = user_id
        if reason:
            kwargs["reason"] = reason
        task_repair_paper_vectors.delay(paper_id, **kwargs)
        return True
    except Exception as e:
        logger.warning(f"Queue paper vector repair failed for {paper_id}: {e}")
        if r is not None:
            try:
                r.delete(lock_key)
            except Exception:
                pass
        return False
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


def clear_paper_vector_repair_lock_sync(paper_id: str) -> None:
    r = None
    try:
        r = _get_sync_redis()
        r.delete(f"paper_vector_repair:{paper_id}")
    except Exception as e:
        logger.warning(f"Clear paper vector repair lock failed for {paper_id}: {e}")
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass
