import logging
import json
import uuid
import redis as sync_redis
from app.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

NOTIFY_CHANNEL = "notifications"


def publish_notification_sync(user_id: str, notification: dict):
    """Persist notification and publish it via Redis pub/sub (for Celery workers)."""
    from sqlalchemy import create_engine, text

    notification_id = str(notification.get("id") or uuid.uuid4())
    notification_type = str(notification.get("type") or "system")
    notification_content = str(notification.get("content") or "")

    engine = None
    r = None
    try:
        engine = create_engine(settings.SYNC_DATABASE_URL)
        with engine.connect() as conn:
            row = conn.execute(
                text("SELECT 1 FROM users WHERE id = :uid"),
                {"uid": user_id},
            ).fetchone()
            if row:
                conn.execute(
                    text(
                        "INSERT INTO notifications (id, user_id, type, content, is_read) "
                        "VALUES (:id, :user_id, :type, :content, false)"
                    ),
                    {
                        "id": notification_id,
                        "user_id": user_id,
                        "type": notification_type,
                        "content": notification_content,
                    },
                )
                notif_row = conn.execute(
                    text(
                        "SELECT created_at FROM notifications WHERE id = :id"
                    ),
                    {"id": notification_id},
                ).fetchone()
                conn.commit()
                created_at = notif_row[0].isoformat() if notif_row and notif_row[0] else None
            else:
                created_at = None

        r = sync_redis.from_url(settings.REDIS_URL)
        message = json.dumps({
            "id": notification_id,
            "user_id": user_id,
            "type": notification_type,
            "content": notification_content,
            "is_read": False,
            "created_at": created_at,
            **notification,
        })
        r.publish(NOTIFY_CHANNEL, message)
    except Exception as e:
        # Notification failure should never break main processing.
        logger.warning(f"publish_notification_sync failed: {e}")
    finally:
        if engine is not None:
            try:
                engine.dispose()
            except Exception:
                pass
        if r is not None:
            try:
                r.close()
            except Exception:
                pass


def update_paper_status_sync(paper_id: str, step: str, status: str, user_id: str | None = None):
    """Update paper step status in DB and notify via Redis."""
    from sqlalchemy import create_engine, text
    engine = create_engine(settings.SYNC_DATABASE_URL)
    with engine.connect() as conn:
        # Update step_statuses JSON
        conn.execute(text(
            "UPDATE papers SET step_statuses = jsonb_set("
            "COALESCE(step_statuses\\:\\:jsonb, '{}'), "
            "ARRAY[:step_key], to_jsonb(:step_val\\:\\:text)) "
            "WHERE id = :paper_id"
        ), {"step_key": step, "step_val": status, "paper_id": paper_id})

        # Check if all steps done
        row = conn.execute(text("SELECT step_statuses FROM papers WHERE id = :pid"), {"pid": paper_id}).fetchone()
        if row:
            statuses = row[0] if isinstance(row[0], dict) else json.loads(row[0])
            all_values = list(statuses.values())
            if all(s == "completed" for s in all_values):
                conn.execute(
                    text(
                        "UPDATE papers SET processing_status = 'completed', processing_started_at = NULL "
                        "WHERE id = :pid"
                    ),
                    {"pid": paper_id},
                )
            elif any(s == "processing" for s in all_values):
                conn.execute(
                    text(
                        "UPDATE papers SET processing_status = 'processing', processing_started_at = NOW() "
                        "WHERE id = :pid"
                    ),
                    {"pid": paper_id},
                )
            elif any(s == "failed" for s in all_values):
                conn.execute(
                    text(
                        "UPDATE papers SET processing_status = 'failed', processing_started_at = NULL "
                        "WHERE id = :pid"
                    ),
                    {"pid": paper_id},
                )
            else:
                conn.execute(
                    text(
                        "UPDATE papers SET processing_status = 'pending', processing_started_at = NULL "
                        "WHERE id = :pid"
                    ),
                    {"pid": paper_id},
                )
        conn.commit()
    engine.dispose()

    # Notify
    if user_id:
        publish_notification_sync(user_id, {
            "type": "task_status",
            "paper_id": paper_id,
            "step": step,
            "status": status,
        })
