import logging
from app.tasks.celery_app import celery_app
from app.utils.chunking import chunk_text
from app.services.embedding_service import embed_texts_batch_sync, get_embedding_config_sync
from app.services.llm_service import get_model_config_sync
from app.services.milvus_service import ensure_milvus_collections
from app.utils.websocket_manager import update_paper_status_sync
from app.utils.paper_payload import get_or_extract_paper_text
from app.utils.concurrency import get_step_limiter, get_worker_limiter
from pymilvus import Collection

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=5)
def task_chunking(
    self,
    paper_id: str,
    full_text: str | None = None,
    user_id: str | None = None,
    object_key: str | None = None,
):
    """Step 1: Chunk text and vectorize."""
    step_limiter = None
    worker_limiter = None
    try:
        configs = get_model_config_sync()
        worker_total_limit = configs.get("worker_total_concurrency_limit", "18")
        worker_limiter = get_worker_limiter(worker_total_limit)
        worker_limiter.acquire_sync(wait=True)

        step_limit = configs.get("chunking_worker_limit", "6")
        step_limiter = get_step_limiter("chunking", step_limit)
        step_limiter.acquire_sync(wait=True)

        update_paper_status_sync(paper_id, "chunking", "processing", user_id)

        full_text = get_or_extract_paper_text(paper_id, full_text=full_text, object_key=object_key)
        chunk_size = int(configs.get("chunk_size", "3000"))
        overlap_ratio = float(configs.get("chunk_overlap_ratio", "0.2"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))

        chunks = chunk_text(full_text, chunk_size, overlap_ratio)
        if not chunks:
            update_paper_status_sync(paper_id, "chunking", "completed", user_id)
            return

        # Get embedding config
        emb_url, emb_key, emb_model = get_embedding_config_sync()
        if not emb_url or not emb_key:
            raise RuntimeError("Embedding model not configured, chunk vectors are required")

        # Batch embed (process in batches of 20)
        batch_size = 20
        all_vectors = []
        for i in range(0, len(chunks), batch_size):
            batch = chunks[i:i + batch_size]
            vectors = embed_texts_batch_sync(
                emb_url, emb_key, emb_model, batch,
                model_limit, user_id=user_id,
            )
            all_vectors.extend(vectors)

        # Insert into Milvus (auto-heal collections when missing)
        ensure_milvus_collections(load=False)
        col = Collection("paper_chunks")
        col.insert([
            [paper_id] * len(chunks),
            list(range(len(chunks))),
            chunks,
            all_vectors,
        ])
        col.flush()

        update_paper_status_sync(paper_id, "chunking", "completed", user_id)
        logger.info(f"Chunking completed for {paper_id}: {len(chunks)} chunks")
    except Exception as e:
        logger.error(f"Chunking attempt failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=45)
        except self.MaxRetriesExceededError:
            logger.error(f"Chunking failed after max retries for {paper_id}: {e}")
            update_paper_status_sync(paper_id, "chunking", "failed", user_id)
            raise
    finally:
        if step_limiter:
            step_limiter.safe_release_sync()
        if worker_limiter:
            worker_limiter.safe_release_sync()
