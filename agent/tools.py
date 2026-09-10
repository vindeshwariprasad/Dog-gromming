import logging
import re
from datetime import datetime, date, timedelta
from zoneinfo import ZoneInfo

from config.settings import TIMEZONE, MAX_BOOKING_WEEKS_AHEAD
from config.shop_data import (
    get_service_by_name, get_service_price, get_service_duration,
    GROOMERS, LARGE_BREED_WEIGHT_KG,
)
from config.breed_mapping import get_dog_size, is_large_breed
from integrations.google_calendar import CalendarClient
from integrations.google_sheets import SheetsClient

logger = logging.getLogger(__name__)

IST = ZoneInfo(TIMEZONE)

VALID_GROOMER_NAMES = {g["name"].lower() for g in GROOMERS}
VALID_DOG_SIZES = {"small", "medium", "large"}


def _validate_groomer(name: str) -> str | None:
    """Return normalized groomer name or None if invalid."""
    for g in GROOMERS:
        if g["name"].lower() == name.lower():
            return g["name"]
    return None


def _validate_dog_size(size: str) -> str | None:
    """Return normalized dog size or None if invalid."""
    if size.lower() in VALID_DOG_SIZES:
        return size.capitalize()
    return None


# --- Gemini Function Declarations ---

TOOL_DECLARATIONS = [
    {
        "name": "check_availability",
        "description": (
            "Check available time slots for a specific service on a given date. "
            "Returns available slots per groomer. Optionally filter by a preferred groomer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {
                    "type": "string",
                    "description": "Name of the service (e.g., 'Full Groom', 'Bath & Brush')",
                },
                "date": {
                    "type": "string",
                    "description": "The date to check in YYYY-MM-DD format",
                },
                "preferred_groomer": {
                    "type": "string",
                    "description": "Optional: name of a preferred groomer (Sarah, Mike, Jessica, Carlos)",
                },
            },
            "required": ["service_name", "date"],
        },
    },
    {
        "name": "book_appointment",
        "description": (
            "Book an appointment after the caller has confirmed all details. "
            "All fields are required. Only call this after explicit caller confirmation."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "service_name": {"type": "string", "description": "Service name"},
                "date": {"type": "string", "description": "Date in YYYY-MM-DD format"},
                "time": {"type": "string", "description": "Start time in HH:MM format (24h)"},
                "groomer_name": {"type": "string", "description": "Groomer name"},
                "customer_name": {"type": "string", "description": "Customer name"},
                "phone": {"type": "string", "description": "10-digit phone number"},
                "dog_name": {"type": "string", "description": "Dog's name"},
                "dog_breed": {"type": "string", "description": "Dog's breed"},
                "dog_size": {"type": "string", "description": "Small, Medium, or Large"},
                "notes": {"type": "string", "description": "Optional booking notes"},
            },
            "required": [
                "service_name", "date", "time", "groomer_name",
                "customer_name", "phone", "dog_name", "dog_breed", "dog_size",
            ],
        },
    },
    {
        "name": "reschedule_appointment",
        "description": (
            "Reschedule an existing appointment. You MUST use the exact event_id and groomer_name "
            "returned by get_upcoming_appointments. NEVER make up or guess event IDs."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "old_event_id": {"type": "string", "description": "The EXACT event_id string returned by get_upcoming_appointments (e.g. 'abc123def456'). NEVER fabricate this."},
                "old_groomer_name": {"type": "string", "description": "The EXACT groomer_name returned by get_upcoming_appointments"},
                "new_date": {"type": "string", "description": "New date in YYYY-MM-DD format"},
                "new_time": {"type": "string", "description": "New start time in HH:MM format"},
                "new_groomer_name": {"type": "string", "description": "Groomer for the new slot"},
                "service_name": {"type": "string", "description": "Service name"},
                "customer_name": {"type": "string", "description": "Customer name"},
                "phone": {"type": "string", "description": "Phone number"},
                "dog_name": {"type": "string", "description": "Dog name"},
                "dog_breed": {"type": "string", "description": "Dog breed"},
                "dog_size": {"type": "string", "description": "Dog size category"},
            },
            "required": [
                "old_event_id", "old_groomer_name", "new_date", "new_time",
                "new_groomer_name", "service_name", "customer_name", "phone",
                "dog_name", "dog_breed", "dog_size",
            ],
        },
    },
    {
        "name": "cancel_appointment",
        "description": "Cancel an existing appointment. You MUST use the exact event_id and groomer_name returned by get_upcoming_appointments. NEVER make up or guess event IDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {"type": "string", "description": "The EXACT event_id string returned by get_upcoming_appointments (e.g. 'abc123def456'). NEVER fabricate this."},
                "groomer_name": {"type": "string", "description": "The EXACT groomer_name returned by get_upcoming_appointments"},
            },
            "required": ["event_id", "groomer_name"],
        },
    },
    {
        "name": "lookup_contact",
        "description": (
            "Look up a caller in the contacts database by their 10-digit phone number. "
            "Returns their name, dog info, and vaccination status."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "10-digit phone number"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "register_contact",
        "description": "Register a new caller in the contacts database.",
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "10-digit phone number"},
                "name": {"type": "string", "description": "Caller's name"},
                "dog_name": {"type": "string", "description": "Dog's name"},
                "dog_breed": {"type": "string", "description": "Dog's breed"},
                "dog_size": {"type": "string", "description": "Small, Medium, or Large"},
            },
            "required": ["phone", "name", "dog_name", "dog_breed", "dog_size"],
        },
    },
    {
        "name": "get_upcoming_appointments",
        "description": (
            "Get a caller's upcoming appointments across all groomers. "
            "Use this for reschedule, cancel, or running-late intents."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "phone": {"type": "string", "description": "10-digit phone number"},
            },
            "required": ["phone"],
        },
    },
    {
        "name": "escalate_to_staff",
        "description": (
            "Escalate the call to a human staff member. Use this for complaints, refund requests, "
            "medical concerns, aggressive dog consultations, or any issue the AI cannot resolve."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Why the call is being escalated (e.g. 'Complaint about grooming quality', 'Refund request')"},
                "phone": {"type": "string", "description": "Caller's phone number (if known)"},
                "caller_name": {"type": "string", "description": "Caller's name (if known)"},
            },
            "required": ["reason"],
        },
    },
]


