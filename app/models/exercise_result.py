from sqlalchemy import Column, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.models.base import TimestampMixin
from app.core.db import Base


class ExerciseResult(Base, TimestampMixin):
    __tablename__ = "exercise_results"

    id = Column(String(36), primary_key=True)
    exercise_id = Column(String(36), ForeignKey("exercises.id"), nullable=False, index=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    score = Column(Integer, nullable=True)
    correct_rate = Column(Integer, nullable=True)
    result_details = Column(JSONB, nullable=True)
    submitted_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
