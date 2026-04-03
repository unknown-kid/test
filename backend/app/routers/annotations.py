from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.dependencies import require_user
from app.models.user import User
from app.models.interaction import Highlight, Annotation, Note
from app.schemas.annotation import (
    HighlightCreate, HighlightInfo, AnnotationCreate, AnnotationInfo,
    NoteUpdate, NoteInfo,
)
from app.services.paper_service import get_owned_personal_paper_for_user

router = APIRouter(prefix="/api/annotations", tags=["annotations"])


# --- Highlights ---
@router.get("/highlights/{paper_id}", response_model=list[HighlightInfo])
async def get_highlights(
    paper_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_owned_personal_paper_for_user(db, paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    result = await db.execute(
        select(Highlight).where(Highlight.paper_id == paper_id, Highlight.user_id == user.id)
    )
    return result.scalars().all()


@router.post("/highlights", response_model=HighlightInfo)
async def create_highlight(
    req: HighlightCreate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_owned_personal_paper_for_user(db, req.paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    h = Highlight(paper_id=req.paper_id, user_id=user.id, page=req.page, position_data=req.position_data)
    db.add(h)
    await db.commit()
    await db.refresh(h)
    return h


@router.delete("/highlights/{highlight_id}")
async def delete_highlight(
    highlight_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Highlight).where(Highlight.id == highlight_id, Highlight.user_id == user.id))
    h = result.scalar_one_or_none()
    if not h:
        raise HTTPException(status_code=404, detail="高亮不存在")
    await db.delete(h)
    await db.commit()
    return {"message": "已删除"}


# --- Annotations ---
@router.get("/annotations/{paper_id}", response_model=list[AnnotationInfo])
async def get_annotations(
    paper_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_owned_personal_paper_for_user(db, paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    result = await db.execute(
        select(Annotation).where(Annotation.paper_id == paper_id, Annotation.user_id == user.id)
    )
    return result.scalars().all()


@router.post("/annotations", response_model=AnnotationInfo)
async def create_annotation(
    req: AnnotationCreate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_owned_personal_paper_for_user(db, req.paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    a = Annotation(
        paper_id=req.paper_id, user_id=user.id,
        page=req.page, position_data=req.position_data, content=req.content,
    )
    db.add(a)
    await db.commit()
    await db.refresh(a)
    return a


@router.delete("/annotations/{annotation_id}")
async def delete_annotation(
    annotation_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(Annotation).where(Annotation.id == annotation_id, Annotation.user_id == user.id))
    a = result.scalar_one_or_none()
    if not a:
        raise HTTPException(status_code=404, detail="批注不存在")
    await db.delete(a)
    await db.commit()
    return {"message": "已删除"}


# --- Notes ---
@router.get("/notes/{paper_id}", response_model=NoteInfo | None)
async def get_note(
    paper_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_owned_personal_paper_for_user(db, paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    result = await db.execute(
        select(Note).where(Note.paper_id == paper_id, Note.user_id == user.id)
    )
    return result.scalar_one_or_none()


@router.put("/notes/{paper_id}", response_model=NoteInfo)
async def update_note(
    paper_id: str,
    req: NoteUpdate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await get_owned_personal_paper_for_user(db, paper_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    result = await db.execute(
        select(Note).where(Note.paper_id == paper_id, Note.user_id == user.id)
    )
    note = result.scalar_one_or_none()
    if note:
        note.content = req.content
    else:
        note = Note(paper_id=paper_id, user_id=user.id, content=req.content)
        db.add(note)
    await db.commit()
    await db.refresh(note)
    return note
