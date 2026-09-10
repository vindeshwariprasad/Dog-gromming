"""
Create 4 groomer calendars using the Google Calendar API.
Run once during initial setup.

Prints the calendar IDs to be added to .env as GROOMER_CALENDARS.
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from googleapiclient.discovery import build
from integrations.auth import get_google_credentials
from config.shop_data import GROOMERS


def main():
    credentials = get_google_credentials()
    service = build("calendar", "v3", credentials=credentials)

    calendar_pairs = []

    for groomer in GROOMERS:
        name = groomer["name"]
        calendar_body = {
            "summary": f"Maple Street Grooming - {name}",
            "description": f"Schedule for groomer {name} ({groomer['specialty']})",
            "timeZone": "Asia/Kolkata",
        }

        created = service.calendars().insert(body=calendar_body).execute()
        cal_id = created["id"]
        print(f"Created calendar for {name}: {cal_id}")
        calendar_pairs.append(f"{name}:{cal_id}")

    env_value = ",".join(calendar_pairs)
    print(f"\nAdd this to your .env file:")
    print(f'GROOMER_CALENDARS="{env_value}"')


if __name__ == "__main__":
    main()
