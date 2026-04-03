from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.schemas.search import KeywordSearchRequest, RAGSearchRequest, CascadeSearchRequest
from app.schemas.paper import PaperInfo, PaperListResponse
from app.services.search_service import (
    get_scope_paper_ids, keyword_search, rag_search, cascade_search,
)
from app.services.llm_service import get_model_config_sync
from app.services.file_service import get_folder_or_raise, check_folder_permission

router = APIRouter(prefix="/api/search", tags=["search"])


def resolve_search_scope(user: User, zone: str) -> tuple[str, str | None]:
    if user.role == "admin":
        if zone != "shared":
            raise HTTPException(status_code=403, detail="管理员只能搜索共享区")
        return "shared", None
    if zone == "shared":
        return "shared", None
    return "personal", user.id


@router.post("/keyword", response_model=PaperListResponse)
async def search_keyword(
    req: KeywordSearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    zone, owner = resolve_search_scope(user, req.zone)
    if req.folder_id:
        folder = await get_folder_or_raise(db, req.folder_id)
        try:
            await check_folder_permission(folder, user.id, user.role)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        if folder.zone != zone:
            raise HTTPException(status_code=400, detail="目录区域与请求区域不一致")

    scope_ids = await get_scope_paper_ids(db, req.folder_id, zone, owner)
    if not scope_ids:
        return PaperListResponse(items=[], total=0, page=req.page, page_size=req.page_size)

    papers, total = await keyword_search(db, req.keywords, scope_ids, req.page, req.page_size)
    return PaperListResponse(items=papers, total=total, page=req.page, page_size=req.page_size)


@router.post("/rag", response_model=PaperListResponse)
async def search_rag(
    req: RAGSearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    zone, owner = resolve_search_scope(user, req.zone)
    if req.folder_id:
        folder = await get_folder_or_raise(db, req.folder_id)
        try:
            await check_folder_permission(folder, user.id, user.role)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        if folder.zone != zone:
            raise HTTPException(status_code=400, detail="目录区域与请求区域不一致")

    scope_ids = await get_scope_paper_ids(db, req.folder_id, zone, owner)
    if not scope_ids:
        return PaperListResponse(items=[], total=0, page=req.page, page_size=req.page_size)

    configs = get_model_config_sync()
    threshold = float(configs.get("rag_similarity_threshold", "0.5"))

    papers, total = await rag_search(
        db, req.query, scope_ids, threshold, req.page, req.page_size, user_id=user.id,
    )
    return PaperListResponse(items=papers, total=total, page=req.page, page_size=req.page_size)


@router.post("/cascade", response_model=PaperListResponse)
async def search_cascade(
    req: CascadeSearchRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if not req.keywords and not req.rag_query:
        raise HTTPException(status_code=400, detail="至少需要一种搜索条件")

    zone, owner = resolve_search_scope(user, req.zone)
    if req.folder_id:
        folder = await get_folder_or_raise(db, req.folder_id)
        try:
            await check_folder_permission(folder, user.id, user.role)
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        if folder.zone != zone:
            raise HTTPException(status_code=400, detail="目录区域与请求区域不一致")

    scope_ids = await get_scope_paper_ids(db, req.folder_id, zone, owner)
    if not scope_ids:
        return PaperListResponse(items=[], total=0, page=req.page, page_size=req.page_size)

    configs = get_model_config_sync()
    threshold = float(configs.get("rag_similarity_threshold", "0.5"))

    papers, total = await cascade_search(
        db, req.keywords, req.rag_query, scope_ids, req.order, threshold, req.page, req.page_size,
        user_id=user.id,
    )
    return PaperListResponse(items=papers, total=total, page=req.page, page_size=req.page_size)
