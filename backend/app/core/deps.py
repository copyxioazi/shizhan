"""FastAPI 依赖：登录态、管理员、项目可见性。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import ApiError, ErrorCode
from app.core.security import decode_access_token
from app.models import Project, User

bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    payload = decode_access_token(credentials.credentials)
    user = await db.get(User, payload["user_id"])
    if user is None:
        raise ApiError(401, ErrorCode.UNAUTHORIZED)
    if user.status != "active":
        raise ApiError(403, ErrorCode.USER_DISABLED)
    return user


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if user.role != "admin":
        raise ApiError(403, ErrorCode.FORBIDDEN)
    return user


async def require_project_visible(
    db: AsyncSession, user: User, project_id: int
) -> Project:
    project = await db.get(Project, project_id)
    if project is None:
        raise ApiError(404, ErrorCode.PROJECT_NOT_FOUND)
    if user.role != "admin" and project.created_by != user.id:
        raise ApiError(403, ErrorCode.FORBIDDEN)
    return project


async def get_visible_project(
    project_id: int,
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Project:
    return await require_project_visible(db, user, project_id)
