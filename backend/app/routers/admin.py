from collections import defaultdict
from datetime import datetime, timezone
import json
import os
import shutil
import subprocess
from fastapi import APIRouter, Depends, HTTPException
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, or_, delete
from app.database import get_db
from app.dependencies import require_admin
from app.models.user import User
from app.models.paper import Paper
from app.models.report import ReadingReport
from app.models.config import SystemConfig
from app.models.notification import Notification
from app.schemas.admin import UserListItem, UserApproveRequest, AdminStats
from app.schemas.config import ConfigItem, ConfigUpdate
from app.schemas.report import ReportInfo
from app.services.report_service import get_reports
from app.services.init_service import DEFAULT_CONFIGS
from app.utils.redis_client import redis_client
from app.utils.model_monitor import get_model_usage_snapshot
from app.tasks.celery_app import celery_app
from app.tasks.cleanup import reset_stale_concurrency_keys_sync

router = APIRouter(prefix="/api/admin", tags=["admin"])

STEP_WORKER_CONFIG_KEYS = {
    "celery_worker_node_count",
    "worker_total_concurrency_limit",
    "chunking_worker_limit",
    "title_worker_limit",
    "abstract_worker_limit",
    "keywords_worker_limit",
    "report_worker_limit",
}
PIPELINE_STEP_KEYS = ("chunking", "title", "abstract", "keywords", "report")
PIPELINE_STEP_STATUS_SET = {"pending", "processing", "completed", "failed"}


def _safe_int(raw, default: int) -> int:
    try:
        return int(str(raw))
    except Exception:
        return default


async def _ensure_default_configs(db: AsyncSession) -> int:
    """Ensure admin page always exposes required system configs."""
    existing_keys = set((await db.execute(select(SystemConfig.key))).scalars().all())
    to_create = []
    for key, (value, description) in DEFAULT_CONFIGS.items():
        if key not in existing_keys:
            to_create.append(SystemConfig(key=key, value=value, description=description))
    if not to_create:
        return 0
    db.add_all(to_create)
    await db.commit()
    return len(to_create)


def _normalize_config_value(key: str, value: str) -> str:
    if key not in STEP_WORKER_CONFIG_KEYS:
        return value
    parsed = _safe_int(value, -1)
    if parsed <= 0:
        raise HTTPException(status_code=400, detail=f"{key} 必须是大于0的整数")
    return str(parsed)


def _normalize_step_status_map(raw_step_map: dict | None) -> dict[str, str]:
    normalized: dict[str, str] = {}
    src = raw_step_map if isinstance(raw_step_map, dict) else {}
    for step in PIPELINE_STEP_KEYS:
        raw = src.get(step)
        val = str(raw).strip().lower() if raw is not None else "pending"
        if val not in PIPELINE_STEP_STATUS_SET:
            val = "pending"
        normalized[step] = val
    return normalized


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


def _collect_vector_presence_sync(paper_ids: list[str]) -> dict[str, set[str]]:
    """
    Return step-level vector presence:
    - chunking: paper has rows in paper_chunks
    - abstract: paper has rows in paper_abstracts
    """
    from pymilvus import Collection, utility
    from app.services.milvus_service import ensure_milvus_connection

    present = {"chunking": set(), "abstract": set()}
    if not paper_ids:
        return present

    # Admin reconciliation should degrade quickly when Milvus is unavailable
    # instead of blocking the whole HTTP request on long retry loops.
    ensure_milvus_connection(max_attempts=1, base_delay=0.1)

    if utility.has_collection("paper_chunks"):
        col = Collection("paper_chunks")
        col.load()
        for pid in paper_ids:
            rows = col.query(
                expr=f'paper_id == "{pid}"',
                output_fields=["paper_id"],
                limit=1,
            )
            if rows:
                present["chunking"].add(pid)

    if utility.has_collection("paper_abstracts"):
        col = Collection("paper_abstracts")
        col.load()
        for pid in paper_ids:
            rows = col.query(
                expr=f'paper_id == "{pid}"',
                output_fields=["paper_id"],
                limit=1,
            )
            if rows:
                present["abstract"].add(pid)

    return present


def _cleanup_step_vectors_sync(chunking_paper_ids: set[str], abstract_paper_ids: set[str]) -> dict:
    """Delete per-step vectors for papers marked failed/processing or invalid output."""
    from pymilvus import Collection, utility
    from app.services.milvus_service import ensure_milvus_connection

    deleted_chunk_rows = 0
    deleted_abstract_rows = 0
    # Fast-fail here too; the caller already treats vector cleanup as best-effort.
    ensure_milvus_connection(max_attempts=1, base_delay=0.1)

    if chunking_paper_ids and utility.has_collection("paper_chunks"):
        col = Collection("paper_chunks")
        for pid in sorted(chunking_paper_ids):
            ret = col.delete(f'paper_id == "{pid}"')
            deleted_chunk_rows += int(getattr(ret, "delete_count", 0) or 0)

    if abstract_paper_ids and utility.has_collection("paper_abstracts"):
        col = Collection("paper_abstracts")
        for pid in sorted(abstract_paper_ids):
            ret = col.delete(f'paper_id == "{pid}"')
            deleted_abstract_rows += int(getattr(ret, "delete_count", 0) or 0)

    return {
        "deleted_chunk_rows": deleted_chunk_rows,
        "deleted_abstract_rows": deleted_abstract_rows,
    }


