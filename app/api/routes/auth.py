from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.security import hash_password, verify_password, create_access_token
from app.models.user import User
from app.repositories.user_repository import create_user, get_user_by_username
from app.schemas.auth import AuthResponse, AuthUser, LoginRequest, RegisterRequest

router = APIRouter()

MAX_BCRYPT_PASSWORD_BYTES = 72


def _ensure_password_length(password: str) -> None:
    if len(password.encode("utf-8")) > MAX_BCRYPT_PASSWORD_BYTES:
        raise HTTPException(status_code=400, detail="密码过长（最多 72 字节）")


def _auth_response(user: User) -> AuthResponse:
    token = create_access_token(user.id)
    return AuthResponse(token=token, user=AuthUser(id=user.id, name=user.name or user.username))


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录：用户名+密码，成功返回 token 与 user。"""
    _ensure_password_length(body.password)
    user = await get_user_by_username(db, body.username)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    if not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _auth_response(user)


@router.post("/register", response_model=AuthResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """注册：用户名+密码+可选姓名，成功即登录，返回 token 与 user。"""
    existing = await get_user_by_username(db, body.username)
    if existing:
        raise HTTPException(status_code=400, detail="用户名已存在")
    _ensure_password_length(body.password)
    password_hash = hash_password(body.password)
    user = await create_user(db, username=body.username, password_hash=password_hash, name=body.name)
    return _auth_response(user)
