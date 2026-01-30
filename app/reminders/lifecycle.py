"""
Event Lifecycle Management.
Handles event state changes and associated cleanup.
"""
from datetime import datetime

from app.storage import Database, EventStatus


class EventLifecycle:
    """
    Manages event lifecycle transitions.
    
    Responsibilities:
    - Mark events as completed
    - Mark events as expired
    - Delete associated reminders immediately on state change
    
    Rules:
    - Deletion follows state change, never precedes it
    - All reminders deleted when event becomes completed/expired
    """
    
    def __init__(self, db: Database):
        self.db = db
    
    async def complete_event(self, event_id: int) -> bool:
        """
        Mark event as completed.
        Immediately deletes all associated reminders.
        
        Returns:
            True if successful, False if event not found
        """
        event = await self.db.get_event(event_id)
        if not event:
            return False
        
        # Update event status
        await self.db.update_event_status(
            event_id=event_id,
            status=EventStatus.COMPLETED,
            completed_at=datetime.now(),
        )
        
        # Delete all reminders immediately
        deleted_count = await self.db.delete_reminders_for_event(event_id)
        
        print(f"Completed event {event_id}: {event.title}")
        print(f"Deleted {deleted_count} reminder(s)")
        
        return True
    
    async def expire_event(self, event_id: int) -> bool:
        """
        Mark event as expired.
        Immediately deletes all associated reminders.
        
        Returns:
            True if successful, False if event not found
        """
        event = await self.db.get_event(event_id)
        if not event:
            return False
        
        # Update event status
        await self.db.update_event_status(
            event_id=event_id,
            status=EventStatus.EXPIRED,
            expires_at=datetime.now(),
        )
        
        # Delete all reminders immediately
        deleted_count = await self.db.delete_reminders_for_event(event_id)
        
        print(f"Expired event {event_id}: {event.title}")
        print(f"Deleted {deleted_count} reminder(s)")
        
        return True
    
    async def auto_expire_past_events(self):
        """
        Auto-expire events whose due date has passed.
        Run this periodically (e.g., daily).
        """
        now = datetime.now()
        active_events = await self.db.get_active_events()
        
        expired_count = 0
        for event in active_events:
            if event.due_date and event.due_date < now:
                await self.expire_event(event.id)
                expired_count += 1
        
        if expired_count > 0:
            print(f"Auto-expired {expired_count} past event(s)")
        
        return expired_count
