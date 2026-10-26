from __future__ import annotations

from pydantic import BaseModel, Field


class InitRequest(BaseModel):
    username: str = Field(min_length=3, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    password: str = Field(min_length=8, max_length=72)


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=72)


class UserOut(BaseModel):
    id: int
    username: str
    role: str
    status: str | None = None
    created_at: str | None = None


class LoginUserOut(BaseModel):
    id: int
    username: str
    role: str


class LoginOut(BaseModel):
    token: str
    token_type: str = "Bearer"
    expires_in: int
    user: LoginUserOut
