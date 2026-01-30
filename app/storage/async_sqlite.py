"""
Async wrapper around synchronous Database using asyncio.to_thread.
Provides async methods mirroring `Database` to avoid blocking the event loop.
"""
import asyncio
from typing import List, Optional
from datetime import datetime

from .sqlite import Database
from .models import Event, Reminder, EventStatus


class AsyncDatabase:
    """Async facade for the sync Database."""

    def __init__(self, db: Database):
        self._db = db

    async def create_event(self, event: Event) -> int:
        return await asyncio.to_thread(self._db.create_event, event)

    async def get_event(self, event_id: int) -> Optional[Event]:
        return await asyncio.to_thread(self._db.get_event, event_id)

    async def get_event_by_message_id(self, message_id: str) -> Optional[Event]:
        return await asyncio.to_thread(self._db.get_event_by_message_id, message_id)

    async def get_active_events(self) -> List[Event]:
        return await asyncio.to_thread(self._db.get_active_events)

    async def update_event_status(
        self,
        event_id: int,
        status: EventStatus,
        completed_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None,
    ):
        return await asyncio.to_thread(self._db.update_event_status, event_id, status, completed_at, expires_at)

    async def delete_old_events(self, older_than: datetime) -> int:
        return await asyncio.to_thread(self._db.delete_old_events, older_than)

    async def create_reminder(self, reminder: Reminder) -> int:
        return await asyncio.to_thread(self._db.create_reminder, reminder)

    async def get_pending_reminders(self, now: datetime) -> List[Reminder]:
        return await asyncio.to_thread(self._db.get_pending_reminders, now)

    async def mark_reminder_sent(self, reminder_id: int):
        return await asyncio.to_thread(self._db.mark_reminder_sent, reminder_id)

    async def delete_reminders_for_event(self, event_id: int) -> int:
        return await asyncio.to_thread(self._db.delete_reminders_for_event, event_id)

    async def delete_old_reminders(self, older_than: datetime) -> int:
        return await asyncio.to_thread(self._db.delete_old_reminders, older_than)

    # Expose underlying sync db for cases where sync access is explicitly required
    @property
    def sync_db(self) -> Database:
        return self._db
