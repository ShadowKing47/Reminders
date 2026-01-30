"""
Main FastAPI application.
Ties all components together and exposes API endpoints.
"""
import os
import asyncio
from contextlib import asynccontextmanager
from typing import Dict, Any

from fastapi import FastAPI, Request, BackgroundTasks
from fastapi.responses import PlainTextResponse
import logging
import redis
from google.oauth2.credentials import Credentials
from app.ingress.gmail_oauth import GmailCredentialsManager
from app.logging_config import configure_logging
from app.middleware.rate_limiter import RedisRateLimiter

from app.storage import Database
from app.storage.async_sqlite import AsyncDatabase
from app.normalize import EmailNormalizer
from app.intelligence import RegexHints, LLMExtractor
from app.decision import EventDecider
from app.ingress import GmailPushHandler
from app.reminders import ReminderScheduler, EventLifecycle
from app.notifications import TwilioSender, WhatsAppWebhook
from app.cleanup import DailyCleanup


# Global instances
db: AsyncDatabase = None
scheduler: ReminderScheduler = None
cleanup: DailyCleanup = None
gmail_handler: GmailPushHandler = None
whatsapp_webhook: WhatsAppWebhook = None
twilio_sender: TwilioSender = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager."""
    global db, scheduler, cleanup, gmail_handler, whatsapp_webhook, twilio_sender
    
    # Configure logging
    configure_logging(os.getenv('LOG_LEVEL', 'INFO'))

    # Initialize database (sync) and async wrapper
    db_sync = Database(db_path=os.getenv('DB_PATH', 'reminders.db'))
    db = AsyncDatabase(db_sync)
    
    # Initialize Redis
    redis_client = redis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
        db=int(os.getenv('REDIS_DB', 0)),
        decode_responses=False,
    )
    # Expose redis on app state for middleware
    app.state.redis = redis_client
    
    # Initialize Gmail credentials using credentials manager
    gmail_mgr = GmailCredentialsManager(
        token_path=os.getenv('GMAIL_TOKEN_PATH', 'token.json'),
        client_id=os.getenv('GMAIL_CLIENT_ID'),
        client_secret=os.getenv('GMAIL_CLIENT_SECRET'),
    )
    try:
        gmail_creds = gmail_mgr.get_credentials()
    except FileNotFoundError:
        # If no token is present, raise with actionable guidance
        raise RuntimeError(
            "Gmail credentials not available. Run OAuth flow to create token.json or set env vars."
        )
    
    # Initialize components
    normalizer = EmailNormalizer()
    regex_hints = RegexHints()
    llm_extractor = LLMExtractor(api_key=os.getenv('GOOGLE_API_KEY'))
    decider = EventDecider(
        confidence_threshold=float(os.getenv('CONFIDENCE_THRESHOLD', '0.7')),
        require_due_date=os.getenv('REQUIRE_DUE_DATE', 'false').lower() == 'true',
    )
    
    # Initialize Twilio
    twilio_sender = TwilioSender()
    
    # Initialize lifecycle
    lifecycle = EventLifecycle(db)
    
    # Initialize scheduler with notification callback
    async def send_notification(reminder, event):
        await twilio_sender.send_reminder(reminder, event)
    
    scheduler = ReminderScheduler(
        db=db,
        notification_callback=send_notification,
        poll_interval=int(os.getenv('SCHEDULER_POLL_INTERVAL', '60')),
    )
    
    # Initialize cleanup
    cleanup = DailyCleanup(
        db=db,
        lifecycle=lifecycle,
        reminder_retention_hours=int(os.getenv('REMINDER_RETENTION_HOURS', '48')),
        event_retention_days=int(os.getenv('EVENT_RETENTION_DAYS', '7')),
    )
    
    # Initialize ingress handler
    gmail_handler = GmailPushHandler(
        db=db,
        redis_client=redis_client,
        gmail_credentials=gmail_creds,
        normalizer=normalizer,
        regex_hints=regex_hints,
        llm_extractor=llm_extractor,
        decider=decider,
    )
    
    # Initialize webhook handler
    whatsapp_webhook = WhatsAppWebhook(lifecycle=lifecycle)

    # Install rate limiter middleware
    rate_limit = RedisRateLimiter(redis_client,
                                  limit=int(os.getenv('RATE_LIMIT_PER_MIN', '60')),
                                  window_seconds=int(os.getenv('RATE_LIMIT_WINDOW', '60')))
    app.middleware('http')(rate_limit)
    
    # Start background tasks
    scheduler_task = asyncio.create_task(scheduler.run())
    cleanup_task = asyncio.create_task(cleanup.run_daily())
    
    print("✅ Application started successfully")
    
    yield
    
    # Cleanup on shutdown
    scheduler.stop()
    cleanup.stop()
    
    await scheduler_task
    await cleanup_task
    
    print("👋 Application shutdown complete")


app = FastAPI(
    title="Event-Driven Reminder System",
    description="Minimal, deterministic reminder system with Gmail → LLM → WhatsApp pipeline",
    version="1.0.0",
    lifespan=lifespan,
)


@app.get("/")
async def root():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "service": "reminder-system",
        "version": "1.0.0",
    }


@app.post("/gmail/push")
async def gmail_push(request: Request, background_tasks: BackgroundTasks):
    """
    Gmail Pub/Sub push notification endpoint.
    
    Receives notifications from Gmail when new messages arrive.
    """
    try:
        # Parse Pub/Sub message
        body = await request.json()
        message = body.get('message', {})
        
        # Process in background
        result = await gmail_handler.handle_push(message)

        # Generate reminders for new events
        if result.get('results'):
            for res in result['results']:
                if res.get('status') == 'created':
                    event_id = res.get('event_id')
                    event = await db.get_event(event_id)
                    if event:
                        await scheduler.generate_reminders_for_event(event)
        
        return {"status": "accepted", "result": result}
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    """
    Twilio WhatsApp webhook endpoint.
    
    Receives inbound WhatsApp messages for event completion.
    """
    try:
        # Parse form data from Twilio
        form_data = await request.form()
        webhook_data = dict(form_data)
        
        # Handle message
        result = await whatsapp_webhook.handle_message(webhook_data)
        
        # Return TwiML response
        reply = result.get('reply', '')
        if reply:
            return PlainTextResponse(
                f'<?xml version="1.0" encoding="UTF-8"?>'
                f'<Response><Message>{reply}</Message></Response>',
                media_type='text/xml',
            )
        
        return PlainTextResponse(
            '<?xml version="1.0" encoding="UTF-8"?><Response></Response>',
            media_type='text/xml',
        )
        
    except Exception as e:
        return {"status": "error", "error": str(e)}


@app.get("/events")
async def list_events(status: str = None):
    """List events, optionally filtered by status."""
    if status:
        from app.storage import EventStatus
        try:
            status_enum = EventStatus(status)
            events = [e for e in await db.get_active_events() if e.status == status_enum]
        except ValueError:
            return {"error": f"Invalid status: {status}"}
    else:
        events = await db.get_active_events()
    
    return {
        "count": len(events),
        "events": [e.to_dict() for e in events],
    }


@app.get("/events/{event_id}")
async def get_event(event_id: int):
    """Get event details by ID."""
    event = await db.get_event(event_id)
    if not event:
        return {"error": "Event not found"}
    
    return event.to_dict()


@app.post("/events/{event_id}/complete")
async def complete_event(event_id: int):
    """Mark event as completed."""
    lifecycle = EventLifecycle(db)
    success = await lifecycle.complete_event(event_id)
    
    if success:
        return {"status": "completed", "event_id": event_id}
    else:
        return {"error": "Event not found"}


@app.post("/cleanup/run")
async def run_cleanup():
    """Manually trigger cleanup job."""
    result = await cleanup.run_once()
    return {"status": "completed", "result": result}


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "main:app",
        host=os.getenv('HOST', '0.0.0.0'),
        port=int(os.getenv('PORT', 8000)),
        reload=os.getenv('RELOAD', 'false').lower() == 'true',
    )
