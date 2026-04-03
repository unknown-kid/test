from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.folder import FolderCreate, FolderRename, FolderInfo, FolderTreeNode
from app.schemas.paper import FolderContentResponse, FolderItemResponse, PaperListResponse, FolderBreadcrumb
from app.services.file_service import (
    create_folder, rename_folder,
    get_folder_children, get_folder_papers, get_breadcrumbs,
    get_folder_tree, get_folder_or_raise, check_folder_permission,
    get_descendant_paper_ids, apply_ancestor_paper_count_delta,
)
from app.services.minio_service import delete_pdf
from app.services.milvus_service import delete_paper_vectors
from app.models.paper import Paper
from sqlalchemy import delete, select

router = APIRouter(prefix="/api/files", tags=["files"])


def resolve_zone_and_owner(user: User, zone: str | None = None):
    if user.role == "admin":
        return "shared", None
    if zone == "shared":
        return "shared", None
    return "personal", user.id


@router.get("/folders/tree")
async def folder_tree(
    zone: str = Query("personal"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    z, owner = resolve_zone_and_owner(user, zone)
    tree = await get_folder_tree(db, z, owner)
    return tree


@router.get("/folders/{folder_id}", response_model=FolderInfo)
async def get_folder(
    folder_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await get_folder_or_raise(db, folder_id)
    await check_folder_permission(folder, user.id, user.role)
    return folder


@router.get("/contents")
async def list_contents(
    folder_id: str | None = Query(None),
    zone: str = Query("personal"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=10, le=100),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    z, owner = resolve_zone_and_owner(user, zone)

    # Validate folder access
    if folder_id:
        folder = await get_folder_or_raise(db, folder_id)
        await check_folder_permission(folder, user.id, user.role)

    # Get child folders
    folders = await get_folder_children(db, folder_id, z, owner)
    folder_items = [FolderItemResponse.model_validate(f) for f in folders]

    # Get papers
    papers, total = await get_folder_papers(db, folder_id, z, owner, page, page_size)
    paper_list = PaperListResponse(
        items=[p for p in papers],
        total=total,
        page=page,
        page_size=page_size,
    )

    # Breadcrumbs
    breadcrumbs = await get_breadcrumbs(db, folder_id)
    bc_list = [FolderBreadcrumb(**b) for b in breadcrumbs]

    current = None
    if folder_id:
        f = await get_folder_or_raise(db, folder_id)
        current = FolderBreadcrumb(id=f.id, name=f.name)

    return FolderContentResponse(
        folders=folder_items,
        papers=paper_list,
        current_folder=current,
        breadcrumbs=bc_list,
    )


@router.post("/folders", response_model=FolderInfo)
async def create_new_folder(
    req: FolderCreate,
    zone: str = Query("personal"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    z, owner = resolve_zone_and_owner(user, zone)
    if user.role == "user" and z == "shared":
        raise HTTPException(status_code=403, detail="普通用户不能在共享区创建文件夹")
    try:
        folder = await create_folder(db, req.name, z, owner, req.parent_id)
    except (ValueError, PermissionError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    return folder


@router.put("/folders/{folder_id}/rename", response_model=FolderInfo)
async def rename_existing_folder(
    folder_id: str,
    req: FolderRename,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await get_folder_or_raise(db, folder_id)
    try:
        await check_folder_permission(folder, user.id, user.role)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if user.role == "user" and folder.zone == "shared":
        raise HTTPException(status_code=403, detail="普通用户不能修改共享区文件夹")
    try:
        return await rename_folder(db, folder_id, req.name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/folders/{folder_id}")
async def delete_existing_folder(
    folder_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    folder = await get_folder_or_raise(db, folder_id)
    try:
        await check_folder_permission(folder, user.id, user.role)
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if user.role == "user" and folder.zone == "shared":
        raise HTTPException(status_code=403, detail="普通用户不能删除共享区文件夹")

    paper_ids = await get_descendant_paper_ids(db, folder_id)
    parent_id = folder.parent_id

    paper_rows = []
    if paper_ids:
        result = await db.execute(
            select(Paper.id, Paper.minio_object_key).where(Paper.id.in_(paper_ids))
        )
        paper_rows = list(result.all())

        # Fail fast before touching DB so the folder never ends up half-deleted.
        for pid, _ in paper_rows:
            try:
                delete_paper_vectors(pid)
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"删除论文向量失败: {e}")

    try:
        if paper_ids:
            await db.execute(delete(Paper).where(Paper.id.in_(paper_ids)))
            await apply_ancestor_paper_count_delta(db, parent_id, -len(paper_ids))
        await db.delete(folder)
        await db.commit()
    except Exception as e:
        await db.rollback()
        raise HTTPException(status_code=500, detail=f"删除文件夹失败: {e}")

    minio_failures = 0
    for _, object_key in paper_rows:
        try:
            delete_pdf(object_key)
        except Exception:
            minio_failures += 1

    if minio_failures:
        return {
            "message": "文件夹已删除",
            "warning": f"{minio_failures} 个PDF文件清理失败，已保留为后台存储残留",
        }
    return {"message": "文件夹已删除"}
