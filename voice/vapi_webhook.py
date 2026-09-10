"""
Phase 2: Vapi integration via OpenAI-compatible /chat/completions endpoint.

Vapi sends standard OpenAI-format requests. This server:
1. Receives the conversation from Vapi
2. Routes it through our ReceptionistAgent (which uses Gemini)
3. Returns the response in OpenAI-compatible streaming SSE format

Run with: uvicorn voice.vapi_webhook:app --host 0.0.0.0 --port 8000
Then expose with: ngrok http 8000
"""

import sys
import os
import json
import time
import logging
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse

from integrations.auth import get_google_credentials
from integrations.google_calendar import CalendarClient
from integrations.google_sheets import SheetsClient
from agent.core import create_agent
from agent.state import SessionState
from config.settings import VAPI_SECRET

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Initialize the agent on server startup."""
    logger.info("Starting Vapi LLM server...")
    get_agent()
    logger.info("Agent initialized, ready for calls")
    yield

app = FastAPI(title="Maple Street Dog Grooming - Vapi LLM Server", lifespan=lifespan)

# Global agent, sheets client, and session store
_agent = None
_sheets_client = None
_sessions: dict[str, SessionState] = {}
_logged_calls: set[str] = set()  # Track which call IDs have been logged


def get_agent():
    global _agent, _sheets_client
    if _agent is None:
        credentials = get_google_credentials()
        calendar_client = CalendarClient(credentials)
        _sheets_client = SheetsClient(credentials)
        _agent = create_agent(calendar_client, _sheets_client)
    return _agent


def _log_call_if_needed(call_id: str, session: SessionState, force: bool = False) -> None:
    """Auto-log the call. Called after action tools or at end-of-call."""
    if call_id in _logged_calls:
        return
    # Skip if no meaningful interaction happened (unless forced by end-of-call)
    if not force and not session.intents_completed and not session.call_summary_parts:
        return

    if session.intents_completed:
        intent = ", ".join(session.intents_completed)
    elif session.current_intent:
        intent = f"{session.current_intent} (abandoned)"
    else:
        intent = "General"
    summary = session.get_call_summary() or "Voice call (no action taken)"

    if _sheets_client:
        _sheets_client.log_call(
            phone=session.phone or "",
            caller_name=session.name or "",
            intent=intent,
            summary=summary,
            outcome="Completed",
        )
        _logged_calls.add(call_id)
        logger.info("Auto-logged Vapi call: %s / %s", session.phone, intent)


def _get_or_create_session(call_id: str, caller_phone: str | None = None) -> SessionState:
    """Get existing session or create a new one for the call."""
    if call_id not in _sessions:
        session = SessionState()
        if caller_phone:
            session.caller_id_from_vapi = caller_phone
        _sessions[call_id] = session
    return _sessions[call_id]


def _extract_call_id(request_body: dict) -> str:
    """Extract call ID from Vapi request. Falls back to a generated ID."""
    # Vapi includes call metadata in the messages or headers
    # The call object may be in the request body
    call = request_body.get("call", {})
    if isinstance(call, dict) and call.get("id"):
        return call["id"]
    # Fallback: check metadata
    metadata = request_body.get("metadata", {})
    if isinstance(metadata, dict) and metadata.get("callId"):
        return metadata["callId"]
    return str(uuid.uuid4())[:8]


def _extract_caller_phone(request_body: dict) -> str | None:
    """Extract caller phone from Vapi request."""
    call = request_body.get("call", {})
    if isinstance(call, dict):
        customer = call.get("customer", {})
        if isinstance(customer, dict):
            number = customer.get("number", "")
            if number:
                # Strip country code, keep last 10 digits
                digits = "".join(c for c in number if c.isdigit())
                if len(digits) >= 10:
                    return digits[-10:]
    return None


def _extract_last_user_message(messages: list[dict]) -> str:
    """Get the last user message from the conversation."""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle content array format
                texts = [p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") == "text"]
                return " ".join(texts)
            return content or ""
    return ""


def _build_gemini_history(messages: list[dict]) -> list:
    """Convert OpenAI-format messages to Gemini chat history (excluding last user message)."""
    from google.genai import types

    history = []
    # Skip system messages and the last user message
    filtered = [m for m in messages if m.get("role") in ("user", "assistant")]
    if filtered and filtered[-1].get("role") == "user":
        filtered = filtered[:-1]  # Exclude last user message (it's sent separately)

    for msg in filtered:
        role = "user" if msg["role"] == "user" else "model"
        content = msg.get("content", "")
        if isinstance(content, list):
            content = " ".join(
                t.get("text", "") for t in content
                if isinstance(t, dict) and t.get("type") == "text"
            )
        if content:
            history.append(
                types.Content(
                    role=role,
                    parts=[types.Part.from_text(text=content)],
                )
            )
    return history


def _make_sse_chunk(content: str, finish_reason: str | None = None) -> str:
    """Create an SSE chunk in OpenAI format."""
    chunk = {
        "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
        "object": "chat.completion.chunk",
        "created": int(time.time()),
        "model": "maple-street-receptionist",
        "choices": [
            {
                "index": 0,
                "delta": {"content": content} if content else {},
                "finish_reason": finish_reason,
            }
        ],
    }
    return f"data: {json.dumps(chunk)}\n\n"


async def _stream_response(text: str) -> AsyncGenerator[str, None]:
    """Stream the response text as SSE chunks."""
    # Send the full text as a single chunk (Vapi handles TTS chunking)
    yield _make_sse_chunk(text)
    yield _make_sse_chunk("", finish_reason="stop")
    yield "data: [DONE]\n\n"


@app.post("/chat/completions", response_model=None)
async def chat_completions(request: Request) -> StreamingResponse | dict:
    """OpenAI-compatible chat completions endpoint for Vapi."""
    # Authenticate if secret is configured
    if VAPI_SECRET:
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer ") or auth_header[7:] != VAPI_SECRET:
            raise HTTPException(status_code=401, detail="Unauthorized")

    body = await request.json()
    logger.info("Received Vapi request")

    messages = body.get("messages", [])
    is_streaming = body.get("stream", False)

    call_id = _extract_call_id(body)
    caller_phone = _extract_caller_phone(body)
    session = _get_or_create_session(call_id, caller_phone)

    # If we have a caller phone from Vapi and haven't identified yet, inject it
    if caller_phone and not session.identified and not session.phone:
        session.phone = caller_phone

    # Get the last user message
    user_message = _extract_last_user_message(messages)
    if not user_message:
        user_message = "Hello"

    # Build Gemini history from the conversation
    gemini_history = _build_gemini_history(messages)

    # Process through our agent
    agent = get_agent()
    response = agent.process_message(
        message=user_message,
        history=gemini_history,
        session=session,
        is_voice=True,
    )

    # Update session
    _sessions[call_id] = response.session

    # Auto-log after booking/reschedule/cancel/escalation
    action_tools = {"book_appointment", "reschedule_appointment", "cancel_appointment", "escalate_to_staff"}
    if action_tools & set(response.tools_called):
        _log_call_if_needed(call_id, response.session)

    if is_streaming:
        return StreamingResponse(
            _stream_response(response.text),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    else:
        # Non-streaming response
        return {
            "id": f"chatcmpl-{uuid.uuid4().hex[:8]}",
            "object": "chat.completion",
            "created": int(time.time()),
            "model": "maple-street-receptionist",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": response.text},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }


@app.post("/vapi-events")
async def vapi_events(request: Request) -> dict:
    """Handle Vapi server events (end-of-call-report, etc.)."""
    body = await request.json()
    event_type = body.get("message", {}).get("type", "")
    logger.info("Vapi event: %s", event_type)

    if event_type == "end-of-call-report":
        call = body.get("message", {}).get("call", {})
        call_id = call.get("id", "")
        if call_id and call_id in _sessions:
            _log_call_if_needed(call_id, _sessions[call_id], force=True)
            # Clean up session
            del _sessions[call_id]
            logger.info("End-of-call logged and session cleaned: %s", call_id)
        elif call_id:
            # Call existed but no session (edge case) — log a minimal entry
            if _sheets_client and call_id not in _logged_calls:
                customer = call.get("customer", {})
                phone = ""
                if isinstance(customer, dict):
                    number = customer.get("number", "")
                    digits = "".join(c for c in number if c.isdigit())
                    if len(digits) >= 10:
                        phone = digits[-10:]
                _sheets_client.log_call(
                    phone=phone, caller_name="", intent="General",
                    summary="Voice call (no session data)", outcome="Completed",
                )
                _logged_calls.add(call_id)
                logger.info("End-of-call logged (no session): %s", call_id)

    return {"status": "ok"}


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


