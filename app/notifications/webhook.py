"""
WhatsApp webhook handler for inbound messages.
Receives completion signals and forwards to lifecycle handler.
"""
from typing import Dict, Any, Optional
import re

from app.reminders import EventLifecycle


class WhatsAppWebhook:
    """
    Handles inbound WhatsApp messages from Twilio.
    
    Responsibilities:
    - Parse incoming messages
    - Detect completion signals (DONE, PAID, SUBMITTED)
    - Forward to event lifecycle handler
    
    Adapter is stateless.
    """
    
    # Completion patterns
    COMPLETION_PATTERNS = [
        r'^\s*done\s+(\d+)\s*$',
        r'^\s*paid\s+(\d+)\s*$',
        r'^\s*submitted\s+(\d+)\s*$',
        r'^\s*complete\s+(\d+)\s*$',
        r'^\s*finished\s+(\d+)\s*$',
    ]
    
    # Info patterns
    INFO_PATTERNS = [
        r'^\s*event\s+(\d+)\s*$',
        r'^\s*details\s+(\d+)\s*$',
        r'^\s*show\s+(\d+)\s*$',
    ]
    
    def __init__(self, lifecycle: EventLifecycle):
        self.lifecycle = lifecycle
    
    async def handle_message(self, webhook_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming WhatsApp message.
        
        Args:
            webhook_data: Twilio webhook POST data
            
        Returns:
            Response dict with action taken
        """
        # Extract message body
        body = webhook_data.get('Body', '').strip()
        from_number = webhook_data.get('From', '')
        
        if not body:
            return {'status': 'ignored', 'reason': 'Empty message'}
        
        # Check for completion signal
        completion_match = self._check_completion(body)
        if completion_match:
            event_id = int(completion_match)
            success = await self.lifecycle.complete_event(event_id)

            if success:
                return {
                    'status': 'completed',
                    'event_id': event_id,
                    'reply': f"✅ Event {event_id} marked as completed!",
                }
            else:
                return {
                    'status': 'error',
                    'event_id': event_id,
                    'reply': f"❌ Event {event_id} not found or already completed.",
                }
        
        # Check for info request
        info_match = self._check_info(body)
        if info_match:
            event_id = int(info_match)
            reply = await self._get_event_info(event_id)
            return {
                'status': 'info_request',
                'event_id': event_id,
                'reply': reply,
            }
        
        # Unknown command
        return {
            'status': 'unknown',
            'reply': self._get_help_message(),
        }
    
    def _check_completion(self, body: str) -> Optional[str]:
        """Check if message is a completion signal."""
        body_lower = body.lower()
        
        for pattern in self.COMPLETION_PATTERNS:
            match = re.match(pattern, body_lower, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    def _check_info(self, body: str) -> Optional[str]:
        """Check if message is an info request."""
        body_lower = body.lower()
        
        for pattern in self.INFO_PATTERNS:
            match = re.match(pattern, body_lower, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    async def _get_event_info(self, event_id: int) -> str:
        """Get event information."""
        event = await self.lifecycle.db.get_event(event_id)

        if not event:
            return f"❌ Event {event_id} not found."

        info = f"📋 Event {event_id}\n"
        info += f"Title: {event.title}\n"
        info += f"Type: {event.type.value}\n"
        info += f"Status: {event.status.value}\n"

        if event.due_date:
            info += f"Due: {event.due_date.strftime('%B %d, %Y at %I:%M %p')}\n"

        return info
    
    def _get_help_message(self) -> str:
        """Return help message."""
        return """🤖 Available commands:

📝 Completion:
• DONE [event_id] - Mark event as done
• PAID [event_id] - Mark payment as paid
• SUBMITTED [event_id] - Mark as submitted

ℹ️ Info:
• EVENT [event_id] - View event details

Example: DONE 123
"""
