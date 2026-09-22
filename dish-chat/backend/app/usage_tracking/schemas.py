from typing import Optional
from functools import cached_property
import datetime

from pydantic import BaseModel, computed_field
from .constants import MODEL_PRICING


class UsageTrackingCreate(BaseModel):
    owner_id: str
    chat_id: str
    model: str
    task: str
    input_tokens: Optional[int] = 0
    input_cache_read: Optional[int] = 0
    input_cache_create: Optional[int] = 0
    output_tokens: Optional[int] = 0

    @computed_field
    @cached_property
    def input_cost(self) -> float:
        return (
            MODEL_PRICING[self.model]["cache_read"] * self.input_cache_read
            + MODEL_PRICING[self.model]["cache_create"] * self.input_cache_create
            + MODEL_PRICING[self.model]["input"] * self.input_tokens
        )

    @computed_field
    @cached_property
    def output_cost(self) -> float:
        return MODEL_PRICING[self.model]["output"] * self.output_tokens


class TokenUsageResp(BaseModel):
    input_token: int = 0
    output_token: int = 0
    cost: float = 0.0
