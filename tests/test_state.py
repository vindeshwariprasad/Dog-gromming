"""Tests for session state management."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from agent.state import SessionState


class TestSessionState:
    def test_initial_state(self):
        s = SessionState()
        assert s.phone is None
        assert s.identified is False
        assert s.current_intent is None
        assert s.intents_completed == []
        assert s.contact_records == []

    def test_has_all_booking_fields_false_initially(self):
        s = SessionState()
        assert s.has_all_booking_fields() is False

    def test_has_all_booking_fields_true_when_complete(self):
        s = SessionState(
            phone="9876543210",
            name="Priya",
            service="Full Groom",
            service_duration=60,
            dog_name="Max",
            dog_breed="Golden Retriever",
            preferred_date="2024-01-15",
            preferred_time="10:00",
            groomer="Sarah",
        )
        assert s.has_all_booking_fields() is True

    def test_has_all_booking_fields_missing_one(self):
        s = SessionState(
            phone="9876543210",
            name="Priya",
            service="Full Groom",
            service_duration=60,
            dog_name="Max",
            dog_breed="Golden Retriever",
            preferred_date="2024-01-15",
            # missing preferred_time
            groomer="Sarah",
        )
        assert s.has_all_booking_fields() is False

    def test_reset_booking_data(self):
        s = SessionState(
            phone="9876543210",
            name="Priya",
            service="Full Groom",
            service_duration=60,
            preferred_date="2024-01-15",
            preferred_time="10:00",
            groomer="Sarah",
            booking_confirmed=True,
            current_intent="book",
        )
        s.reset_booking_data()
        assert s.service is None
        assert s.preferred_date is None
        assert s.preferred_time is None
        assert s.groomer is None
        assert s.booking_confirmed is False
        assert s.current_intent is None
        # These should be preserved
        assert s.phone == "9876543210"
        assert s.name == "Priya"

    def test_call_summary(self):
        s = SessionState()
        assert s.get_call_summary() == "No actions taken"
        s.call_summary_parts.append("Booked Full Groom")
        assert s.get_call_summary() == "Booked Full Groom"
        s.call_summary_parts.append("Rescheduled Bath")
        assert "Booked Full Groom" in s.get_call_summary()
        assert "Rescheduled Bath" in s.get_call_summary()

    def test_conversation_id_generated(self):
        s1 = SessionState()
        s2 = SessionState()
        assert s1.conversation_id != s2.conversation_id
        assert len(s1.conversation_id) == 8
