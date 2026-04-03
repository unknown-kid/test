from sqlalchemy import String, Integer, BigInteger, DateTime, Text, ForeignKey, Index, func
from sqlalchemy.dialects.postgresql import JSON
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.models import Base, generate_uuid


class Paper(Base):
    __tablename__ = "papers"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    title: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    abstract: Mapped[str | None] = mapped_column(Text, nullable=True)
    keywords: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # list of strings
    file_size: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    folder_id: Mapped[str | None] = mapped_column(String(36), ForeignKey("folders.id", ondelete="SET NULL"), nullable=True, index=True)
    minio_object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    processing_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending/processing/completed/failed
    step_statuses: Mapped[dict] = mapped_column(
        JSON, nullable=False,
        default=lambda: {
            "chunking": "pending",
            "title": "pending",
            "abstract": "pending",
            "keywords": "pending",
            "report": "pending",
        }
    )
    uploaded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    zone: Mapped[str] = mapped_column(String(20), nullable=False)  # shared / personal
    original_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    processing_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_papers_title_trgm", "title", postgresql_using="gin",
              postgresql_ops={"title": "gin_trgm_ops"}),
    )
