# Event-Driven Reminder System

A minimal, deterministic reminder system that processes Gmail notifications through an LLM pipeline and sends WhatsApp reminders via Twilio.

## Architecture

```
Gmail → Pub/Sub → Ingress → Normalization → Intelligence (Regex + LLM) 
→ Event Decision → Event Store (SQLite) → Reminder Scheduler → Twilio (WhatsApp)
```

### Key Principles

- **Single Responsibility**: Each layer has exactly one job
- **No LLM Database Access**: LLMs propose, they never persist
- **Side Effects Last**: Twilio notifications only at final stage
- **Event-Driven Deletion**: State changes precede deletion
- **Database as Source of Truth**: SQLite is authoritative
- **Redis for Deduplication Only**: Temporary message tracking

## Project Structure

```
app/
├── ingress/          # Gmail Pub/Sub webhook handler
├── normalize/        # Email to canonical format
├── intelligence/     # Regex hints + LLM extraction
├── decision/         # Business logic decision engine
├── storage/          # SQLite models and operations
├── reminders/        # Scheduler and lifecycle management
├── notifications/    # Twilio WhatsApp adapter
├── cleanup/          # Daily garbage collection
└── main.py          # FastAPI application
```

## Setup

### 1. Prerequisites

- Python 3.10+
- Redis server
- Gmail API credentials
- Google Generative AI API key (Gemini)
- Twilio account with WhatsApp

### 2. Install Dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure Environment

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

Required configuration:

- **Gmail API**: OAuth2 credentials from Google Cloud Console
- **Google AI**: API key for Gemini from Google AI Studio
- **Twilio**: Account SID, Auth Token, WhatsApp numbers
- **Redis**: Connection details (default: localhost:6379)

### 4. Gmail Setup

1. Enable Gmail API in Google Cloud Console
2. Create OAuth2 credentials
3. Set up Pub/Sub topic for Gmail push notifications
4. Subscribe your endpoint: `https://your-domain.com/gmail/push`

### 5. Twilio Setup

1. Get Twilio WhatsApp sandbox or approved number
2. Configure webhook: `https://your-domain.com/whatsapp/webhook`

### 6. Run the Application

```bash
# Development
uvicorn app.main:app --reload

# Production
python -m app.main
```

## API Endpoints

### Gmail Webhook
```
POST /gmail/push
```
Receives Gmail Pub/Sub notifications

### WhatsApp Webhook
```
POST /whatsapp/webhook
```
Receives inbound WhatsApp messages

### Event Management
```
GET /events              # List all events
GET /events/{id}         # Get event details
POST /events/{id}/complete  # Mark event complete
```

### Utilities
```
POST /cleanup/run        # Manually trigger cleanup
GET /                    # Health check
```

## Pipeline Stages

### 1. Ingress (`gmail_push.py`)
- Decodes Pub/Sub payload
- Fetches Gmail messages
- Deduplicates with Redis SETNX
- Orchestrates pipeline

### 2. Normalization (`email_normalizer.py`)
- Strips HTML
- Merges multipart bodies
- Normalizes whitespace
- Produces canonical structure

### 3. Intelligence (`regex_hints.py` + `llm_extractor.py`)
- **Regex**: Extracts dates, keywords, amounts (hints only)
- **LLM**: Analyzes full email, outputs structured JSON
- Must see complete context
- Schema-validated output

### 4. Decision Engine (`event_decider.py`)
- Applies confidence threshold (default: 0.7)
- Validates due dates
- Checks criticality
- Pure business logic (no I/O)

### 5. Event Store (`sqlite.py`)
- Persists approved events
- Enforces idempotency via `message_id`
- Lifecycle: active → completed/expired

### 6. Reminder Scheduler (`scheduler.py`)
- Generates reminder schedule by event type
- Polls every 60s for pending reminders
- Sends via Twilio adapter

### 7. Notification Adapter (`twilio_sender.py`)
- Stateless WhatsApp sender
- Receives completion signals via webhook
- Forwards to lifecycle handler

### 8. Cleanup (`daily_gc.py`)
- Expires past events
- Deletes old reminders (48h)
- Deletes old events (7 days)

## Event Completion

Users can complete events via WhatsApp:

```
DONE 123
PAID 456
SUBMITTED 789
```

System immediately:
1. Marks event as completed
2. Deletes all associated reminders
3. Sends confirmation

## Configuration

### Decision Engine

- `CONFIDENCE_THRESHOLD`: Minimum LLM confidence (0-1)
- `REQUIRE_DUE_DATE`: Whether events must have due dates

### Scheduler

- `SCHEDULER_POLL_INTERVAL`: Seconds between reminder checks

### Cleanup

- `REMINDER_RETENTION_HOURS`: Keep sent reminders this long
- `EVENT_RETENTION_DAYS`: Keep completed events this long

## Reminder Schedules

By event type:

- **Fee Payment**: 7d, 3d, 1d, 2h before
- **Assignment**: 3d, 1d, 4h before
- **Dues**: 5d, 1d before
- **Other**: 1d, 6h before

## Database Schema

### Events
```sql
id, type, title, due_date, status, message_id (unique),
thread_id, created_at, completed_at, expires_at
```

### Reminders
```sql
id, event_id, trigger_at, message, created_at, sent
```

## Safety Features

1. **Idempotency**: Redis + database-level deduplication
2. **Deterministic**: Same input → same output
3. **Debuggable**: Decisions include reasoning
4. **Safe Deletion**: State changes precede cleanup
5. **No Bloat**: Automatic garbage collection

## Non-Goals

This system does NOT implement:

- Polling
- Kafka/message queues
- Vector databases
- WebSockets
- Complex monitoring
- Microservices
- Multi-tenancy

## Development

### Running Tests

```bash
pytest tests/
```

### Manual Testing

1. **Send test email** to configured Gmail account
2. **Check logs** for pipeline processing
3. **Verify event** created: `GET /events`
4. **Wait for reminder** or adjust trigger time
5. **Complete via WhatsApp**: `DONE {event_id}`

## Production Deployment

1. Use proper OAuth2 flow for Gmail (not env tokens)
2. Set up Redis persistence
3. Configure Pub/Sub retry policies
4. Enable HTTPS for webhooks
5. Set up monitoring (logs, health checks)
6. Use process manager (systemd, supervisor)

## Troubleshooting

### LLM not detecting reminders
- Lower `CONFIDENCE_THRESHOLD`
- Check prompt in `llm_extractor.py`
- Verify Google API key

### Reminders not sending
- Check Twilio credentials
- Verify WhatsApp sandbox/approval
- Check scheduler logs

### Duplicate processing
- Verify Redis is running
- Check database constraints
- Review ingress deduplication

## License

MIT

## Contributing

This is a reference implementation. Adapt to your needs.

---

**Built with**: FastAPI, SQLite, Redis, Google Gemini, Twilio  
**Optimized for**: Correctness, idempotency, clarity
