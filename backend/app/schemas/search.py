from pydantic import BaseModel, Field


class KeywordSearchRequest(BaseModel):
    keywords: str = Field(..., description="分号分隔的关键词")
    folder_id: str | None = None
    zone: str = "personal"
    page: int = 1
    page_size: int = 20


class RAGSearchRequest(BaseModel):
    query: str = Field(..., description="自然语言检索语句")
    folder_id: str | None = None
    zone: str = "personal"
    page: int = 1
    page_size: int = 20


class CascadeSearchRequest(BaseModel):
    keywords: str | None = None
    rag_query: str | None = None
    folder_id: str | None = None
    zone: str = "personal"
    order: str = "keyword_first"  # keyword_first / rag_first
    page: int = 1
    page_size: int = 20
