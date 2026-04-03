from pydantic import BaseModel, Field


class PaginationParams(BaseModel):
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=10, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size
