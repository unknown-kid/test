import json
import logging
from datetime import datetime, timezone

from sqlalchemy import create_engine, text
from pymilvus import Collection
import redis as sync_redis

from app.config import get_settings
from app.tasks.celery_app import celery_app
from app.services.embedding_service import (
    embed_text_sync,
    embed_texts_batch_sync,
    get_embedding_config_sync,
)
from app.services.llm_service import get_model_config_sync
from app.services.milvus_service import delete_paper_vectors, ensure_milvus_collections
from app.services.vector_health_service import (
    clear_paper_vector_repair_lock_sync,
    get_paper_vector_presence_sync,
    normalize_step_status_map,
)
from app.utils.paper_payload import get_or_extract_paper_text

logger = logging.getLogger(__name__)
settings = get_settings()
_ARTIFACT_AUDIT_SUMMARY_KEY = "paper:artifact_audit_summary"


def _has_non_empty_keywords(keywords_raw) -> bool:
    if keywords_raw is None:
        return False
    if isinstance(keywords_raw, list):
        return any(str(k).strip() for k in keywords_raw)
    if isinstance(keywords_raw, str):
        return bool(keywords_raw.strip())
    if isinstance(keywords_raw, dict):
        return bool(keywords_raw)
    return bool(keywords_raw)


def _write_audit_summary(summary: dict) -> None:
    r = None
    try:
        r = sync_redis.from_url(settings.REDIS_URL, decode_responses=True)
        r.set(_ARTIFACT_AUDIT_SUMMARY_KEY, json.dumps(summary, ensure_ascii=False), ex=60 * 60)
    except Exception as e:
        logger.warning(f"Write artifact audit summary failed: {e}")
    finally:
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


@celery_app.task(bind=True, max_retries=3)
def task_repair_paper_vectors(
    self,
    paper_id: str,
    user_id: str | None = None,
    reason: str | None = None,
):
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        emb_url, emb_key, emb_model = get_embedding_config_sync()
        if not emb_url or not emb_key:
            logger.warning(f"Skip vector repair for {paper_id}: embedding model not configured")
            return {"paper_id": paper_id, "status": "skipped", "reason": "embedding_not_configured"}

        configs = get_model_config_sync()
        chunk_size = int(configs.get("chunk_size", "3000"))
        overlap_ratio = float(configs.get("chunk_overlap_ratio", "0.2"))
        model_limit = int(configs.get("llm_concurrency_limit", "64"))

        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT minio_object_key, abstract, step_statuses "
                    "FROM papers WHERE id = :pid"
                ),
                {"pid": paper_id},
            ).fetchone()
        if not row:
            return {"paper_id": paper_id, "status": "missing"}

        object_key, abstract, step_statuses = row[0], row[1], row[2]
        step_map = normalize_step_status_map(step_statuses)

        needs_chunk = step_map.get("chunking") == "completed"
        needs_abstract = step_map.get("abstract") == "completed" and bool((abstract or "").strip())
        if not needs_chunk and not needs_abstract:
            return {"paper_id": paper_id, "status": "skipped", "reason": "steps_not_completed"}

        ensure_milvus_collections(load=False)
        delete_paper_vectors(paper_id)

        repaired_chunks = 0
        repaired_abstract = False

        if needs_chunk:
            full_text = get_or_extract_paper_text(paper_id, object_key=object_key)
            from app.utils.chunking import chunk_text

            chunks = chunk_text(full_text, chunk_size, overlap_ratio)
            if chunks:
                all_vectors = []
                batch_size = 20
                for i in range(0, len(chunks), batch_size):
                    batch = chunks[i:i + batch_size]
                    vectors = embed_texts_batch_sync(
                        emb_url, emb_key, emb_model, batch,
                        model_limit, user_id=user_id,
                    )
                    all_vectors.extend(vectors)

                chunk_col = Collection("paper_chunks")
                chunk_col.insert([
                    [paper_id] * len(chunks),
                    list(range(len(chunks))),
                    chunks,
                    all_vectors,
                ])
                chunk_col.flush()
                repaired_chunks = len(chunks)

        if needs_abstract:
            vector = embed_text_sync(
                emb_url, emb_key, emb_model, abstract,
                model_limit, user_id=user_id,
            )
            abstract_col = Collection("paper_abstracts")
            abstract_col.insert([[paper_id], [abstract[:65000]], [vector]])
            abstract_col.flush()
            repaired_abstract = True

        logger.info(
            "Repaired vectors for %s: chunks=%s abstract=%s reason=%s",
            paper_id,
            repaired_chunks,
            repaired_abstract,
            reason or "unknown",
        )
        return {
            "paper_id": paper_id,
            "status": "repaired",
            "chunks": repaired_chunks,
            "abstract": repaired_abstract,
        }
    except Exception as e:
        logger.error(f"Vector repair failed for {paper_id}: {e}")
        try:
            raise self.retry(exc=e, countdown=60)
        except self.MaxRetriesExceededError:
            logger.error(f"Vector repair max retries exceeded for {paper_id}: {e}")
            raise
    finally:
        clear_paper_vector_repair_lock_sync(paper_id)
        engine.dispose()


