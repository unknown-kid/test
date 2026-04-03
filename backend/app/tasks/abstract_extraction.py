import logging
from app.tasks.celery_app import celery_app
from app.services.llm_service import call_llm_sync, get_model_config_sync
from app.services.embedding_service import embed_text_sync, get_embedding_config_sync
from app.services.milvus_service import ensure_milvus_collections
from app.utils.websocket_manager import update_paper_status_sync
from app.utils.paper_payload import get_or_extract_paper_text
from app.utils.concurrency import get_step_limiter, get_worker_limiter
from pymilvus import Collection
from sqlalchemy import create_engine, text
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


def _build_fallback_abstract(full_text: str, max_chars: int = 1200) -> str:
    sections = []
    for raw_line in full_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lower_line = line.lower()
        if lower_line in {"abstract", "摘要"}:
            continue
        sections.append(line)
        if sum(len(item) for item in sections) >= max_chars:
            break
    text = "\n".join(sections).strip()
    return text[:max_chars].strip()


def _save_abstract_to_db(engine, paper_id: str, abstract: str) -> None:
    with engine.connect() as conn:
        conn.execute(
            text("UPDATE papers SET abstract = :abstract WHERE id = :pid"),
            {"abstract": abstract, "pid": paper_id},
        )
        conn.commit()


def _vectorize_abstract_or_raise(
    paper_id: str,
    abstract: str,
    model_limit: int,
    user_id: str | None = None,
) -> None:
    emb_url, emb_key, emb_model = get_embedding_config_sync()
    if not emb_url or not emb_key:
        raise RuntimeError("Embedding model not configured, abstract vector is required")

    vector = embed_text_sync(
        emb_url, emb_key, emb_model, abstract,
        model_limit, user_id=user_id,
    )
    ensure_milvus_collections(load=False)
    col = Collection("paper_abstracts")
    col.insert([
        [paper_id],
        [abstract[:65000]],
        [vector],
    ])
    col.flush()


@celery_app.task(bind=True, max_retries=5)
def task_abstract_extraction(
    self,
    paper_id: str,
    full_text: str | None = None,
    user_id: str | None = None,
    object_key: str | None = None,
):
    """Step 3: Extract abstract via LLM, then vectorize."""
    step_limiter = None
    worker_limiter = None
    engine = None
    try:
        configs = get_model_config_sync()
        worker_total_limit = configs.get("worker_total_concurrency_limit", "18")
        worker_limiter = get_worker_limiter(worker_total_limit)
        worker_limiter.acquire_sync(wait=True)

        step_limit = configs.get("abstract_worker_limit", "6")
        step_limiter = get_step_limiter("abstract", step_limit)
        step_limiter.acquire_sync(wait=True)

        update_paper_status_sync(paper_id, "abstract", "processing", user_id)

        full_text = get_or_extract_paper_text(paper_id, full_text=full_text, object_key=object_key)
        abstract_chars = int(configs.get("abstract_extract_chars", "10000"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))

        chat_url = configs.get("chat_api_url", "")
        chat_key = configs.get("chat_api_key", "")
        chat_model = configs.get("chat_model_name", "")

        engine = create_engine(settings.SYNC_DATABASE_URL)
        if not chat_url or not chat_key:
            abstract = _build_fallback_abstract(full_text or "")
            if not abstract:
                raise RuntimeError("Failed to build fallback abstract")
            logger.warning(f"Abstract fallback applied for {paper_id} because chat model is not configured")
        else:
            prompt = f"请从以下论文文本中提取摘要(Abstract)，只返回摘要内容，不要其他内容：\n\n{full_text[:abstract_chars]}"
            abstract = call_llm_sync(
                chat_url, chat_key, chat_model, prompt,
                model_limit=model_limit, user_id=user_id,
            ).strip()
            if not abstract:
                raise RuntimeError("LLM returned empty abstract")

        _save_abstract_to_db(engine, paper_id, abstract)
        _vectorize_abstract_or_raise(paper_id, abstract, model_limit, user_id=user_id)

        update_paper_status_sync(paper_id, "abstract", "completed", user_id)
        logger.info(f"Abstract extracted for {paper_id}")
    except Exception as e:
        logger.error(f"Abstract extraction attempt failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=45)
        except self.MaxRetriesExceededError:
            logger.error(f"Abstract extraction failed after max retries for {paper_id}: {e}")
            fallback_abstract = _build_fallback_abstract(full_text or "")
            if fallback_abstract:
                engine = create_engine(settings.SYNC_DATABASE_URL)
                _save_abstract_to_db(engine, paper_id, fallback_abstract)
                logger.warning(f"Abstract fallback persisted for {paper_id} after model/vector failure")
            update_paper_status_sync(paper_id, "abstract", "failed", user_id)
            raise
    finally:
        if engine is not None:
            engine.dispose()
        if step_limiter:
            step_limiter.safe_release_sync()
        if worker_limiter:
            worker_limiter.safe_release_sync()
