"""Tests for voice/vapi_webhook.py — helper functions and HTTP endpoints."""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------------------------------------------------------------------------
# Pre-mock heavy / optional dependencies that the webhook module imports
# at module level.  We must do this BEFORE importing vapi_webhook so the
# import chain never hits the real packages.
# ---------------------------------------------------------------------------
from unittest.mock import MagicMock, patch, AsyncMock
from dataclasses import dataclass, field

# google.genai types — used inside _build_gemini_history
_mock_genai = MagicMock()
_mock_genai_types = MagicMock()
_mock_genai_errors = MagicMock()
# Use direct assignment (not setdefault) to ensure our mocks take
# priority even if another test module already inserted a different mock.
sys.modules["google.genai"] = _mock_genai
sys.modules["google.genai.types"] = _mock_genai_types
sys.modules["google.genai.errors"] = _mock_genai_errors


# Provide a realistic Content/Part stub so _build_gemini_history can be
# tested without the real google-genai SDK.
@dataclass
class _FakePart:
    text: str


@dataclass
class _FakeContent:
    role: str
    parts: list = field(default_factory=list)


def _fake_from_text(text: str = "") -> _FakePart:
    return _FakePart(text=text)


_mock_genai_types.Content = _FakeContent
_mock_genai_types.Part = MagicMock()
_mock_genai_types.Part.from_text = _fake_from_text

# Ensure `from google.genai import types` inside _build_gemini_history
# resolves to our fake types (MagicMock auto-creates a *different* .types attr).
_mock_genai.types = _mock_genai_types

# Mock the integration / agent imports that vapi_webhook pulls in at
# module level so we never need real credentials or network access.
sys.modules.setdefault("integrations.auth", MagicMock())
sys.modules.setdefault("integrations.google_calendar", MagicMock())
sys.modules.setdefault("integrations.google_sheets", MagicMock())

# Mock agent.core — we need AgentResponse to be a real dataclass
_mock_agent_core = MagicMock()


@dataclass
class _FakeAgentResponse:
    text: str
    session: object
    tools_called: list = field(default_factory=list)


_mock_agent_core.AgentResponse = _FakeAgentResponse
_mock_agent_core.create_agent = MagicMock()
sys.modules.setdefault("agent.core", _mock_agent_core)

# agent.state — we want the real SessionState
# (already importable because sys.path was adjusted above)
import agent.state  # noqa: E402

sys.modules.setdefault("agent.state", agent.state)

# config.settings — mock just the VAPI_SECRET so auth tests are predictable
_mock_settings = MagicMock()
_mock_settings.VAPI_SECRET = ""
sys.modules["config.settings"] = _mock_settings

# ---------------------------------------------------------------------------
# NOW import the webhook module under test
# ---------------------------------------------------------------------------
import voice.vapi_webhook as webhook  # noqa: E402
from voice.vapi_webhook import (  # noqa: E402
    _extract_call_id,
    _extract_caller_phone,
    _extract_last_user_message,
    _build_gemini_history,
    _make_sse_chunk,
    _log_call_if_needed,
    app,
)
from agent.state import SessionState  # noqa: E402

import json  # noqa: E402
import pytest  # noqa: E402
import httpx  # noqa: E402


# ===================================================================
# 1. Helper function tests (no HTTP required)
# ===================================================================


class TestExtractCallId:
    def test_extracts_from_call_id(self):
        body = {"call": {"id": "call-abc123"}}
        assert _extract_call_id(body) == "call-abc123"

    def test_extracts_from_metadata_callId(self):
        body = {"metadata": {"callId": "meta-xyz"}}
        assert _extract_call_id(body) == "meta-xyz"

    def test_prefers_call_id_over_metadata(self):
        body = {"call": {"id": "call-1"}, "metadata": {"callId": "meta-2"}}
        assert _extract_call_id(body) == "call-1"

    def test_generates_fallback_when_missing(self):
        result = _extract_call_id({})
        assert isinstance(result, str)
        assert len(result) == 8  # uuid4()[:8]

    def test_generates_fallback_for_empty_call_object(self):
        body = {"call": {}}
        result = _extract_call_id(body)
        assert len(result) == 8

    def test_handles_non_dict_call(self):
        body = {"call": "not-a-dict"}
        result = _extract_call_id(body)
        assert len(result) == 8

    def test_handles_non_dict_metadata(self):
        body = {"metadata": "not-a-dict"}
        result = _extract_call_id(body)
        assert len(result) == 8


