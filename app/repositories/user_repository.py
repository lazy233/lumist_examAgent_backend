from sqlalchemy.orm import Session

from app.models.user import User

DEV_USER_ID = "dev-user-001"


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
