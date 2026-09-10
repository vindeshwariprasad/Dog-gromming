# Maple Street Dog Grooming — AI Receptionist

An AI-powered receptionist that handles phone calls for a dog grooming shop. It books appointments, reschedules, cancels, answers FAQs, and escalates complex situations to staff — all through natural conversation.

**Phase 1**: Text chat via Streamlit
**Phase 2**: Live voice calls via Vapi

## Architecture

```
Interface Layer (Streamlit / FastAPI+Vapi)
         │
         ▼
Agent Core (Gemini 2.5 Flash + function calling)
         │
         ▼
Tool Executor (validation + business logic)
         │
         ▼
Integration Layer (Google Calendar API + Google Sheets API)
```

**Core design decisions:**

- **One calendar per groomer** (4 calendars) — enables per-groomer availability via batch freebusy queries
- **Google Sheets** with two tabs: `Contacts` (composite key: phone + dog name) and `Call Log`
- **Hybrid state management** — LLM drives the conversation, `SessionState` dataclass tracks collected data and validates required fields before tool execution
- **Create-before-delete reschedule** — new event is created first; if creation fails, original booking is preserved
- **Post-booking conflict detection** — after every `create_event`, a conflict check runs and rolls back if a simultaneous booking was made
- **Event ID resolution** — code-level resolution of LLM-fabricated event IDs using cached appointment data (match by groomer name or single-appointment fallback)



## Features

| Feature | Description |
|---|---|
| Booking | Collect service, date/time, caller info → check availability → book on groomer's calendar |
| Reschedule | Find existing appointment → check new slot → create new → delete old (atomic rollback on failure) |
| Cancel | Find existing appointment → confirm → delete from calendar |
| FAQ | Answer hours, pricing, services, policies — no identification required |
| Running late | Acknowledge, inform session end time unchanged, mention reschedule threshold |
| Escalation | Complaints, refunds, medical concerns → log reason → promise staff callback |
| Multi-dog | Same phone, different dogs — composite key in Contacts sheet |
| Large breed routing | Dogs >25 kg auto-assigned to Mike (large breed specialist) |
| Cancellation fee | <24 hours notice → warn about ₹300 fee, let caller decide |
| Auto call logging | Every call logged to Google Sheets (deduplicated across voice and text) |
| Input validation | Groomer names, dog sizes, phone numbers, dates, service names validated before API calls |

## Tech Stack

| Component | Technology |
|---|---|
| LLM | Gemini 2.5 Flash (function calling, manual tool dispatch) |
| Phase 1 UI | Streamlit |
| Phase 2 server | FastAPI (OpenAI-compatible `/chat/completions` for Vapi) |
| Scheduling | Google Calendar API v3 (freebusy + events) |
| Data store | Google Sheets API v4 (Contacts + Call Log tabs) |
| Auth | Google Service Account |
| Voice | Vapi (Custom LLM provider) |
| Testing | pytest, pytest-asyncio, httpx (198 tests) |

## Project Structure