class TestExtractCallerPhone:
    def test_extracts_and_normalises_us_number(self):
        body = {"call": {"customer": {"number": "+14155551234"}}}
        assert _extract_caller_phone(body) == "4155551234"

    def test_extracts_ten_digit_number(self):
        body = {"call": {"customer": {"number": "4155551234"}}}
        assert _extract_caller_phone(body) == "4155551234"

    def test_strips_country_code_from_long_number(self):
        body = {"call": {"customer": {"number": "+919876543210"}}}
        assert _extract_caller_phone(body) == "9876543210"

    def test_returns_none_for_missing_customer(self):
        body = {"call": {}}
        assert _extract_caller_phone(body) is None

    def test_returns_none_for_empty_number(self):
        body = {"call": {"customer": {"number": ""}}}
        assert _extract_caller_phone(body) is None

    def test_returns_none_for_short_number(self):
        body = {"call": {"customer": {"number": "12345"}}}
        assert _extract_caller_phone(body) is None

    def test_returns_none_for_empty_body(self):
        assert _extract_caller_phone({}) is None

    def test_handles_non_dict_customer(self):
        body = {"call": {"customer": "not-a-dict"}}
        assert _extract_caller_phone(body) is None


class TestExtractLastUserMessage:
    def test_gets_last_user_text(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "Book me an appointment"},
        ]
        assert _extract_last_user_message(messages) == "Book me an appointment"

    def test_skips_assistant_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Last msg is assistant"},
        ]
        assert _extract_last_user_message(messages) == "Hello"

    def test_handles_content_array_format(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "I want"},
                    {"type": "text", "text": "a bath"},
                ],
            }
        ]
        assert _extract_last_user_message(messages) == "I want a bath"

    def test_returns_empty_for_no_messages(self):
        assert _extract_last_user_message([]) == ""

    def test_returns_empty_for_only_assistant_messages(self):
        messages = [{"role": "assistant", "content": "Hello"}]
        assert _extract_last_user_message(messages) == ""

    def test_handles_empty_content(self):
        messages = [{"role": "user", "content": ""}]
        assert _extract_last_user_message(messages) == ""

    def test_handles_missing_content_key(self):
        messages = [{"role": "user"}]
        assert _extract_last_user_message(messages) == ""


class TestBuildGeminiHistory:
    def test_skips_system_messages(self):
        messages = [
            {"role": "system", "content": "You are a receptionist"},
            {"role": "user", "content": "Hello"},
        ]
        # Last user message is excluded, system skipped => empty history
        result = _build_gemini_history(messages)
        assert result == []

    def test_excludes_last_user_message(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
            {"role": "user", "content": "Book me"},
        ]
        result = _build_gemini_history(messages)
        # "Hello" -> user, "Hi there" -> model; last user "Book me" excluded
        assert len(result) == 2
        assert result[0].role == "user"
        assert result[0].parts[0].text == "Hello"
        assert result[1].role == "model"
        assert result[1].parts[0].text == "Hi there"

    def test_converts_roles_correctly(self):
        messages = [
            {"role": "user", "content": "A"},
            {"role": "assistant", "content": "B"},
            {"role": "user", "content": "C"},
            {"role": "assistant", "content": "D"},
            {"role": "user", "content": "last"},
        ]
        result = _build_gemini_history(messages)
        assert len(result) == 4
        assert [c.role for c in result] == ["user", "model", "user", "model"]

    def test_handles_content_array(self):
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "part1"},
                    {"type": "text", "text": "part2"},
                ],
            },
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "last"},
        ]
        result = _build_gemini_history(messages)
        assert len(result) == 2
        assert result[0].parts[0].text == "part1 part2"

    def test_empty_messages(self):
        assert _build_gemini_history([]) == []

    def test_only_system_message(self):
        messages = [{"role": "system", "content": "sys"}]
        assert _build_gemini_history(messages) == []

    def test_skips_empty_content(self):
        messages = [
            {"role": "user", "content": ""},
            {"role": "assistant", "content": "Hi"},
            {"role": "user", "content": "last"},
        ]
        result = _build_gemini_history(messages)
        # first user has empty content so it is skipped
        assert len(result) == 1
        assert result[0].role == "model"


class TestMakeSseChunk:
    def test_returns_sse_format_with_content(self):
        chunk = _make_sse_chunk("Hello")
        assert chunk.startswith("data: ")
        assert chunk.endswith("\n\n")
        data = json.loads(chunk[len("data: "):])
        assert data["object"] == "chat.completion.chunk"
        assert data["model"] == "maple-street-receptionist"
        assert data["choices"][0]["delta"]["content"] == "Hello"
        assert data["choices"][0]["finish_reason"] is None

    def test_returns_sse_format_with_finish_reason(self):
        chunk = _make_sse_chunk("", finish_reason="stop")
        data = json.loads(chunk[len("data: "):])
        assert data["choices"][0]["delta"] == {}
        assert data["choices"][0]["finish_reason"] == "stop"

    def test_chunk_has_unique_ids(self):
        c1 = _make_sse_chunk("a")
        c2 = _make_sse_chunk("b")
        d1 = json.loads(c1[len("data: "):])
        d2 = json.loads(c2[len("data: "):])
        assert d1["id"] != d2["id"]


