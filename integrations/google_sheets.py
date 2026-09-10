import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

from config.settings import GOOGLE_SHEET_ID, TIMEZONE

logger = logging.getLogger(__name__)

IST = ZoneInfo(TIMEZONE)

CONTACTS_TAB = "Contacts"
CALL_LOG_TAB = "Call Log"

CONTACTS_HEADERS = [
    "Phone", "Name", "Dog Name", "Dog Breed", "Dog Size",
    "First Contact Date", "Last Contact Date", "Vaccination Verified", "Notes",
]

CALL_LOG_HEADERS = [
    "Timestamp", "Phone", "Caller Name", "Intent", "Summary", "Outcome", "Escalation Reason",
]


class SheetsClient:
    def __init__(self, credentials: Credentials, spreadsheet_id: str | None = None):
        self.service = build("sheets", "v4", credentials=credentials)
        self.spreadsheet_id = spreadsheet_id or GOOGLE_SHEET_ID

    def _read_all_rows(self, tab: str) -> list[list[str]]:
        """Read all rows from a tab (including header)."""
        try:
            result = (
                self.service.spreadsheets()
                .values()
                .get(spreadsheetId=self.spreadsheet_id, range=f"{tab}!A:Z")
                .execute()
            )
            return result.get("values", [])
        except HttpError as e:
            logger.error("Failed to read %s tab: %s", tab, e)
            return []

    def _append_row(self, tab: str, row: list[str]) -> bool:
        """Append a single row to a tab."""
        try:
            self.service.spreadsheets().values().append(
                spreadsheetId=self.spreadsheet_id,
                range=f"{tab}!A:A",
                valueInputOption="USER_ENTERED",
                insertDataOption="INSERT_ROWS",
                body={"values": [row]},
            ).execute()
            return True
        except HttpError as e:
            logger.error("Failed to append to %s: %s", tab, e)
            return False

    def _update_row(self, tab: str, row_index: int, row: list[str]) -> bool:
        """Update a specific row (1-indexed, row 1 = header)."""
        try:
            self.service.spreadsheets().values().update(
                spreadsheetId=self.spreadsheet_id,
                range=f"{tab}!A{row_index}:{chr(64 + len(row))}{row_index}",
                valueInputOption="USER_ENTERED",
                body={"values": [row]},
            ).execute()
            return True
        except HttpError as e:
            logger.error("Failed to update row %d in %s: %s", row_index, tab, e)
            return False

    def lookup_contact(self, phone: str) -> list[dict]:
        """
        Find all contacts matching a phone number.
        Returns list of dicts (one per dog for multi-dog households).
        """
        rows = self._read_all_rows(CONTACTS_TAB)
        if len(rows) < 2:  # Only header or empty
            return []

        headers = rows[0]
        results = []
        for row in rows[1:]:
            # Pad row to match headers length
            padded = row + [""] * (len(headers) - len(row))
            row_dict = dict(zip(headers, padded))
            if row_dict.get("Phone", "").strip() == phone.strip():
                results.append(row_dict)

        return results

    def register_contact(
        self,
        phone: str,
        name: str,
        dog_name: str,
        dog_breed: str,
        dog_size: str,
        vaccination_verified: str = "No",
        notes: str = "",
    ) -> dict:
        """
        Register a new contact. Checks for duplicate (phone + dog_name) first.
        Returns {"success": True} or {"success": False, "error": "..."}.
        """
        # Check for existing contact with same phone + dog name
        existing = self.lookup_contact(phone)
        for contact in existing:
            if contact.get("Dog Name", "").strip().lower() == dog_name.strip().lower():
                logger.info("Contact already exists: %s / %s", phone, dog_name)
                return {"success": True, "already_exists": True}

        today = datetime.now(IST).strftime("%Y-%m-%d")
        row = [
            phone, name, dog_name, dog_breed, dog_size,
            today, today, vaccination_verified, notes,
        ]
        success = self._append_row(CONTACTS_TAB, row)
        if success:
            logger.info("Registered contact: %s / %s", phone, dog_name)
            return {"success": True, "already_exists": False}
        return {"success": False, "error": "Failed to write to Google Sheets"}

    def update_contact_last_date(self, phone: str, dog_name: str) -> bool:
        """Update the Last Contact Date for a contact."""
        rows = self._read_all_rows(CONTACTS_TAB)
        if len(rows) < 2:
            return False

        headers = rows[0]
        phone_idx = headers.index("Phone") if "Phone" in headers else 0
        dog_name_idx = headers.index("Dog Name") if "Dog Name" in headers else 2
        last_date_idx = headers.index("Last Contact Date") if "Last Contact Date" in headers else 6

        for i, row in enumerate(rows[1:], start=2):  # row 2 is first data row
            padded = row + [""] * (len(headers) - len(row))
            if (
                padded[phone_idx].strip() == phone.strip()
                and padded[dog_name_idx].strip().lower() == dog_name.strip().lower()
            ):
                padded[last_date_idx] = datetime.now(IST).strftime("%Y-%m-%d")
                return self._update_row(CONTACTS_TAB, i, padded)

        return False

    def log_call(
        self,
        phone: str = "",
        caller_name: str = "",
        intent: str = "",
        summary: str = "",
        outcome: str = "Completed",
        escalation_reason: str = "",
    ) -> bool:
        """Append a row to the Call Log tab."""
        timestamp = datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S")
        row = [timestamp, phone, caller_name, intent, summary, outcome, escalation_reason]
        success = self._append_row(CALL_LOG_TAB, row)
        if success:
            logger.info("Logged call: %s / %s / %s", phone, intent, outcome)
        return success
