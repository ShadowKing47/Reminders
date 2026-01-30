"""
Data models for events and reminders.
Immutable except for lifecycle fields.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum


class EventStatus(Enum):
    """Event lifecycle states."""
    ACTIVE = "active"
    COMPLETED = "completed"
    EXPIRED = "expired"


class EventType(Enum):
    """Types of events the system recognizes."""
    FEE_PAYMENT = "fee_payment"
    ASSIGNMENT = "assignment"
    DUES = "dues"
    OTHER = "other"


@dataclass
class Event:
    """
    Immutable event representation (except lifecycle fields).
    Only active events can generate reminders.
    """
    id: Optional[int]
    type: EventType
    title: str
    due_date: Optional[datetime]
    status: EventStatus
    message_id: str  # Gmail message ID for idempotency
    thread_id: str
    created_at: datetime
    completed_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    
    def to_dict(self):
        """Convert to dict for database storage."""
        return {
            'id': self.id,
            'type': self.type.value,
            'title': self.title,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'status': self.status.value,
            'message_id': self.message_id,
            'thread_id': self.thread_id,
            'created_at': self.created_at.isoformat(),
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
            'expires_at': self.expires_at.isoformat() if self.expires_at else None,
        }


@dataclass
class Reminder:
    """
    Scheduled reminder for an event.
    Deleted immediately when event is completed/expired.
    """
    id: Optional[int]
    event_id: int
    trigger_at: datetime
    message: str
    created_at: datetime
    sent: bool = False
    
    def to_dict(self):
        """Convert to dict for database storage."""
        return {
            'id': self.id,
            'event_id': self.event_id,
            'trigger_at': self.trigger_at.isoformat(),
            'message': self.message,
            'created_at': self.created_at.isoformat(),
            'sent': self.sent,
        }


@dataclass
class NormalizedMessage:
    """Canonical representation of an email message."""
    message_id: str
    subject: str
    body: str
    sender: str
    received_at: datetime
    thread_id: str
    
    def to_dict(self):
        """Convert to dict."""
        return {
            'message_id': self.message_id,
            'subject': self.subject,
            'body': self.body,
            'sender': self.sender,
            'received_at': self.received_at.isoformat(),
            'thread_id': self.thread_id,
        }


@dataclass
class LLMOutput:
    """Structured output from LLM intelligence layer."""
    is_reminder: bool
    event_type: EventType
    title: str
    due_date: Optional[datetime]
    confidence: float
    
    def to_dict(self):
        """Convert to dict."""
        return {
            'is_reminder': self.is_reminder,
            'event_type': self.event_type.value,
            'title': self.title,
            'due_date': self.due_date.isoformat() if self.due_date else None,
            'confidence': self.confidence,
        }


@dataclass
class EventIntent:
    """
    Final decision from the event decision engine.
    This is what gets persisted to the database.
    """
    should_create: bool
    event_type: EventType
    title: str
    due_date: Optional[datetime]
    message_id: str
    thread_id: str
    reason: str  # Why this decision was made (for debugging)
