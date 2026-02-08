from sqlalchemy import Column, Integer, String

from app.models.base import TimestampMixin
from app.core.db import Base


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id = Column(String(36), primary_key=True)
    name = Column(String(100), nullable=False)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    # 个人中心：辅助 AI 出题
    school = Column(String(200), nullable=True)
    major = Column(String(200), nullable=True)
    grade = Column(String(50), nullable=True)
    age = Column(Integer, nullable=True)
    gender = Column(String(20), nullable=True)
    question_type_preference = Column(String(500), nullable=True)
    difficulty_preference = Column(String(50), nullable=True)
    question_count = Column(Integer, nullable=True)
