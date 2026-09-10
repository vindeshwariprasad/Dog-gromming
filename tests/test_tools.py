"""Comprehensive unit tests for agent/tools.py ToolExecutor."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, date, timedelta
from unittest.mock import MagicMock, patch, call
from zoneinfo import ZoneInfo

from agent.tools import ToolExecutor, IST


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

FROZEN_NOW = datetime(2026, 9, 10, 12, 0, 0, tzinfo=IST)   # Thursday
FROZEN_TODAY = FROZEN_NOW.date()                              # 2026-09-10
FUTURE_DATE = "2026-09-15"                                    # Tuesday
FAR_FUTURE = "2027-03-01"                                     # >4 weeks ahead
PAST_DATE = "2026-09-01"                                      # already gone


def _make_executor():
    """Return a ToolExecutor with mocked calendar & sheets clients."""
    cal = MagicMock(name="CalendarClient")
    sheets = MagicMock(name="SheetsClient")
    return ToolExecutor(cal, sheets), cal, sheets


def _dt_now_frozen(*_args, **_kwargs):
    """Replacement for datetime.now() that always returns FROZEN_NOW."""
    return FROZEN_NOW


# ---------------------------------------------------------------------------
# 1. ToolExecutor.execute() dispatch
# ---------------------------------------------------------------------------

class TestExecuteDispatch:
    """Verify the generic dispatch/error-handling wrapper."""

    def test_known_tool_dispatches_correctly(self):
        """Known tool name routes to the correct handler method."""
        ex, cal, sheets = _make_executor()
        cal.find_events_by_phone.return_value = []
        result = ex.execute("get_upcoming_appointments", {"phone": "9876543210"})
        # Should have delegated to _exec_get_upcoming_appointments
        cal.find_events_by_phone.assert_called_once()
        assert "found" in result

    def test_unknown_tool_returns_error(self):
        """Unknown tool name returns an error dict, not an exception."""
        ex, _, _ = _make_executor()
        result = ex.execute("nonexistent_tool", {})
        assert "error" in result
        assert "Unknown tool" in result["error"]

    def test_tool_exception_returns_error(self):
        """If the handler raises, execute() catches it and returns error dict."""
        ex, cal, _ = _make_executor()
        cal.find_events_by_phone.side_effect = RuntimeError("boom")
        result = ex.execute("get_upcoming_appointments", {"phone": "9876543210"})
        assert "error" in result
        assert "Tool execution failed" in result["error"]
        assert "boom" in result["error"]


# ---------------------------------------------------------------------------
# 2. _exec_check_availability()
# ---------------------------------------------------------------------------

class TestCheckAvailability:
    """Test slot-availability checking."""

    @patch("agent.tools.datetime")
    def test_unknown_service(self, mock_dt):
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, _, _ = _make_executor()
        result = ex.execute("check_availability", {
            "service_name": "Alien Grooming",
            "date": FUTURE_DATE,
        })
        assert "error" in result
        assert "Unknown service" in result["error"]

    @patch("agent.tools.datetime")
    def test_invalid_date_format(self, mock_dt):
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, _, _ = _make_executor()
        result = ex.execute("check_availability", {
            "service_name": "Full Groom",
            "date": "not-a-date",
        })
        assert "error" in result
        assert "Invalid date format" in result["error"]

    @patch("agent.tools.datetime")
    def test_past_date(self, mock_dt):
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, _, _ = _make_executor()
        result = ex.execute("check_availability", {
            "service_name": "Full Groom",
            "date": PAST_DATE,
        })
        assert "error" in result
        assert "past" in result["error"].lower()

    @patch("agent.tools.datetime")
    def test_date_too_far_ahead(self, mock_dt):
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, _, _ = _make_executor()
        result = ex.execute("check_availability", {
            "service_name": "Full Groom",
            "date": FAR_FUTURE,
        })
        assert "error" in result
        assert "weeks ahead" in result["error"]

    @patch("agent.tools.datetime")
    def test_valid_request_with_slots(self, mock_dt):
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, cal, _ = _make_executor()
        cal.get_available_slots.return_value = {
            "Sarah": [{"start": "10:00", "end": "11:00"}],
            "Mike": [{"start": "14:00", "end": "15:00"}],
        }
        result = ex.execute("check_availability", {
            "service_name": "Full Groom",
            "date": FUTURE_DATE,
        })
        assert result["available"] is True
        assert result["date"] == FUTURE_DATE
        assert "Sarah" in result["slots_by_groomer"]
        assert result["slots_by_groomer"]["Sarah"] == ["10:00"]
        assert result["duration_minutes"] == 60

    @patch("agent.tools.datetime")
    def test_valid_request_no_slots_closed_day(self, mock_dt):
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, cal, _ = _make_executor()
        cal.get_available_slots.return_value = {}
        result = ex.execute("check_availability", {
            "service_name": "Bath & Brush",
            "date": FUTURE_DATE,
        })
        assert result["available"] is False
        assert result["slots"] == {}
        assert "closed" in result["message"].lower() or "no available" in result["message"].lower()

    @patch("agent.tools.datetime")
    def test_preferred_groomer_forwarded(self, mock_dt):
        """Preferred groomer arg is passed through to the calendar client."""
        mock_dt.now.return_value = FROZEN_NOW
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
        ex, cal, _ = _make_executor()
        cal.get_available_slots.return_value = {
            "Sarah": [{"start": "09:00", "end": "09:30"}],
        }
        ex.execute("check_availability", {
            "service_name": "Nail Trim & File",
            "date": FUTURE_DATE,
            "preferred_groomer": "Sarah",
        })
        _, kwargs = cal.get_available_slots.call_args
        # positional or keyword: the third argument should be "Sarah"
        args_positional = cal.get_available_slots.call_args[0]
        assert args_positional[2] == "Sarah"


# ---------------------------------------------------------------------------
# 3. _exec_book_appointment()
# ---------------------------------------------------------------------------

def _book_args(**overrides):
    """Return a valid set of booking arguments, with optional overrides."""
    defaults = {
        "service_name": "Full Groom",
        "date": FUTURE_DATE,
        "time": "10:00",
        "groomer_name": "Sarah",
        "customer_name": "Priya",
        "phone": "9876543210",
        "dog_name": "Max",
        "dog_breed": "Golden Retriever",
        "dog_size": "Large",
        "notes": "",
    }
    defaults.update(overrides)
    return defaults


class TestBookAppointment:
    """Test the booking flow."""

    def test_invalid_phone(self):
        ex, _, _ = _make_executor()
        result = ex.execute("book_appointment", _book_args(phone="123"))
        assert "error" in result
        assert "Invalid phone" in result["error"]

    def test_unknown_service(self):
        ex, _, _ = _make_executor()
        result = ex.execute("book_appointment", _book_args(service_name="Magic Groom"))
        assert "error" in result
        assert "Unknown service" in result["error"]

    def test_invalid_date_time(self):
        ex, _, _ = _make_executor()
        result = ex.execute("book_appointment", _book_args(date="bad", time="xx:yy"))
        assert "error" in result
        assert "Invalid date/time" in result["error"]

    def test_invalid_time_format(self):
        ex, _, _ = _make_executor()
        result = ex.execute("book_appointment", _book_args(time="25:99"))
        assert "error" in result
        assert "Invalid date/time" in result["error"]

    def test_pre_booking_conflict(self):
        """Pre-booking check detects a conflict -> success:False, no event created."""
        ex, cal, _ = _make_executor()
        cal.check_conflict.return_value = True
        result = ex.execute("book_appointment", _book_args())
        assert result["success"] is False
        assert "no longer available" in result["error"]
        cal.create_event.assert_not_called()

    def test_successful_booking(self):
        """Happy path: no conflict, event created, contacts updated."""
        ex, cal, sheets = _make_executor()
        cal.check_conflict.return_value = False
        cal.create_event.return_value = {"success": True, "event_id": "evt123"}
        result = ex.execute("book_appointment", _book_args())
        assert result["success"] is True
        assert result["event_id"] == "evt123"
        assert result["groomer"] == "Sarah"
        assert result["date"] == FUTURE_DATE
        assert result["time"] == "10:00"
        assert result["end_time"] == "11:00"  # 60-min Full Groom
        assert result["service"] == "Full Groom"
        assert result["price"] == 1200  # Large Full Groom
        assert result["dog_name"] == "Max"
        assert result["customer_name"] == "Priya"
        # Sheets calls
        sheets.register_contact.assert_called_once()
        sheets.update_contact_last_date.assert_called_once_with("9876543210", "Max")

    def test_successful_booking_with_notes(self):
        """Notes are included in event description."""
        ex, cal, sheets = _make_executor()
        cal.check_conflict.return_value = False
        cal.create_event.return_value = {"success": True, "event_id": "evt456"}
        ex.execute("book_appointment", _book_args(notes="Anxious dog"))
        # Verify description includes notes
        _, kwargs = cal.create_event.call_args
        assert "Anxious dog" in kwargs["description"]

    def test_post_booking_conflict_deletes_event(self):
        """If a conflict is found after creation, delete the new event."""
        ex, cal, sheets = _make_executor()
        # First check_conflict (pre-booking): no conflict
        # Second check_conflict (post-booking): conflict!
        cal.check_conflict.side_effect = [False, True]
        cal.create_event.return_value = {"success": True, "event_id": "evt_race"}
        result = ex.execute("book_appointment", _book_args())
        assert result["success"] is False
        assert "just taken" in result["error"]
        cal.delete_event.assert_called_once_with("Sarah", "evt_race")
        # Sheets should NOT be updated
        sheets.register_contact.assert_not_called()

    def test_create_event_fails(self):
        """If calendar.create_event fails, booking returns success:False."""
        ex, cal, _ = _make_executor()
        cal.check_conflict.return_value = False
        cal.create_event.return_value = {"success": False, "error": "Calendar API error"}
        result = ex.execute("book_appointment", _book_args())
        assert result["success"] is False
        assert "Failed to create event" in result["error"] or "Calendar API error" in result["error"]

    def test_bath_and_brush_duration_and_price(self):
        """Verify a 30-min service uses correct duration and fixed price."""
        ex, cal, sheets = _make_executor()
        cal.check_conflict.return_value = False
        cal.create_event.return_value = {"success": True, "event_id": "evtBB"}
        result = ex.execute("book_appointment", _book_args(
            service_name="Bath & Brush",
            dog_size="Small",
        ))
        assert result["success"] is True
        assert result["end_time"] == "10:30"  # 30-min service
        assert result["price"] == 500


# ---------------------------------------------------------------------------
# 4. _exec_reschedule_appointment()
# ---------------------------------------------------------------------------

def _reschedule_args(**overrides):
    defaults = {
        "old_event_id": "old_evt_1",
        "old_groomer_name": "Sarah",
        "new_date": FUTURE_DATE,
        "new_time": "14:00",
        "new_groomer_name": "Mike",
        "service_name": "Full Groom",
        "customer_name": "Priya",
        "phone": "9876543210",
        "dog_name": "Max",
        "dog_breed": "Golden Retriever",
        "dog_size": "Large",
    }
    defaults.update(overrides)
    return defaults


class TestRescheduleAppointment:

    def test_unknown_service(self):
        ex, _, _ = _make_executor()
        result = ex.execute("reschedule_appointment", _reschedule_args(service_name="Magic"))
        assert "error" in result
        assert "Unknown service" in result["error"]

    def test_invalid_date_time(self):
        ex, _, _ = _make_executor()
        result = ex.execute("reschedule_appointment", _reschedule_args(new_date="bad"))
        assert "error" in result
        assert "Invalid date/time" in result["error"]

    def test_create_fails(self):
        """If creating the new event fails, original is preserved."""
        ex, cal, _ = _make_executor()
        cal.create_event.return_value = {"success": False, "error": "API down"}
        result = ex.execute("reschedule_appointment", _reschedule_args())
        assert result["success"] is False
        assert "Original kept" in result["error"]
        cal.delete_event.assert_not_called()

    def test_conflict_on_new_slot(self):
        """If conflict detected on the new slot, delete it and keep original."""
        ex, cal, _ = _make_executor()
        cal.create_event.return_value = {"success": True, "event_id": "new_evt"}
        cal.check_conflict.return_value = True  # conflict on the new slot
        result = ex.execute("reschedule_appointment", _reschedule_args())
        assert result["success"] is False
        assert "just taken" in result["error"]
        cal.delete_event.assert_called_once_with("Mike", "new_evt")

    def test_rollback_when_old_delete_fails(self):
        """New event created, old event delete fails -> rolls back new event, returns failure."""
        ex, cal, _ = _make_executor()
        cal.create_event.return_value = {"success": True, "event_id": "new_evt_ok"}
        cal.check_conflict.return_value = False
        # First delete call (old event) fails, second (rollback new event) succeeds
        cal.delete_event.side_effect = [
            {"success": False, "error": "404"},
            {"success": True},
        ]
        result = ex.execute("reschedule_appointment", _reschedule_args())
        assert result["success"] is False
        assert "Could not remove the original appointment" in result["error"]
        # Should have tried to delete old event, then rolled back new event
        assert cal.delete_event.call_count == 2
        cal.delete_event.assert_any_call("Sarah", "old_evt_1")
        cal.delete_event.assert_any_call("Mike", "new_evt_ok")

    def test_success_happy_path(self):
        """Full happy-path reschedule."""
        ex, cal, _ = _make_executor()
        cal.create_event.return_value = {"success": True, "event_id": "new_evt_happy"}
        cal.check_conflict.return_value = False
        cal.delete_event.return_value = {"success": True}
        result = ex.execute("reschedule_appointment", _reschedule_args())
        assert result["success"] is True
        assert result["new_event_id"] == "new_evt_happy"
        cal.delete_event.assert_called_once_with("Sarah", "old_evt_1")

    def test_description_includes_rescheduled(self):
        """Event description should mention 'rescheduled'."""
        ex, cal, _ = _make_executor()
        cal.create_event.return_value = {"success": True, "event_id": "evt_desc"}
        cal.check_conflict.return_value = False
        cal.delete_event.return_value = {"success": True}
        ex.execute("reschedule_appointment", _reschedule_args())
        _, kwargs = cal.create_event.call_args
        assert "rescheduled" in kwargs["description"]


# ---------------------------------------------------------------------------
# 5. _exec_cancel_appointment()
# ---------------------------------------------------------------------------

class TestCancelAppointment:

    def test_delegates_to_calendar_delete(self):
        """cancel_appointment simply delegates to calendar.delete_event."""
        ex, cal, _ = _make_executor()
        cal.delete_event.return_value = {"success": True}
        result = ex.execute("cancel_appointment", {
            "event_id": "evt_cancel",
            "groomer_name": "Carlos",
        })
        cal.delete_event.assert_called_once_with("Carlos", "evt_cancel")
        assert result == {"success": True}

    def test_returns_error_from_calendar(self):
        """If calendar returns error, it is passed through."""
        ex, cal, _ = _make_executor()
        cal.delete_event.return_value = {"success": False, "error": "Not found"}
        result = ex.execute("cancel_appointment", {
            "event_id": "missing",
            "groomer_name": "Sarah",
        })
        assert result["success"] is False
        assert "Not found" in result["error"]


# ---------------------------------------------------------------------------
# 6. _exec_lookup_contact()
# ---------------------------------------------------------------------------

class TestLookupContact:

    def test_invalid_phone(self):
        ex, _, _ = _make_executor()
        result = ex.execute("lookup_contact", {"phone": "12345"})
        assert "error" in result
        assert "Invalid phone" in result["error"]

    def test_strips_country_code(self):
        """Phone with country code prefix is stripped to last 10 digits."""
        ex, _, sheets = _make_executor()
        sheets.lookup_contact.return_value = []
        ex.execute("lookup_contact", {"phone": "+919876543210"})
        sheets.lookup_contact.assert_called_once_with("9876543210")

    def test_strips_non_digits(self):
        """Non-digit characters (dashes, spaces, parens) are removed."""
        ex, _, sheets = _make_executor()
        sheets.lookup_contact.return_value = []
        ex.execute("lookup_contact", {"phone": "(987) 654-3210"})
        sheets.lookup_contact.assert_called_once_with("9876543210")

    def test_not_found(self):
        ex, _, sheets = _make_executor()
        sheets.lookup_contact.return_value = []
        result = ex.execute("lookup_contact", {"phone": "9876543210"})
        assert result["found"] is False
        assert result["phone"] == "9876543210"

    def test_found(self):
        ex, _, sheets = _make_executor()
        contact_data = [{"name": "Priya", "dog_name": "Max"}]
        sheets.lookup_contact.return_value = contact_data
        result = ex.execute("lookup_contact", {"phone": "9876543210"})
        assert result["found"] is True
        assert result["phone"] == "9876543210"
        assert result["contacts"] == contact_data


# ---------------------------------------------------------------------------
# 7. _exec_register_contact()
# ---------------------------------------------------------------------------

class TestRegisterContact:

    def test_dog_size_inferred_from_breed(self):
        """When dog_size is empty, it is looked up from the breed mapping."""
        ex, _, sheets = _make_executor()
        sheets.register_contact.return_value = {"success": True}
        ex.execute("register_contact", {
            "phone": "9876543210",
            "name": "Priya",
            "dog_name": "Max",
            "dog_breed": "Golden Retriever",
            "dog_size": "",       # not provided
        })
        sheets.register_contact.assert_called_once_with(
            phone="9876543210",
            name="Priya",
            dog_name="Max",
            dog_breed="Golden Retriever",
            dog_size="Large",     # inferred from breed mapping
        )

    def test_dog_size_unknown_breed(self):
        """When breed is not in mapping and dog_size empty, use 'Unknown'."""
        ex, _, sheets = _make_executor()
        sheets.register_contact.return_value = {"success": True}
        ex.execute("register_contact", {
            "phone": "9876543210",
            "name": "Ravi",
            "dog_name": "Buddy",
            "dog_breed": "Alien Dog",
            "dog_size": "",
        })
        sheets.register_contact.assert_called_once_with(
            phone="9876543210",
            name="Ravi",
            dog_name="Buddy",
            dog_breed="Alien Dog",
            dog_size="Unknown",
        )

    def test_explicit_dog_size_passed_through(self):
        """When dog_size is already provided, it is NOT overridden."""
        ex, _, sheets = _make_executor()
        sheets.register_contact.return_value = {"success": True}
        ex.execute("register_contact", {
            "phone": "9876543210",
            "name": "Priya",
            "dog_name": "Max",
            "dog_breed": "Golden Retriever",
            "dog_size": "Medium",  # explicitly passed (even though breed says Large)
        })
        sheets.register_contact.assert_called_once_with(
            phone="9876543210",
            name="Priya",
            dog_name="Max",
            dog_breed="Golden Retriever",
            dog_size="Medium",
        )

    def test_phone_country_code_stripped(self):
        """Country code prefix is stripped before registering."""
        ex, _, sheets = _make_executor()
        sheets.register_contact.return_value = {"success": True}
        ex.execute("register_contact", {
            "phone": "+919876543210",
            "name": "Priya",
            "dog_name": "Max",
            "dog_breed": "Pomeranian",
            "dog_size": "Small",
        })
        call_kwargs = sheets.register_contact.call_args[1]
        assert call_kwargs["phone"] == "9876543210"

    def test_returns_sheets_result(self):
        """Result from sheets.register_contact is passed through."""
        ex, _, sheets = _make_executor()
        sheets.register_contact.return_value = {"success": True, "row": 42}
        result = ex.execute("register_contact", {
            "phone": "9876543210",
            "name": "Priya",
            "dog_name": "Max",
            "dog_breed": "Pug",
            "dog_size": "Medium",
        })
        assert result == {"success": True, "row": 42}


# ---------------------------------------------------------------------------
# 8. _exec_get_upcoming_appointments()
# ---------------------------------------------------------------------------

class TestGetUpcomingAppointments:

    def test_no_events(self):
        ex, cal, _ = _make_executor()
        cal.find_events_by_phone.return_value = []
        result = ex.execute("get_upcoming_appointments", {"phone": "9876543210"})
        assert result["found"] is False
        assert result["phone"] == "9876543210"
        assert "No upcoming" in result["message"]

    def test_events_found(self):
        ex, cal, _ = _make_executor()
        events = [
            {"event_id": "e1", "groomer_name": "Sarah", "summary": "Full Groom - Max"},
            {"event_id": "e2", "groomer_name": "Mike", "summary": "Bath & Brush - Max"},
        ]
        cal.find_events_by_phone.return_value = events
        result = ex.execute("get_upcoming_appointments", {"phone": "9876543210"})
        assert result["found"] is True
        assert result["phone"] == "9876543210"
        assert len(result["appointments"]) == 2
        assert result["appointments"][0]["event_id"] == "e1"

    def test_phone_with_country_code(self):
        """Country code is stripped before the calendar lookup."""
        ex, cal, _ = _make_executor()
        cal.find_events_by_phone.return_value = []
        ex.execute("get_upcoming_appointments", {"phone": "+919876543210"})
        cal.find_events_by_phone.assert_called_once_with("9876543210")

    def test_phone_with_non_digit_characters(self):
        """Non-digit characters are cleaned before lookup."""
        ex, cal, _ = _make_executor()
        cal.find_events_by_phone.return_value = []
        ex.execute("get_upcoming_appointments", {"phone": "(987) 654-3210"})
        cal.find_events_by_phone.assert_called_once_with("9876543210")


# ---------------------------------------------------------------------------
# 9. _exec_escalate_to_staff()
# ---------------------------------------------------------------------------

class TestEscalateToStaff:

    def test_returns_success_with_reason(self):
        ex, _, _ = _make_executor()
        result = ex.execute("escalate_to_staff", {"reason": "Refund request"})
        assert result["success"] is True
        assert result["reason"] == "Refund request"
        assert "staff" in result["message"].lower()

    def test_default_reason(self):
        """If reason is missing from args, a default is used."""
        ex, _, _ = _make_executor()
        result = ex.execute("escalate_to_staff", {})
        assert result["success"] is True
        assert result["reason"] == "Unknown reason"

    def test_optional_phone_and_name(self):
        """Phone and caller_name are optional and don't affect the result."""
        ex, _, _ = _make_executor()
        result = ex.execute("escalate_to_staff", {
            "reason": "Aggressive dog",
            "phone": "9876543210",
            "caller_name": "Priya",
        })
        assert result["success"] is True
        assert result["reason"] == "Aggressive dog"
