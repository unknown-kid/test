from pydantic import BaseModel, Field
from datetime import datetime


class ChatSessionCreate(BaseModel):
    paper_id: str
    source_type: str = "normal"  # normal / ask_ai
    source_text: str | None = None


class ChatSessionInfo(BaseModel):
    id: str
    paper_id: str
    user_id: str
    title: str | None = None
    source_type: str
    source_text: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ChatMessageCreate(BaseModel):
    content: str = Field(..., min_length=1)


class ChatMessageInfo(BaseModel):
    id: str
    session_id: str
    role: str
    content: str
    context_chunks: dict | None = None
    created_at: datetime

    class Config:
        from_attributes = True
