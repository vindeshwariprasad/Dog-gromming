"""
Create a Google Spreadsheet with Contacts and Call Log tabs.
Run once during initial setup.

Prints the spreadsheet ID to be added to .env as GOOGLE_SHEET_ID.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from googleapiclient.discovery import build
from integrations.auth import get_google_credentials
from integrations.google_sheets import CONTACTS_HEADERS, CALL_LOG_HEADERS


def main():
    credentials = get_google_credentials()
    service = build("sheets", "v4", credentials=credentials)

    spreadsheet_body = {
        "properties": {
            "title": "Maple Street Dog Grooming - Receptionist Data",
        },
        "sheets": [
            {
                "properties": {
                    "title": "Contacts",
                    "index": 0,
                },
            },
            {
                "properties": {
                    "title": "Call Log",
                    "index": 1,
                },
            },
        ],
    }

    spreadsheet = service.spreadsheets().create(body=spreadsheet_body).execute()
    spreadsheet_id = spreadsheet["spreadsheetId"]
    print(f"Created spreadsheet: {spreadsheet_id}")
    print(f"URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}")

    # Add headers to Contacts tab
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Contacts!A1",
        valueInputOption="RAW",
        body={"values": [CONTACTS_HEADERS]},
    ).execute()
    print("Added Contacts headers")

    # Add headers to Call Log tab
    service.spreadsheets().values().update(
        spreadsheetId=spreadsheet_id,
        range="Call Log!A1",
        valueInputOption="RAW",
        body={"values": [CALL_LOG_HEADERS]},
    ).execute()
    print("Added Call Log headers")

    print(f"\nAdd this to your .env file:")
    print(f'GOOGLE_SHEET_ID="{spreadsheet_id}"')


if __name__ == "__main__":
    main()