def _get_worker_pool_rows(stats_map: dict) -> list[tuple[str, int]]:
    rows: list[tuple[str, int]] = []
    for worker_name, stats in (stats_map or {}).items():
        pool = stats.get("pool", {}) if isinstance(stats, dict) else {}
        processes = pool.get("processes") or []
        if isinstance(processes, list):
            current = len(processes)
        else:
            current = 0
        if current <= 0:
            # Fallback for workers that don't expose process list.
            current = _safe_int(pool.get("max-concurrency"), 0)
        rows.append((worker_name, current))
    return rows


def _apply_worker_total_limit_sync(target_total: int) -> dict:
    target = target_total if target_total > 0 else 1
    inspect = celery_app.control.inspect(timeout=1.0)
    stats_map = inspect.stats() or {}
    pool_rows = _get_worker_pool_rows(stats_map)
    if not pool_rows:
        return {"applied": False, "reason": "no_online_workers"}

    current_total = sum(v for _, v in pool_rows)
    if current_total == target:
        return {"applied": True, "current_total": current_total, "target_total": target}

    if current_total < target:
        diff = target - current_total
        idx = 0
        while diff > 0 and pool_rows:
            worker_name, current = pool_rows[idx % len(pool_rows)]
            celery_app.control.broadcast(
                "pool_grow",
                arguments={"n": 1},
                destination=[worker_name],
                reply=False,
            )
            pool_rows[idx % len(pool_rows)] = (worker_name, current + 1)
            diff -= 1
            idx += 1
    else:
        diff = current_total - target
        while diff > 0:
            worker_idx = max(range(len(pool_rows)), key=lambda i: pool_rows[i][1])
            worker_name, current = pool_rows[worker_idx]
            # Keep at least one process per worker node to avoid draining all pools.
            if current <= 1:
                break
            celery_app.control.broadcast(
                "pool_shrink",
                arguments={"n": 1},
                destination=[worker_name],
                reply=False,
            )
            pool_rows[worker_idx] = (worker_name, current - 1)
            diff -= 1

    applied_total = sum(v for _, v in pool_rows)
    return {"applied": True, "current_total": applied_total, "target_total": target}


def _compose_cmd_prefix() -> list[str]:
    docker_bin = shutil.which("docker")
    if docker_bin:
        try:
            probe = subprocess.run(
                [docker_bin, "compose", "version"],
                capture_output=True,
                text=True,
                timeout=8,
            )
            if probe.returncode == 0:
                return [docker_bin, "compose"]
        except Exception:
            pass
    compose_bin = shutil.which("docker-compose")
    if compose_bin:
        return [compose_bin]
    raise RuntimeError("docker compose command is unavailable in backend container")


def _detect_host_project_dir_from_mount(container_dir: str = "/workspace") -> str | None:
    """
    Best-effort host project directory detection for Docker Desktop bind mounts.

    When compose is executed inside backend container but talks to host Docker daemon,
    relative bind paths must be resolved against a host path (not container path).
    """
    try:
        with open("/proc/self/mountinfo", "r", encoding="utf-8") as fp:
            for raw in fp:
                if " - " not in raw:
                    continue
                left, right = raw.strip().split(" - ", 1)
                left_parts = left.split()
                if len(left_parts) < 5:
                    continue
                mount_point = left_parts[4]
                if mount_point != container_dir:
                    continue
                root = left_parts[3]
                right_parts = right.split()
                if len(right_parts) < 2:
                    continue
                source = right_parts[1]

                # Docker Desktop on macOS commonly exposes /run/host_mark/<prefix>.
                if source.startswith("/run/host_mark"):
                    prefix = source[len("/run/host_mark"):] or "/"
                    candidate = os.path.normpath(f"{prefix}{root}")
                    if candidate.startswith("/"):
                        return candidate

                # Linux bind mounts may directly expose host path as source.
                if source.startswith("/") and not source.startswith("/dev/"):
                    if root and root != "/":
                        return os.path.normpath(f"{source}{root}")
                    return os.path.normpath(source)
    except Exception:
        return None
    return None


def _apply_celery_node_count_sync(target_nodes: int) -> dict:
    target = target_nodes if target_nodes > 0 else 1
    compose_file = os.getenv("DOCKER_COMPOSE_FILE", "/workspace/docker-compose.yml")
    project_name = os.getenv("DOCKER_COMPOSE_PROJECT", "test")
    project_dir = os.getenv("DOCKER_COMPOSE_PROJECT_DIR")
    if not project_dir:
        project_dir = _detect_host_project_dir_from_mount("/workspace")
    base_cmd = _compose_cmd_prefix()
    cmd = [
        *base_cmd,
    ]
    if project_dir:
        cmd.extend(["--project-directory", project_dir])
    cmd.extend([
        "-f",
        compose_file,
        "-p",
        project_name,
        "up",
        "-d",
        "--no-deps",
        "--scale",
        f"celery={target}",
        "celery",
    ])
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or proc.stdout.strip() or "scale celery failed")
    return {"applied": True, "target_nodes": target, "project_dir": project_dir}