@celery_app.task
def audit_missing_paper_vectors(batch_size: int = 200):
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        emb_url, emb_key, _ = get_embedding_config_sync()
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id, uploaded_by, title, abstract, keywords, step_statuses "
                    "FROM papers "
                    "WHERE processing_status = 'completed' "
                    "ORDER BY created_at DESC "
                    "LIMIT :limit"
                ),
                {"limit": max(int(batch_size), 1)},
            ).fetchall()
            report_rows = conn.execute(
                text(
                    "SELECT DISTINCT paper_id FROM reading_reports "
                    "WHERE status = 'completed' AND content IS NOT NULL AND length(btrim(content)) > 0"
                )
            ).fetchall()

        queued = 0
        scanned = 0
        missing_chunk_vectors = 0
        missing_abstract_vectors = 0
        missing_title = 0
        missing_abstract = 0
        missing_keywords = 0
        missing_report = 0
        completed_papers_with_any_gap = 0
        report_completed_paper_ids = {str(pid) for (pid,) in report_rows if pid}

        for row in rows:
            paper_id, uploaded_by, title, abstract, keywords, step_statuses = row[0], row[1], row[2], row[3], row[4], row[5]
            step_map = normalize_step_status_map(step_statuses)
            if step_map.get("chunking") != "completed" and step_map.get("abstract") != "completed":
                pass

            presence = get_paper_vector_presence_sync(paper_id)
            need_chunk = step_map.get("chunking") == "completed" and not presence["chunking"]
            need_abstract = (
                step_map.get("abstract") == "completed"
                and bool((abstract or "").strip())
                and not presence["abstract"]
            )
            title_gap = step_map.get("title") == "completed" and not bool((title or "").strip())
            abstract_gap = step_map.get("abstract") == "completed" and not bool((abstract or "").strip())
            keywords_gap = step_map.get("keywords") == "completed" and not _has_non_empty_keywords(keywords)
            report_gap = step_map.get("report") == "completed" and paper_id not in report_completed_paper_ids

            scanned += 1
            if need_chunk:
                missing_chunk_vectors += 1
            if need_abstract:
                missing_abstract_vectors += 1
            if title_gap:
                missing_title += 1
            if abstract_gap:
                missing_abstract += 1
            if keywords_gap:
                missing_keywords += 1
            if report_gap:
                missing_report += 1
            if need_chunk or need_abstract or title_gap or abstract_gap or keywords_gap or report_gap:
                completed_papers_with_any_gap += 1

        summary = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "scanned_completed_papers": scanned,
            "queued_repairs": queued,
            "embedding_configured": bool(emb_url and emb_key),
            "completed_papers_with_any_gap": completed_papers_with_any_gap,
            "completed_papers_missing_chunk_vectors": missing_chunk_vectors,
            "completed_papers_missing_abstract_vectors": missing_abstract_vectors,
            "completed_steps_missing_title": missing_title,
            "completed_steps_missing_abstract": missing_abstract,
            "completed_steps_missing_keywords": missing_keywords,
            "completed_steps_missing_report": missing_report,
        }
        _write_audit_summary(summary)
        return summary
    finally:
        engine.dispose()
