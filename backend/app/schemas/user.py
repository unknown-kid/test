from pydantic import BaseModel
from datetime import datetime


class UserInfo(BaseModel):
    id: str
    username: str
    role: str
    status: str
    created_at: datetime
    last_login: datetime | None = None
    custom_chat_api_url: str | None = None
    custom_chat_model_name: str | None = None

    class Config:
        from_attributes = True


class UserListItem(BaseModel):
    id: str
    username: str
    status: str
    created_at: datetime
    last_login: datetime | None = None
    paper_count: int = 0

    class Config:
        from_attributes = True
