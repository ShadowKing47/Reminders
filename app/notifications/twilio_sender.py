"""
Twilio WhatsApp notification adapter.
Sends notifications and receives completion signals.
"""
import os
from typing import Optional
from twilio.rest import Client

from app.storage import Reminder, Event
import logging
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class TwilioSender:
    """
    Sends WhatsApp messages via Twilio.
    
    Responsibilities:
    - Send reminder notifications
    - Format messages appropriately
    
    MUST NOT:
    - Know about Gmail or emails
    - Call LLM
    - Make event decisions
    - Access database directly
    
    Adapter is stateless.
    """
    
    def __init__(
        self,
        account_sid: Optional[str] = None,
        auth_token: Optional[str] = None,
        from_whatsapp: Optional[str] = None,
        to_whatsapp: Optional[str] = None,
    ):
        """
        Initialize Twilio client.
        
        Args:
            account_sid: Twilio account SID
            auth_token: Twilio auth token
            from_whatsapp: Twilio WhatsApp number (format: whatsapp:+1234567890)
            to_whatsapp: Recipient WhatsApp number (format: whatsapp:+1234567890)
        """
        self.account_sid = account_sid or os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = auth_token or os.getenv('TWILIO_AUTH_TOKEN')
        self.from_whatsapp = from_whatsapp or os.getenv('TWILIO_WHATSAPP_FROM')
        self.to_whatsapp = to_whatsapp or os.getenv('TWILIO_WHATSAPP_TO')
        
        if not all([self.account_sid, self.auth_token, self.from_whatsapp, self.to_whatsapp]):
            raise ValueError("Missing required Twilio configuration")
        
        self.client = Client(self.account_sid, self.auth_token)
    
    async def send_reminder(self, reminder: Reminder, event: Event) -> dict:
        """
        Send reminder notification via WhatsApp.
        
        Args:
            reminder: Reminder to send
            event: Associated event
            
        Returns:
            Dict with send status
        """
        # Format message
        message_body = self._format_message(reminder, event)
        
        try:
            # Send via Twilio with retry on transient errors
            res = await self._send_with_retry(message_body)
            return {
                'success': True,
                'message_sid': res.sid,
                'reminder_id': reminder.id,
                'event_id': event.id,
            }
        except Exception as e:
            logger.exception('Twilio send failed')
            return {
                'success': False,
                'error': str(e),
                'reminder_id': reminder.id,
                'event_id': event.id,
            }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception_type(Exception))
    async def _send_with_retry(self, message_body: str):
        # Twilio client is synchronous; run in thread
        from asyncio import to_thread

        def send_sync():
            return self.client.messages.create(
                from_=self.from_whatsapp,
                to=self.to_whatsapp,
                body=message_body,
            )

        return await to_thread(send_sync)
    
    def _format_message(self, reminder: Reminder, event: Event) -> str:
        """
        Format reminder message for WhatsApp.
        
        Includes:
        - Event title
        - Due date
        - Quick reply instructions
        """
        message = reminder.message
        
        # Add completion instructions
        message += f"\n\n📝 Reply with:\n"
        message += f"• DONE {event.id} - Mark as completed\n"
        message += f"• EVENT {event.id} - View details"
        
        return message