class TestLogCallIfNeeded:
    def setup_method(self):
        """Reset global state before each test."""
        webhook._logged_calls.clear()
        webhook._sessions.clear()

    def test_skips_already_logged(self):
        webhook._logged_calls.add("call-1")
        mock_sheets = MagicMock()
        webhook._sheets_client = mock_sheets

        session = SessionState()
        session.intents_completed = ["book"]
        _log_call_if_needed("call-1", session)

        mock_sheets.log_call.assert_not_called()

    def test_skips_no_interaction_force_false(self):
        mock_sheets = MagicMock()
        webhook._sheets_client = mock_sheets

        session = SessionState()
        # No intents_completed, no call_summary_parts, force=False
        _log_call_if_needed("call-2", session)

        mock_sheets.log_call.assert_not_called()

    def test_logs_with_force_true_no_intents(self):
        mock_sheets = MagicMock()
        webhook._sheets_client = mock_sheets

        session = SessionState()
        _log_call_if_needed("call-3", session, force=True)

        mock_sheets.log_call.assert_called_once()
        call_kwargs = mock_sheets.log_call.call_args
        assert call_kwargs[1]["intent"] == "General"
        # get_call_summary() returns "No actions taken" (truthy), so the
        # `or "Voice call (no action taken)"` fallback is not reached.
        assert call_kwargs[1]["summary"] == "No actions taken"
        assert "call-3" in webhook._logged_calls

    def test_uses_current_intent_for_abandoned(self):
        mock_sheets = MagicMock()
        webhook._sheets_client = mock_sheets

        session = SessionState()
        session.current_intent = "reschedule"
        _log_call_if_needed("call-4", session, force=True)

        call_kwargs = mock_sheets.log_call.call_args
        assert call_kwargs[1]["intent"] == "reschedule (abandoned)"

    def test_logs_with_completed_intents(self):
        mock_sheets = MagicMock()
        webhook._sheets_client = mock_sheets

        session = SessionState()
        session.intents_completed = ["book", "cancel"]
        session.call_summary_parts = ["Booked Full Groom", "Cancelled Bath"]
        _log_call_if_needed("call-5", session)

        mock_sheets.log_call.assert_called_once()
        call_kwargs = mock_sheets.log_call.call_args
        assert call_kwargs[1]["intent"] == "book, cancel"
        assert "Booked Full Groom" in call_kwargs[1]["summary"]
        assert "Cancelled Bath" in call_kwargs[1]["summary"]
        assert "call-5" in webhook._logged_calls

    def test_logs_with_phone_and_name(self):
        mock_sheets = MagicMock()
        webhook._sheets_client = mock_sheets

        session = SessionState()
        session.phone = "4155551234"
        session.name = "Priya"
        session.intents_completed = ["book"]
        session.call_summary_parts = ["Booked Bath"]
        _log_call_if_needed("call-6", session)

        call_kwargs = mock_sheets.log_call.call_args
        assert call_kwargs[1]["phone"] == "4155551234"
        assert call_kwargs[1]["caller_name"] == "Priya"

    def test_does_not_log_without_sheets_client(self):
        webhook._sheets_client = None

        session = SessionState()
        session.intents_completed = ["book"]
        _log_call_if_needed("call-7", session)

        assert "call-7" not in webhook._logged_calls


# ===================================================================
# 2. Endpoint tests (httpx.AsyncClient + FastAPI)
# ===================================================================


