import logging
from app.tasks.celery_app import celery_app
from app.services.minio_service import delete_pdf
from app.services.milvus_service import delete_paper_vectors
from app.utils.paper_payload import clear_cached_paper_text
from sqlalchemy import create_engine, text
from app.config import get_settings
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)
settings = get_settings()


def _get_sync_redis():
    import redis as sync_redis
    return sync_redis.from_url(settings.REDIS_URL, decode_responses=True)


def _inspect_celery_runtime_sync() -> dict:
    from app.tasks.celery_app import celery_app as app

    inspect = app.control.inspect(timeout=1.0)
    active = inspect.active() or {}
    reserved = inspect.reserved() or {}
    scheduled = inspect.scheduled() or {}
    return {
        "active_count": sum(len(tasks or []) for tasks in active.values()),
        "reserved_count": sum(len(tasks or []) for tasks in reserved.values()),
        "scheduled_count": sum(len(tasks or []) for tasks in scheduled.values()),
    }


def reset_stale_concurrency_keys_sync(force: bool = False) -> dict:
    """Reset leaked concurrency counters when the runtime is idle.

    Returns a summary that can be used by both beat tasks and admin pages.
    """
    r = _get_sync_redis()
    try:
        keys = sorted(r.keys("concurrency:*") or [])
        if not keys:
            return {
                "applied": False,
                "reason": "no_keys",
                "reset_keys": [],
                "queue_waiting": 0,
                "active_count": 0,
                "reserved_count": 0,
                "scheduled_count": 0,
            }

        try:
            queue_waiting = int(r.llen("celery") or 0)
        except Exception:
            queue_waiting = 0

        runtime = _inspect_celery_runtime_sync()
        active_count = int(runtime["active_count"])
        reserved_count = int(runtime["reserved_count"])
        scheduled_count = int(runtime["scheduled_count"])

        is_idle = (
            queue_waiting == 0
            and active_count == 0
            and reserved_count == 0
            and scheduled_count == 0
        )
        if not force and not is_idle:
            return {
                "applied": False,
                "reason": "runtime_busy",
                "reset_keys": [],
                "queue_waiting": queue_waiting,
                "active_count": active_count,
                "reserved_count": reserved_count,
                "scheduled_count": scheduled_count,
            }

        reset_keys: list[dict[str, int]] = []
        pipe = r.pipeline(transaction=False)
        for key in keys:
            try:
                val = int(r.get(key) or 0)
            except Exception:
                val = 0
            if val > 0:
                logger.warning(f"Resetting stale concurrency key {key}: was {val}")
                pipe.set(key, 0)
                reset_keys.append({"key": key, "previous": val})
        if reset_keys:
            pipe.execute()

        return {
            "applied": bool(reset_keys),
            "reason": "reset" if reset_keys else "already_zero",
            "reset_keys": reset_keys,
            "queue_waiting": queue_waiting,
            "active_count": active_count,
            "reserved_count": reserved_count,
            "scheduled_count": scheduled_count,
        }
    finally:
        try:
            r.close()
        except Exception:
            pass


def cleanup_paper_sync(paper_id: str):
    """Synchronously delete all data for a paper.

    Match the safer primary delete flow:
    1. Delete vectors first and abort on hard failure.
    2. Delete DB row and folder counts in one transaction.
    3. Delete MinIO object last as best-effort cleanup.
    """
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT minio_object_key, folder_id FROM papers WHERE id = :pid"),
                              {"pid": paper_id}).fetchone()
            if not row:
                clear_cached_paper_text(paper_id)
                return

            object_key, folder_id = row[0], row[1]

            try:
                delete_paper_vectors(paper_id)
            except Exception as e:
                logger.warning(f"Milvus cleanup failed for {paper_id}: {e}")
                return

            # Delete from PG (cascade deletes related records)
            conn.execute(text("DELETE FROM papers WHERE id = :pid"), {"pid": paper_id})

            # Update folder paper_count
            if folder_id:
                conn.execute(text("""
                    WITH RECURSIVE ancestors AS (
                        SELECT id, parent_id FROM folders WHERE id = :fid
                        UNION ALL
                        SELECT f.id, f.parent_id FROM folders f JOIN ancestors a ON f.id = a.parent_id
                    )
                    UPDATE folders SET paper_count = GREATEST(paper_count - 1, 0)
                    WHERE id IN (SELECT id FROM ancestors)
                """), {"fid": folder_id})

            conn.commit()
        clear_cached_paper_text(paper_id)
        try:
            delete_pdf(object_key)
        except Exception as e:
            logger.warning(f"MinIO cleanup failed for {paper_id}: {e}")
        logger.info(f"Cleaned up paper {paper_id}")
    finally:
        engine.dispose()


@celery_app.task
def cleanup_stuck_papers():
    """Celery Beat task: mark papers stuck in 'processing' for over 30 minutes as failed."""
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=30)
        with engine.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT id FROM papers "
                    "WHERE processing_status = 'processing' "
                    "AND processing_started_at IS NOT NULL "
                    "AND processing_started_at < :cutoff"
                ),
                {"cutoff": cutoff},
            ).fetchall()
            if not rows:
                return
            for row in rows:
                paper_id = row[0]
                # Get current step_statuses
                sr = conn.execute(
                    text("SELECT step_statuses FROM papers WHERE id = :pid"),
                    {"pid": paper_id},
                ).fetchone()
                if sr and sr[0]:
                    import json
                    statuses = sr[0] if isinstance(sr[0], dict) else json.loads(sr[0])
                    # Mark any non-completed step as failed
                    for step, status in statuses.items():
                        if status != "completed":
                            statuses[step] = "failed"
                    conn.execute(
                        text(
                            "UPDATE papers SET step_statuses = :ss, processing_status = 'failed', "
                            "processing_started_at = NULL WHERE id = :pid"
                        ),
                        {"ss": json.dumps(statuses), "pid": paper_id},
                    )
                else:
                    conn.execute(
                        text(
                            "UPDATE papers SET processing_status = 'failed', processing_started_at = NULL "
                            "WHERE id = :pid"
                        ),
                        {"pid": paper_id},
                    )
            conn.commit()
            logger.info(f"Marked {len(rows)} stuck papers as failed")
    finally:
        engine.dispose()


@celery_app.task
def cleanup_stale_concurrency_keys():
    """Celery Beat task: reset leaked concurrency counters when the runtime is idle."""
    try:
        return reset_stale_concurrency_keys_sync(force=False)
    except Exception as e:
        logger.error(f"cleanup_stale_concurrency_keys failed: {e}")


@celery_app.task
def cleanup_old_notifications():
    """Celery Beat task: delete notifications older than 3 days."""
    engine = create_engine(settings.SYNC_DATABASE_URL)
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(days=3)
        with engine.connect() as conn:
            result = conn.execute(
                text("DELETE FROM notifications WHERE created_at < :cutoff"),
                {"cutoff": cutoff},
            )
            conn.commit()
            logger.info(f"Cleaned up {result.rowcount} old notifications")
    finally:
        engine.dispose()