def _extract_task_name(entry: dict, phase: str) -> str:
    if not isinstance(entry, dict):
        return "unknown"
    if phase == "scheduled":
        req = entry.get("request")
        if isinstance(req, dict):
            return req.get("name") or req.get("task") or "unknown"
    return entry.get("name") or entry.get("task") or "unknown"


def _collect_celery_snapshot_sync() -> dict:
    snapshot = {
        "workers_online": 0,
        "worker_process_total": 0,
        "running_count": 0,
        "reserved_count": 0,
        "scheduled_count": 0,
        "task_breakdown": [],
        "inspect_error": None,
    }
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_map = inspect.active() or {}
        reserved_map = inspect.reserved() or {}
        scheduled_map = inspect.scheduled() or {}
        stats_map = inspect.stats() or {}

        worker_names = set(active_map.keys()) | set(reserved_map.keys()) | set(scheduled_map.keys()) | set(stats_map.keys())
        snapshot["workers_online"] = len(worker_names)
        snapshot["worker_process_total"] = sum(v for _, v in _get_worker_pool_rows(stats_map))
        snapshot["running_count"] = sum(len(v or []) for v in active_map.values())
        snapshot["reserved_count"] = sum(len(v or []) for v in reserved_map.values())
        snapshot["scheduled_count"] = sum(len(v or []) for v in scheduled_map.values())

        breakdown = defaultdict(lambda: {"running": 0, "reserved": 0, "scheduled": 0})
        for tasks in active_map.values():
            for t in tasks or []:
                breakdown[_extract_task_name(t, "active")]["running"] += 1
        for tasks in reserved_map.values():
            for t in tasks or []:
                breakdown[_extract_task_name(t, "reserved")]["reserved"] += 1
        for tasks in scheduled_map.values():
            for t in tasks or []:
                breakdown[_extract_task_name(t, "scheduled")]["scheduled"] += 1

        snapshot["task_breakdown"] = [
            {"task_name": name, **counts}
            for name, counts in sorted(
                breakdown.items(),
                key=lambda item: (item[1]["running"] + item[1]["reserved"] + item[1]["scheduled"]),
                reverse=True,
            )
        ]
    except Exception as e:
        snapshot["inspect_error"] = str(e)
    return snapshot


def _extract_task_id(entry: dict, phase: str) -> str | None:
    if not isinstance(entry, dict):
        return None
    if phase == "scheduled":
        req = entry.get("request")
        if isinstance(req, dict):
            task_id = req.get("id")
            if task_id:
                return str(task_id)
    task_id = entry.get("id")
    return str(task_id) if task_id else None


def _clear_celery_runtime_sync() -> dict:
    """Force-clear broker waiting tasks and revoke active/reserved/scheduled tasks."""
    cleared = {
        "active_revoked": 0,
        "reserved_revoked": 0,
        "scheduled_revoked": 0,
        "purged_waiting": 0,
        "inspect_error": None,
    }
    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        active_map = inspect.active() or {}
        reserved_map = inspect.reserved() or {}
        scheduled_map = inspect.scheduled() or {}

        active_ids: set[str] = set()
        reserved_ids: set[str] = set()
        scheduled_ids: set[str] = set()

        for tasks in active_map.values():
            for entry in tasks or []:
                task_id = _extract_task_id(entry, "active")
                if task_id:
                    active_ids.add(task_id)
        for tasks in reserved_map.values():
            for entry in tasks or []:
                task_id = _extract_task_id(entry, "reserved")
                if task_id:
                    reserved_ids.add(task_id)
        for tasks in scheduled_map.values():
            for entry in tasks or []:
                task_id = _extract_task_id(entry, "scheduled")
                if task_id:
                    scheduled_ids.add(task_id)

        for task_id in sorted(active_ids):
            celery_app.control.revoke(task_id, terminate=True, signal="SIGKILL")
        for task_id in sorted(reserved_ids - active_ids):
            celery_app.control.revoke(task_id, terminate=False)
        for task_id in sorted(scheduled_ids - active_ids - reserved_ids):
            celery_app.control.revoke(task_id, terminate=False)

        cleared["active_revoked"] = len(active_ids)
        cleared["reserved_revoked"] = len(reserved_ids - active_ids)
        cleared["scheduled_revoked"] = len(scheduled_ids - active_ids - reserved_ids)
    except Exception as e:
        cleared["inspect_error"] = str(e)

    try:
        purged = celery_app.control.purge()
        cleared["purged_waiting"] = _safe_int(purged, 0)
    except Exception as e:
        if not cleared["inspect_error"]:
            cleared["inspect_error"] = str(e)

    return cleared


