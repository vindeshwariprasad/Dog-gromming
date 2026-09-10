"""
Integration tests for Google Calendar client.

These require real Google credentials and calendar IDs.
Run with: pytest tests/test_integration_calendar.py -v -s

Skip in CI with: pytest -m "not integration"
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from config.settings import GROOMER_CALENDAR_IDS, TIMEZONE
from integrations.auth import get_google_credentials
from integrations.google_calendar import CalendarClient

IST = ZoneInfo(TIMEZONE)

# Skip all tests if no calendar IDs configured
pytestmark = pytest.mark.skipif(
    not GROOMER_CALENDAR_IDS,
    reason="GROOMER_CALENDARS not configured in .env",
)


@pytest.fixture(scope="module")
def calendar_client():
    credentials = get_google_credentials()
    return CalendarClient(credentials)


@pytest.fixture
def test_groomer():
    """Return the first configured groomer name."""
    return next(iter(GROOMER_CALENDAR_IDS.keys()))


class TestCalendarIntegration:
    def test_get_available_slots_working_day(self, calendar_client):
        """Check availability on a future working day."""
        # Find next Monday
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)

        slots = calendar_client.get_available_slots(next_monday, 30)
        assert isinstance(slots, dict)
        # Should have at least one groomer with available slots
        assert len(slots) > 0

    def test_get_available_slots_sunday(self, calendar_client):
        """Sunday should return no slots (shop closed)."""
        today = date.today()
        days_until_sunday = (6 - today.weekday()) % 7
        if days_until_sunday == 0:
            days_until_sunday = 7
        next_sunday = today + timedelta(days=days_until_sunday)

        slots = calendar_client.get_available_slots(next_sunday, 30)
        assert slots == {}

    def test_create_and_delete_event(self, calendar_client, test_groomer):
        """Create an event, verify it exists, then delete it."""
        # Use a far-future date to avoid conflicts with seed data
        future = datetime.now(IST) + timedelta(days=25)
        start_dt = future.replace(hour=9, minute=0, second=0, microsecond=0)
        end_dt = start_dt + timedelta(minutes=30)

        # Create
        result = calendar_client.create_event(
            groomer_name=test_groomer,
            summary="TEST - Integration Test Event",
            start_dt=start_dt.isoformat(),
            end_dt=end_dt.isoformat(),
            description="Test event - safe to delete\nPhone: 0000000000",
        )
        assert result["success"] is True
        event_id = result["event_id"]

        # Verify conflict detection
        has_conflict = calendar_client.check_conflict(
            test_groomer, start_dt.isoformat(), end_dt.isoformat(),
            exclude_event_id=event_id,
        )
        assert has_conflict is False  # No OTHER event at this time

        # Search by phone
        events = calendar_client.find_events_by_phone("0000000000", time_min=start_dt - timedelta(hours=1))
        found = [e for e in events if e["event_id"] == event_id]
        assert len(found) == 1

        # Delete
        del_result = calendar_client.delete_event(test_groomer, event_id)
        assert del_result["success"] is True

    def test_60_min_slots_respect_closing_time(self, calendar_client):
        """60-min service should not have slots after 4:00 PM (ends at 5:00 PM)."""
        today = date.today()
        days_until_monday = (7 - today.weekday()) % 7
        if days_until_monday == 0:
            days_until_monday = 7
        next_monday = today + timedelta(days=days_until_monday)

        slots = calendar_client.get_available_slots(next_monday, 60)
        for groomer, groomer_slots in slots.items():
            for slot in groomer_slots:
                # Last 60-min slot should start at 16:00 (end at 17:00)
                assert slot["start"] <= "16:00", f"Got slot starting at {slot['start']} for 60-min service"
