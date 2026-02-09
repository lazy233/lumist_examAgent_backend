import uuid
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User

DEV_USER_ID = "dev-user-001"


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    """按用户名查询用户，不存在返回 None。"""
    result = await db.execute(select(User).where(User.username == username))
    return result.scalars().first()


async def get_user_by_id(db: AsyncSession, user_id: str) -> User | None:
    """按用户 ID 查询用户，不存在返回 None。"""
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalars().first()


async def create_user(
    db: AsyncSession,
    *,
    username: str,
    password_hash: str,
    name: str | None = None,
) -> User:
    """创建新用户，name 为空时用 username 作为显示名。"""
    user_id = str(uuid.uuid4())
    user = User(
        id=user_id,
        username=username,
        password_hash=password_hash,
        name=name or username,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


async def get_or_create_dev_user(db: AsyncSession) -> User:
    result = await db.execute(select(User).where(User.id == DEV_USER_ID))
    user = result.scalars().first()
    if user:
        return user
    user = User(
        id=DEV_USER_ID,
        name="Dev User",
        username="dev",
        password_hash="placeholder",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user
