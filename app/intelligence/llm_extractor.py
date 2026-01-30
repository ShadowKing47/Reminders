"""
LLM-based intelligence layer.
Proposes events but does NOT decide or persist.
Uses Google Generative AI (Gemini).
"""
import json
import os
from typing import Dict, Any, Optional
from datetime import datetime
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from google import generativeai as genai

from app.storage.models import NormalizedMessage, LLMOutput, EventType
from app.schemas import LLMOutputSchema
import logging
logger = logging.getLogger(__name__)


class LLMExtractor:
    """
    Uses LLM to extract reminder intent from emails.
    RULES:
    - Must see full email context
    - Must output structured JSON
    - Must NOT write to database
    - Must NOT make final decisions
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """Initialize with Google API key."""
        api_key = api_key or os.getenv('GOOGLE_API_KEY')
        if not api_key:
            raise ValueError("GOOGLE_API_KEY must be set")
        
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-1.5-flash')
    
    def extract(
        self, 
        normalized_message: NormalizedMessage, 
        regex_hints: Dict[str, Any]
    ) -> LLMOutput:
        """
        Extract reminder intent from normalized email.
        
        Args:
            normalized_message: Cleaned email content
            regex_hints: Hints from regex layer
            
        Returns:
            LLMOutput with structured extraction
        """
        prompt = self._build_prompt(normalized_message, regex_hints)
        
        try:
            result = self._call_model_with_retry(prompt)
            result_json = self._parse_response(result.text)

            # Validate with pydantic schema
            schema = LLMOutputSchema.parse_obj(result_json)

            # Convert to internal LLMOutput
            return LLMOutput(
                is_reminder=schema.is_reminder,
                event_type=EventType(schema.event_type.value),
                title=schema.title,
                due_date=schema.due_date,
                confidence=schema.confidence,
            )
        except Exception as e:
            logger.exception("LLM extraction failed")
            return LLMOutput(
                is_reminder=False,
                event_type=EventType.OTHER,
                title="",
                due_date=None,
                confidence=0.0,
            )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8),
           retry=retry_if_exception_type(Exception))
    def _call_model_with_retry(self, prompt: str):
        return self.model.generate_content(
            prompt,
            generation_config={
                'temperature': 0.1,
                'top_p': 0.95,
                'top_k': 40,
            }
        )
    
    def _build_prompt(
        self, 
        message: NormalizedMessage, 
        hints: Dict[str, Any]
    ) -> str:
        """Build prompt for LLM with full context."""
        return f"""You are an expert at analyzing emails to detect reminder-worthy events.

EMAIL CONTENT:
From: {message.sender}
Subject: {message.subject}
Date: {message.received_at.isoformat()}

Body:
{message.body}

REGEX HINTS (non-binding suggestions):
- Has payment keywords: {hints.get('has_payment_keywords', False)}
- Has assignment keywords: {hints.get('has_assignment_keywords', False)}
- Has deadline keywords: {hints.get('has_deadline_keywords', False)}
- Possible dates found: {hints.get('possible_dates', [])}
- Possible amounts: {hints.get('possible_amounts', [])}
- Urgency indicators: {hints.get('urgency_indicators', [])}

TASK:
Analyze this email and determine if it contains a reminder-worthy event.

OUTPUT REQUIREMENTS:
Return ONLY valid JSON with this exact structure:
{{
  "is_reminder": boolean,
  "event_type": "fee_payment" | "assignment" | "dues" | "other",
  "title": string (brief, clear description of the event),
  "due_date": "ISO-8601 datetime string" | null,
  "confidence": number between 0 and 1
}}

CLASSIFICATION RULES:
1. is_reminder: true only if the email contains actionable deadline/payment/task
2. event_type: 
   - "fee_payment": tuition, bills, invoices, payments required
   - "assignment": homework, projects, submissions, academic deadlines
   - "dues": recurring payments, memberships, subscriptions
   - "other": any other actionable reminder
3. title: Extract clear, concise event description (max 100 chars)
4. due_date: Extract or infer deadline. Use ISO-8601 format. null if no deadline.
5. confidence: How certain are you? 0.0-1.0

IMPORTANT:
- Focus on ACTIONABLE items requiring user action
- Ignore promotional emails, newsletters, confirmations
- Be conservative: when unsure, set is_reminder=false
- DO NOT make up dates if none are mentioned
- Consider context and sender reputation

Return ONLY the JSON, no explanations or markdown.
"""
    
    def _parse_response(self, response_text: str) -> Dict[str, Any]:
        """Parse and clean LLM response."""
        # Remove markdown code blocks if present
        text = response_text.strip()
        if text.startswith('```'):
            # Remove code fence
            lines = text.split('\n')
            text = '\n'.join(lines[1:-1]) if len(lines) > 2 else text
        
        text = text.strip()
        if text.startswith('```json'):
            text = text[7:]
        if text.endswith('```'):
            text = text[:-3]
        
        text = text.strip()
        
        # Parse JSON
        return json.loads(text)
    
    def _validate_output(self, result: Dict[str, Any]) -> LLMOutput:
        """Validate and convert to LLMOutput."""
        # Validate required fields
        required = ['is_reminder', 'event_type', 'title', 'due_date', 'confidence']
        for field in required:
            if field not in result:
                raise ValueError(f"Missing required field: {field}")
        
        # Parse event type
        event_type_str = result['event_type'].lower()
        event_type_map = {
            'fee_payment': EventType.FEE_PAYMENT,
            'assignment': EventType.ASSIGNMENT,
            'dues': EventType.DUES,
            'other': EventType.OTHER,
        }
        event_type = event_type_map.get(event_type_str, EventType.OTHER)
        
        # Parse due date
        due_date = None
        if result['due_date']:
            try:
                due_date = datetime.fromisoformat(result['due_date'].replace('Z', '+00:00'))
            except Exception:
                # Invalid date format, ignore
                pass
        
        # Validate confidence
        confidence = float(result['confidence'])
        confidence = max(0.0, min(1.0, confidence))
        
        return LLMOutput(
            is_reminder=bool(result['is_reminder']),
            event_type=event_type,
            title=str(result['title'])[:200],  # Truncate if too long
            due_date=due_date,
            confidence=confidence,
        )
