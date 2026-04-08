import logging
import uuid
import re
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.paper import Paper
from app.models.folder import Folder
from app.services.minio_service import upload_pdf, delete_pdf
from app.services.milvus_service import delete_paper_vectors
from app.services.file_service import (
    update_ancestor_paper_counts,
    get_folder_or_raise,
    apply_ancestor_paper_count_delta,
)

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100MB
PDF_SIGNATURE = b"%PDF-"
SAFE_FILENAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def is_pdf_bytes(file_data: bytes) -> bool:
    return bool(file_data) and file_data.startswith(PDF_SIGNATURE)


def normalize_pdf_filename(filename: str) -> str:
    raw = (filename or "").strip()
    if not raw:
        raw = "untitled.pdf"
    sanitized = SAFE_FILENAME_RE.sub("_", raw).strip("._") or "untitled.pdf"
    if not sanitized.lower().endswith(".pdf"):
        sanitized = f"{sanitized}.pdf"
    return sanitized


async def create_paper(
    db: AsyncSession, file_data: bytes, filename: str,
    folder_id: str | None, zone: str, uploaded_by: str | None,
) -> Paper:
    if len(file_data) > MAX_FILE_SIZE:
        raise ValueError("文件大小不能超过100MB")
    if not is_pdf_bytes(file_data):
        raise ValueError("仅支持有效的PDF文件")
    filename = normalize_pdf_filename(filename)

    paper_id = str(uuid.uuid4())
    if zone == "shared":
        object_key = f"shared/{paper_id}.pdf"
    else:
        object_key = f"personal/{uploaded_by}/{paper_id}.pdf"

    # Validate folder
    if folder_id:
        folder = await get_folder_or_raise(db, folder_id)
        if folder.zone != zone:
            raise ValueError("文件夹区域不匹配")

    # Upload to MinIO
    upload_pdf(object_key, file_data)

    paper = Paper(
        id=paper_id,
        title=None,
        file_size=len(file_data),
        folder_id=folder_id,
        minio_object_key=object_key,
        processing_status="pending",
        uploaded_by=uploaded_by,
        zone=zone,
        original_filename=filename,
    )
    try:
        db.add(paper)
        await apply_ancestor_paper_count_delta(db, folder_id, 1)
        await db.commit()
        await db.refresh(paper)
    except Exception:
        await db.rollback()
        try:
            delete_pdf(object_key)
        except Exception as cleanup_error:
            logger.warning(f"MinIO cleanup failed after create_paper rollback for {paper_id}: {cleanup_error}")
        raise

    return paper


async def delete_paper(db: AsyncSession, paper_id: str) -> bool:
    """Delete paper with user-visible consistency prioritized over storage cleanup.

    Order:
    1. Delete Milvus vectors first. If this fails, abort without touching DB/PDF.
    2. Delete DB row and update folder counts in one transaction.
    3. Delete MinIO object last as best-effort cleanup.

    This avoids the worst case where the paper still appears in the product but
    its PDF has already been removed.
    """
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise ValueError("论文不存在")

    folder_id = paper.folder_id
    object_key = paper.minio_object_key

    try:
        delete_paper_vectors(paper_id)
    except Exception as e:
        logger.error(f"Milvus delete failed for {paper_id}: {e}")
        raise ValueError("删除失败：向量数据删除出错")

    try:
        await db.delete(paper)
        await apply_ancestor_paper_count_delta(db, folder_id, -1)
        await db.commit()
    except Exception as e:
        logger.error(f"PG delete failed for {paper_id}: {e}")
        await db.rollback()
        raise ValueError("删除失败：数据库删除出错")

    try:
        delete_pdf(object_key)
    except Exception as e:
        # At this point the user-visible delete already succeeded. Keep the API
        # successful and log the orphaned object for later cleanup.
        logger.warning(f"MinIO delete failed after DB removal for {paper_id}: {e}")

    return True


async def move_paper(
    db: AsyncSession, paper_id: str, target_folder_id: str | None,
    user_id: str, role: str,
) -> Paper:
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise ValueError("论文不存在")

    # Permission check
    if role == "admin" and paper.zone != "shared":
        raise PermissionError("管理员只能操作共享区论文")
    if role == "user" and (paper.zone != "personal" or paper.uploaded_by != user_id):
        raise PermissionError("无权移动此论文")

    # Validate target folder
    if target_folder_id:
        target = await get_folder_or_raise(db, target_folder_id)
        if target.zone != paper.zone:
            raise ValueError("不能跨区域移动论文")
        if paper.zone == "personal" and target.owner_id != user_id:
            raise PermissionError("无权移动到此文件夹")

    old_folder_id = paper.folder_id
    paper.folder_id = target_folder_id
    try:
        await apply_ancestor_paper_count_delta(db, old_folder_id, -1)
        await apply_ancestor_paper_count_delta(db, target_folder_id, 1)
        await db.commit()
        await db.refresh(paper)
    except Exception:
        await db.rollback()
        raise

    return paper


async def get_paper(db: AsyncSession, paper_id: str) -> Paper:
    result = await db.execute(select(Paper).where(Paper.id == paper_id))
    paper = result.scalar_one_or_none()
    if not paper:
        raise ValueError("论文不存在")
    return paper


async def get_accessible_paper_for_user(db: AsyncSession, paper_id: str, user_id: str) -> Paper:
    """Return a paper a normal user is allowed to access.

    Rules:
    - shared zone: any approved user can access
    - personal zone: only the uploader can access
    """
    paper = await get_paper(db, paper_id)
    if paper.zone == "personal" and paper.uploaded_by != user_id:
        raise PermissionError("无权访问此论文")
    return paper


async def get_owned_personal_paper_for_user(db: AsyncSession, paper_id: str, user_id: str) -> Paper:
    """Return a personal-zone paper owned by the current user."""
    paper = await get_paper(db, paper_id)
    if paper.zone != "personal" or paper.uploaded_by != user_id:
        raise PermissionError("无权访问此论文")
    return paper


async def batch_delete_papers(db: AsyncSession, paper_ids: list[str]) -> dict:
    """Delete multiple papers. Returns success/failure counts."""
    success = 0
    failed = 0
    for pid in paper_ids:
        try:
            await delete_paper(db, pid)
            success += 1
        except Exception as e:
            logger.error(f"Batch delete failed for {pid}: {e}")
            failed += 1
    return {"success": success, "failed": failed}