# --- Tool Execution ---

class ToolExecutor:
    def __init__(self, calendar_client: CalendarClient, sheets_client: SheetsClient):
        self.calendar = calendar_client
        self.sheets = sheets_client

    def execute(self, tool_name: str, args: dict) -> dict:
        """Dispatch and execute a tool call. Returns a result dict."""
        handler = getattr(self, f"_exec_{tool_name}", None)
        if handler is None:
            logger.warning("Unknown tool: %s", tool_name)
            return {"error": f"Unknown tool: {tool_name}"}

        try:
            logger.info("Executing tool: %s with args: %s", tool_name, args)
            result = handler(args)
            logger.info("Tool %s result: %s", tool_name, result)
            return result
        except Exception as e:
            logger.exception("Tool %s failed", tool_name)
            return {"error": f"Tool execution failed: {str(e)}"}

    def _exec_check_availability(self, args: dict) -> dict:
        service_name = args.get("service_name", "")
        date_str = args.get("date", "")
        preferred_groomer = args.get("preferred_groomer")

        # Validate preferred groomer (if provided)
        if preferred_groomer:
            normalized_groomer = _validate_groomer(preferred_groomer)
            if not normalized_groomer:
                valid = ", ".join(g["name"] for g in GROOMERS)
                return {"error": f"Unknown groomer: {preferred_groomer}. Valid groomers: {valid}."}
            preferred_groomer = normalized_groomer

        service = get_service_by_name(service_name)
        if not service:
            return {"error": f"Unknown service: {service_name}. Available: Bath & Brush, Nail Trim & File, Teeth Brushing, Puppy Introduction, Full Groom, De-shedding Treatment, Flea & Tick Treatment."}

        try:
            target_date = date.fromisoformat(date_str)
        except (ValueError, TypeError):
            return {"error": f"Invalid date format: {date_str}. Use YYYY-MM-DD."}

        # Validate date range
        today = datetime.now(IST).date()
        if target_date < today:
            return {"error": "Cannot book in the past."}
        max_date = today + timedelta(weeks=MAX_BOOKING_WEEKS_AHEAD)
        if target_date > max_date:
            return {"error": f"Cannot book more than {MAX_BOOKING_WEEKS_AHEAD} weeks ahead. Latest: {max_date.isoformat()}."}

        available = self.calendar.get_available_slots(
            target_date, service["duration_minutes"], preferred_groomer
        )

        if not available:
            return {
                "available": False,
                "message": f"No available slots on {target_date.strftime('%A, %B %d')}. The shop may be closed or fully booked.",
                "slots": {},
            }

        # Format for the LLM
        formatted = {}
        for groomer, slots in available.items():
            formatted[groomer] = [s["start"] for s in slots]

        return {
            "available": True,
            "date": date_str,
            "service": service_name,
            "duration_minutes": service["duration_minutes"],
            "slots_by_groomer": formatted,
        }

    def _exec_book_appointment(self, args: dict) -> dict:
        service_name = args.get("service_name", "")
        date_str = args.get("date", "")
        time_str = args.get("time", "")
        groomer_name = args.get("groomer_name", "")
        customer_name = args.get("customer_name", "")
        phone = args.get("phone", "")
        dog_name = args.get("dog_name", "")
        dog_breed = args.get("dog_breed", "")
        dog_size = args.get("dog_size", "")
        notes = args.get("notes", "")

        # Validate phone
        if not re.match(r"^\d{10}$", phone):
            return {"error": f"Invalid phone number: {phone}. Must be 10 digits."}

        # Validate groomer
        normalized_groomer = _validate_groomer(groomer_name)
        if not normalized_groomer:
            valid = ", ".join(g["name"] for g in GROOMERS)
            return {"error": f"Unknown groomer: {groomer_name}. Valid groomers: {valid}."}
        groomer_name = normalized_groomer

        # Validate dog size
        normalized_size = _validate_dog_size(dog_size)
        if not normalized_size:
            return {"error": f"Invalid dog size: {dog_size}. Must be Small, Medium, or Large."}
        dog_size = normalized_size

        service = get_service_by_name(service_name)
        if not service:
            return {"error": f"Unknown service: {service_name}"}

        duration = service["duration_minutes"]
        price = get_service_price(service_name, dog_size)

        # Build datetime
        try:
            target_date = date.fromisoformat(date_str)
            hour, minute = map(int, time_str.split(":"))
            start_dt = datetime(target_date.year, target_date.month, target_date.day,
                                hour, minute, tzinfo=IST)
            end_dt = start_dt + timedelta(minutes=duration)
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid date/time: {e}"}

        # Pre-booking availability check (avoids create→conflict→delete loop)
        has_conflict = self.calendar.check_conflict(
            groomer_name, start_dt.isoformat(), end_dt.isoformat()
        )
        if has_conflict:
            return {
                "success": False,
                "error": "That slot is no longer available. Please check availability again.",
            }

        # Build event
        summary = f"{service_name} - {dog_name} ({customer_name})"
        description = (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Dog: {dog_name} ({dog_breed})\n"
            f"Service: {service_name}\n"
            f"Price: ₹{price or '?'}\n"
            f"Booked via: AI Receptionist"
        )
        if notes:
            description += f"\nNotes: {notes}"

        # Create event
        result = self.calendar.create_event(
            groomer_name=groomer_name,
            summary=summary,
            start_dt=start_dt.isoformat(),
            end_dt=end_dt.isoformat(),
            description=description,
        )

        if not result.get("success"):
            return {"success": False, "error": result.get("error", "Failed to create event")}

        event_id = result["event_id"]

        # Post-booking conflict check
        has_conflict = self.calendar.check_conflict(
            groomer_name, start_dt.isoformat(), end_dt.isoformat(), exclude_event_id=event_id
        )
        if has_conflict:
            # Delete our event — someone else booked it simultaneously
            self.calendar.delete_event(groomer_name, event_id)
            return {
                "success": False,
                "error": "That slot was just taken by another booking. Please check availability again.",
            }

        # Register or update contact
        self.sheets.register_contact(
            phone=phone, name=customer_name, dog_name=dog_name,
            dog_breed=dog_breed, dog_size=dog_size,
        )
        self.sheets.update_contact_last_date(phone, dog_name)

        return {
            "success": True,
            "event_id": event_id,
            "groomer": groomer_name,
            "date": date_str,
            "time": time_str,
            "end_time": end_dt.strftime("%H:%M"),
            "service": service_name,
            "price": price,
            "dog_name": dog_name,
            "customer_name": customer_name,
        }

    def _exec_reschedule_appointment(self, args: dict) -> dict:
        old_event_id = args.get("old_event_id", "")
        old_groomer = args.get("old_groomer_name", "")
        new_date_str = args.get("new_date", "")
        new_time_str = args.get("new_time", "")
        new_groomer = args.get("new_groomer_name", "")
        service_name = args.get("service_name", "")
        customer_name = args.get("customer_name", "")
        phone = args.get("phone", "")
        dog_name = args.get("dog_name", "")
        dog_breed = args.get("dog_breed", "")
        dog_size = args.get("dog_size", "")

        # Validate new groomer
        normalized_groomer = _validate_groomer(new_groomer)
        if not normalized_groomer:
            valid = ", ".join(g["name"] for g in GROOMERS)
            return {"error": f"Unknown groomer: {new_groomer}. Valid groomers: {valid}."}
        new_groomer = normalized_groomer

        # Validate dog size
        normalized_size = _validate_dog_size(dog_size)
        if not normalized_size:
            return {"error": f"Invalid dog size: {dog_size}. Must be Small, Medium, or Large."}
        dog_size = normalized_size

        service = get_service_by_name(service_name)
        if not service:
            return {"error": f"Unknown service: {service_name}"}

        duration = service["duration_minutes"]
        price = get_service_price(service_name, dog_size)

        try:
            target_date = date.fromisoformat(new_date_str)
            hour, minute = map(int, new_time_str.split(":"))
            start_dt = datetime(target_date.year, target_date.month, target_date.day,
                                hour, minute, tzinfo=IST)
            end_dt = start_dt + timedelta(minutes=duration)
        except (ValueError, TypeError) as e:
            return {"error": f"Invalid date/time: {e}"}

        # Create new event FIRST
        summary = f"{service_name} - {dog_name} ({customer_name})"
        description = (
            f"Customer: {customer_name}\n"
            f"Phone: {phone}\n"
            f"Dog: {dog_name} ({dog_breed})\n"
            f"Service: {service_name}\n"
            f"Price: ₹{price or '?'}\n"
            f"Booked via: AI Receptionist (rescheduled)"
        )

        create_result = self.calendar.create_event(
            groomer_name=new_groomer,
            summary=summary,
            start_dt=start_dt.isoformat(),
            end_dt=end_dt.isoformat(),
            description=description,
        )

        if not create_result.get("success"):
            return {"success": False, "error": "Failed to create new appointment. Original kept."}

        new_event_id = create_result["event_id"]

        # Conflict check on new slot
        has_conflict = self.calendar.check_conflict(
            new_groomer, start_dt.isoformat(), end_dt.isoformat(), exclude_event_id=new_event_id
        )
        if has_conflict:
            self.calendar.delete_event(new_groomer, new_event_id)
            return {"success": False, "error": "New slot was just taken. Original appointment kept."}

        # Delete old event
        delete_result = self.calendar.delete_event(old_groomer, old_event_id)
        if not delete_result.get("success"):
            # Roll back: delete the newly created event so we don't end up with duplicates
            logger.error("Failed to delete old event %s — rolling back new event %s", old_event_id, new_event_id)
            self.calendar.delete_event(new_groomer, new_event_id)
            return {
                "success": False,
                "error": (
                    f"Could not remove the original appointment (event_id: {old_event_id}, "
                    f"groomer: {old_groomer}). Reschedule aborted. "
                    "Please ask the customer to confirm which appointment to reschedule "
                    "and use get_upcoming_appointments to get the correct event details."
                ),
            }

        return {
            "success": True,
            "new_event_id": new_event_id,
            "new_groomer": new_groomer,
            "new_date": new_date_str,
            "new_time": new_time_str,
            "new_end_time": end_dt.strftime("%H:%M"),
            "service": service_name,
            "price": price,
        }

    def _exec_cancel_appointment(self, args: dict) -> dict:
        event_id = args.get("event_id", "")
        groomer_name = args.get("groomer_name", "")

        # Validate groomer
        normalized_groomer = _validate_groomer(groomer_name)
        if not normalized_groomer:
            valid = ", ".join(g["name"] for g in GROOMERS)
            return {"error": f"Unknown groomer: {groomer_name}. Valid groomers: {valid}."}
        groomer_name = normalized_groomer

        result = self.calendar.delete_event(groomer_name, event_id)
        return result

    def _exec_lookup_contact(self, args: dict) -> dict:
        phone = args.get("phone", "")
        phone = re.sub(r"\D", "", phone)  # Strip non-digits
        if len(phone) > 10:
            phone = phone[-10:]  # Take last 10 digits (strip country code)

        if len(phone) != 10:
            return {"error": f"Invalid phone: {phone}. Need 10 digits."}

        contacts = self.sheets.lookup_contact(phone)
        if not contacts:
            return {"found": False, "phone": phone}

        return {
            "found": True,
            "phone": phone,
            "contacts": contacts,
        }

    def _exec_register_contact(self, args: dict) -> dict:
        phone = re.sub(r"\D", "", args.get("phone", ""))
        if len(phone) > 10:
            phone = phone[-10:]

        name = args.get("name", "")
        dog_name = args.get("dog_name", "")
        dog_breed = args.get("dog_breed", "")
        dog_size = args.get("dog_size", "")

        if not dog_size:
            dog_size = get_dog_size(dog_breed) or "Unknown"

        result = self.sheets.register_contact(
            phone=phone, name=name, dog_name=dog_name,
            dog_breed=dog_breed, dog_size=dog_size,
        )
        return result

    def _exec_get_upcoming_appointments(self, args: dict) -> dict:
        phone = re.sub(r"\D", "", args.get("phone", ""))
        if len(phone) > 10:
            phone = phone[-10:]

        events = self.calendar.find_events_by_phone(phone)
        if not events:
            return {"found": False, "phone": phone, "message": "No upcoming appointments found."}

        return {
            "found": True,
            "phone": phone,
            "appointments": events,
        }

    def _exec_escalate_to_staff(self, args: dict) -> dict:
        reason = args.get("reason", "Unknown reason")
        phone = args.get("phone", "")
        caller_name = args.get("caller_name", "")
        logger.info("Escalation: %s (phone: %s, name: %s)", reason, phone, caller_name)
        return {
            "success": True,
            "message": "A staff member will call back shortly.",
            "reason": reason,
        }

