"""
Gmail Push Notification Ingress Handler.
Receives Pub/Sub notifications and orchestrates the pipeline.
"""
import os
import base64
import json
from datetime import datetime
from typing import Dict, Any, Optional
import redis
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.normalize import EmailNormalizer
from app.intelligence import RegexHints, LLMExtractor
from app.decision import EventDecider
from app.storage import Database, Event, EventStatus
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import logging

logger = logging.getLogger(__name__)


class GmailPushHandler:
    """
    Handles Gmail Pub/Sub push notifications.
    
    Responsibilities:
    - Decode Pub/Sub payload
    - Extract historyId
    - Fetch new messages via Gmail API
    - Deduplicate using Redis
    - Orchestrate pipeline: normalize → intelligence → decision → storage
    
    MUST NOT:
    - Parse emails directly
    - Run regex/LLM itself
    - Create reminders (scheduler does this)
    - Send notifications
    """
    
    def __init__(
        self,
        db: Database,
        redis_client: redis.Redis,
        gmail_credentials: Credentials,
        normalizer: EmailNormalizer,
        regex_hints: RegexHints,
        llm_extractor: LLMExtractor,
        decider: EventDecider,
    ):
        self.db = db
        self.redis = redis_client
        self.gmail_service = build('gmail', 'v1', credentials=gmail_credentials)
        self.normalizer = normalizer
        self.regex_hints = regex_hints
        self.llm_extractor = llm_extractor
        self.decider = decider
    
    async def handle_push(self, pubsub_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Handle incoming Pub/Sub push notification.
        
        Args:
            pubsub_message: Decoded Pub/Sub message
            
        Returns:
            Processing summary
        """
        # Decode Pub/Sub payload
        try:
            data = base64.b64decode(pubsub_message['data']).decode('utf-8')
            notification = json.loads(data)
        except Exception as e:
            return {'error': f'Failed to decode Pub/Sub message: {e}'}
        
        email_address = notification.get('emailAddress')
        history_id = notification.get('historyId')
        
        if not email_address or not history_id:
            return {'error': 'Missing emailAddress or historyId'}
        
        # Fetch new messages since this historyId
        messages = self._fetch_new_messages(email_address, history_id)
        
        processed = []
        for message_data in messages:
            result = await self._process_message(message_data)
            processed.append(result)
        
        return {
            'email': email_address,
            'history_id': history_id,
            'messages_processed': len(processed),
            'results': processed,
        }
    
    def _fetch_new_messages(self, email_address: str, history_id: str) -> list:
        """
        Fetch new Gmail messages via API.
        
        Args:
            email_address: User's email
            history_id: Starting history ID
            
        Returns:
            List of message objects
        """
        try:
            history = self._fetch_history_with_retry(history_id)
            messages = []
            for record in history.get('history', []):
                for msg_added in record.get('messagesAdded', []):
                    message_id = msg_added['message']['id']
                    message = self.gmail_service.users().messages().get(
                        userId='me',
                        id=message_id,
                        format='full',
                    ).execute()
                    messages.append(message)
            return messages
        except Exception as e:
            logger.exception('Error fetching messages')
            return []

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception_type(Exception))
    def _fetch_history_with_retry(self, history_id: str):
        return self.gmail_service.users().history().list(
            userId='me',
            startHistoryId=history_id,
            historyTypes=['messageAdded'],
        ).execute()
    
    async def _process_message(self, gmail_message: Dict[str, Any]) -> Dict[str, Any]:
        """
        Process a single Gmail message through the pipeline.
        
        Pipeline:
        1. Deduplicate (Redis)
        2. Normalize
        3. Extract regex hints
        4. LLM intelligence
        5. Decision engine
        6. Store event (if approved)
        """
        message_id = gmail_message['id']
        
        # Step 1: Deduplicate using Redis SETNX
        cache_key = f"email:{message_id}"
        is_new = self.redis.setnx(cache_key, '1')
        
        if not is_new:
            return {
                'message_id': message_id,
                'status': 'duplicate',
                'reason': 'Already processed',
            }
        
        # Set expiry (7 days)
        self.redis.expire(cache_key, 7 * 24 * 60 * 60)
        
        # Check if event already exists (database-level idempotency)
        existing_event = await self.db.get_event_by_message_id(message_id)
        if existing_event:
            return {
                'message_id': message_id,
                'status': 'duplicate',
                'reason': 'Event already exists in database',
            }
        
        try:
            # Step 2: Normalize
            normalized = self.normalizer.normalize(gmail_message)
            
            # Step 3: Extract regex hints
            hints = self.regex_hints.extract_hints(
                normalized.subject,
                normalized.body,
            )
            
            # Step 4: LLM intelligence
            llm_output = self.llm_extractor.extract(normalized, hints)
            
            # Step 5: Decision engine
            intent = self.decider.decide(llm_output, normalized)
            
            # Step 6: Store if approved
            if intent.should_create:
                event = Event(
                    id=None,
                    type=intent.event_type,
                    title=intent.title,
                    due_date=intent.due_date,
                    status=EventStatus.ACTIVE,
                    message_id=message_id,
                    thread_id=normalized.thread_id,
                    created_at=datetime.now(),
                )
                
                event_id = await self.db.create_event(event)
                
                return {
                    'message_id': message_id,
                    'status': 'created',
                    'event_id': event_id,
                    'title': intent.title,
                    'reason': intent.reason,
                }
            else:
                return {
                    'message_id': message_id,
                    'status': 'rejected',
                    'reason': intent.reason,
                }
                
        except Exception as e:
            return {
                'message_id': message_id,
                'status': 'error',
                'reason': str(e),
            }
