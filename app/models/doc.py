from sqlalchemy import Boolean, Column, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB

from app.models.base import TimestampMixin
from app.core.db import Base


class Doc(Base, TimestampMixin):
    __tablename__ = "docs"

    id = Column(String(36), primary_key=True)
    owner_id = Column(String(36), ForeignKey("users.id"), nullable=False, index=True)
    file_name = Column(String(255), nullable=False)
    file_path = Column(String(500), nullable=False)
    file_hash = Column(String(64), nullable=True)
    file_size = Column(Integer, nullable=True)
    status = Column(String(20), nullable=False, default="uploaded")
    save_to_library = Column(Boolean, nullable=False, default=False)
    parsed_school = Column(String(200), nullable=True)
    parsed_major = Column(String(200), nullable=True)
    parsed_course = Column(String(200), nullable=True)
    parsed_summary = Column(Text, nullable=True)
    parsed_knowledge_points = Column(JSONB, nullable=True)
