import uuid
from sqlalchemy.orm import Session

from app.models.user import User

DEV_USER_ID = "dev-user-001"


def get_user_by_username(db: Session, username: str) -> User | None:
    """按用户名查询用户，不存在返回 None。"""
    return db.query(User).filter(User.username == username).first()


def get_user_by_id(db: Session, user_id: str) -> User | None:
    """按用户 ID 查询用户，不存在返回 None。"""
    return db.query(User).filter(User.id == user_id).first()


def create_user(
    db: Session,
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
    db.commit()
    db.refresh(user)
    return user


def get_or_create_dev_user(db: Session) -> User:
    user = db.query(User).filter(User.id == DEV_USER_ID).first()
    if user:
        return user
    user = User(
        id=DEV_USER_ID,
        name="Dev User",
        username="dev",
        password_hash="placeholder",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