```
proindex/
├── agent/
│   ├── core.py                 # Agent orchestrator — LLM loop, tool dispatch, event ID resolution
│   ├── state.py                # SessionState dataclass (conversation state tracking)
│   ├── prompts.py              # System prompt builder (shop data + policies + state context)
│   └── tools.py                # 8 tool declarations + ToolExecutor with validation
├── integrations/
│   ├── auth.py                 # Google service account authentication
│   ├── google_calendar.py      # Calendar client (freebusy, create, delete, conflict check)
│   └── google_sheets.py        # Sheets client (contacts CRUD, call logging)
├── config/
│   ├── settings.py             # Environment variable loading
│   ├── shop_data.py            # Services, pricing, groomers, policies, hours
│   └── breed_mapping.py        # Breed → size category mapping (~50 breeds)
├── ui/
│   └── streamlit_app.py        # Phase 1: text chat interface
├── voice/
│   ├── vapi_webhook.py         # Phase 2: FastAPI server (SSE streaming, session management)
│   └── vapi_config.py          # Vapi assistant configuration template
├── scripts/
│   ├── setup_calendars.py      # Create 4 groomer calendars
│   ├── setup_sheets.py         # Create spreadsheet with Contacts + Call Log tabs
│   └── seed_calendar.py        # Seed ~12 test appointments for demo scenarios
├── tests/
│   ├── test_core.py            # Agent core: event ID resolution, session state updates (58 tests)
│   ├── test_tools.py           # Tool executor: all 8 tools with mocked APIs (46 tests)
│   ├── test_vapi_webhook.py    # Vapi webhook: helpers + FastAPI endpoints (46 tests)
│   ├── test_breed_mapping.py   # Breed → size mapping
│   ├── test_shop_data.py       # Service lookup, pricing, hours
│   ├── test_state.py           # SessionState dataclass
│   ├── test_phone_validation.py # Phone normalization
│   ├── test_integration_calendar.py  # Google Calendar API (requires credentials)
│   └── test_integration_sheets.py    # Google Sheets API (requires credentials)
├── .env.example                # Environment variable template
├── .gitignore
├── requirements.txt
├── ARCHITECTURE.md             # Full design specification
└── README.md
```

## Prerequisites

