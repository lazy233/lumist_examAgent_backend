from sqlalchemy import Column, ForeignKey, Integer, String

from app.models.base import TimestampMixin
from app.core.db import Base


class Exercise(Base, TimestampMixin):
    __tablename__ = "exercises"

    id = Column(String(36), primary_key=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    title = Column(String(255), nullable=True)
    status = Column(String(20), nullable=False, default="generating")
    difficulty = Column(String(20), nullable=False)
    count = Column(Integer, nullable=False)
    source_doc_id = Column(String(36), ForeignKey("docs.id"), nullable=True, index=True)
