"""
Regex-based hint extraction.
Helper layer that provides hints to the LLM.
Does NOT make decisions.
"""
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dateutil import parser as date_parser
import calendar


class RegexHints:
    """
    Extract possible dates, keywords, and patterns.
    Provides hints to LLM, does not decide.
    """
    
    # Keyword patterns for different event types
    PAYMENT_KEYWORDS = [
        r'\b(fee|payment|pay|due|bill|invoice|charge|tuition)\b',
        r'\b(paid|payable|outstanding|overdue)\b',
    ]
    
    ASSIGNMENT_KEYWORDS = [
        r'\b(assignment|homework|project|submit|submission|deadline)\b',
        r'\b(essay|paper|report|presentation)\b',
    ]
    
    DEADLINE_KEYWORDS = [
        r'\b(deadline|due date|by|before|until)\b',
    ]
    
    # Date patterns
    DATE_PATTERNS = [
        # ISO format: 2026-01-30
        r'\b(\d{4}-\d{2}-\d{2})\b',
        # US format: 01/30/2026, 1/30/26
        r'\b(\d{1,2}/\d{1,2}/\d{2,4})\b',
        # Written: January 30, 2026
        r'\b((?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4})\b',
        # Short written: Jan 30
        r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{1,2})\b',
        # Relative: tomorrow, next week, in 3 days
        r'\b(tomorrow|today|tonight)\b',
        r'\b(next\s+(?:week|month|monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b',
        r'\b(in\s+\d+\s+(?:day|days|week|weeks|month|months))\b',
    ]
    
    # Amount patterns (for payment reminders)
    AMOUNT_PATTERNS = [
        r'\$\s*(\d+(?:,\d{3})*(?:\.\d{2})?)',
        r'\b(\d+(?:,\d{3})*(?:\.\d{2})?)\s*(?:dollars|USD|INR|rupees)\b',
    ]
    
    def extract_hints(self, subject: str, body: str) -> Dict[str, Any]:
        """
        Extract hints from email content.
        Returns a dict of hints for the LLM to consider.
        """
        text = f"{subject}\n{body}"
        
        return {
            'has_payment_keywords': self._check_keywords(text, self.PAYMENT_KEYWORDS),
            'has_assignment_keywords': self._check_keywords(text, self.ASSIGNMENT_KEYWORDS),
            'has_deadline_keywords': self._check_keywords(text, self.DEADLINE_KEYWORDS),
            'possible_dates': self._extract_dates(text),
            'possible_amounts': self._extract_amounts(text),
            'urgency_indicators': self._check_urgency(text),
        }
    
    def _check_keywords(self, text: str, patterns: List[str]) -> bool:
        """Check if any keyword pattern matches."""
        text_lower = text.lower()
        for pattern in patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False
    
    def _extract_dates(self, text: str) -> List[str]:
        """Extract possible dates from text."""
        dates = []
        
        for pattern in self.DATE_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                date_str = match.group(1)
                # Try to parse and normalize
                parsed = self._parse_date(date_str)
                if parsed:
                    dates.append(parsed.isoformat())
        
        # Deduplicate
        return list(set(dates))
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse date string to datetime.
        Handles various formats including relative dates.
        """
        date_str_lower = date_str.lower().strip()
        now = datetime.now()
        
        # Handle relative dates
        if date_str_lower == 'today':
            return now.replace(hour=23, minute=59, second=59)
        elif date_str_lower == 'tomorrow':
            return (now + timedelta(days=1)).replace(hour=23, minute=59, second=59)
        elif date_str_lower == 'tonight':
            return now.replace(hour=23, minute=59, second=59)
        
        # Handle "next week/month/day"
        if date_str_lower.startswith('next '):
            period = date_str_lower[5:]
            if period == 'week':
                return now + timedelta(weeks=1)
            elif period == 'month':
                return now + timedelta(days=30)
            elif period in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                return self._next_weekday(now, period)
        
        # Handle "in X days/weeks/months"
        in_match = re.match(r'in\s+(\d+)\s+(day|days|week|weeks|month|months)', date_str_lower)
        if in_match:
            count = int(in_match.group(1))
            unit = in_match.group(2)
            if 'day' in unit:
                return now + timedelta(days=count)
            elif 'week' in unit:
                return now + timedelta(weeks=count)
            elif 'month' in unit:
                return now + timedelta(days=count * 30)
        
        # Try standard parsing
        try:
            # Use dateutil for flexible parsing
            parsed = date_parser.parse(date_str, fuzzy=True, default=now)
            # Only return if it's in the future
            if parsed > now:
                return parsed
            # If year not specified and date is in past, assume next year
            if parsed.year == now.year and parsed < now:
                parsed = parsed.replace(year=now.year + 1)
            return parsed
        except Exception:
            return None
    
    def _next_weekday(self, current: datetime, weekday_name: str) -> datetime:
        """Get next occurrence of a weekday."""
        weekdays = {
            'monday': 0, 'tuesday': 1, 'wednesday': 2, 'thursday': 3,
            'friday': 4, 'saturday': 5, 'sunday': 6
        }
        target_day = weekdays.get(weekday_name.lower())
        if target_day is None:
            return current
        
        days_ahead = target_day - current.weekday()
        if days_ahead <= 0:
            days_ahead += 7
        
        return current + timedelta(days=days_ahead)
    
    def _extract_amounts(self, text: str) -> List[str]:
        """Extract monetary amounts from text."""
        amounts = []
        
        for pattern in self.AMOUNT_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                amount = match.group(1).replace(',', '')
                amounts.append(f"${amount}")
        
        return amounts
    
    def _check_urgency(self, text: str) -> List[str]:
        """Check for urgency indicators."""
        urgency_patterns = [
            r'\b(urgent|asap|immediately|critical|important)\b',
            r'\b(final|last)\s+(?:reminder|notice|warning)\b',
            r'\b(overdue|late|missed)\b',
        ]
        
        indicators = []
        text_lower = text.lower()
        
        for pattern in urgency_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                match = re.search(pattern, text_lower, re.IGNORECASE)
                if match:
                    indicators.append(match.group(0))
        
        return indicators
