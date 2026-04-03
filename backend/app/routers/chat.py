from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from app.dependencies import require_user
from app.models.user import User
from app.schemas.chat import ChatSessionCreate, ChatSessionInfo, ChatMessageCreate, ChatMessageInfo
from app.services.chat_service import (
    create_session, get_sessions, get_messages, delete_session, delete_sessions_by_paper, stream_chat,
)
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db

router = APIRouter(prefix="/api/chat", tags=["chat"])


@router.post("/sessions", response_model=ChatSessionInfo)
async def create_chat_session(
    req: ChatSessionCreate,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        session = await create_session(db, req.paper_id, user.id, req.source_type, req.source_text)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    return session


@router.get("/sessions/{paper_id}", response_model=list[ChatSessionInfo])
async def list_sessions(
    paper_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    return await get_sessions(db, paper_id, user.id)


@router.get("/messages/{session_id}", response_model=list[ChatMessageInfo])
async def list_messages(
    session_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_messages(db, session_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/sessions/paper/{paper_id}")
async def clear_paper_chat_sessions(
    paper_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    deleted = await delete_sessions_by_paper(db, paper_id, user.id)
    return {"message": "会话已清空", "deleted": deleted}


@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        await delete_session(db, session_id, user.id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"message": "会话已删除"}


@router.post("/sessions/{session_id}/chat")
async def chat(
    session_id: str,
    req: ChatMessageCreate,
    paper_id: str = Query(...),
    include_report: bool = Query(False),
    user: User = Depends(require_user),
):
    """SSE streaming chat endpoint."""
    return StreamingResponse(
        stream_chat(session_id, user.id, req.content, paper_id, include_report),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
    )
