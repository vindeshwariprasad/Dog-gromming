# AI Receptionist for Maple Street Dog Grooming — Handoff Specification

## A. Problem Statement

Maple Street Dog Grooming receives ~30 inbound phone calls daily. Most are routine (booking, rescheduling, pricing questions). An AI receptionist will handle these autonomously, integrating with Google Calendar for scheduling and Google Sheets for contact/call logging, escalating complex situations to a human. Phase 1 delivers a text chat (Streamlit). Phase 2 wires the same agent to Vapi for live voice calls with <1.2s response latency.

---

## B. Finalized Decisions

| Decision | Choice |
|---|---|
| Language | Python |
| LLM | Gemini 2.5 Flash |
| Currency | INR |
| Phone format | 10-digit Indian mobile (e.g., 9876543210) |
| Google Auth | Service account |
| Calendar model | One calendar per groomer (4 calendars) |
| Slot model | Fixed grid (half-hour boundaries) |
| Groomer assignment | Auto-assign, honor preference if stated |
| Conversation state | Hybrid — data-bag state + LLM function calling |
| Multi-intent | Handle sequentially, loop back after each |
| Google Sheets | Two tabs — Contacts + Call Log |
| Contacts key | Composite: Phone + Dog Name (supports multi-dog households) |
| Caller identification | Phone number; intent-first flow (identify only when needed) |
| Phase 1 UI | Streamlit |
| Phase 2 | Vapi webhook via FastAPI, ngrok for local dev |
| Booking window | Up to 4 weeks ahead |
| Deployment | Local (clone repo, add credentials, run) |

---

## C. Shop Data

### Business Info
- **Name**: Maple Street Dog Grooming
- **Address**: 742 Maple Street
- **Hours**: Monday–Saturday, 9:00 AM – 5:00 PM. Closed Sunday.
- **Timezone**: IST (Asia/Kolkata)
- **Phone**: (555) 123-4567

### Groomers (4)

| Name | Specialty |
|---|---|
| Sarah | All breeds, senior dogs |
| Mike | Large breeds |
| Jessica | Small breeds, puppies |
| Carlos | All breeds, anxious dogs |

### Services

**30-minute services:**

| Service | Price | Duration |
|---|---|---|
| Bath & Brush | ₹500 | 30 min |
| Nail Trim & File | ₹200 | 30 min |
| Teeth Brushing | ₹150 | 30 min |
| Puppy Introduction (first groom) | ₹350 | 30 min |

**60-minute services:**

| Service | Price | Duration |
|---|---|---|
| Full Groom (bath, haircut, nails, ears) | ₹800–₹1,200 (size-dependent) | 60 min |
| De-shedding Treatment | ₹700 | 60 min |
| Flea & Tick Treatment | ₹650 | 60 min |

**Full Groom size-based pricing:**

| Size Category | Weight | Price |
|---|---|---|
| Small | <10 kg | ₹800 |
| Medium | 10–25 kg | ₹1,000 |
| Large | >25 kg | ₹1,200 |

Breed→size mapping covers ~50 common breeds. Unknown breeds: ask caller for weight.

### Policies

**Vaccination**: All dogs must be up to date on Rabies, DHPP, and Bordetella. Proof required at first visit, kept on file. If not current, appointment is rescheduled.

**Breed**: All breeds accepted. Dogs over 100 lbs require booking with Mike. Aggressive dogs require a pre-visit consultation (escalate to human).

**Cancellation**:
- Cancel/reschedule ≥24 hours in advance: no fee
- Cancel/reschedule <24 hours: ₹300 fee (warn caller, let them decide)
- No-show: ₹500 fee

**Late arrival**: Session end time is unchanged. If 60-min session at 3:00 PM and caller arrives at 3:10, grooming ends at 4:00 PM (50 min of actual grooming). If >15 minutes late, may need to reschedule.

---

## D. Architecture

