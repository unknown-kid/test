import logging
import uuid
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, delete
from datetime import datetime, timedelta, timezone
from app.models.notification import Notification

logger = logging.getLogger(__name__)


async def get_unread_notifications(db: AsyncSession, user_id: str) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(and_(Notification.user_id == user_id, Notification.is_read == False))
        .order_by(Notification.created_at.desc())
        .limit(50)
    )
    return list(result.scalars().all())


async def get_all_notifications(db: AsyncSession, user_id: str, limit: int = 50) -> list[Notification]:
    result = await db.execute(
        select(Notification)
        .where(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .limit(limit)
    )
    return list(result.scalars().all())


async def create_notification(db: AsyncSession, user_id: str, type: str, content: str) -> Notification:
    notif = Notification(id=str(uuid.uuid4()), user_id=user_id, type=type, content=content)
    db.add(notif)
    await db.commit()
    await db.refresh(notif)
    return notif


async def mark_as_read(db: AsyncSession, notification_id: str, user_id: str):
    result = await db.execute(
        select(Notification).where(
            and_(Notification.id == notification_id, Notification.user_id == user_id)
        )
    )
    notif = result.scalar_one_or_none()
    if notif:
        notif.is_read = True
        await db.commit()


async def mark_all_read(db: AsyncSession, user_id: str):
    result = await db.execute(
        select(Notification).where(
            and_(Notification.user_id == user_id, Notification.is_read == False)
        )
    )
    for notif in result.scalars().all():
        notif.is_read = True
    await db.commit()


async def delete_notification(db: AsyncSession, notification_id: str, user_id: str):
    result = await db.execute(
        select(Notification).where(
            and_(Notification.id == notification_id, Notification.user_id == user_id)
        )
    )
    notif = result.scalar_one_or_none()
    if notif:
        await db.delete(notif)
        await db.commit()
