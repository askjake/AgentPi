from pydantic import BaseModel, Field

from ..config import get_settings
from ..core.utils import get_timestr_now_utc


class Health(BaseModel):
    status: str = "Healthy"
    version: str = get_settings().VERSION
    timestamp: str = Field(default_factory=get_timestr_now_utc)