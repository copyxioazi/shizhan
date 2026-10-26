"""密码哈希与 JWT 签发/校验。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import uuid4

import bcrypt
import jwt

from app.core.config import settings
from app.core.errors import ApiError, ErrorCode

ALGORITHM = "HS256"
BCRYPT_ROUNDS = 12


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))
    except ValueError:
        return False


def create_access_token(user_id: int, username: str, role: str) -> tuple[str, int]:
    """返回 (token, expires_in_seconds)。"""
    expires_in = settings.jwt_expire_hours * 3600
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "username": username,
        "role": role,
        "iat": now,
        "exp": now + timedelta(seconds=expires_in),
        "jti": str(uuid4()),
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITHM)
    return token, expires_in


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "登录已过期") from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "登录凭证无效") from exc
    try:
        payload["user_id"] = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ApiError(401, ErrorCode.UNAUTHORIZED, "登录凭证无效") from exc
    return payload
