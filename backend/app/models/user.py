from sqlalchemy import String, DateTime, Text, func
from sqlalchemy.orm import Mapped, mapped_column
from datetime import datetime
from app.models import Base, generate_uuid


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    username: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="user")  # admin / user
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")  # pending / approved
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # User custom chat model config
    custom_chat_api_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_chat_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    custom_chat_model_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
