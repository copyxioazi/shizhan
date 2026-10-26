"""认证接口：初始化、登录、当前用户、系统状态。"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db
from app.core.deps import get_current_user
from app.core.errors import ApiError, ErrorCode, ok
from app.core.security import create_access_token, hash_password, verify_password
from app.core.timeutil import cn_time
from app.models import User
from app.schemas.auth import InitRequest, LoginOut, LoginRequest
from app.services.config_service import get_raw_config

router = APIRouter(prefix="/system", tags=["认证"])


async def _admin_exists(db: AsyncSession) -> bool:
    value = await db.scalar(select(func.count(User.id)).where(User.role == "admin"))
    return bool(value)


@router.post("/init", status_code=201)
async def system_init(payload: InitRequest, db: AsyncSession = Depends(get_db)):
    # 事务级 advisory lock 保证并发初始化最多一个成功
    await db.execute(text("SELECT pg_advisory_xact_lock(1005)"))
    if await _admin_exists(db):
        raise ApiError(409, ErrorCode.SYSTEM_ALREADY_INITIALIZED)

    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        role="admin",
        status="active",
    )
    db.add(user)
    try:
        await db.commit()
    except Exception as exc:  # noqa: BLE001 - 唯一索引竞态
        await db.rollback()
        raise ApiError(409, ErrorCode.SYSTEM_ALREADY_INITIALIZED, "系统已初始化") from exc
    await db.refresh(user)
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "status": user.status,
        }
    )


@router.post("/login")
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    user = await db.scalar(
        select(User).where(func.lower(User.username) == payload.username.lower())
    )
    if user is None or not verify_password(payload.password, user.password_hash):
        raise ApiError(401, ErrorCode.INVALID_CREDENTIALS)
    if user.status != "active":
        raise ApiError(403, ErrorCode.USER_DISABLED)
    token, expires_in = create_access_token(user.id, user.username, user.role)
    body = LoginOut(
        token=token,
        expires_in=expires_in,
        user={"id": user.id, "username": user.username, "role": user.role},
    )
    return ok(body.model_dump())


@router.get("/me")
async def me(user: User = Depends(get_current_user)):
    return ok(
        {
            "id": user.id,
            "username": user.username,
            "role": user.role,
            "status": user.status,
            "created_at": cn_time(user.created_at),
        }
    )


@router.get("/status")
async def system_status(db: AsyncSession = Depends(get_db)):
    initialized = await _admin_exists(db)
    config = await get_raw_config()
    llm_configured = bool(
        config.get("llm.base_url") and config.get("llm.model") and config.get("llm.api_key")
    )
    return ok(
        {
            "initialized": initialized,
            "llm_configured": llm_configured,
            "isolation_available": {
                "docker": bool(settings.docker_host),
                "local": False,
            },
        }
    )
