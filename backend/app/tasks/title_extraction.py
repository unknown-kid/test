import logging
from app.tasks.celery_app import celery_app
from app.services.llm_service import call_llm_sync, get_model_config_sync
from app.utils.text_extraction import extract_metadata_title
from app.utils.websocket_manager import update_paper_status_sync, publish_notification_sync
from app.utils.paper_payload import get_pdf_bytes_for_paper, get_or_extract_paper_text
from app.utils.concurrency import get_step_limiter, get_worker_limiter
from sqlalchemy import create_engine, text
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()


@celery_app.task(bind=True, max_retries=2)
def task_title_extraction(
    self,
    paper_id: str,
    pdf_hex: str | None,
    text_head: str | None,
    user_id: str | None = None,
    zone: str = "personal",
    object_key: str | None = None,
):
    """Step 2: Extract title with fallback chain, then dedup."""
    step_limiter = None
    worker_limiter = None
    try:
        configs = get_model_config_sync()
        worker_total_limit = configs.get("worker_total_concurrency_limit", "18")
        worker_limiter = get_worker_limiter(worker_total_limit)
        worker_limiter.acquire_sync(wait=True)

        step_limit = configs.get("title_worker_limit", "6")
        step_limiter = get_step_limiter("title", step_limit)
        step_limiter.acquire_sync(wait=True)

        update_paper_status_sync(paper_id, "title", "processing", user_id)

        if pdf_hex:
            pdf_bytes = bytes.fromhex(pdf_hex)
        else:
            pdf_bytes, _ = get_pdf_bytes_for_paper(paper_id, object_key)

        if not text_head:
            text_head = get_or_extract_paper_text(paper_id, object_key=object_key)[:5000]

        title_chars = int(configs.get("title_extract_chars", "2000"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))

        # 1. Try metadata
        title = extract_metadata_title(pdf_bytes)

        # 2. Try LLM
        if not title:
            chat_url = configs.get("chat_api_url", "")
            chat_key = configs.get("chat_api_key", "")
            chat_model = configs.get("chat_model_name", "")
            if chat_url and chat_key and chat_model:
                prompt = f"请从以下论文文本中提取论文标题，只返回标题文本，不要其他内容：\n\n{text_head[:title_chars]}"
                try:
                    title = call_llm_sync(
                        chat_url, chat_key, chat_model, prompt,
                        model_limit=model_limit, user_id=user_id,
                    )
                    title = title.strip().strip('"').strip("'").strip()
                except Exception as e:
                    logger.warning(f"LLM title extraction failed: {e}")

        # 3. Fallback to filename
        if not title:
            engine = create_engine(settings.SYNC_DATABASE_URL)
            with engine.connect() as conn:
                row = conn.execute(text("SELECT original_filename FROM papers WHERE id = :pid"), {"pid": paper_id}).fetchone()
                if row and row[0]:
                    title = row[0].replace(".pdf", "").replace(".PDF", "")
            engine.dispose()

        if not title:
            title = paper_id

        # Save title
        engine = create_engine(settings.SYNC_DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("UPDATE papers SET title = :title WHERE id = :pid"), {"title": title, "pid": paper_id})
            conn.commit()
        engine.dispose()

        update_paper_status_sync(paper_id, "title", "completed", user_id)
        logger.info(f"Title extracted for {paper_id}: {title[:50]}")
    except Exception as e:
        logger.error(f"Title extraction attempt failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=30)
        except self.MaxRetriesExceededError:
            logger.error(f"Title extraction failed after max retries for {paper_id}: {e}")
            update_paper_status_sync(paper_id, "title", "failed", user_id)
            raise
    finally:
        if step_limiter:
            step_limiter.safe_release_sync()
        if worker_limiter:
            worker_limiter.safe_release_sync()
