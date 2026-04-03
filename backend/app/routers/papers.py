import json
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from io import BytesIO
from app.database import get_db, AsyncSessionLocal
from app.dependencies import get_current_user, require_admin, require_user
from app.models.user import User
from app.models.paper import Paper
from app.schemas.paper import PaperInfo, PaperMove, PaperCopy, PaperBatchMove, PaperBatchCopy, PaperKeywordsUpdate
from app.services.paper_service import (
    create_paper, delete_paper, move_paper, get_paper, batch_delete_papers,
)
from app.services.minio_service import get_pdf
from app.services.file_service import get_folder_or_raise, check_folder_permission, get_descendant_paper_ids
from app.services.auth_service import decode_token
from app.tasks.processing import process_paper
from app.tasks.deep_copy import task_deep_copy

router = APIRouter(prefix="/api/papers", tags=["papers"])


@router.post("/upload", response_model=PaperInfo)
async def upload_paper(
    file: UploadFile = File(...),
    folder_id: str | None = Query(None),
    zone: str = Query("personal"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Permission
    if user.role == "user" and zone == "shared":
        raise HTTPException(status_code=403, detail="普通用户不能上传到共享区")
    if user.role == "admin" and zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能上传到共享区")

    uploaded_by = user.id if user.role == "user" else None
    data = await file.read()
    try:
        paper = await create_paper(db, data, file.filename or "untitled.pdf", folder_id, zone, uploaded_by)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    # Trigger async processing
    process_paper.delay(paper.id, paper.minio_object_key, uploaded_by, zone)
    return paper


@router.post("/upload/batch")
async def upload_papers_batch(
    files: list[UploadFile] = File(...),
    folder_id: str | None = Query(None),
    zone: str = Query("personal"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if user.role == "user" and zone == "shared":
        raise HTTPException(status_code=403, detail="普通用户不能上传到共享区")
    if user.role == "admin" and zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能上传到共享区")

    uploaded_by = user.id if user.role == "user" else None
    results = []
    for f in files:
        data = await f.read()
        try:
            paper = await create_paper(db, data, f.filename or "untitled.pdf", folder_id, zone, uploaded_by)
            process_paper.delay(paper.id, paper.minio_object_key, uploaded_by, zone)
            results.append({"filename": f.filename, "paper_id": paper.id, "status": "success"})
        except ValueError as e:
            results.append({"filename": f.filename, "status": "failed", "error": str(e)})
    return {"results": results}


@router.get("/{paper_id}", response_model=PaperInfo)
async def get_paper_info(
    paper_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper = await get_paper(db, paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    # Permission: user can see own papers + shared papers
    if user.role == "user":
        if paper.zone == "personal" and paper.uploaded_by != user.id:
            raise HTTPException(status_code=403, detail="无权查看此论文")
    elif user.role == "admin":
        if paper.zone != "shared":
            raise HTTPException(status_code=403, detail="管理员不能查看个人区论文")
    return paper


@router.put("/{paper_id}/keywords", response_model=PaperInfo)
async def update_paper_keywords(
    paper_id: str,
    req: PaperKeywordsUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper = await get_paper(db, paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Permission: user can only edit own personal papers; admin can only edit shared papers
    if user.role == "user":
        if paper.zone != "personal" or paper.uploaded_by != user.id:
            raise HTTPException(status_code=403, detail="无权修改此论文关键词")
    elif user.role == "admin":
        if paper.zone != "shared":
            raise HTTPException(status_code=403, detail="管理员只能修改共享区论文关键词")

    seen = set()
    cleaned_keywords: list[str] = []
    for raw in req.keywords or []:
        keyword = str(raw).strip()
        if not keyword:
            continue
        dedupe_key = keyword.lower()
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        cleaned_keywords.append(keyword)

    paper.keywords = cleaned_keywords
    await db.commit()
    await db.refresh(paper)
    return paper


@router.get("/{paper_id}/pdf")
async def get_paper_pdf(
    paper_id: str,
    request: Request,
    token: str | None = Query(None),
):
    """Serve PDF. Accepts JWT via query param (for iframe) or Authorization header."""
    import jwt as pyjwt
    if not token:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            token = auth_header[7:].strip()

    if not token:
        raise HTTPException(status_code=401, detail="缺少认证Token")
    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="无效的Token类型")
        user_id = payload.get("sub")
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token已过期")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="无效的Token")

    async with AsyncSessionLocal() as db:
        result = await db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="用户不存在")

        try:
            paper = await get_paper(db, paper_id)
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))
        if user.role == "user" and paper.zone == "personal" and paper.uploaded_by != user.id:
            raise HTTPException(status_code=403, detail="无权查看此论文")

    try:
        pdf_data = get_pdf(paper.minio_object_key)
    except Exception:
        raise HTTPException(status_code=500, detail="PDF文件获取失败")

    return StreamingResponse(
        BytesIO(pdf_data),
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{paper.original_filename or paper.id}.pdf"'},
    )


@router.delete("/{paper_id}")
async def delete_paper_endpoint(
    paper_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper = await get_paper(db, paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    if user.role == "user" and (paper.zone != "personal" or paper.uploaded_by != user.id):
        raise HTTPException(status_code=403, detail="无权删除此论文")
    if user.role == "admin" and paper.zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能删除共享区论文")

    try:
        await delete_paper(db, paper_id)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"message": "论文已删除"}


@router.post("/batch/delete")
async def batch_delete(
    paper_ids: list[str],
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validate permissions for all papers first
    for pid in paper_ids:
        try:
            paper = await get_paper(db, pid)
        except ValueError:
            raise HTTPException(status_code=404, detail=f"论文 {pid} 不存在")
        if user.role == "user" and (paper.zone != "personal" or paper.uploaded_by != user.id):
            raise HTTPException(status_code=403, detail=f"无权删除论文 {pid}")
        if user.role == "admin" and paper.zone != "shared":
            raise HTTPException(status_code=403, detail=f"管理员只能删除共享区论文")

    result = await batch_delete_papers(db, paper_ids)
    return result


@router.post("/batch/move")
async def batch_move(
    req: PaperBatchMove,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.paper_ids:
        raise HTTPException(status_code=400, detail="请选择要移动的论文")

    success = 0
    failed = 0
    errors: list[dict] = []

    for pid in req.paper_ids:
        try:
            await move_paper(db, pid, req.target_folder_id, user.id, user.role)
            success += 1
        except (ValueError, PermissionError) as e:
            failed += 1
            errors.append({"paper_id": pid, "error": str(e)})
        except Exception:
            failed += 1
            errors.append({"paper_id": pid, "error": "移动失败"})

    return {"success": success, "failed": failed, "errors": errors}


@router.post("/batch/copy")
async def batch_copy(
    req: PaperBatchCopy,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.paper_ids:
        raise HTTPException(status_code=400, detail="请选择要复制的论文")

    target_zone = "shared" if user.role == "admin" else "personal"
    if req.target_folder_id:
        target = await get_folder_or_raise(db, req.target_folder_id)
        target_zone = target.zone
        if user.role == "user":
            if target.zone != "personal" or target.owner_id != user.id:
                raise HTTPException(status_code=403, detail="只能复制到自己的个人区")
        elif user.role == "admin":
            if target.zone != "shared":
                raise HTTPException(status_code=403, detail="管理员只能复制到共享区")
    else:
        if user.role == "admin":
            target_zone = "shared"
        else:
            target_zone = "personal"

    if user.role == "user" and target_zone != "personal":
        raise HTTPException(status_code=403, detail="只能复制到自己的个人区")
    if user.role == "admin" and target_zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能复制到共享区")

    success = 0
    failed = 0
    errors: list[dict] = []

    for pid in req.paper_ids:
        try:
            paper = await get_paper(db, pid)
            if user.role == "user" and paper.zone == "personal" and paper.uploaded_by != user.id:
                raise PermissionError("无权复制此论文")
            if user.role == "admin" and paper.zone != "shared":
                raise PermissionError("管理员只能复制共享区论文")
            task_deep_copy.delay(pid, req.target_folder_id, user.id, target_zone)
            success += 1
        except ValueError as e:
            failed += 1
            errors.append({"paper_id": pid, "error": str(e)})
        except PermissionError as e:
            failed += 1
            errors.append({"paper_id": pid, "error": str(e)})
        except Exception:
            failed += 1
            errors.append({"paper_id": pid, "error": "复制任务提交失败"})

    return {"success": success, "failed": failed, "errors": errors}


@router.put("/{paper_id}/move", response_model=PaperInfo)
async def move_paper_endpoint(
    paper_id: str,
    req: PaperMove,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        paper = await move_paper(db, paper_id, req.target_folder_id, user.id, user.role)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return paper


@router.post("/{paper_id}/copy")
async def copy_paper_endpoint(
    paper_id: str,
    req: PaperCopy,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deep copy paper to target folder (async Celery task)."""
    try:
        paper = await get_paper(db, paper_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Validate source paper permission
    if user.role == "user" and paper.zone == "personal" and paper.uploaded_by != user.id:
        raise HTTPException(status_code=403, detail="无权复制此论文")
    if user.role == "admin" and paper.zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能复制共享区论文")

    target_zone = "shared" if user.role == "admin" else "personal"
    # Validate target folder when specified
    if req.target_folder_id:
        target = await get_folder_or_raise(db, req.target_folder_id)
        target_zone = target.zone
        if user.role == "user":
            if target.zone != "personal" or target.owner_id != user.id:
                raise HTTPException(status_code=403, detail="只能复制到自己的个人区")
        elif user.role == "admin":
            if target.zone != "shared":
                raise HTTPException(status_code=403, detail="管理员只能复制到共享区")
    else:
        if user.role == "admin":
            target_zone = "shared"
        else:
            target_zone = "personal"

    if user.role == "user":
        if target_zone != "personal":
            raise HTTPException(status_code=403, detail="只能复制到自己的个人区")
    elif user.role == "admin":
        if target_zone != "shared":
            raise HTTPException(status_code=403, detail="管理员只能复制到共享区")

    task_deep_copy.delay(paper_id, req.target_folder_id, user.id, target_zone)
    return {"message": "复制任务已提交", "paper_id": paper_id}


@router.post("/reprocess")
async def reprocess_papers(
    folder_id: str | None = Query(None),
    zone: str = Query("personal"),
    failed_only: bool = Query(False),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """One-click reprocess in current scope.

    - failed_only=False: retry all non-completed papers.
    - failed_only=True: retry only previously failed papers.
    """
    if user.role == "user" and zone == "shared":
        raise HTTPException(status_code=403, detail="普通用户不能在共享区触发一键补全")
    if user.role == "admin" and zone != "shared":
        raise HTTPException(status_code=403, detail="管理员只能在共享区触发一键补全")

    # Validate folder scope and permissions when folder is specified.
    if folder_id:
        folder = await get_folder_or_raise(db, folder_id)
        try:
            await check_folder_permission(folder, user.id, user.role)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        if folder.zone != zone:
            raise HTTPException(status_code=400, detail="目录区域与请求区域不一致")
        paper_ids = await get_descendant_paper_ids(db, folder_id)
    else:
        query = select(Paper.id).where(Paper.zone == zone)
        if zone == "personal":
            query = query.where(Paper.uploaded_by == user.id)
        result = await db.execute(query)
        paper_ids = [r[0] for r in result.fetchall()]

    if not paper_ids:
        return {"message": "当前目录没有可处理论文", "total": 0}

    result = await db.execute(select(Paper).where(Paper.id.in_(paper_ids)))
    papers = result.scalars().all()

    def is_failed_paper(p: Paper) -> bool:
        if p.processing_status == "failed":
            return True
        step_statuses = p.step_statuses if isinstance(p.step_statuses, dict) else {}
        return any(v == "failed" for v in step_statuses.values())

    if failed_only:
        targets = [p for p in papers if is_failed_paper(p)]
    else:
        targets = [p for p in papers if p.processing_status != "completed"]

    uploaded_by = user.id if user.role == "user" else None
    for p in targets:
        await db.execute(
            text(
                "UPDATE papers SET step_statuses = :step_statuses, processing_status = 'pending', "
                "processing_started_at = NULL WHERE id = :pid"
            ),
            {
                "pid": p.id,
                "step_statuses": json.dumps(
                    {
                        "chunking": "pending",
                        "title": "pending",
                        "abstract": "pending",
                        "keywords": "pending",
                        "report": "pending",
                    }
                ),
            },
        )
        process_paper.delay(p.id, p.minio_object_key, uploaded_by, zone)
    await db.commit()

    if failed_only:
        return {"message": f"已提交 {len(targets)} 篇失败论文的5步重跑任务", "total": len(targets)}
    return {"message": f"已提交 {len(targets)} 篇论文的补全任务", "total": len(targets)}
