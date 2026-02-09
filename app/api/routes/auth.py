"""登录与注册接口：POST /auth/login、POST /auth/register。"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.repositories.user_repository import get_user_by_username, create_user
from app.models.user import User

router = APIRouter()


MAX_BCRYPT_PASSWORD_BYTES = 72


def _ensure_password_length(password: str) -> None:
    """bcrypt 限制 72 bytes，超过会抛异常。"""
    if len(password.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
        raise HTTPException(status_code=400, detail="密码过长（最多 72 字节）")


# ----- 请求体 -----
class LoginRequest(BaseModel):
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class RegisterRequest(BaseModel):
    username: str = Field(..., description="用户名（建议唯一）")
    password: str = Field(..., min_length=6, description="密码（至少 6 位）")
    name: str | None = Field(None, description="姓名/昵称")


# ----- 响应体（与前端约定：token + user.id / user.name）-----
class AuthUser(BaseModel):
    id: str = Field(..., description="用户 ID")
    name: str = Field(..., description="显示名称")


class AuthResponse(BaseModel):
    token: str = Field(..., description="JWT 或会话令牌")
    user: AuthUser = Field(..., description="用户信息")


def _auth_response(user: User) -> AuthResponse:
    token = create_access_token(user.id)
    return AuthResponse(token=token, user=AuthUser(id=user.id, name=user.name or user.username))


@router.post("/login", response_model=AuthResponse)
def login(body: LoginRequest, db: Session = Depends(get_db)):
    """登录：用户名+密码，成功返回 token 与 user。"""
    _ensure_password_length(body.password)
    user = get_user_by_username(db, body.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _auth_response(user)


@router.post("/register", response_model=AuthResponse)
def register(body: RegisterRequest, db: Session = Depends(get_db)):
    """注册：用户名+密码+可选姓名，成功即登录，返回 token 与 user。"""
    existing = get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    _ensure_password_length(body.password)
    password_hash = hash_password(body.password)
    user = create_user(db, username=body.username, password_hash=password_hash, name=body.name)
    return _auth_response(user)