async def _maybe_reset_stale_concurrency_keys(
    queue_waiting: int,
    celery_snapshot: dict,
) -> dict | None:
    if celery_snapshot.get("inspect_error"):
        return None
    if any(
        int(celery_snapshot.get(key) or 0) > 0
        for key in ("running_count", "reserved_count", "scheduled_count")
    ):
        return None
    if int(queue_waiting or 0) > 0:
        return None
    try:
        return await run_in_threadpool(reset_stale_concurrency_keys_sync, False)
    except Exception:
        return None


# ---- Dashboard Stats ----

@router.get("/stats", response_model=AdminStats)
async def get_stats(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    total_users = (await db.execute(select(func.count()).select_from(User).where(User.role == "user"))).scalar() or 0
    pending_users = (await db.execute(select(func.count()).select_from(User).where(User.status == "pending"))).scalar() or 0
    total_papers = (await db.execute(select(func.count()).select_from(Paper))).scalar() or 0
    shared_papers = (await db.execute(select(func.count()).select_from(Paper).where(Paper.zone == "shared"))).scalar() or 0
    user_rows = (await db.execute(
        select(
            User.id,
            User.username,
            func.count(Paper.id).label("total_papers"),
            func.count(Paper.id).filter(Paper.zone == "personal").label("personal_papers"),
            func.count(Paper.id).filter(Paper.processing_status == "failed").label("failed_papers"),
        )
        .select_from(User)
        .outerjoin(Paper, Paper.uploaded_by == User.id)
        .where(User.role == "user")
        .group_by(User.id, User.username)
        .order_by(func.count(Paper.id).desc(), User.username.asc())
    )).all()
    user_paper_counts = [
        {
            "user_id": user_id,
            "username": username,
            "total_papers": int(total_count or 0),
            "personal_papers": int(personal_count or 0),
            "failed_papers": int(failed_count or 0),
        }
        for user_id, username, total_count, personal_count, failed_count in user_rows
    ]
    return AdminStats(
        total_users=total_users,
        pending_users=pending_users,
        total_papers=total_papers,
        shared_papers=shared_papers,
        user_paper_counts=user_paper_counts,
    )


@router.get("/papers/{paper_id}/reports", response_model=list[ReportInfo])
async def get_shared_paper_reports(
    paper_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise HTTPException(status_code=404, detail="论文不存在")
    if paper.zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能查看共享区论文报告")

    # Admin read-only: only return system reports
    return await get_reports(db, paper_id, user_id=None)


# ---- User Management ----

@router.get("/users", response_model=list[UserListItem])
async def list_users(
    status: str | None = None,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    q = select(User).where(User.role == "user").order_by(User.created_at.desc())
    if status:
        q = q.where(User.status == status)
    result = await db.execute(q)
    return list(result.scalars().all())


@router.post("/users/{user_id}/approve")
async def approve_user(
    user_id: str,
    req: UserApproveRequest,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(and_(User.id == user_id, User.role == "user")))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    if req.action == "approve":
        user.status = "approved"
        await db.commit()
        return {"message": "用户已审批通过"}
    elif req.action == "reject":
        await db.delete(user)
        await db.commit()
        return {"message": "用户已拒绝（已删除）"}
    else:
        raise HTTPException(status_code=400, detail="无效操作")


@router.delete("/users/{user_id}")
async def remove_user(
    user_id: str,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(and_(User.id == user_id, User.role == "user")))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    # Delete the user's personal papers explicitly before deleting the user record.
    paper_rows = (await db.execute(
        select(Paper.id, Paper.minio_object_key).where(Paper.uploaded_by == user_id)
    )).all()
    user_papers = [paper_id for paper_id, _ in paper_rows]

    # Delete vectors for user's papers
    if paper_rows:
        from app.services.milvus_service import delete_paper_vectors
        for pid, _ in paper_rows:
            try:
                delete_paper_vectors(pid)
            except Exception:
                pass

    # Delete MinIO files
    if paper_rows:
        from app.services.minio_service import delete_pdf
        for _, object_key in paper_rows:
            try:
                delete_pdf(object_key)
            except Exception:
                pass

    if user_papers:
        await db.execute(delete(Paper).where(Paper.id.in_(user_papers)))

    # DB cascade handles folders/notes/annotations/highlights/chat sessions/notifications
    await db.delete(user)
    await db.commit()

    # Clear refresh tokens
    await redis_client.delete(f"user_refresh:{user_id}")

    return {"message": "用户已移除"}


# ---- System Config ----

@router.get("/configs", response_model=list[ConfigItem])
async def list_configs(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _ensure_default_configs(db)
    result = await db.execute(select(SystemConfig).order_by(SystemConfig.key))
    return list(result.scalars().all())


@router.put("/configs/{key}", response_model=ConfigItem)
async def update_config(
    key: str,
    req: ConfigUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    normalized_value = _normalize_config_value(key, req.value)
    result = await db.execute(select(SystemConfig).where(SystemConfig.key == key))
    config = result.scalar_one_or_none()
    if not config:
        default_desc = DEFAULT_CONFIGS.get(key, (None, key))[1]
        config = SystemConfig(key=key, value=normalized_value, description=default_desc)
        db.add(config)
    else:
        config.value = normalized_value
    await db.commit()
    await db.refresh(config)

    if key == "worker_total_concurrency_limit":
        try:
            await run_in_threadpool(_apply_worker_total_limit_sync, int(normalized_value))
        except Exception:
            # Keep config persistence successful even when runtime pool adjustment fails.
            pass
    elif key == "celery_worker_node_count":
        try:
            await run_in_threadpool(_apply_celery_node_count_sync, int(normalized_value))
        except Exception:
            # Keep config persistence successful even when runtime scaling fails.
            pass

    return config


@router.post("/tasks/fail-stuck")
async def fail_stuck_tasks(
    force: bool = False,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """
    Full paper pipeline reconciliation across ALL papers:
    - validate each step status against actual artifacts
    - clear artifacts for processing/failed steps (and invalid completed steps)
    - normalize all invalid states to failed/pending/completed consistently
    """
    try:
        queue_waiting = _safe_int(await redis_client.llen("celery"), 0)
    except Exception:
        queue_waiting = 0
    celery_snapshot = await run_in_threadpool(_collect_celery_snapshot_sync)
    running_total = int(celery_snapshot.get("running_count") or 0)
    reserved_total = int(celery_snapshot.get("reserved_count") or 0)
    scheduled_total = int(celery_snapshot.get("scheduled_count") or 0)
    runtime_cleanup: dict | None = None
    if (queue_waiting > 0 or running_total > 0 or reserved_total > 0 or scheduled_total > 0) and not force:
        raise HTTPException(
            status_code=409,
            detail=(
                f"当前队列未空闲(waiting={queue_waiting}, running={running_total}, "
                f"reserved={reserved_total}, scheduled={scheduled_total})，"
                "请等待空闲后执行，或使用 ?force=true 强制清理。"
            ),
        )
    if force:
        runtime_cleanup = await run_in_threadpool(_clear_celery_runtime_sync)
        await run_in_threadpool(reset_stale_concurrency_keys_sync, True)

    papers = list((await db.execute(select(Paper))).scalars().all())
    scanned_papers = len(papers)

    report_rows = (await db.execute(
        select(ReadingReport.paper_id).where(
            and_(
                ReadingReport.status == "completed",
                ReadingReport.content.isnot(None),
                func.length(func.btrim(ReadingReport.content)) > 0,
            )
        )
    )).all()
    report_completed_paper_ids = {str(pid) for (pid,) in report_rows if pid}

    paper_ids = [p.id for p in papers]
    vector_presence: dict[str, set[str]] | None = None
    vector_probe_error: str | None = None
    try:
        vector_presence = await run_in_threadpool(_collect_vector_presence_sync, paper_ids)
    except Exception as e:
        # Keep reconciliation available even if Milvus is temporarily unavailable.
        vector_probe_error = str(e)

    matched_papers = 0
    failed_papers = 0
    completed_fixed_papers = 0
    failed_steps = 0
    cleared_title_count = 0
    cleared_abstract_count = 0
    cleared_keywords_count = 0

    chunking_vector_cleanup_paper_ids: set[str] = set()
    abstract_vector_cleanup_paper_ids: set[str] = set()
    report_cleanup_paper_ids: set[str] = set()

    for paper in papers:
        old_status = str(paper.processing_status or "pending")
        step_map = _normalize_step_status_map(paper.step_statuses)
        step_map_before = dict(step_map)
        cleanup_touched = False

        title_ok = bool((paper.title or "").strip()) if isinstance(paper.title, str) else bool(paper.title)
        abstract_text_ok = bool((paper.abstract or "").strip()) if isinstance(paper.abstract, str) else bool(paper.abstract)
        keywords_ok = _has_non_empty_keywords(paper.keywords)
        report_ok = paper.id in report_completed_paper_ids

        # If Milvus probe fails, skip vector-based "completed" validation to avoid false negatives.
        chunking_ok = True if vector_presence is None else (paper.id in vector_presence["chunking"])
        abstract_ok = abstract_text_ok if vector_presence is None else (abstract_text_ok and paper.id in vector_presence["abstract"])

        for step in PIPELINE_STEP_KEYS:
            status = step_map.get(step, "pending")
            has_data = True
            if step == "chunking":
                has_data = chunking_ok
            elif step == "title":
                has_data = title_ok
            elif step == "abstract":
                has_data = abstract_ok
            elif step == "keywords":
                has_data = keywords_ok
            elif step == "report":
                has_data = report_ok

            should_fail = False
            should_cleanup_artifact = False

            # Completed but no output artifact -> inconsistent, mark failed.
            if status == "completed" and not has_data:
                should_fail = True
                should_cleanup_artifact = True

            # processing/failed should be force-reconciled:
            # clear this step's artifact and ensure final state is failed.
            if status in {"processing", "failed"}:
                should_fail = True
                should_cleanup_artifact = True

            if should_fail:
                if status != "failed":
                    failed_steps += 1
                step_map[step] = "failed"

            if should_cleanup_artifact:
                cleanup_touched = True
                if step == "chunking":
                    chunking_vector_cleanup_paper_ids.add(paper.id)
                elif step == "title":
                    if paper.title is not None:
                        paper.title = None
                        cleared_title_count += 1
                elif step == "abstract":
                    if paper.abstract is not None:
                        paper.abstract = None
                        cleared_abstract_count += 1
                    abstract_vector_cleanup_paper_ids.add(paper.id)
                elif step == "keywords":
                    if paper.keywords is not None:
                        paper.keywords = None
                        cleared_keywords_count += 1
                elif step == "report":
                    report_cleanup_paper_ids.add(paper.id)

        if all(step_map.get(step) == "completed" for step in PIPELINE_STEP_KEYS):
            new_status = "completed"
        elif any(step_map.get(step) == "processing" for step in PIPELINE_STEP_KEYS):
            new_status = "processing"
        elif any(step_map.get(step) == "failed" for step in PIPELINE_STEP_KEYS):
            new_status = "failed"
        else:
            new_status = "pending"

        # Force cleanup should also close out interrupted half-finished pipelines:
        # if a paper has already completed some steps but the remaining ones are still
        # pending after runtime tasks were purged, those pending steps are stale.
        if force and new_status == "pending":
            completed_count = sum(1 for step in PIPELINE_STEP_KEYS if step_map.get(step) == "completed")
            pending_count = sum(1 for step in PIPELINE_STEP_KEYS if step_map.get(step) == "pending")
            if completed_count > 0 and pending_count > 0:
                for step in PIPELINE_STEP_KEYS:
                    if step_map.get(step) == "pending":
                        step_map[step] = "failed"
                new_status = "failed"

        # Canonicalize final paper state so the dashboard doesn't show
        # impossible combinations like "paper failed but several steps pending".
        if new_status == "failed":
            for step in PIPELINE_STEP_KEYS:
                if step_map.get(step) != "completed":
                    step_map[step] = "failed"
        elif new_status == "completed":
            for step in PIPELINE_STEP_KEYS:
                step_map[step] = "completed"
        elif new_status == "pending":
            for step in PIPELINE_STEP_KEYS:
                step_map[step] = "pending"

        paper_changed = False
        if paper.step_statuses != step_map:
            paper.step_statuses = step_map
            paper_changed = True
        if old_status != new_status:
            paper.processing_status = new_status
            paper_changed = True

        if paper_changed or step_map != step_map_before or cleanup_touched:
            matched_papers += 1
            if new_status == "failed":
                failed_papers += 1
            if new_status == "completed" and old_status != "completed":
                completed_fixed_papers += 1

    deleted_reports = 0
    if report_cleanup_paper_ids:
        report_delete_stmt = delete(ReadingReport).where(
            ReadingReport.paper_id.in_(list(report_cleanup_paper_ids)),
            or_(
                ReadingReport.status.in_(["pending", "generating", "failed"]),
                ReadingReport.content.is_(None),
                func.length(func.btrim(ReadingReport.content)) == 0,
            ),
        )
        report_ret = await db.execute(report_delete_stmt)
        deleted_reports = int(report_ret.rowcount or 0)

    deleted_chunk_rows = 0
    deleted_abstract_rows = 0
    vector_cleanup_error: str | None = None
    if chunking_vector_cleanup_paper_ids or abstract_vector_cleanup_paper_ids:
        try:
            vector_cleanup_ret = await run_in_threadpool(
                _cleanup_step_vectors_sync,
                chunking_vector_cleanup_paper_ids,
                abstract_vector_cleanup_paper_ids,
            )
            deleted_chunk_rows = int(vector_cleanup_ret.get("deleted_chunk_rows") or 0)
            deleted_abstract_rows = int(vector_cleanup_ret.get("deleted_abstract_rows") or 0)
        except Exception as e:
            vector_cleanup_error = str(e)

    await db.commit()

    return {
        "message": "论文步骤状态与产物已全量校验并清理完成",
        "force_mode": bool(force),
        "queue_waiting_before_cleanup": int(queue_waiting),
        "running_before_cleanup": int(running_total),
        "reserved_before_cleanup": int(reserved_total),
        "scheduled_before_cleanup": int(scheduled_total),
        "runtime_cleanup": runtime_cleanup,
        "scanned_papers": scanned_papers,
        "matched_papers": matched_papers,
        "failed_papers": failed_papers,
        "completed_fixed_papers": completed_fixed_papers,
        "failed_steps": failed_steps,
        "cleared_title_count": cleared_title_count,
        "cleared_abstract_count": cleared_abstract_count,
        "cleared_keywords_count": cleared_keywords_count,
        "deleted_reports": deleted_reports,
        "deleted_chunk_rows": deleted_chunk_rows,
        "deleted_abstract_rows": deleted_abstract_rows,
        "vector_probe_error": vector_probe_error,
        "vector_cleanup_error": vector_cleanup_error,
    }


@router.get("/tasks/overview")
async def get_tasks_overview(
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    cfg_rows = (await db.execute(
        select(SystemConfig.key, SystemConfig.value).where(SystemConfig.key.in_([
            "paper_concurrency_limit",
            "llm_concurrency_limit",
            "celery_worker_node_count",
            "worker_total_concurrency_limit",
            "chat_model_name",
            "embedding_model_name",
            "translate_model_name",
        ]))
    )).all()
    cfg_map = {k: v for k, v in cfg_rows}
    paper_limit = _safe_int(cfg_map.get("paper_concurrency_limit"), 10)
    model_limit = _safe_int(cfg_map.get("llm_concurrency_limit"), 64)
    worker_nodes_target = _safe_int(cfg_map.get("celery_worker_node_count"), 6)
    worker_total_limit = _safe_int(cfg_map.get("worker_total_concurrency_limit"), 18)

    processing_status_counts = {"pending": 0, "processing": 0, "completed": 0, "failed": 0}
    status_rows = (await db.execute(
        select(Paper.processing_status, func.count()).group_by(Paper.processing_status)
    )).all()
    for status_name, count_val in status_rows:
        processing_status_counts[str(status_name)] = int(count_val or 0)

    steps = ["chunking", "title", "abstract", "keywords", "report"]
    statuses = ["pending", "processing", "completed", "failed"]
    step_status_counts: dict[str, dict[str, int]] = {}
    for step in steps:
        step_status_counts[step] = {}
        for s in statuses:
            count_val = (await db.execute(
                select(func.count()).select_from(Paper).where(Paper.step_statuses[step].astext == s)
            )).scalar() or 0
            step_status_counts[step][s] = int(count_val)

    running_step_total = sum(step_status_counts[step]["processing"] for step in steps)
    completed_step_total = sum(step_status_counts[step]["completed"] for step in steps)
    failed_step_total = sum(step_status_counts[step]["failed"] for step in steps)
    total_papers = sum(processing_status_counts.values())
    total_step_slots = total_papers * len(steps)
    overall_step_progress = round((completed_step_total / total_step_slots) * 100, 2) if total_step_slots > 0 else 0.0

    running_rows = (await db.execute(
        select(Paper, User.username)
        .select_from(Paper)
        .outerjoin(User, User.id == Paper.uploaded_by)
        .where(Paper.processing_status == "processing")
        .order_by(Paper.created_at.desc())
        .limit(100)
    )).all()
    running_papers = []
    running_progress_sum = 0.0
    for paper, username in running_rows:
        step_map = paper.step_statuses if isinstance(paper.step_statuses, dict) else {}
        completed_steps = sum(1 for v in step_map.values() if v == "completed")
        processing_steps = sum(1 for v in step_map.values() if v == "processing")
        failed_steps = sum(1 for v in step_map.values() if v == "failed")
        progress_percent = round((completed_steps / len(steps)) * 100, 2)
        running_progress_sum += progress_percent
        running_papers.append({
            "paper_id": paper.id,
            "title": paper.title or paper.original_filename or paper.id,
            "zone": paper.zone,
            "uploaded_by": username,
            "progress_percent": progress_percent,
            "completed_steps": completed_steps,
            "processing_steps": processing_steps,
            "failed_steps": failed_steps,
            "step_statuses": step_map,
            "created_at": paper.created_at,
        })

    avg_running_progress = round(running_progress_sum / len(running_papers), 2) if running_papers else 0.0

    recent_failed_rows = (await db.execute(
        select(Notification, User.username)
        .select_from(Notification)
        .outerjoin(User, User.id == Notification.user_id)
        .where(or_(Notification.type.ilike("%failed%"), Notification.content.ilike("%失败%")))
        .order_by(Notification.created_at.desc())
        .limit(20)
    )).all()
    recent_failed_tasks = [
        {
            "id": n.id,
            "type": n.type,
            "content": n.content,
            "username": uname,
            "created_at": n.created_at,
        }
        for n, uname in recent_failed_rows
    ]

    queue_waiting = 0
    try:
        queue_waiting = _safe_int(await redis_client.llen("celery"), 0)
    except Exception:
        queue_waiting = 0

    celery_snapshot = await run_in_threadpool(_collect_celery_snapshot_sync)
    await _maybe_reset_stale_concurrency_keys(queue_waiting, celery_snapshot)

    paper_in_use = _safe_int(await redis_client.get("concurrency:paper"), 0)
    worker_in_use = _safe_int(await redis_client.get("concurrency:worker_total"), 0)
    model_concurrency_rows = []
    try:
        model_keys = await redis_client.keys("concurrency:model:*")
        for key in model_keys:
            model_name = key.replace("concurrency:model:", "", 1)
            in_use = _safe_int(await redis_client.get(key), 0)
            model_type = "unknown"
            if model_name and model_name == cfg_map.get("chat_model_name"):
                model_type = "chat"
            elif model_name and model_name == cfg_map.get("embedding_model_name"):
                model_type = "embedding"
            elif model_name and model_name == cfg_map.get("translate_model_name"):
                model_type = "translate"
            model_concurrency_rows.append({
                "model_type": model_type,
                "model_name": model_name or "unknown",
                "in_use": in_use,
                "limit": model_limit,
                "utilization_percent": round((in_use / model_limit) * 100, 2) if model_limit > 0 else None,
            })
    except Exception:
        model_concurrency_rows = []
    model_concurrency_rows.sort(key=lambda x: x["in_use"], reverse=True)

    usage_snapshot = await get_model_usage_snapshot(hours=24, max_user_rows=200)
    user_usage_rows = usage_snapshot.get("user_model_usage_24h", [])
    user_ids = list({row["user_id"] for row in user_usage_rows if row.get("user_id")})
    user_name_map: dict[str, str] = {}
    if user_ids:
        user_name_rows = (await db.execute(
            select(User.id, User.username).where(User.id.in_(user_ids))
        )).all()
        user_name_map = {uid: uname for uid, uname in user_name_rows}
    for row in user_usage_rows:
        row["username"] = user_name_map.get(row["user_id"], row["user_id"])

    user_usage_totals: dict[str, dict] = {}
    for row in user_usage_rows:
        uname = row.get("username")
        if uname not in user_usage_totals:
            user_usage_totals[uname] = {
                "username": uname,
                "requests_24h": 0,
                "failed_24h": 0,
                "model_count": 0,
            }
        user_usage_totals[uname]["requests_24h"] += int(row.get("requests_24h") or 0)
        user_usage_totals[uname]["failed_24h"] += int(row.get("failed_24h") or 0)
    model_counter_by_user = defaultdict(int)
    for row in user_usage_rows:
        model_counter_by_user[row.get("username")] += 1
    for uname, cnt in model_counter_by_user.items():
        if uname in user_usage_totals:
            user_usage_totals[uname]["model_count"] = cnt
    top_users = sorted(user_usage_totals.values(), key=lambda x: x["requests_24h"], reverse=True)[:20]

    artifact_audit = {
        "generated_at": None,
        "scanned_completed_papers": 0,
        "queued_repairs": 0,
        "embedding_configured": True,
        "completed_papers_with_any_gap": 0,
        "completed_papers_missing_chunk_vectors": 0,
        "completed_papers_missing_abstract_vectors": 0,
        "completed_steps_missing_title": 0,
        "completed_steps_missing_abstract": 0,
        "completed_steps_missing_keywords": 0,
        "completed_steps_missing_report": 0,
    }
    try:
        raw_audit_summary = await redis_client.get("paper:artifact_audit_summary")
        if raw_audit_summary:
            parsed_audit = json.loads(raw_audit_summary)
            if isinstance(parsed_audit, dict):
                artifact_audit.update(parsed_audit)
    except Exception:
        pass

    queue_total = int(queue_waiting) + int(celery_snapshot["reserved_count"]) + int(celery_snapshot["scheduled_count"])

    return {
        "generated_at": datetime.now(timezone.utc),
        "queue": {
            "waiting_count": int(queue_waiting),
            "running_count": int(celery_snapshot["running_count"]),
            "reserved_count": int(celery_snapshot["reserved_count"]),
            "scheduled_count": int(celery_snapshot["scheduled_count"]),
            "queued_total": int(queue_total),
            "workers_online": int(celery_snapshot["workers_online"]),
            "worker_nodes_target": int(worker_nodes_target),
            "worker_process_total": int(celery_snapshot["worker_process_total"]),
            "worker_total_limit": int(worker_total_limit),
            "worker_total_in_use": int(worker_in_use),
            "worker_total_utilization_percent": round((worker_in_use / worker_total_limit) * 100, 2) if worker_total_limit > 0 else None,
            "inspect_error": celery_snapshot.get("inspect_error"),
            "task_breakdown": celery_snapshot.get("task_breakdown", []),
        },
        "concurrency": {
            "paper": {
                "in_use": int(paper_in_use),
                "limit": int(paper_limit),
                "utilization_percent": round((paper_in_use / paper_limit) * 100, 2) if paper_limit > 0 else None,
            },
            "model_limit": int(model_limit),
            "models": model_concurrency_rows,
        },
        "processing": {
            "paper_status_counts": processing_status_counts,
            "step_status_counts": step_status_counts,
            "running_step_total": int(running_step_total),
            "failed_step_total": int(failed_step_total),
            "completed_step_total": int(completed_step_total),
            "overall_step_progress_percent": overall_step_progress,
            "running_papers_count": len(running_papers),
            "running_papers_avg_progress_percent": avg_running_progress,
            "running_papers": running_papers,
        },
        "model_usage_24h": usage_snapshot.get("model_usage_24h", []),
        "user_model_usage_24h": user_usage_rows,
        "top_users_24h": top_users,
        "recent_failed_tasks": recent_failed_tasks,
        "artifact_audit": artifact_audit,
    }
