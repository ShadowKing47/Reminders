"""
Reminder Scheduler.
Generates and triggers reminders for active events.
"""
import asyncio
from datetime import datetime, timedelta
from typing import List

from app.storage import Database, Event, Reminder, EventType


class ReminderScheduler:
    """
    Background service that generates and triggers reminders.
    
    Responsibilities:
    - Generate reminder timestamps based on event type
    - Store reminders in DB
    - Poll for eligible reminders every 30-60 seconds
    - Forward eligible reminders to notification adapter
    
    MUST NOT:
    - Inspect emails
    - Call LLM
    - Decide event validity
    """
    
    def __init__(
        self,
        db: Database,
        notification_callback,  # Function to send notification
        poll_interval: int = 60,  # seconds
    ):
        self.db = db
        self.notification_callback = notification_callback
        self.poll_interval = poll_interval
        self._running = False
    
    async def generate_reminders_for_event(self, event: Event):
        """
        Generate reminders for a new event based on its type and due date.
        
        Reminder schedule:
        - Fee payment: 7 days, 3 days, 1 day, 2 hours before
        - Assignment: 3 days, 1 day, 4 hours before
        - Dues: 5 days, 1 day before
        - Other: 1 day, 6 hours before
        """
        if not event.due_date:
            # No due date, create single reminder for awareness
            reminder = Reminder(
                id=None,
                event_id=event.id,
                trigger_at=datetime.now() + timedelta(hours=1),
                message=f"New event: {event.title} (no deadline)",
                created_at=datetime.now(),
            )
            await self.db.create_reminder(reminder)
            return
        
        # Generate schedule based on type
        schedule = self._get_reminder_schedule(event.type)
        
        now = datetime.now()
        for offset_days, offset_hours in schedule:
            trigger_at = event.due_date - timedelta(days=offset_days, hours=offset_hours)
            
            # Only create if in future
            if trigger_at > now:
                time_desc = self._format_time_remaining(event.due_date, trigger_at)
                
                reminder = Reminder(
                    id=None,
                    event_id=event.id,
                    trigger_at=trigger_at,
                    message=f"⏰ {event.title}\nDue: {event.due_date.strftime('%B %d, %Y at %I:%M %p')}\n{time_desc}",
                    created_at=now,
                )
                
                await self.db.create_reminder(reminder)
    
    def _get_reminder_schedule(self, event_type: EventType) -> List[tuple]:
        """
        Get reminder schedule for event type.
        Returns list of (days_before, hours_before) tuples.
        """
        schedules = {
            EventType.FEE_PAYMENT: [
                (7, 0),   # 7 days before
                (3, 0),   # 3 days before
                (1, 0),   # 1 day before
                (0, 2),   # 2 hours before
            ],
            EventType.ASSIGNMENT: [
                (3, 0),   # 3 days before
                (1, 0),   # 1 day before
                (0, 4),   # 4 hours before
            ],
            EventType.DUES: [
                (5, 0),   # 5 days before
                (1, 0),   # 1 day before
            ],
            EventType.OTHER: [
                (1, 0),   # 1 day before
                (0, 6),   # 6 hours before
            ],
        }
        
        return schedules.get(event_type, schedules[EventType.OTHER])
    
    def _format_time_remaining(self, due_date: datetime, trigger_at: datetime) -> str:
        """Format human-readable time remaining."""
        delta = due_date - trigger_at
        
        if delta.days > 0:
            return f"⚠️ {delta.days} day{'s' if delta.days != 1 else ''} remaining"
        else:
            hours = delta.seconds // 3600
            return f"🚨 {hours} hour{'s' if hours != 1 else ''} remaining"
    
    async def run(self):
        """
        Main scheduler loop.
        Runs continuously, checking for pending reminders.
        """
        self._running = True
        print(f"Reminder scheduler started (polling every {self.poll_interval}s)")
        
        while self._running:
            try:
                await self._check_and_send_reminders()
            except Exception as e:
                print(f"Error in scheduler loop: {e}")
            
            await asyncio.sleep(self.poll_interval)
    
    async def _check_and_send_reminders(self):
        """Check for pending reminders and send them."""
        now = datetime.now()
        
        # Get all pending reminders
        pending = await self.db.get_pending_reminders(now)
        
        if not pending:
            return
        
        print(f"Found {len(pending)} pending reminder(s)")
        
        for reminder in pending:
            try:
                # Get associated event
                event = await self.db.get_event(reminder.event_id)
                
                if not event:
                    # Event deleted, clean up reminder
                    self.db.delete_reminders_for_event(reminder.event_id)
                    continue
                
                # Only send if event is still active
                from app.storage import EventStatus
                if event.status != EventStatus.ACTIVE:
                    # Event completed/expired, skip
                    continue
                
                # Send notification
                await self.notification_callback(reminder, event)
                
                # Mark as sent
                await self.db.mark_reminder_sent(reminder.id)
                
                print(f"Sent reminder {reminder.id} for event {event.id}: {event.title}")
                
            except Exception as e:
                print(f"Error sending reminder {reminder.id}: {e}")
    
    def stop(self):
        """Stop the scheduler loop."""
        self._running = False
