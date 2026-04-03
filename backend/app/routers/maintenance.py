from fastapi import APIRouter, Depends
from app.dependencies import require_admin, check_maintenance, MAINTENANCE_KEY
from app.models.user import User
from app.utils.redis_client import redis_client

router = APIRouter(prefix="/api/admin/maintenance", tags=["maintenance"])


@router.get("/status")
async def get_maintenance_status(admin: User = Depends(require_admin)):
    is_maintenance = await check_maintenance()
    return {"maintenance": is_maintenance}


@router.post("/enable")
async def enable_maintenance(admin: User = Depends(require_admin)):
    await redis_client.set(MAINTENANCE_KEY, "1")

    # Clear all user refresh tokens to force logout
    keys = []
    async for key in redis_client.scan_iter("user_refresh:*"):
        keys.append(key)
    if keys:
        await redis_client.delete(*keys)

    return {"message": "维护模式已开启，所有用户已强制登出"}


@router.post("/disable")
async def disable_maintenance(admin: User = Depends(require_admin)):
    await redis_client.delete(MAINTENANCE_KEY)
    return {"message": "维护模式已关闭"}
