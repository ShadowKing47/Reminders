"""
Email normalization layer.
Converts raw Gmail messages into clean, canonical structure.
"""
import re
import html
from datetime import datetime
from typing import Dict, Any
from bs4 import BeautifulSoup
import base64

from app.storage.models import NormalizedMessage


class EmailNormalizer:
    """
    Converts raw Gmail API messages to canonical format.
    Responsibilities:
    - Strip HTML
    - Merge multipart bodies
    - Normalize whitespace
    - Preserve semantic context
    """
    
    def normalize(self, gmail_message: Dict[str, Any]) -> NormalizedMessage:
        """
        Convert Gmail API message to NormalizedMessage.
        
        Args:
            gmail_message: Raw message dict from Gmail API
            
        Returns:
            NormalizedMessage with cleaned data
        """
        message_id = gmail_message['id']
        thread_id = gmail_message['threadId']
        
        # Extract headers
        headers = {
            header['name'].lower(): header['value']
            for header in gmail_message['payload'].get('headers', [])
        }
        
        subject = headers.get('subject', '(No Subject)')
        sender = headers.get('from', 'unknown@unknown.com')
        date_str = headers.get('date', datetime.utcnow().isoformat())
        
        # Parse received date
        received_at = self._parse_date(date_str)
        
        # Extract body
        body = self._extract_body(gmail_message['payload'])
        
        # Clean body
        body = self._clean_body(body)
        
        return NormalizedMessage(
            message_id=message_id,
            subject=subject,
            body=body,
            sender=sender,
            received_at=received_at,
            thread_id=thread_id,
        )
    
    def _extract_body(self, payload: Dict[str, Any]) -> str:
        """
        Extract and merge body from multipart message.
        Handles both plain text and HTML.
        """
        # Check for simple body
        if 'body' in payload and payload['body'].get('data'):
            return self._decode_body(payload['body']['data'])
        
        # Handle multipart
        if 'parts' in payload:
            return self._extract_from_parts(payload['parts'])
        
        return ""
    
    def _extract_from_parts(self, parts: list) -> str:
        """Recursively extract body from multipart message."""
        bodies = []
        
        for part in parts:
            mime_type = part.get('mimeType', '')
            
            # Prefer plain text
            if mime_type == 'text/plain' and 'data' in part.get('body', {}):
                bodies.append(self._decode_body(part['body']['data']))
            
            # Fallback to HTML
            elif mime_type == 'text/html' and 'data' in part.get('body', {}):
                html_content = self._decode_body(part['body']['data'])
                bodies.append(self._html_to_text(html_content))
            
            # Recurse into nested parts
            elif 'parts' in part:
                bodies.append(self._extract_from_parts(part['parts']))
        
        return '\n\n'.join(filter(None, bodies))
    
    def _decode_body(self, data: str) -> str:
        """Decode base64url-encoded body data."""
        try:
            # Gmail uses base64url encoding
            data = data.replace('-', '+').replace('_', '/')
            decoded = base64.b64decode(data)
            return decoded.decode('utf-8', errors='ignore')
        except Exception:
            return ""
    
    def _html_to_text(self, html_content: str) -> str:
        """Convert HTML to plain text while preserving structure."""
        try:
            # Unescape HTML entities
            text = html.unescape(html_content)
            
            # Parse with BeautifulSoup
            soup = BeautifulSoup(text, 'html.parser')
            
            # Remove script and style elements
            for element in soup(['script', 'style', 'meta', 'link']):
                element.decompose()
            
            # Get text
            text = soup.get_text(separator='\n')
            
            return text
        except Exception:
            # Fallback: basic HTML stripping
            return re.sub(r'<[^>]+>', '', html_content)
    
    def _clean_body(self, body: str) -> str:
        """
        Normalize whitespace while preserving semantic structure.
        """
        # Replace multiple newlines with max 2
        body = re.sub(r'\n{3,}', '\n\n', body)
        
        # Remove trailing whitespace from lines
        lines = [line.rstrip() for line in body.split('\n')]
        body = '\n'.join(lines)
        
        # Collapse multiple spaces to single space (except newlines)
        body = re.sub(r'[^\S\n]+', ' ', body)
        
        # Strip leading/trailing whitespace
        body = body.strip()
        
        return body
    
    def _parse_date(self, date_str: str) -> datetime:
        """
        Parse email date string to datetime.
        Falls back to current time if parsing fails.
        """
        from email.utils import parsedate_to_datetime
        
        try:
            return parsedate_to_datetime(date_str)
        except Exception:
            # Fallback
            return datetime.utcnow()
