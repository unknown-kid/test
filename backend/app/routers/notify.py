import logging
import json
import asyncio
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db, AsyncSessionLocal
from app.dependencies import require_user
from app.models.user import User
from app.services.auth_service import decode_token
from app.schemas.notification import NotificationInfo
from app.services.notify_service import (
    get_unread_notifications, get_all_notifications,
    mark_as_read, mark_all_read, delete_notification,
)
from app.utils.redis_client import redis_client
import jwt

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/notify", tags=["notify"])

# In-memory WebSocket connections: user_id -> set of WebSocket
ws_connections: dict[str, set[WebSocket]] = {}


@router.get("/", response_model=list[NotificationInfo])
async def list_notifications(
    unread_only: bool = False,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    if unread_only:
        return await get_unread_notifications(db, user.id)
    return await get_all_notifications(db, user.id)


@router.post("/{notification_id}/read")
async def read_notification(
    notification_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await mark_as_read(db, notification_id, user.id)
    return {"message": "ok"}


@router.post("/read-all")
async def read_all_notifications(
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await mark_all_read(db, user.id)
    return {"message": "ok"}


@router.delete("/{notification_id}")
async def remove_notification(
    notification_id: str,
    user: User = Depends(require_user),
    db: AsyncSession = Depends(get_db),
):
    await delete_notification(db, notification_id, user.id)
    return {"message": "ok"}


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """WebSocket endpoint for real-time notifications. Auth via query param token."""
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4001, reason="Missing token")
        return

    try:
        payload = decode_token(token)
        if payload.get("type") != "access":
            await websocket.close(code=4001, reason="Invalid token type")
            return
        user_id = payload.get("sub")
    except jwt.ExpiredSignatureError:
        await websocket.close(code=4001, reason="Token expired")
        return
    except jwt.InvalidTokenError:
        await websocket.close(code=4001, reason="Invalid token")
        return

    await websocket.accept()

    # Register connection
    if user_id not in ws_connections:
        ws_connections[user_id] = set()
    ws_connections[user_id].add(websocket)

    # Start Redis subscriber task
    subscriber_task = asyncio.create_task(_redis_subscriber(user_id, websocket))

    try:
        while True:
            # Keep connection alive, handle pings
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        subscriber_task.cancel()
        ws_connections.get(user_id, set()).discard(websocket)
        if user_id in ws_connections and not ws_connections[user_id]:
            del ws_connections[user_id]


async def _redis_subscriber(user_id: str, websocket: WebSocket):
    """Subscribe to Redis pub/sub and forward notifications to this WebSocket."""
    pubsub = redis_client.pubsub()
    await pubsub.subscribe("notifications")
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                try:
                    data = json.loads(message["data"])
                    if data.get("user_id") == user_id:
                        await websocket.send_text(json.dumps(data))
                except (json.JSONDecodeError, Exception):
                    pass
    except asyncio.CancelledError:
        pass
    finally:
        await pubsub.unsubscribe("notifications")
        await pubsub.close()
