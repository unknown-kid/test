import logging
import uuid
import json
from app.tasks.celery_app import celery_app
from app.services.minio_service import copy_pdf, delete_pdf
from app.services.milvus_service import copy_paper_vectors, delete_paper_vectors
from app.utils.websocket_manager import publish_notification_sync
from sqlalchemy import create_engine, text
from app.config import get_settings
from app.utils.paper_payload import clear_cached_paper_text

logger = logging.getLogger(__name__)
settings = get_settings()

COMPLETED_STEP_MAP = {
    "chunking": "completed",
    "title": "completed",
    "abstract": "completed",
    "keywords": "completed",
    "report": "completed",
}

PENDING_STEP_MAP = {
    "chunking": "pending",
    "title": "pending",
    "abstract": "pending",
    "keywords": "pending",
    "report": "pending",
}


def _apply_folder_count_delta_sync(conn, folder_id: str | None, delta: int):
    if not folder_id or delta == 0:
        return

    conn.execute(text("""
        WITH RECURSIVE ancestors AS (
            SELECT id, parent_id FROM folders WHERE id = :fid
            UNION ALL
            SELECT f.id, f.parent_id FROM folders f JOIN ancestors a ON f.id = a.parent_id
        )
        UPDATE folders
        SET paper_count = GREATEST(paper_count + :delta, 0)
        WHERE id IN (SELECT id FROM ancestors)
    """), {"fid": folder_id, "delta": delta})


@celery_app.task(bind=True, max_retries=1)
def task_deep_copy(self, source_paper_id: str, target_folder_id: str | None, user_id: str, zone: str = "personal"):
    """Deep copy a paper: PDF + PG metadata + Milvus vectors."""
    engine = create_engine(settings.SYNC_DATABASE_URL)
    new_paper_id = str(uuid.uuid4())
    new_object_key = ""
    rollback_steps = []

    try:
        # 1. Get source paper
        with engine.connect() as conn:
            row = conn.execute(text("""
                SELECT title, abstract, keywords, file_size, minio_object_key,
                       processing_status, step_statuses, original_filename, zone
                FROM papers WHERE id = :pid
            """), {"pid": source_paper_id}).fetchone()
            if not row:
                raise ValueError(f"Source paper {source_paper_id} not found")

        title, abstract, keywords, file_size, source_key = row[0], row[1], row[2], row[3], row[4]
        proc_status, step_statuses, orig_filename, source_zone = row[5], row[6], row[7], row[8]

        step_map = step_statuses if isinstance(step_statuses, dict) else {}
        is_fully_completed = (
            proc_status == "completed"
            and all(step_map.get(step) == "completed" for step in COMPLETED_STEP_MAP)
        )
        new_processing_status = "completed" if is_fully_completed else "pending"
        new_step_statuses = COMPLETED_STEP_MAP if is_fully_completed else PENDING_STEP_MAP

        # 2. Copy PDF in MinIO
        if zone == "shared":
            new_object_key = f"shared/{new_paper_id}.pdf"
        else:
            new_object_key = f"personal/{user_id}/{new_paper_id}.pdf"

        copy_pdf(source_key, new_object_key)
        rollback_steps.append(("minio", new_object_key))

        # 3. Copy Milvus vectors
        vector_copy_succeeded = False
        if is_fully_completed:
            try:
                copy_paper_vectors(source_paper_id, new_paper_id)
                rollback_steps.append(("milvus", new_paper_id))
                vector_copy_succeeded = True
            except Exception as vector_error:
                logger.warning(
                    f"Deep copy vector duplication skipped for {source_paper_id} -> {new_paper_id}: {vector_error}"
                )

        # 4. Create new paper record in PG
        kw_json = json.dumps(keywords, ensure_ascii=False) if keywords else None
        ss_json = json.dumps(new_step_statuses)

        with engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO papers (id, title, abstract, keywords, file_size, folder_id,
                    minio_object_key, processing_status, step_statuses, uploaded_by, zone, original_filename)
                VALUES (:id, :title, :abstract, :kw, :fs, :fid, :key, :ps, :ss, :uid, :zone, :fn)
            """), {
                "id": new_paper_id, "title": title, "abstract": abstract,
                "kw": kw_json, "fs": file_size, "fid": target_folder_id,
                "key": new_object_key, "ps": new_processing_status, "ss": ss_json,
                "uid": user_id, "zone": zone, "fn": orig_filename,
            })
            rollback_steps.append(("pg", new_paper_id))

            # 5. Copy completed system reports only for fully completed source papers.
            if is_fully_completed:
                reports = conn.execute(text("""
                    SELECT content, status, report_type FROM reading_reports
                    WHERE paper_id = :pid AND report_type = 'system' AND status = 'completed'
                """), {"pid": source_paper_id}).fetchall()
                for r in reports:
                    conn.execute(text("""
                        INSERT INTO reading_reports (id, paper_id, user_id, report_type, content, status)
                        VALUES (:rid, :pid, NULL, :rtype, :content, :status)
                    """), {
                        "rid": str(uuid.uuid4()), "pid": new_paper_id,
                        "rtype": r[2], "content": r[0], "status": r[1],
                    })

            # 6. Update folder paper_count
            _apply_folder_count_delta_sync(conn, target_folder_id, 1)

            conn.commit()

        if not is_fully_completed:
            from app.tasks.processing import process_paper

            process_paper.delay(
                new_paper_id,
                new_object_key,
                user_id if zone == "personal" else None,
                zone,
            )

        publish_notification_sync(user_id, {
            "type": "deep_copy_complete",
            "paper_id": new_paper_id,
            "source_paper_id": source_paper_id,
            "content": (
                f"论文复制完成：{title or orig_filename}"
                if is_fully_completed
                else f"论文复制完成：{title or orig_filename}，正在为新论文重新处理内容"
            ),
        })
        logger.info(f"Deep copy completed: {source_paper_id} -> {new_paper_id}")
        return {"status": "success", "new_paper_id": new_paper_id}

    except Exception as e:
        logger.error(f"Deep copy failed for {source_paper_id}: {e}")
        # Rollback
        for step_type, step_data in reversed(rollback_steps):
            try:
                if step_type == "minio":
                    delete_pdf(step_data)
                elif step_type == "milvus":
                    delete_paper_vectors(step_data)
                elif step_type == "pg":
                    with engine.connect() as conn:
                        conn.execute(text("DELETE FROM reading_reports WHERE paper_id = :pid"), {"pid": step_data})
                        conn.execute(text("DELETE FROM papers WHERE id = :pid"), {"pid": step_data})
                        _apply_folder_count_delta_sync(conn, target_folder_id, -1)
                        conn.commit()
                    clear_cached_paper_text(step_data)
            except Exception as re:
                logger.error(f"Rollback step {step_type} failed: {re}")

        publish_notification_sync(user_id, {
            "type": "deep_copy_failed",
            "source_paper_id": source_paper_id,
            "content": f"论文复制失败：{str(e)}",
        })
        raise
    finally:
        engine.dispose()
