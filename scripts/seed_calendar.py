"""
Pre-seed Google Calendar with test appointments.
Creates ~12 appointments over the next 3 days to test:
- Conflict handling (fully booked slots)
- Reschedule flow (existing bookings with known contacts)
- Mix of 30-min and 60-min services
- Appointments across all 4 groomers

Also seeds the Contacts tab with corresponding contacts.

Run once after setup_calendars.py and setup_sheets.py.
"""

import sys
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from integrations.auth import get_google_credentials
from integrations.google_calendar import CalendarClient
from integrations.google_sheets import SheetsClient
from config.settings import TIMEZONE

IST = ZoneInfo(TIMEZONE)


def _next_weekday(start: datetime, target_weekday: int) -> datetime:
    """Find the next date that falls on the given weekday (0=Mon, 5=Sat)."""
    days_ahead = target_weekday - start.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    return start + timedelta(days=days_ahead)


def main():
    credentials = get_google_credentials()
    calendar = CalendarClient(credentials)
    sheets = SheetsClient(credentials)

    now = datetime.now(IST)
    today = now.date()

    # Find the next 3 working days (Mon-Sat)
    working_days = []
    d = today + timedelta(days=1)
    while len(working_days) < 3:
        if d.weekday() < 6:  # Mon=0 through Sat=5
            working_days.append(d)
        d += timedelta(days=1)

    day1, day2, day3 = working_days
    print(f"Seeding appointments for: {day1}, {day2}, {day3}")

    # Test contacts to seed
    contacts = [
        {"phone": "9876543210", "name": "Priya", "dog_name": "Max", "breed": "Golden Retriever", "size": "Large"},
        {"phone": "9876543211", "name": "Rahul", "dog_name": "Bella", "breed": "Beagle", "size": "Medium"},
        {"phone": "9876543212", "name": "Ananya", "dog_name": "Rocky", "breed": "German Shepherd", "size": "Large"},
        {"phone": "9876543213", "name": "Vikram", "dog_name": "Luna", "breed": "Shih Tzu", "size": "Small"},
        {"phone": "9876543214", "name": "Meera", "dog_name": "Bruno", "breed": "Labrador", "size": "Large"},
        {"phone": "9876543215", "name": "Arjun", "dog_name": "Coco", "breed": "Pomeranian", "size": "Small"},
        {"phone": "9876543216", "name": "Sneha", "dog_name": "Tiger", "breed": "Rottweiler", "size": "Large"},
        {"phone": "9876543217", "name": "Karthik", "dog_name": "Daisy", "breed": "Cocker Spaniel", "size": "Medium"},
        {"phone": "9876543210", "name": "Priya", "dog_name": "Milo", "breed": "Pug", "size": "Medium"},
    ]

    # Seed contacts to Sheets
    for c in contacts:
        sheets.register_contact(
            phone=c["phone"], name=c["name"], dog_name=c["dog_name"],
            dog_breed=c["breed"], dog_size=c["size"],
        )
        print(f"  Registered contact: {c['name']} / {c['dog_name']}")

    # Appointments to seed
    # Format: (day, time_str, duration_min, groomer, contact_index, service)
    appointments = [
        # Day 1: Make 10:00 AM fully booked (all 4 groomers)
        (day1, "10:00", 60, "Sarah", 0, "Full Groom"),    # Priya / Max
        (day1, "10:00", 60, "Mike", 2, "Full Groom"),     # Ananya / Rocky
        (day1, "10:00", 30, "Jessica", 3, "Bath & Brush"), # Vikram / Luna
        (day1, "10:00", 30, "Carlos", 5, "Nail Trim & File"), # Arjun / Coco

        # Day 1: Some afternoon slots
        (day1, "14:00", 60, "Sarah", 4, "De-shedding Treatment"),  # Meera / Bruno
        (day1, "14:30", 30, "Jessica", 7, "Teeth Brushing"),       # Karthik / Daisy

        # Day 2: Priya's appointment (for testing reschedule)
        (day2, "11:00", 60, "Sarah", 8, "Full Groom"),    # Priya / Milo (second dog)
        (day2, "09:00", 30, "Mike", 1, "Bath & Brush"),   # Rahul / Bella
        (day2, "15:00", 60, "Carlos", 6, "Flea & Tick Treatment"), # Sneha / Tiger

        # Day 3: Light schedule
        (day3, "09:30", 30, "Jessica", 3, "Puppy Introduction"),  # Vikram / Luna
        (day3, "11:00", 60, "Mike", 4, "Full Groom"),     # Meera / Bruno
        (day3, "13:00", 60, "Sarah", 2, "De-shedding Treatment"), # Ananya / Rocky
    ]

    for day, time_str, duration, groomer, ci, service in appointments:
        c = contacts[ci]
        hour, minute = map(int, time_str.split(":"))
        start_dt = datetime(day.year, day.month, day.day, hour, minute, tzinfo=IST)
        end_dt = start_dt + timedelta(minutes=duration)

        price = "?"
        if service == "Full Groom":
            price_map = {"Small": 800, "Medium": 1000, "Large": 1200}
            price = price_map.get(c["size"], "?")
        elif service == "Bath & Brush":
            price = 500
        elif service == "Nail Trim & File":
            price = 200
        elif service == "Teeth Brushing":
            price = 150
        elif service == "Puppy Introduction":
            price = 350
        elif service == "De-shedding Treatment":
            price = 700
        elif service == "Flea & Tick Treatment":
            price = 650

        summary = f"{service} - {c['dog_name']} ({c['name']})"
        description = (
            f"Customer: {c['name']}\n"
            f"Phone: {c['phone']}\n"
            f"Dog: {c['dog_name']} ({c['breed']})\n"
            f"Service: {service}\n"
            f"Price: ₹{price}\n"
            f"Booked via: AI Receptionist (seeded)"
        )

        result = calendar.create_event(
            groomer_name=groomer,
            summary=summary,
            start_dt=start_dt.isoformat(),
            end_dt=end_dt.isoformat(),
            description=description,
        )

        status = "OK" if result.get("success") else f"FAILED: {result.get('error')}"
        print(f"  {day} {time_str} {groomer:8s} {service:25s} {c['dog_name']:8s} -> {status}")

    print(f"\nSeeded {len(appointments)} appointments and {len(contacts)} contacts.")
    print("\nKey test scenarios:")
    print(f"  - {day1} 10:00 AM is FULLY BOOKED (all 4 groomers)")
    print(f"  - Priya (9876543210) has appointments to test reschedule")
    print(f"  - Priya has 2 dogs (Max and Milo) to test multi-dog lookup")
    print(f"  - Mix of 30-min and 60-min services across all groomers")


if __name__ == "__main__":
    main()