- Python 3.11+
- Google Cloud project with **Calendar API** and **Sheets API** enabled
- Google service account with Calendar and Sheets access
- Gemini API key (from [Google AI Studio](https://aistudio.google.com/))
- (Phase 2) [Vapi](https://vapi.ai/) account + [ngrok](https://ngrok.com/)

## Setup

### 1. Clone and install

```bash
git clone <repo-url>
cd proindex
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Google Cloud setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project (or use existing)
3. Enable **Google Calendar API** and **Google Sheets API**
4. Create a **Service Account** (IAM & Admin → Service Accounts → Create)
5. Download the JSON key file, save as `service_account.json` in the project root
6. Get a **Gemini API key** from [Google AI Studio](https://aistudio.google.com/)

### 3. Configure environment

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```
GEMINI_API_KEY="your-gemini-api-key"
GOOGLE_SERVICE_ACCOUNT_FILE="service_account.json"
```

### 4. Create calendars and spreadsheet

```bash
python scripts/setup_calendars.py
# Copy the GROOMER_CALENDARS output into your .env

python scripts/setup_sheets.py
# Copy the GOOGLE_SHEET_ID output into your .env
```

### 5. Seed test data

```bash
python scripts/seed_calendar.py
```

Creates ~12 appointments over the next 3 days:
- A fully booked 10:00 AM slot (all 4 groomers) for conflict testing
- Existing bookings for Priya (9876543210) for reschedule/cancel testing
- Multi-dog household (Priya has Max and Milo)

## Running

### Phase 1: Text Chat

```bash
python -m streamlit run ui/streamlit_app.py
```

Open http://localhost:8501.

### Phase 2: Voice (Vapi)

```bash
# Terminal 1: Start the server
python -m uvicorn voice.vapi_webhook:app --host 0.0.0.0 --port 8000

# Terminal 2: Expose via ngrok
ngrok http 8000
```

In the Vapi Dashboard:
1. Create an assistant → select **Custom LLM** provider
2. Set Custom LLM URL to `<ngrok-url>/chat/completions`
3. Set Server URL to `<ngrok-url>/vapi-events` (for end-of-call logging)
4. Configure voice (e.g., ElevenLabs) and transcriber (e.g., Deepgram)

## Testing

```bash
# All unit tests (no credentials needed) — 198 tests
pytest tests/ --ignore=tests/test_integration_sheets.py --ignore=tests/test_integration_calendar.py -v

# Integration tests (requires .env + service_account.json)
pytest tests/test_integration_calendar.py tests/test_integration_sheets.py -v
```

### Test coverage

| Test file | What it covers | Tests |
|---|---|---|
| `test_core.py` | `_resolve_event_id` (4 resolution strategies), `_update_session` (all 8 tool types), `AgentResponse` | 58 |
| `test_tools.py` | `ToolExecutor.execute` dispatch, all 8 tool methods, input validation, conflict detection, rollback | 46 |
| `test_vapi_webhook.py` | Helper functions, SSE formatting, call logging dedup, FastAPI endpoints (health, chat, events) | 46 |
| `test_breed_mapping.py` | Breed → size mapping, case insensitivity, partial matching | 11 |
| `test_shop_data.py` | Service lookup, pricing, duration, hours | 15 |
| `test_state.py` | SessionState fields, booking field validation, reset, call summary | 7 |
| `test_phone_validation.py` | Phone normalization, country code stripping, edge cases | 9 |
| `test_integration_*.py` | Live Google Calendar and Sheets API calls | 7 |

## Demo Scenarios

### 1. New Caller Booking
> "I want to book a grooming for my dog"

Agent collects service, date/time, phone → discovers new caller → collects name, dog name, breed → registers in Contacts → checks availability → confirms details + price → books on calendar.

### 2. Returning Caller Reschedule
> "I need to reschedule my appointment"

Agent asks for phone → recognizes Priya → finds upcoming appointments → if within 24 hours, warns about ₹300 fee → collects new date/time → checks availability → confirms → reschedules (atomic: creates new, deletes old, rolls back on failure).

### 3. Cancel Appointment
> "I need to cancel my appointment"

Agent asks for phone → looks up upcoming appointments → confirms which one → warns about fee if <24 hours → cancels from calendar.

### 4. FAQ (No Identification Needed)
> "What are your hours?" / "How much for a bath?"

Agent answers immediately from shop data. No phone number asked.

### 5. Running Late
> "Hi, I'm running about 10 minutes late"

Agent asks for phone → finds appointment → "Your session will still end at the originally scheduled time. If you're more than 15 minutes late, we may need to reschedule."

### 6. Escalation
> "I want to complain about my last visit"

Agent: "I'm sorry to hear that. Let me have a staff member call you back shortly." → logs escalation with reason.

### 7. Conflict Handling
> Book anything for tomorrow at 10:00 AM (seeded as fully booked)

Agent: "That time is fully booked. I have openings at 10:30, 11:00..."

### 8. Multi-Dog Household
> Priya (9876543210) books for her second dog Milo after booking for Max

Agent recognizes Priya, asks which dog, handles each booking independently.

## Key Engineering Decisions

1. **Event ID resolution** — LLMs frequently fabricate event IDs when cancelling/rescheduling. Rather than relying on prompt engineering alone, `_resolve_event_id` in `core.py` implements a 4-strategy resolution: exact match → groomer name match → single appointment fallback → pass-through. This eliminates 404 errors on cancel/reschedule.

2. **Atomic reschedule with rollback** — Reschedule creates the new event first (preserving the original if creation fails). If the old event can't be deleted afterward, the new event is rolled back to prevent duplicate appointments.

3. **Pre-booking conflict check** — Before creating an event, `check_conflict` verifies the slot is still free. After creation, a post-booking check catches race conditions and auto-cleans duplicates.

4. **Deduplicated call logging** — Both voice (Vapi) and text (Streamlit) auto-log calls. Vapi uses a `_logged_calls` set keyed by call ID; Streamlit uses a `call_logged` session flag. End-of-call events provide a final catch-all.

5. **Hybrid state management** — The LLM drives conversation flow, but `SessionState` tracks collected data independently. Tools validate required fields before execution. This prevents the LLM from skipping steps while keeping conversation natural.

## Known Limitations

- **Google Sheets** is not a production database — adequate for ~30 calls/day but wouldn't scale to hundreds
- **Phone numbers** stored as plaintext PII (encryption not implemented for take-home scope)
- **Breed mapping** covers ~50 breeds; unknown breeds require the caller to provide weight
- **Race condition window** — post-booking conflict check has a tiny window (milliseconds) between creation and check; acceptable at this scale
- **Vapi session state** stored in-memory on the server (lost on restart); production would use Redis or a database
- **No authentication** on the Streamlit UI (suitable for demo; production would add auth middleware)
