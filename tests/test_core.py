"""Tests for agent core: AgentResponse, _resolve_event_id, and _update_session."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch

# Pre-inject mock google.genai modules into sys.modules so that
# ``import google.genai`` inside agent/core.py resolves to our mocks
# instead of hitting the real (possibly absent) package.
# We must NOT replace the top-level ``google`` namespace package because
# other real packages (googleapiclient, google.oauth2) depend on it.
_mock_genai = MagicMock()
_mock_types = MagicMock()
_mock_errors = MagicMock()

sys.modules.setdefault("google.genai", _mock_genai)
sys.modules.setdefault("google.genai.types", _mock_types)
sys.modules.setdefault("google.genai.errors", _mock_errors)

from agent.core import AgentResponse, ReceptionistAgent  # noqa: E402
from agent.state import SessionState  # noqa: E402

import pytest  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_agent() -> ReceptionistAgent:
    """Create a ReceptionistAgent with fully mocked external dependencies."""
    mock_calendar = MagicMock()
    mock_sheets = MagicMock()
    with patch.object(ReceptionistAgent, "__init__", lambda self, *a, **kw: None):
        agent = ReceptionistAgent.__new__(ReceptionistAgent)
    # Manually set the pieces that _update_session / _resolve_event_id need.
    # (They don't touch self.client, self.model_name, etc.)
    agent.tool_executor = MagicMock()
    return agent


def _fresh_session(**overrides) -> SessionState:
    """Return a fresh SessionState with optional field overrides."""
    return SessionState(**overrides)


# ---------------------------------------------------------------------------
# AgentResponse dataclass
# ---------------------------------------------------------------------------

class TestAgentResponse:
    def test_creation_with_required_fields(self):
        session = _fresh_session()
        resp = AgentResponse(text="Hello!", session=session, tools_called=["lookup_contact"])
        assert resp.text == "Hello!"
        assert resp.session is session
        assert resp.tools_called == ["lookup_contact"]

    def test_empty_tools_called(self):
        session = _fresh_session()
        resp = AgentResponse(text="Hi", session=session, tools_called=[])
        assert resp.tools_called == []

    def test_multiple_tools_called(self):
        session = _fresh_session()
        tools = ["lookup_contact", "check_availability", "book_appointment"]
        resp = AgentResponse(text="Done", session=session, tools_called=tools)
        assert len(resp.tools_called) == 3
        assert resp.tools_called == tools

    def test_fields_are_accessible(self):
        session = _fresh_session(phone="9876543210")
        resp = AgentResponse(text="ok", session=session, tools_called=[])
        assert resp.session.phone == "9876543210"

    def test_text_can_be_empty(self):
        resp = AgentResponse(text="", session=_fresh_session(), tools_called=[])
        assert resp.text == ""


# ---------------------------------------------------------------------------
# _resolve_event_id  (static method — no instance state needed)
# ---------------------------------------------------------------------------

class TestResolveEventId:
    """Tests for the 4 resolution strategies."""

    APPOINTMENTS = [
        {"event_id": "real_abc123", "groomer_name": "Sarah", "date": "2025-03-01"},
        {"event_id": "real_def456", "groomer_name": "Mike", "date": "2025-03-02"},
        {"event_id": "real_ghi789", "groomer_name": "Jessica", "date": "2025-03-03"},
    ]

    # --- Strategy 1: real event_id matches ---

    def test_real_id_returned_as_is(self):
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "real_abc123", "Sarah", self.APPOINTMENTS
        )
        assert eid == "real_abc123"
        assert groomer == "Sarah"

    def test_real_id_corrects_groomer(self):
        """If the LLM gives a real event_id but the wrong groomer, we fix the groomer."""
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "real_abc123", "WrongName", self.APPOINTMENTS
        )
        assert eid == "real_abc123"
        assert groomer == "Sarah"

    def test_real_id_second_appointment(self):
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "real_def456", "Mike", self.APPOINTMENTS
        )
        assert eid == "real_def456"
        assert groomer == "Mike"

    # --- Strategy 2: fake ID + single groomer match ---

    def test_fake_id_resolved_by_groomer_name(self):
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "fake_id_999", "sarah", self.APPOINTMENTS  # lowercase
        )
        assert eid == "real_abc123"
        assert groomer == "Sarah"

    def test_fake_id_resolved_by_groomer_case_insensitive(self):
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "bogus", "MIKE", self.APPOINTMENTS
        )
        assert eid == "real_def456"
        assert groomer == "Mike"

    def test_fake_id_resolved_by_groomer_jessica(self):
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "hallucinated_id", "Jessica", self.APPOINTMENTS
        )
        assert eid == "real_ghi789"
        assert groomer == "Jessica"

    # --- Strategy 3: fake ID + single appointment total ---

    def test_fake_id_single_appointment_resolved(self):
        single = [{"event_id": "only_one", "groomer_name": "Carlos"}]
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "made_up", "UnknownGroomer", single
        )
        assert eid == "only_one"
        assert groomer == "Carlos"

    def test_fake_id_single_appointment_groomer_mismatch(self):
        """Even when groomer doesn't match, single-appointment fallback works."""
        single = [{"event_id": "evt_solo", "groomer_name": "Sarah"}]
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "fake_xyz", "Mike", single
        )
        assert eid == "evt_solo"
        assert groomer == "Sarah"

    # --- Strategy 4: multiple ambiguous matches — falls back to LLM value ---

    def test_fake_id_multiple_groomer_matches_falls_back(self):
        """Two appointments with the same groomer → ambiguous, return LLM values."""
        dupes = [
            {"event_id": "evt1", "groomer_name": "Sarah"},
            {"event_id": "evt2", "groomer_name": "Sarah"},
            {"event_id": "evt3", "groomer_name": "Mike"},
        ]
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "fake_id", "Sarah", dupes
        )
        # Two Sarah matches → can't pick, fall back to LLM values
        assert eid == "fake_id"
        assert groomer == "Sarah"

    def test_fake_id_no_groomer_match_multiple_appointments(self):
        """Groomer name matches nobody and there are multiple appointments → fallback."""
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "fake_id", "NoSuchGroomer", self.APPOINTMENTS
        )
        # No groomer match, 3 appointments → fallback
        assert eid == "fake_id"
        assert groomer == "NoSuchGroomer"

    def test_fake_id_empty_groomer_multiple_appointments(self):
        """Empty groomer string with multiple appointments → fallback."""
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "fake_id", "", self.APPOINTMENTS
        )
        assert eid == "fake_id"
        assert groomer == ""

    # --- Edge cases ---

    def test_empty_appointments_list_fallback(self):
        """No cached appointments at all — strategy 3 check (len==1) fails, fallback."""
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "any_id", "Sarah", []
        )
        assert eid == "any_id"
        assert groomer == "Sarah"

    def test_real_id_with_empty_groomer(self):
        """Real event_id but empty groomer string — should still match and fix groomer."""
        eid, groomer = ReceptionistAgent._resolve_event_id(
            "real_abc123", "", self.APPOINTMENTS
        )
        assert eid == "real_abc123"
        assert groomer == "Sarah"


