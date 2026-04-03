from celery import Celery
from celery.schedules import crontab
import os

redis_url = os.getenv("REDIS_URL", "redis://redis:6379/0")

celery_app = Celery(
    "paper_tasks",
    broker=redis_url,
    backend=redis_url,
    include=[
        "app.tasks.processing",
        "app.tasks.chunking",
        "app.tasks.title_extraction",
        "app.tasks.abstract_extraction",
        "app.tasks.keyword_extraction",
        "app.tasks.report_generation",
        "app.tasks.deep_copy",
        "app.tasks.cleanup",
        "app.tasks.vector_rebuild",
        "app.tasks.vector_health",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Asia/Shanghai",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    beat_schedule={
        "cleanup-old-notifications": {
            "task": "app.tasks.cleanup.cleanup_old_notifications",
            "schedule": crontab(minute=0, hour="*"),  # every hour
        },
        "cleanup-stuck-papers": {
            "task": "app.tasks.cleanup.cleanup_stuck_papers",
            "schedule": crontab(minute="*/10"),  # every 10 minutes
        },
        "cleanup-stale-concurrency": {
            "task": "app.tasks.cleanup.cleanup_stale_concurrency_keys",
            "schedule": crontab(minute="*/10"),  # every 10 minutes
        },
        "audit-missing-paper-vectors": {
            "task": "app.tasks.vector_health.audit_missing_paper_vectors",
            "schedule": crontab(minute="*/15"),  # every 15 minutes
        },
    },
)