@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_returns_ok(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
class TestChatCompletionsEndpoint:
    async def test_non_streaming_returns_200(self):
        """POST /chat/completions with mocked agent returns 200 + assistant reply."""
        mock_agent = MagicMock()
        mock_response = _FakeAgentResponse(
            text="Welcome to Maple Street Dog Grooming!",
            session=SessionState(),
            tools_called=[],
        )
        mock_agent.process_message.return_value = mock_response

        # Patch module globals
        original_agent = webhook._agent
        original_sheets = webhook._sheets_client
        original_sessions = webhook._sessions
        original_logged = webhook._logged_calls.copy()
        original_secret = webhook.VAPI_SECRET

        try:
            webhook._agent = mock_agent
            webhook._sheets_client = MagicMock()
            webhook._sessions = {}
            webhook._logged_calls = set()
            webhook.VAPI_SECRET = ""

            body = {
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": False,
                "call": {"id": "test-call-1"},
            }

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/chat/completions", json=body)

            assert resp.status_code == 200
            data = resp.json()
            assert data["choices"][0]["message"]["content"] == "Welcome to Maple Street Dog Grooming!"
            assert data["choices"][0]["finish_reason"] == "stop"
            mock_agent.process_message.assert_called_once()

        finally:
            webhook._agent = original_agent
            webhook._sheets_client = original_sheets
            webhook._sessions = original_sessions
            webhook._logged_calls = original_logged
            webhook.VAPI_SECRET = original_secret

    async def test_streaming_returns_sse(self):
        """POST /chat/completions with stream=True returns SSE."""
        mock_agent = MagicMock()
        mock_response = _FakeAgentResponse(
            text="Hi there!",
            session=SessionState(),
            tools_called=[],
        )
        mock_agent.process_message.return_value = mock_response

        original_agent = webhook._agent
        original_sheets = webhook._sheets_client
        original_sessions = webhook._sessions
        original_logged = webhook._logged_calls.copy()
        original_secret = webhook.VAPI_SECRET

        try:
            webhook._agent = mock_agent
            webhook._sheets_client = MagicMock()
            webhook._sessions = {}
            webhook._logged_calls = set()
            webhook.VAPI_SECRET = ""

            body = {
                "messages": [{"role": "user", "content": "Hello"}],
                "stream": True,
                "call": {"id": "test-call-2"},
            }

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/chat/completions", json=body)

            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            text = resp.text
            assert "data: " in text
            assert "Hi there!" in text
            assert "data: [DONE]" in text

        finally:
            webhook._agent = original_agent
            webhook._sheets_client = original_sheets
            webhook._sessions = original_sessions
            webhook._logged_calls = original_logged
            webhook.VAPI_SECRET = original_secret


@pytest.mark.asyncio
class TestVapiEventsEndpoint:
    async def test_end_of_call_report_logs_and_cleans(self):
        """end-of-call-report with existing session triggers logging + cleanup."""
        mock_sheets = MagicMock()
        session = SessionState()
        session.phone = "4155551234"
        session.intents_completed = ["book"]
        session.call_summary_parts = ["Booked Full Groom"]

        original_agent = webhook._agent
        original_sheets = webhook._sheets_client
        original_sessions = webhook._sessions
        original_logged = webhook._logged_calls.copy()

        try:
            webhook._agent = MagicMock()
            webhook._sheets_client = mock_sheets
            webhook._sessions = {"vapi-call-99": session}
            webhook._logged_calls = set()

            body = {
                "message": {
                    "type": "end-of-call-report",
                    "call": {"id": "vapi-call-99"},
                }
            }

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/vapi-events", json=body)

            assert resp.status_code == 200
            assert resp.json() == {"status": "ok"}
            mock_sheets.log_call.assert_called_once()
            # Session should be cleaned up
            assert "vapi-call-99" not in webhook._sessions
            assert "vapi-call-99" in webhook._logged_calls

        finally:
            webhook._agent = original_agent
            webhook._sheets_client = original_sheets
            webhook._sessions = original_sessions
            webhook._logged_calls = original_logged

    async def test_end_of_call_no_session_logs_minimal(self):
        """end-of-call-report without session logs a minimal entry."""
        mock_sheets = MagicMock()

        original_sheets = webhook._sheets_client
        original_sessions = webhook._sessions
        original_logged = webhook._logged_calls.copy()

        try:
            webhook._sheets_client = mock_sheets
            webhook._sessions = {}
            webhook._logged_calls = set()

            body = {
                "message": {
                    "type": "end-of-call-report",
                    "call": {
                        "id": "no-session-call",
                        "customer": {"number": "+14155559999"},
                    },
                }
            }

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post("/vapi-events", json=body)

            assert resp.status_code == 200
            mock_sheets.log_call.assert_called_once()
            call_kwargs = mock_sheets.log_call.call_args
            assert call_kwargs[1]["phone"] == "4155559999"
            assert call_kwargs[1]["intent"] == "General"
            assert "no-session-call" in webhook._logged_calls

        finally:
            webhook._sheets_client = original_sheets
            webhook._sessions = original_sessions
            webhook._logged_calls = original_logged

    async def test_unknown_event_returns_ok(self):
        """Unknown event type returns 200 with no error."""
        body = {"message": {"type": "speech-update"}}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/vapi-events", json=body)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    async def test_empty_event_returns_ok(self):
        """Empty/missing message type returns 200."""
        body = {"message": {}}

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post("/vapi-events", json=body)

        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
