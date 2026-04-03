from pydantic import BaseModel, Field
from datetime import datetime


class FolderCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)
    parent_id: str | None = None


class FolderRename(BaseModel):
    name: str = Field(..., min_length=1, max_length=500)


class FolderMove(BaseModel):
    target_parent_id: str | None = None
    conflict_resolution: str | None = None  # "overwrite" / "merge"


class FolderInfo(BaseModel):
    id: str
    name: str
    parent_id: str | None = None
    zone: str
    owner_id: str | None = None
    depth: int
    paper_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class FolderTreeNode(BaseModel):
    id: str
    name: str
    children: list['FolderTreeNode'] = []
    paper_count: int = 0
