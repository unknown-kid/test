from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.auth import (
    LoginRequest, RegisterRequest, TokenResponse,
    RefreshRequest, ChangePasswordRequest,
)
from app.schemas.user import UserInfo
from app.services.auth_service import (
    register_user, authenticate_user, change_password,
    create_access_token, create_refresh_token,
    store_refresh_token, get_stored_refresh_token,
    delete_refresh_token, decode_token,
)
from app.dependencies import get_current_user, require_admin, require_user
from app.models.user import User
from app.utils.redis_client import redis_client
import jwt

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/register")
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await register_user(db, req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "注册成功，请等待管理员审批", "user_id": user.id}


@router.post("/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    # Check maintenance mode for non-admin
    maintenance = await redis_client.get("system:maintenance_mode")
    try:
        user = await authenticate_user(db, req.username, req.password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    if maintenance == "1" and user.role != "admin":
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="系统维护中，暂时无法登录")
    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)
    await store_refresh_token(user.id, user.role, refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role=user.role)


@router.post("/admin/login", response_model=TokenResponse)
async def admin_login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    try:
        user = await authenticate_user(db, req.username, req.password, expected_role="admin")
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(e))
    access_token = create_access_token(user.id, user.role)
    refresh_token = create_refresh_token(user.id, user.role)
    await store_refresh_token(user.id, user.role, refresh_token)
    return TokenResponse(access_token=access_token, refresh_token=refresh_token, role=user.role)


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = decode_token(req.refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的Token类型")
        user_id = payload["sub"]
        role = payload["role"]
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh Token已过期，请重新登录")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="无效的Token")

    stored = await get_stored_refresh_token(user_id, role)
    if stored != req.refresh_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh Token已失效")

    # Check maintenance for non-admin
    if role != "admin":
        maintenance = await redis_client.get("system:maintenance_mode")
        if maintenance == "1":
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="系统维护中")

    new_access = create_access_token(user_id, role)
    new_refresh = create_refresh_token(user_id, role)
    await store_refresh_token(user_id, role, new_refresh)
    return TokenResponse(access_token=new_access, refresh_token=new_refresh, role=role)


@router.post("/logout")
async def logout(user: User = Depends(get_current_user)):
    await delete_refresh_token(user.id, user.role)
    return {"message": "已退出登录"}


@router.get("/me", response_model=UserInfo)
async def get_me(user: User = Depends(get_current_user)):
    return user


@router.put("/admin/password")
async def admin_change_password(
    req: ChangePasswordRequest,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    try:
        await change_password(db, user.id, req.old_password, req.new_password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"message": "密码修改成功"}
