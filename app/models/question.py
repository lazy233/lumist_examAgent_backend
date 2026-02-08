from sqlalchemy import Column, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import TimestampMixin
from app.core.db import Base


class Question(Base, TimestampMixin):
    __tablename__ = "questions"

    id = Column(String(36), primary_key=True)
    exercise_id = Column(String(36), ForeignKey("exercises.id"), nullable=False, index=True)
    type = Column(String(30), nullable=False)
    stem = Column(Text, nullable=False)
    options = Column(JSONB, nullable=True)