```
┌─────────────────────────────────────────────────┐
│                   I/O Layer                      │
│  ┌──────────────┐       ┌────────────────────┐  │
│  │  Streamlit    │       │  FastAPI Webhook   │  │
│  │  (Phase 1)    │       │  (Phase 2 - Vapi)  │  │
│  └──────┬───────┘       └────────┬───────────┘  │
│         └────────┬───────────────┘               │
│                  ▼                                │
│  ┌──────────────────────────────────────────┐    │
│  │            Agent Core                     │    │
│  │  ┌──────────────────────────────────┐     │    │
│  │  │  State Machine (validates flow)  │     │    │
│  │  └──────────────┬───────────────────┘     │    │
│  │                 ▼                          │    │
│  │  ┌──────────────────────────────────┐     │    │
│  │  │  Gemini 2.5 Flash               │     │    │
│  │  │  (conversation + function calls) │     │    │
│  │  └──────────────┬───────────────────┘     │    │
│  │                 ▼                          │    │
│  │  ┌──────────────────────────────────┐     │    │
│  │  │  Tool Executor                   │     │    │
│  │  │  (Calendar, Sheets, shop data)   │     │    │
│  │  └──────────────────────────────────┘     │    │
│  └──────────────────────────────────────────┘    │
│                  │                                │
│  ┌──────────────────────────────────────────┐    │
│  │           Integrations                    │    │
│  │  ┌────────────┐    ┌─────────────┐        │    │
│  │  │  Google     │    │  Google     │        │    │
│  │  │  Calendar   │    │  Sheets     │        │    │
│  │  │  (4 cals)   │    │  (2 tabs)   │        │    │
│  │  └────────────┘    └─────────────┘        │    │
│  └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────┘
```

### Component Responsibilities

- **I/O Layer**: Adapters translating between user-facing interface and agent core. Streamlit for text chat, FastAPI for Vapi webhooks. Both call the same agent core.
- **State Machine**: Tracks conversation state. Validates LLM isn't skipping required steps. Does NOT generate responses.
- **Gemini 2.5 Flash**: Natural language understanding, response generation, function calling. System prompt contains shop data, policies, behavioral instructions.
- **Tool Executor**: Executes validated function calls against Google APIs.
- **Integrations**: Thin clients wrapping Google Calendar API and Google Sheets API.

### Data Flow (single turn)

1. User message arrives (Streamlit or Vapi webhook)
2. I/O adapter passes message + current state to agent core
3. State machine determines valid next actions
4. Message + state + valid tools → Gemini 2.5 Flash
5. Gemini returns response (possibly with function calls)
6. State machine validates function calls against current state
7. Tool executor runs approved function calls
8. Results fed back to Gemini for final response
9. State updated
10. Response returned to I/O adapter → user

---

## E. State Machine

### States & Transitions

```
GREETING
  → DETERMINE_INTENT (ask "How can I help?")
    → BOOK_SERVICE → BOOK_DATE → BOOK_TIME → IDENTIFY_CALLER → CONFIRM_BOOKING → DONE
    → RESCHEDULE → IDENTIFY_CALLER → RESCHEDULE_LOOKUP → RESCHEDULE_NEW_TIME → CONFIRM_RESCHEDULE → DONE
    → CANCEL → IDENTIFY_CALLER → CANCEL_LOOKUP → CONFIRM_CANCEL → DONE
    → FAQ_RESPONSE → DONE (or → DETERMINE_INTENT for follow-ups)
    → RUNNING_LATE → IDENTIFY_CALLER → ACKNOWLEDGE_LATE → DONE
    → ESCALATE → COLLECT_PHONE → LOG_ESCALATION → DONE
```

### Hybrid Model

- State machine defines valid transitions and required fields per state
- Gemini drives the conversation and calls tools
- State machine validates that required data is collected before booking/rescheduling tools execute
- If Gemini tries to skip a step, state machine blocks and Gemini is prompted to collect missing info

### Required Fields Before Booking

