from sqlalchemy import Column, ForeignKey, String, Text

from app.models.base import TimestampMixin
from app.core.db import Base


class Answer(Base, TimestampMixin):
    __tablename__ = "answers"

    id = Column(String(36), primary_key=True)
    question_id = Column(String(36), ForeignKey("questions.id"), nullable=False, index=True)
    correct_answer = Column(Text, nullable=False)
    analysis = Column(Text, nullable=True)
