"""
Pydantic models for request/response validation and LLM output schema.
"""
from typing import Optional
from datetime import datetime
from pydantic import BaseModel, Field, validator
from enum import Enum


class EventTypeStr(str, Enum):
    fee_payment = "fee_payment"
    assignment = "assignment"
    dues = "dues"
    other = "other"


class LLMOutputSchema(BaseModel):
    is_reminder: bool
    event_type: EventTypeStr
    title: str = Field(..., max_length=200)
    due_date: Optional[datetime] = None
    confidence: float = Field(..., ge=0.0, le=1.0)

    @validator('title')
    def title_not_empty(cls, v):
        if not v or not v.strip():
            raise ValueError('title must be non-empty')
        return v.strip()


class NormalizedMessageSchema(BaseModel):
    message_id: str
    subject: str
    body: str
    sender: str
    received_at: datetime
    thread_id: str


class EventIntentSchema(BaseModel):
    should_create: bool
    event_type: EventTypeStr
    title: str
    due_date: Optional[datetime] = None
    message_id: str
    thread_id: str
    reason: str