| Field | Source |
|---|---|
| Service | Caller (via conversation) |
| Date | Caller |
| Time | Caller or suggested by agent |
| Groomer | Auto-assigned or caller preference |
| Phone | Caller |
| Name | Caller (or Sheets lookup) |
| Dog Name | Caller (or Sheets lookup) |
| Dog Breed | Caller (or Sheets lookup) |
| Dog Size | Derived from breed or asked |

---

## F. Function-Calling Tools

| Tool | Purpose | Google API | Required State |
|---|---|---|---|
| `check_availability` | Query groomer calendars for a date/time | Calendar freebusy | Service + date known |
| `book_appointment` | Create event on groomer's calendar | Calendar events.insert | All booking fields collected + confirmed |
| `reschedule_appointment` | Create new event, then delete old | Calendar events.insert + delete | New time confirmed |
| `cancel_appointment` | Delete event | Calendar events.delete | Event identified + confirmed |
| `lookup_contact` | Find caller in Contacts tab by phone | Sheets values.get | Phone collected |
| `register_contact` | Add new row to Contacts tab | Sheets values.append | Name, phone, dog info collected |
| `get_upcoming_appointments` | Find caller's bookings across calendars | Calendar events.list | Phone known |
| `escalate_to_staff` | Log escalation for complaints/refunds/medical | — (in-memory) | Reason collected |

> **Note**: Call logging is handled automatically at the application layer (not as an LLM tool) to prevent duplicate/missed logs. Contact updates happen implicitly via `register_contact`.

### Critical Implementation Detail

**Reschedule order**: Create new event FIRST, then delete old event. If creation fails, the original booking is preserved.

**Post-booking conflict check**: After `book_appointment`, immediately query the slot. If duplicate found, delete the later event, apologize, offer alternatives.

---

## G. Google Sheets Schema

### Contacts Tab

| Column | Type | Notes |
|---|---|---|
| Phone | String | Part of composite key |
| Name | String | |
| Dog Name | String | Part of composite key (Phone + Dog Name) |
| Dog Breed | String | |
| Dog Size | String | Small / Medium / Large |
| First Contact Date | Date | |
| Last Contact Date | Date | Updated each call |
| Vaccination Verified | String | Yes / No |
| Notes | String | Special notes |

### Call Log Tab

| Column | Type | Notes |
|---|---|---|
| Timestamp | DateTime | IST |
| Phone | String | FK to Contacts |
| Caller Name | String | |
| Intent | String | Book / Reschedule / Cancel / FAQ / Running Late / Complaint |
| Summary | String | Human-readable call summary |
| Outcome | String | Completed / Escalated / Dropped |
| Escalation Reason | String | Blank if not escalated |

---

## H. Google Calendar Event Format

- **Title**: `{Service} - {Dog Name} ({Owner Name})`
- **Calendar**: Assigned groomer's calendar
- **Start/End**: Based on service duration
- **Description**:
  ```
  Customer: {Name}
  Phone: {Phone}
  Dog: {Dog Name} ({Breed})
  Service: {Service}
  Price: ₹{Price}
  Booked via: AI Receptionist
  Notes: {any special notes}
  ```

---

## I. Slot Model

- Fixed grid: slots start at :00 and :30
- Operating hours: 9:00 AM – 5:00 PM IST, Monday–Saturday
- 30-min services: occupy one slot
- 60-min services: occupy two consecutive slots
- Last valid 60-min slot: 4:00 PM (ends at 5:00 PM)
- Last valid 30-min slot: 4:30 PM (ends at 5:00 PM)
- 4 groomers = up to 4 concurrent slots per time
- A slot is "full" only when all 4 groomers are occupied at that time
- Large breed dogs (>25 kg): must book with Mike

---

## J. Escalation Behavior

### What Gets Escalated
- Complaints about service/charges
- Refund requests
- Medical/injury concerns
- Aggressive dog consultation requests
- Anything unresolvable after 2-3 turns

### Phase 1 (Text Chat)
- Agent says: "I'm sorry to hear that. Let me have a staff member call you back shortly."
- Collects phone if not already identified
- Logs to Call Log with Outcome=Escalated and reason

