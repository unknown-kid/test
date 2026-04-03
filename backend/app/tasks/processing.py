import logging
from celery import group
from app.tasks.celery_app import celery_app
from app.services.minio_service import get_pdf
from app.utils.text_extraction import extract_text_from_pdf, is_scanned_pdf
from app.utils.websocket_manager import update_paper_status_sync, publish_notification_sync
from app.utils.concurrency import get_paper_limiter
from app.utils.paper_payload import cache_paper_text

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=2)
def process_paper(self, paper_id: str, object_key: str, user_id: str | None = None, zone: str = "personal"):
    """Main orchestrator: extract text, check scan, launch 5 parallel tasks."""
    from app.tasks.chunking import task_chunking
    from app.tasks.title_extraction import task_title_extraction
    from app.tasks.abstract_extraction import task_abstract_extraction
    from app.tasks.keyword_extraction import task_keyword_extraction
    from app.tasks.report_generation import task_report_generation

    # Acquire paper-level concurrency
    limiter = get_paper_limiter()
    limiter.acquire_sync(wait=True)

    try:
        # Update status to processing
        update_paper_status_sync(paper_id, "chunking", "processing", user_id)

        # Get PDF from MinIO
        pdf_bytes = get_pdf(object_key)

        # Extract text
        full_text = extract_text_from_pdf(pdf_bytes)
        cache_paper_text(paper_id, full_text)

        # Check if scanned PDF
        if is_scanned_pdf(full_text):
            logger.warning(f"Scanned PDF detected: {paper_id}")
            if user_id:
                publish_notification_sync(user_id, {
                    "type": "scan_detected",
                    "paper_id": paper_id,
                    "content": "检测到扫描版PDF，不支持处理，已自动清理",
                })
            # Cleanup: delete paper data
            from app.tasks.cleanup import cleanup_paper_sync
            cleanup_paper_sync(paper_id)
            return {"status": "scanned", "paper_id": paper_id}

        # Launch 5 parallel tasks
        job = group(
            task_chunking.s(paper_id, None, user_id, object_key),
            task_title_extraction.s(paper_id, None, None, user_id, zone, object_key),
            task_abstract_extraction.s(paper_id, None, user_id, object_key),
            task_keyword_extraction.s(paper_id, None, user_id, object_key),
            task_report_generation.s(paper_id, None, user_id, zone, None, None, object_key),
        )
        job.apply_async()

        return {"status": "processing", "paper_id": paper_id}
    except Exception as e:
        logger.error(f"process_paper failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error(f"process_paper max retries exceeded for {paper_id}")
            # Only mark failed when retry budget is exhausted.
            try:
                for step in ("chunking", "title", "abstract", "keywords", "report"):
                    update_paper_status_sync(paper_id, step, "failed", user_id)
            except Exception:
                logger.error(f"Failed to update status for {paper_id} during max-retry handling")
            raise
    finally:
        limiter.safe_release_sync()
