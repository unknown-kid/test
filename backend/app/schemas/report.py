from pydantic import BaseModel
from datetime import datetime


class ReportInfo(BaseModel):
    id: str
    paper_id: str
    user_id: str | None
    report_type: str
    content: str | None
    focus_points: str | None
    status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class ReportGenerateRequest(BaseModel):
    focus_points: str | None = None