### Phase 2 (Voice via Vapi)
- Attempt call transfer to shop staff number
- If transfer fails: fall back to callback promise
- Log to Call Log either way

---

## K. Caller Identification Flow

### Intent-First Approach
- Agent greets and asks how it can help
- FAQ intents (hours, pricing) answered immediately — no phone number needed
- Booking/rescheduling/cancellation/running-late triggers identification

### Phase 1 (Text)
- Agent asks caller for phone number
- Looks up in Contacts tab

### Phase 2 (Voice via Vapi)
- Vapi provides caller ID automatically
- Agent auto-looks up and confirms: "I see this might be Priya calling about Max — is that right?"
- If not found: asks for phone, name, dog breed

### New Caller Registration
- Collect: name, phone, dog name, dog breed
- Create row in Contacts tab
- Proceed with intent

### Returning Caller
- Greet by name, reference dog name
- Proceed with intent

---

## L. Failure Handling

| Failure | Behavior |
|---|---|
| Gemini API down | "I'm having technical difficulties. Please call back shortly." |
| Google Calendar API down | "I can't check our schedule right now. Can I take your number and have someone call you back?" |
| Google Sheets API down | Continue with booking (Calendar is critical path). Retry Sheets write with backoff. Fallback: log locally |
| Gemini returns invalid function call | State machine rejects. Agent asks caller to clarify |
| Caller drops mid-conversation | Log partial call with Outcome=Dropped |
| Post-booking conflict detected | Delete conflicting event, apologize, offer alternatives |
| Groomer calendar inaccessible | Skip that groomer, continue with remaining 3 |
| No availability on requested day | Offer next 2-3 available days |
| Requested groomer fully booked | Offer another groomer or another day |
| Reschedule create-new fails | Keep original booking intact, inform caller |

---

## M. Concurrency

- Post-booking conflict check after every Calendar event creation
- If duplicate detected: delete the later event, apologize, offer alternatives
- Google Sheets row appends are inherently safe for concurrent use
- At 30 calls/day, concurrent booking conflicts are rare but handled

---

## N. Security

- Service account credentials in `.json` file, in `.gitignore`, never committed
- `.env` file for any API keys, also in `.gitignore`
- Phone numbers are PII — acknowledge in README (encryption not implemented for take-home)
- Vapi webhook: validate request origin in Phase 2
- Input validation: 10-digit phone, date not in past, date within 4 weeks, valid service name

---

## O. Performance / Latency Budget (Phase 2)

| Step | Target |
|---|---|
| Vapi → server | ~50ms |
| Server processing | ~10ms |
| Google API call (if needed) | ~200-400ms |
| Gemini 2.5 Flash | ~300-500ms |
| Server → Vapi | ~50ms |
| **Total with API call** | **~600-1000ms** |
| **Total without API call (FAQ)** | **~400-600ms** |

### Optimization Strategies
- Cache shop data (hours, prices, policies) in memory — no API call for FAQs
- Use Calendar freebusy batch query instead of per-groomer queries where possible
- Keep system prompts concise
- Use Gemini 2.5 Flash (not Pro)

---

## P. Testing Strategy

### Unit Tests
- State machine transitions (all valid paths + invalid transitions blocked)
- Breed→size mapping
- Phone number normalization
- Price calculation (service + size)
- Slot grid generation (respecting closing time)

### Integration Tests
- Google Calendar: create, read, delete events
- Google Sheets: read, write, append rows
- Real API calls against test calendars/sheets

### Agent Scenario Tests
- New caller books 30-min service
- New caller books 60-min service (size-dependent pricing)
- Returning caller recognized and greeted
- Returning caller reschedules within 24 hours (fee warning)
- Returning caller reschedules outside 24 hours (no fee)
- FAQ-only call (no identification)
- Running late notification
- Escalation (complaint)
- Fully booked slot → alternatives offered
- Multi-intent call (book + reschedule)
- Large breed → assigned to Mike
- Unknown breed → asks weight
- Multi-dog household (same phone, different dogs)

