from pydantic import BaseModel
from datetime import datetime


class HighlightCreate(BaseModel):
    paper_id: str
    page: int
    position_data: dict


class HighlightInfo(BaseModel):
    id: str
    paper_id: str
    user_id: str
    page: int
    position_data: dict
    created_at: datetime

    class Config:
        from_attributes = True


class AnnotationCreate(BaseModel):
    paper_id: str
    page: int
    position_data: dict
    content: str


class AnnotationInfo(BaseModel):
    id: str
    paper_id: str
    user_id: str
    page: int
    position_data: dict
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class NoteUpdate(BaseModel):
    content: str


class NoteInfo(BaseModel):
    id: str
    paper_id: str
    user_id: str
    content: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
