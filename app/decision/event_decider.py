"""
Event Decision Engine.
Pure business logic layer that makes final decisions.
MUST NOT call LLM or external APIs.
"""
from datetime import datetime
from typing import Optional

from app.storage.models import LLMOutput, EventIntent, NormalizedMessage


class EventDecider:
    """
    Makes final decision on whether to create an event.
    
    Responsibilities:
    - Apply business rules
    - Check confidence thresholds
    - Consider event criticality
    - Produce EventIntent
    
    MUST NOT:
    - Call LLM
    - Send notifications
    - Access external APIs
    - Write to database
    """
    
    def __init__(
        self, 
        confidence_threshold: float = 0.7,
        require_due_date: bool = False,
    ):
        """
        Initialize decision engine with configuration.
        
        Args:
            confidence_threshold: Minimum confidence to create event (0-1)
            require_due_date: Whether events must have a due date
        """
        self.confidence_threshold = confidence_threshold
        self.require_due_date = require_due_date
    
    def decide(
        self, 
        llm_output: LLMOutput, 
        message: NormalizedMessage,
    ) -> EventIntent:
        """
        Make final decision on event creation.
        
        Args:
            llm_output: Structured output from LLM
            message: Original normalized message
            
        Returns:
            EventIntent with decision and reasoning
        """
        # Rule 1: LLM must flag as reminder
        if not llm_output.is_reminder:
            return EventIntent(
                should_create=False,
                event_type=llm_output.event_type,
                title=llm_output.title,
                due_date=llm_output.due_date,
                message_id=message.message_id,
                thread_id=message.thread_id,
                reason="LLM classified as not a reminder",
            )
        
        # Rule 2: Check confidence threshold
        if llm_output.confidence < self.confidence_threshold:
            return EventIntent(
                should_create=False,
                event_type=llm_output.event_type,
                title=llm_output.title,
                due_date=llm_output.due_date,
                message_id=message.message_id,
                thread_id=message.thread_id,
                reason=f"Confidence {llm_output.confidence:.2f} below threshold {self.confidence_threshold}",
            )
        
        # Rule 3: Check if due date required
        if self.require_due_date and llm_output.due_date is None:
            return EventIntent(
                should_create=False,
                event_type=llm_output.event_type,
                title=llm_output.title,
                due_date=llm_output.due_date,
                message_id=message.message_id,
                thread_id=message.thread_id,
                reason="Due date required but not found",
            )
        
        # Rule 4: Validate due date is in future
        if llm_output.due_date:
            if llm_output.due_date < datetime.now():
                return EventIntent(
                    should_create=False,
                    event_type=llm_output.event_type,
                    title=llm_output.title,
                    due_date=llm_output.due_date,
                    message_id=message.message_id,
                    thread_id=message.thread_id,
                    reason="Due date is in the past",
                )
        
        # Rule 5: Validate title is not empty
        if not llm_output.title or len(llm_output.title.strip()) < 3:
            return EventIntent(
                should_create=False,
                event_type=llm_output.event_type,
                title=llm_output.title,
                due_date=llm_output.due_date,
                message_id=message.message_id,
                thread_id=message.thread_id,
                reason="Event title too short or empty",
            )
        
        # Rule 6: Apply criticality overrides
        # High-criticality events (fee_payment) may bypass some rules
        is_critical = self._is_critical_event(llm_output)
        
        if is_critical:
            # Critical events get approved even with lower confidence
            if llm_output.confidence >= 0.5:
                return EventIntent(
                    should_create=True,
                    event_type=llm_output.event_type,
                    title=llm_output.title,
                    due_date=llm_output.due_date,
                    message_id=message.message_id,
                    thread_id=message.thread_id,
                    reason=f"Critical event approved with confidence {llm_output.confidence:.2f}",
                )
        
        # All rules passed
        return EventIntent(
            should_create=True,
            event_type=llm_output.event_type,
            title=llm_output.title,
            due_date=llm_output.due_date,
            message_id=message.message_id,
            thread_id=message.thread_id,
            reason=f"Approved with confidence {llm_output.confidence:.2f}",
        )
    
    def _is_critical_event(self, llm_output: LLMOutput) -> bool:
        """
        Determine if event is high-criticality.
        Critical events: fee_payment, dues
        """
        from app.storage.models import EventType
        
        critical_types = {
            EventType.FEE_PAYMENT,
            EventType.DUES,
        }
        
        return llm_output.event_type in critical_types
