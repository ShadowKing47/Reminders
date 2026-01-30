"""
SQLite database operations.
Database is the source of truth.
"""
import sqlite3
from datetime import datetime
from typing import List, Optional
from contextlib import contextmanager
from pathlib import Path

from .models import Event, Reminder, EventStatus, EventType


class Database:
    """SQLite database manager."""
    
    def __init__(self, db_path: str = "reminders.db"):
        self.db_path = db_path
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def _init_db(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Events table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    type TEXT NOT NULL,
                    title TEXT NOT NULL,
                    due_date TEXT,
                    status TEXT NOT NULL,
                    message_id TEXT NOT NULL UNIQUE,
                    thread_id TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    completed_at TEXT,
                    expires_at TEXT
                )
            """)
            
            # Reminders table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS reminders (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id INTEGER NOT NULL,
                    trigger_at TEXT NOT NULL,
                    message TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    sent INTEGER DEFAULT 0,
                    FOREIGN KEY (event_id) REFERENCES events(id) ON DELETE CASCADE
                )
            """)
            
            # Indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_status 
                ON events(status)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_message_id 
                ON events(message_id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reminders_trigger 
                ON reminders(trigger_at, sent)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_reminders_event_id 
                ON reminders(event_id)
            """)
    
    # Event operations
    
    def create_event(self, event: Event) -> int:
        """
        Create a new event. Returns event ID.
        Raises sqlite3.IntegrityError if message_id already exists.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO events (
                    type, title, due_date, status, message_id, 
                    thread_id, created_at, completed_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.type.value,
                event.title,
                event.due_date.isoformat() if event.due_date else None,
                event.status.value,
                event.message_id,
                event.thread_id,
                event.created_at.isoformat(),
                event.completed_at.isoformat() if event.completed_at else None,
                event.expires_at.isoformat() if event.expires_at else None,
            ))
            return cursor.lastrowid
    
    def get_event(self, event_id: int) -> Optional[Event]:
        """Get event by ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE id = ?", (event_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(row)
    
    def get_event_by_message_id(self, message_id: str) -> Optional[Event]:
        """Get event by Gmail message ID (for idempotency)."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE message_id = ?", (message_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return self._row_to_event(row)
    
    def get_active_events(self) -> List[Event]:
        """Get all active events."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM events WHERE status = ?", (EventStatus.ACTIVE.value,))
            return [self._row_to_event(row) for row in cursor.fetchall()]
    
    def update_event_status(
        self, 
        event_id: int, 
        status: EventStatus, 
        completed_at: Optional[datetime] = None,
        expires_at: Optional[datetime] = None
    ):
        """Update event status and related timestamps."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE events 
                SET status = ?, completed_at = ?, expires_at = ?
                WHERE id = ?
            """, (
                status.value,
                completed_at.isoformat() if completed_at else None,
                expires_at.isoformat() if expires_at else None,
                event_id,
            ))
    
    def delete_old_events(self, older_than: datetime) -> int:
        """Delete completed/expired events older than specified date."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM events 
                WHERE status IN (?, ?) 
                AND (completed_at < ? OR expires_at < ?)
            """, (
                EventStatus.COMPLETED.value,
                EventStatus.EXPIRED.value,
                older_than.isoformat(),
                older_than.isoformat(),
            ))
            return cursor.rowcount
    
    # Reminder operations
    
    def create_reminder(self, reminder: Reminder) -> int:
        """Create a new reminder. Returns reminder ID."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO reminders (
                    event_id, trigger_at, message, created_at, sent
                ) VALUES (?, ?, ?, ?, ?)
            """, (
                reminder.event_id,
                reminder.trigger_at.isoformat(),
                reminder.message,
                reminder.created_at.isoformat(),
                1 if reminder.sent else 0,
            ))
            return cursor.lastrowid
    
    def get_pending_reminders(self, now: datetime) -> List[Reminder]:
        """Get all unsent reminders that should trigger now."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM reminders 
                WHERE trigger_at <= ? AND sent = 0
                ORDER BY trigger_at ASC
            """, (now.isoformat(),))
            return [self._row_to_reminder(row) for row in cursor.fetchall()]
    
    def mark_reminder_sent(self, reminder_id: int):
        """Mark a reminder as sent."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                UPDATE reminders SET sent = 1 WHERE id = ?
            """, (reminder_id,))
    
    def delete_reminders_for_event(self, event_id: int) -> int:
        """Delete all reminders for a specific event. Returns count deleted."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM reminders WHERE event_id = ?", (event_id,))
            return cursor.rowcount
    
    def delete_old_reminders(self, older_than: datetime) -> int:
        """Delete reminders older than specified date."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM reminders WHERE created_at < ?
            """, (older_than.isoformat(),))
            return cursor.rowcount
    
    # Helper methods
    
    def _row_to_event(self, row: sqlite3.Row) -> Event:
        """Convert database row to Event object."""
        return Event(
            id=row['id'],
            type=EventType(row['type']),
            title=row['title'],
            due_date=datetime.fromisoformat(row['due_date']) if row['due_date'] else None,
            status=EventStatus(row['status']),
            message_id=row['message_id'],
            thread_id=row['thread_id'],
            created_at=datetime.fromisoformat(row['created_at']),
            completed_at=datetime.fromisoformat(row['completed_at']) if row['completed_at'] else None,
            expires_at=datetime.fromisoformat(row['expires_at']) if row['expires_at'] else None,
        )
    
    def _row_to_reminder(self, row: sqlite3.Row) -> Reminder:
        """Convert database row to Reminder object."""
        return Reminder(
            id=row['id'],
            event_id=row['event_id'],
            trigger_at=datetime.fromisoformat(row['trigger_at']),
            message=row['message'],
            created_at=datetime.fromisoformat(row['created_at']),
            sent=bool(row['sent']),
        )
