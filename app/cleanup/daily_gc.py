"""
Daily garbage collection job.
Cleans up old events and reminders.
"""
import asyncio
from datetime import datetime, timedelta

from app.storage import Database
from app.reminders import EventLifecycle


class DailyCleanup:
    """
    Periodic cleanup job for database maintenance.
    
    Responsibilities:
    - Delete reminders older than 48 hours
    - Delete completed/expired events older than 7 days
    - Auto-expire events past their due date
    
    Deletion follows state change, never precedes it.
    """
    
    def __init__(
        self,
        db: Database,
        lifecycle: EventLifecycle,
        reminder_retention_hours: int = 48,
        event_retention_days: int = 7,
    ):
        self.db = db
        self.lifecycle = lifecycle
        self.reminder_retention_hours = reminder_retention_hours
        self.event_retention_days = event_retention_days
        self._running = False
    
    async def run_once(self):
        """Run cleanup once (for manual triggering)."""
        print(f"Running cleanup job at {datetime.now()}")
        
        # Step 1: Auto-expire past events
        expired_count = self.lifecycle.auto_expire_past_events()
        
        # Step 2: Delete old reminders
        reminder_cutoff = datetime.now() - timedelta(hours=self.reminder_retention_hours)
        deleted_reminders = self.db.delete_old_reminders(reminder_cutoff)
        print(f"Deleted {deleted_reminders} old reminder(s) (older than {self.reminder_retention_hours}h)")
        
        # Step 3: Delete old completed/expired events
        event_cutoff = datetime.now() - timedelta(days=self.event_retention_days)
        deleted_events = self.db.delete_old_events(event_cutoff)
        print(f"Deleted {deleted_events} old event(s) (older than {self.event_retention_days} days)")
        
        return {
            'expired_events': expired_count,
            'deleted_reminders': deleted_reminders,
            'deleted_events': deleted_events,
        }
    
    async def run_daily(self):
        """
        Run cleanup job daily.
        Runs at midnight (or configurable time).
        """
        self._running = True
        print("Daily cleanup job started")
        
        while self._running:
            try:
                # Calculate seconds until next midnight
                now = datetime.now()
                tomorrow = now + timedelta(days=1)
                midnight = tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)
                seconds_until_midnight = (midnight - now).total_seconds()
                
                print(f"Next cleanup in {seconds_until_midnight / 3600:.1f} hours")
                
                # Wait until midnight
                await asyncio.sleep(seconds_until_midnight)
                
                # Run cleanup
                await self.run_once()
                
            except Exception as e:
                print(f"Error in cleanup job: {e}")
                # Wait 1 hour before retrying
                await asyncio.sleep(3600)
    
    def stop(self):
        """Stop the cleanup loop."""
        self._running = False
