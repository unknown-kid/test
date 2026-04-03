from pydantic import BaseModel
from datetime import datetime


class NotificationInfo(BaseModel):
    id: str
    user_id: str
    type: str
    content: str
    is_read: bool
    created_at: datetime

    model_config = {"from_attributes": True}