# ---------------------------------------------------------------------------
# _update_session
# ---------------------------------------------------------------------------

class TestUpdateSessionLookupContact:
    def test_sets_phone_on_lookup(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": False}
        agent._update_session(session, "lookup_contact", {"phone": "9876543210"}, result)
        assert session.phone == "9876543210"

    def test_not_found_leaves_identified_false(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": False}
        agent._update_session(session, "lookup_contact", {"phone": "9876543210"}, result)
        assert session.identified is False
        assert session.contact_records == []

    def test_found_sets_identified_and_name(self):
        agent = _make_agent()
        session = _fresh_session()
        contacts = [
            {"Name": "Priya", "Dog Name": "Buddy", "Dog Breed": "Labrador", "Dog Size": "Large"}
        ]
        result = {"found": True, "contacts": contacts}
        agent._update_session(session, "lookup_contact", {"phone": "9876543210"}, result)
        assert session.identified is True
        assert session.name == "Priya"
        assert session.contact_records == contacts

    def test_single_contact_sets_dog_info(self):
        agent = _make_agent()
        session = _fresh_session()
        contacts = [
            {"Name": "Raj", "Dog Name": "Max", "Dog Breed": "Poodle", "Dog Size": "Medium"}
        ]
        result = {"found": True, "contacts": contacts}
        agent._update_session(session, "lookup_contact", {"phone": "1111111111"}, result)
        assert session.dog_name == "Max"
        assert session.dog_breed == "Poodle"
        assert session.dog_size == "Medium"

    def test_multiple_contacts_does_not_set_dog_info(self):
        agent = _make_agent()
        session = _fresh_session()
        contacts = [
            {"Name": "Raj", "Dog Name": "Max", "Dog Breed": "Poodle", "Dog Size": "Medium"},
            {"Name": "Raj", "Dog Name": "Luna", "Dog Breed": "Husky", "Dog Size": "Large"},
        ]
        result = {"found": True, "contacts": contacts}
        agent._update_session(session, "lookup_contact", {"phone": "1111111111"}, result)
        assert session.name == "Raj"
        assert session.dog_name is None  # not set because multiple contacts
        assert session.dog_breed is None

    def test_found_but_empty_contacts_list(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": True, "contacts": []}
        agent._update_session(session, "lookup_contact", {"phone": "5555555555"}, result)
        assert session.identified is True
        assert session.name is None  # empty list, no name to extract


class TestUpdateSessionRegisterContact:
    def test_sets_all_fields(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {
            "phone": "9876543210",
            "name": "Anita",
            "dog_name": "Rocky",
            "dog_breed": "Beagle",
            "dog_size": "Small",
        }
        agent._update_session(session, "register_contact", args, {"success": True})
        assert session.phone == "9876543210"
        assert session.name == "Anita"
        assert session.dog_name == "Rocky"
        assert session.dog_breed == "Beagle"
        assert session.dog_size == "Small"
        assert session.identified is True

    def test_preserves_existing_values_when_args_missing(self):
        agent = _make_agent()
        session = _fresh_session(phone="1234567890", name="OldName")
        args = {"dog_name": "Spot", "dog_breed": "Dalmatian", "dog_size": "Large"}
        agent._update_session(session, "register_contact", args, {"success": True})
        assert session.phone == "1234567890"  # preserved
        assert session.name == "OldName"  # preserved
        assert session.dog_name == "Spot"
        assert session.identified is True

    def test_overwrites_existing_values_when_args_provided(self):
        agent = _make_agent()
        session = _fresh_session(phone="0000000000", name="Old")
        args = {"phone": "9999999999", "name": "New", "dog_name": "Rex",
                "dog_breed": "GSD", "dog_size": "Large"}
        agent._update_session(session, "register_contact", args, {})
        assert session.phone == "9999999999"
        assert session.name == "New"


class TestUpdateSessionBookAppointment:
    def test_success_appends_summary_and_event_id(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {
            "service_name": "Full Groom",
            "dog_name": "Buddy",
            "date": "2025-04-01",
            "time": "10:00",
            "groomer_name": "Sarah",
        }
        result = {"success": True, "event_id": "evt_123", "price": 1500}
        agent._update_session(session, "book_appointment", args, result)

        assert "evt_123" in session.booked_event_ids
        assert len(session.call_summary_parts) == 1
        assert "Full Groom" in session.call_summary_parts[0]
        assert "Buddy" in session.call_summary_parts[0]
        assert "2025-04-01" in session.call_summary_parts[0]
        assert "10:00" in session.call_summary_parts[0]
        assert "Sarah" in session.call_summary_parts[0]
        assert "1500" in session.call_summary_parts[0]
        assert session.current_intent == "book"
        assert "book" in session.intents_completed

    def test_success_without_event_id(self):
        """event_id missing from result dict — no event_id appended but summary still recorded."""
        agent = _make_agent()
        session = _fresh_session()
        args = {"service_name": "Bath & Brush", "dog_name": "Coco",
                "date": "2025-05-01", "time": "14:00", "groomer_name": "Mike"}
        result = {"success": True, "price": 800}
        agent._update_session(session, "book_appointment", args, result)
        assert session.booked_event_ids == []
        assert len(session.call_summary_parts) == 1

    def test_success_with_empty_event_id(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"service_name": "Nail Trim", "dog_name": "Tiny",
                "date": "2025-06-01", "time": "09:00", "groomer_name": "Jessica"}
        result = {"success": True, "event_id": "", "price": 300}
        agent._update_session(session, "book_appointment", args, result)
        # Empty event_id is falsy, not appended
        assert session.booked_event_ids == []

    def test_failure_does_nothing(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"service_name": "Full Groom", "dog_name": "Buddy",
                "date": "2025-04-01", "time": "10:00", "groomer_name": "Sarah"}
        result = {"success": False, "error": "Slot taken"}
        agent._update_session(session, "book_appointment", args, result)
        assert session.booked_event_ids == []
        assert session.call_summary_parts == []
        assert session.intents_completed == []

    def test_price_unknown(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"service_name": "Full Groom", "dog_name": "Buddy",
                "date": "2025-04-01", "time": "10:00", "groomer_name": "Sarah"}
        result = {"success": True, "event_id": "evt_x"}
        agent._update_session(session, "book_appointment", args, result)
        assert "?" in session.call_summary_parts[0]

    def test_multiple_bookings_accumulate(self):
        agent = _make_agent()
        session = _fresh_session()
        for i in range(3):
            args = {"service_name": f"Service{i}", "dog_name": f"Dog{i}",
                    "date": f"2025-04-0{i+1}", "time": "10:00", "groomer_name": "Sarah"}
            result = {"success": True, "event_id": f"evt_{i}", "price": 100 * (i + 1)}
            agent._update_session(session, "book_appointment", args, result)
        assert len(session.booked_event_ids) == 3
        assert len(session.call_summary_parts) == 3
        assert session.intents_completed.count("book") == 3


class TestUpdateSessionRescheduleAppointment:
    def test_success_appends_summary(self):
        agent = _make_agent()
        session = _fresh_session(phone="1234567890", name="Priya")
        args = {
            "new_date": "2025-05-10",
            "new_time": "14:00",
            "new_groomer_name": "Mike",
            "phone": "1234567890",
            "customer_name": "Priya",
        }
        result = {"success": True}
        agent._update_session(session, "reschedule_appointment", args, result)
        assert len(session.call_summary_parts) == 1
        assert "2025-05-10" in session.call_summary_parts[0]
        assert "14:00" in session.call_summary_parts[0]
        assert "Mike" in session.call_summary_parts[0]
        assert "reschedule" in session.intents_completed

    def test_captures_phone_when_session_empty(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"phone": "5555555555", "customer_name": "Raj",
                "new_date": "2025-06-01", "new_time": "09:00", "new_groomer_name": "Sarah"}
        result = {"success": True}
        agent._update_session(session, "reschedule_appointment", args, result)
        assert session.phone == "5555555555"
        assert session.name == "Raj"

    def test_does_not_overwrite_existing_phone(self):
        agent = _make_agent()
        session = _fresh_session(phone="1111111111", name="Existing")
        args = {"phone": "2222222222", "customer_name": "NewPerson",
                "new_date": "2025-06-01", "new_time": "09:00", "new_groomer_name": "Sarah"}
        result = {"success": True}
        agent._update_session(session, "reschedule_appointment", args, result)
        assert session.phone == "1111111111"  # not overwritten
        assert session.name == "Existing"  # not overwritten

    def test_failure_does_not_append_summary(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"phone": "5555555555", "customer_name": "Raj",
                "new_date": "2025-06-01", "new_time": "09:00", "new_groomer_name": "Sarah"}
        result = {"success": False, "error": "slot taken"}
        agent._update_session(session, "reschedule_appointment", args, result)
        assert session.call_summary_parts == []
        assert "reschedule" not in session.intents_completed
        # But phone/name should still be captured
        assert session.phone == "5555555555"

    def test_no_phone_in_args(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"new_date": "2025-06-01", "new_time": "09:00", "new_groomer_name": "Sarah"}
        result = {"success": True}
        agent._update_session(session, "reschedule_appointment", args, result)
        assert session.phone is None  # no phone to capture


class TestUpdateSessionCancelAppointment:
    def test_success_appends_summary(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"success": True}
        agent._update_session(session, "cancel_appointment", {}, result)
        assert session.call_summary_parts == ["Cancelled appointment"]
        assert "cancel" in session.intents_completed

    def test_failure_does_nothing(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"success": False, "error": "not found"}
        agent._update_session(session, "cancel_appointment", {}, result)
        assert session.call_summary_parts == []
        assert session.intents_completed == []


class TestUpdateSessionEscalateToStaff:
    def test_appends_escalation_summary(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"reason": "Complaint about grooming quality", "phone": "8888888888",
                "caller_name": "Vikram"}
        result = {"success": True}
        agent._update_session(session, "escalate_to_staff", args, result)
        assert "Escalated: Complaint about grooming quality" in session.call_summary_parts
        assert "escalation" in session.intents_completed

    def test_captures_phone_and_name_when_empty(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"reason": "Refund", "phone": "7777777777", "caller_name": "Sita"}
        agent._update_session(session, "escalate_to_staff", args, {})
        assert session.phone == "7777777777"
        assert session.name == "Sita"

    def test_does_not_overwrite_existing_phone_and_name(self):
        agent = _make_agent()
        session = _fresh_session(phone="1111111111", name="Existing")
        args = {"reason": "Refund", "phone": "7777777777", "caller_name": "Sita"}
        agent._update_session(session, "escalate_to_staff", args, {})
        assert session.phone == "1111111111"
        assert session.name == "Existing"

    def test_default_reason(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {}  # no reason key
        agent._update_session(session, "escalate_to_staff", args, {})
        assert "Escalated: Unknown" in session.call_summary_parts[0]

    def test_no_phone_or_name_in_args(self):
        agent = _make_agent()
        session = _fresh_session()
        args = {"reason": "Emergency"}
        agent._update_session(session, "escalate_to_staff", args, {})
        assert session.phone is None
        assert session.name is None
        assert "Escalated: Emergency" in session.call_summary_parts


class TestUpdateSessionCheckAvailability:
    def test_sets_current_intent_to_book(self):
        agent = _make_agent()
        session = _fresh_session()
        agent._update_session(session, "check_availability", {}, {})
        assert session.current_intent == "book"

    def test_does_not_overwrite_existing_intent(self):
        agent = _make_agent()
        session = _fresh_session(current_intent="reschedule")
        agent._update_session(session, "check_availability", {}, {})
        assert session.current_intent == "reschedule"


class TestUpdateSessionGetUpcomingAppointments:
    def test_caches_appointments(self):
        agent = _make_agent()
        session = _fresh_session()
        appts = [
            {"event_id": "e1", "groomer_name": "Sarah", "description": "Customer: Priya\nDog: Buddy"},
            {"event_id": "e2", "groomer_name": "Mike", "description": "Customer: Raj\nDog: Max"},
        ]
        result = {"found": True, "appointments": appts}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.fetched_appointments == appts

    def test_sets_phone_from_args(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": False}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "5555555555"}, result)
        assert session.phone == "5555555555"

    def test_does_not_overwrite_existing_phone(self):
        agent = _make_agent()
        session = _fresh_session(phone="1111111111")
        result = {"found": False}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "2222222222"}, result)
        assert session.phone == "1111111111"

    def test_extracts_name_from_description(self):
        agent = _make_agent()
        session = _fresh_session()
        appts = [
            {"event_id": "e1", "groomer_name": "Sarah",
             "description": "Customer: Priya Sharma\nPhone: 1234567890\nDog: Buddy"},
        ]
        result = {"found": True, "appointments": appts}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.name == "Priya Sharma"

    def test_does_not_overwrite_existing_name(self):
        agent = _make_agent()
        session = _fresh_session(name="AlreadyKnown")
        appts = [
            {"event_id": "e1", "groomer_name": "Sarah",
             "description": "Customer: SomebodyElse\nDog: Rex"},
        ]
        result = {"found": True, "appointments": appts}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.name == "AlreadyKnown"

    def test_no_customer_line_in_description(self):
        agent = _make_agent()
        session = _fresh_session()
        appts = [
            {"event_id": "e1", "groomer_name": "Sarah",
             "description": "Phone: 123\nDog: Buddy"},
        ]
        result = {"found": True, "appointments": appts}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.name is None  # no "Customer: " line found

    def test_empty_appointments_not_found(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": False}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.fetched_appointments == []
        assert session.name is None

    def test_found_but_empty_appointments_list(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": True, "appointments": []}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.fetched_appointments == []
        assert session.name is None  # no appointments to extract from

    def test_description_without_newline(self):
        """Description has Customer on a single line (no newlines)."""
        agent = _make_agent()
        session = _fresh_session()
        appts = [
            {"event_id": "e1", "groomer_name": "Sarah",
             "description": "Customer: Solo"},
        ]
        result = {"found": True, "appointments": appts}
        agent._update_session(session, "get_upcoming_appointments", {"phone": "1234567890"}, result)
        assert session.name == "Solo"

    def test_no_phone_in_args(self):
        agent = _make_agent()
        session = _fresh_session()
        result = {"found": False}
        agent._update_session(session, "get_upcoming_appointments", {}, result)
        assert session.phone is None


# ---------------------------------------------------------------------------
# _update_session with unknown tool (no-op, no crash)
# ---------------------------------------------------------------------------

class TestUpdateSessionUnknownTool:
    def test_unknown_tool_does_not_crash(self):
        agent = _make_agent()
        session = _fresh_session()
        # Should silently do nothing
        agent._update_session(session, "nonexistent_tool", {"foo": "bar"}, {"ok": True})
        assert session.phone is None
        assert session.identified is False
        assert session.call_summary_parts == []
        assert session.intents_completed == []
