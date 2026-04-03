import jwt
from datetime import datetime, timedelta, timezone
from passlib.context import CryptContext
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import get_settings
from app.models.user import User
from app.utils.redis_client import redis_client

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


def create_access_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    payload = {"sub": user_id, "role": role, "exp": expire, "type": "access"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(user_id: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    payload = {"sub": user_id, "role": role, "exp": expire, "type": "refresh"}
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])


async def store_refresh_token(user_id: str, role: str, token: str):
    key = f"{role}_refresh:{user_id}"
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    await redis_client.set(key, token, ex=ttl)


async def get_stored_refresh_token(user_id: str, role: str) -> str | None:
    key = f"{role}_refresh:{user_id}"
    return await redis_client.get(key)


async def delete_refresh_token(user_id: str, role: str):
    key = f"{role}_refresh:{user_id}"
    await redis_client.delete(key)


async def register_user(db: AsyncSession, username: str, password: str) -> User:
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise ValueError("用户名已存在")
    user = User(
        username=username,
        password_hash=hash_password(password),
        role="user",
        status="pending",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def authenticate_user(db: AsyncSession, username: str, password: str, expected_role: str | None = None) -> User:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.password_hash):
        raise ValueError("用户名或密码错误")
    if expected_role and user.role != expected_role:
        raise ValueError("用户名或密码错误")
    if user.role == "user" and user.status != "approved":
        raise ValueError("账号尚未审批通过，请等待管理员审批")
    # Update last_login
    user.last_login = datetime.now(timezone.utc)
    await db.commit()
    return user


async def change_password(db: AsyncSession, user_id: str, old_password: str, new_password: str):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("用户不存在")
    if not verify_password(old_password, user.password_hash):
        raise ValueError("原密码错误")
    user.password_hash = hash_password(new_password)
    await db.commit()