---

## Q. Pre-Seeded Calendar Data

Seed ~10-15 appointments over the next 3 days:
- At least one time slot fully booked (all 4 groomers occupied) to test conflict handling
- At least one existing booking with a known contact to test reschedule flow
- Mix of 30-min and 60-min services
- Appointments spread across all 4 groomers
- Include a booking within 24 hours to test cancellation fee logic

---

## R. Project Structure

```
proindex/
├── agent/
│   ├── core.py              # Agent core — orchestrates LLM + tools
│   ├── state.py             # Session state dataclass (data-bag)
│   ├── prompts.py           # System prompt builder
│   └── tools.py             # Tool declarations + executor
├── integrations/
│   ├── google_calendar.py   # Google Calendar API client (4 calendars)
│   ├── google_sheets.py     # Google Sheets API client (2 tabs)
│   └── auth.py              # Service account authentication
├── config/
│   ├── shop_data.py         # Shop info, services, pricing, policies
│   ├── breed_mapping.py     # Breed → size category mapping
│   └── settings.py          # Environment config, calendar IDs, sheet ID
├── ui/
│   └── streamlit_app.py     # Phase 1 chat interface
├── voice/
│   ├── vapi_webhook.py      # FastAPI webhook for Vapi (Phase 2)
│   └── vapi_config.py       # Vapi assistant configuration
├── scripts/
│   ├── seed_calendar.py     # Pre-seed calendar with test appointments
│   ├── setup_sheets.py      # Create sheet with correct tabs/headers
│   └── setup_calendars.py   # Create 4 groomer calendars
├── tests/
│   ├── test_core.py               # Agent core: event ID resolution, state updates (58 tests)
│   ├── test_tools.py              # Tool executor: all 8 tools, validation, rollback (46 tests)
│   ├── test_vapi_webhook.py       # Vapi webhook: helpers, endpoints (46 tests)
│   ├── test_breed_mapping.py
│   ├── test_shop_data.py
│   ├── test_state.py
│   ├── test_phone_validation.py
│   ├── test_integration_calendar.py
│   └── test_integration_sheets.py
├── .env.example             # Template for environment variables
├── .gitignore
├── requirements.txt
└── README.md                # Setup instructions, demo guide
```

---

## S. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vapi + Gemini integration issues | Medium | High | Test early with minimal hello-world. Have OpenAI as emergency fallback |
| Gemini function calling quirks | Low-Medium | Medium | State machine validates all calls. Retry on malformed |
| >1.2s latency with Google API | Low | Medium | Cache shop data, use freebusy batch, keep prompts concise |
| Evaluator setup difficulty | Medium | High | Detailed README, .env.example, setup scripts |

---

## T. Acceptance Criteria

1. New caller booking: collects all info, checks availability, books on correct groomer's calendar, registers in Contacts, logs in Call Log
2. Returning caller recognized: looks up by phone, greets by name and dog name
3. Conflict handling: full slot → agent offers alternatives
4. Reschedule with fee warning: <24 hours → warns about ₹300 fee, lets caller decide
5. FAQ without identification: hours/pricing answered immediately, no phone asked
6. Running late: acknowledges, communicates session end time unchanged, logs it
7. Escalation: complaint → callback promise, logged with reason
8. Multi-dog support: same phone, different dogs handled correctly
9. Calendar state correct: after all operations, Google Calendar reflects correct state
10. Sheets state correct: Contacts tab has composite-keyed rows, Call Log has one row per call
11. Phase 2 voice: same agent logic via Vapi, <1.2s response latency
12. Pre-seeded data: 10-15 test appointments demonstrating conflict scenarios
13. Late arrival: session end time unchanged, caller informed
14. Large breed routing: dogs >25 kg auto-assigned to Mike
15. Cancellation policy enforced: <24 hours = fee warning, >24 hours = no fee
