"""
Integration tests for Google Sheets client.

These require real Google credentials and spreadsheet ID.
Run with: pytest tests/test_integration_sheets.py -v -s

Skip in CI with: pytest -m "not integration"
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from config.settings import GOOGLE_SHEET_ID
from integrations.auth import get_google_credentials
from integrations.google_sheets import SheetsClient

pytestmark = pytest.mark.skipif(
    not GOOGLE_SHEET_ID,
    reason="GOOGLE_SHEET_ID not configured in .env",
)


@pytest.fixture(scope="module")
def sheets_client():
    credentials = get_google_credentials()
    return SheetsClient(credentials)


class TestSheetsIntegration:
    TEST_PHONE = "0001112222"

    def test_lookup_nonexistent_contact(self, sheets_client):
        result = sheets_client.lookup_contact("0000000001")
        assert result == []

    def test_register_and_lookup_contact(self, sheets_client):
        """Register a test contact and look it up."""
        result = sheets_client.register_contact(
            phone=self.TEST_PHONE,
            name="Test User",
            dog_name="TestDog",
            dog_breed="Test Breed",
            dog_size="Medium",
        )
        assert result["success"] is True

        # Lookup
        contacts = sheets_client.lookup_contact(self.TEST_PHONE)
        assert len(contacts) >= 1
        found = [c for c in contacts if c.get("Dog Name") == "TestDog"]
        assert len(found) == 1
        assert found[0]["Name"] == "Test User"

    def test_register_duplicate_ignored(self, sheets_client):
        """Registering the same phone+dog should not create duplicate."""
        result = sheets_client.register_contact(
            phone=self.TEST_PHONE,
            name="Test User",
            dog_name="TestDog",
            dog_breed="Test Breed",
            dog_size="Medium",
        )
        assert result["success"] is True
        assert result.get("already_exists") is True

    def test_log_call(self, sheets_client):
        """Log a call entry."""
        success = sheets_client.log_call(
            phone=self.TEST_PHONE,
            caller_name="Test User",
            intent="FAQ",
            summary="Integration test call",
            outcome="Completed",
        )
        assert success is True

    def test_update_last_contact_date(self, sheets_client):
        """Update last contact date for a contact."""
        success = sheets_client.update_contact_last_date(self.TEST_PHONE, "TestDog")
        assert success is True
