from pydantic import BaseModel, Field
from datetime import datetime


class PaperInfo(BaseModel):
    id: str
    title: str | None = None
    abstract: str | None = None
    keywords: list[str] | None = None
    similarity_score: float | None = None
    file_size: int
    folder_id: str | None = None
    processing_status: str
    step_statuses: dict
    zone: str
    original_filename: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class PaperMove(BaseModel):
    target_folder_id: str | None = None
    conflict_resolution: str | None = None  # "overwrite" / "skip"


class PaperCopy(BaseModel):
    target_folder_id: str | None = None
    conflict_resolution: str | None = None  # "overwrite" / "skip"


class PaperBatchMove(BaseModel):
    paper_ids: list[str]
    target_folder_id: str | None = None


class PaperBatchCopy(BaseModel):
    paper_ids: list[str]
    target_folder_id: str | None = None


class PaperKeywordsUpdate(BaseModel):
    keywords: list[str] = Field(default_factory=list)


class PaperListResponse(BaseModel):
    items: list[PaperInfo]
    total: int
    page: int
    page_size: int


class FolderContentResponse(BaseModel):
    folders: list['FolderItemResponse']
    papers: PaperListResponse
    current_folder: 'FolderBreadcrumb | None' = None
    breadcrumbs: list['FolderBreadcrumb'] = []


class FolderItemResponse(BaseModel):
    id: str
    name: str
    paper_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class FolderBreadcrumb(BaseModel):
    id: str
    name: str
