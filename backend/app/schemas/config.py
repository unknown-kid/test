from pydantic import BaseModel
from datetime import datetime


class ConfigItem(BaseModel):
    key: str
    value: str
    description: str | None = None
    updated_at: datetime | None = None

    model_config = {"from_attributes": True}


class ConfigUpdate(BaseModel):
    value: str


class ModelTestRequest(BaseModel):
    model_type: str  # chat / embedding / translate
    api_url: str
    api_key: str
    model_name: str
    translate_type: str = "openai"  # openai / deepl
