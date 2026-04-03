from pydantic import BaseModel
from datetime import datetime


class UserListItem(BaseModel):
    id: str
    username: str
    role: str
    status: str
    created_at: datetime
    last_login: datetime | None = None

    model_config = {"from_attributes": True}


class UserApproveRequest(BaseModel):
    action: str  # approve / reject


class AdminStats(BaseModel):
    total_users: int
    pending_users: int
    total_papers: int
    shared_papers: int
    user_paper_counts: list[dict]
