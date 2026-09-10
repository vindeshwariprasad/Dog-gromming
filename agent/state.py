from dataclasses import dataclass, field
import uuid


@dataclass
class SessionState:
    """Tracks what data has been collected during a conversation."""

    conversation_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # Caller identification
    phone: str | None = None
    name: str | None = None
    identified: bool = False
    contact_records: list[dict] = field(default_factory=list)

    # Current booking data being collected
    service: str | None = None
    service_duration: int | None = None
    service_price: int | None = None
    dog_name: str | None = None
    dog_breed: str | None = None
    dog_size: str | None = None
    preferred_date: str | None = None
    preferred_time: str | None = None
    groomer: str | None = None
    booking_confirmed: bool = False

    # Intent tracking
    current_intent: str | None = None
    intents_completed: list[str] = field(default_factory=list)

    # For reschedule/cancel — the existing event being modified
    existing_event: dict | None = None

    # Call summary for logging
    call_summary_parts: list[str] = field(default_factory=list)

    # Track booked event IDs to prevent duplicate bookings (especially in voice)
    booked_event_ids: list[str] = field(default_factory=list)

    # Cached appointments from get_upcoming_appointments (used to resolve event IDs)
    fetched_appointments: list[dict] = field(default_factory=list)

    # Phase 2: caller ID from Vapi
    caller_id_from_vapi: str | None = None

    def has_all_booking_fields(self) -> bool:
        """Check if all required fields for booking are collected."""
        return all([
            self.phone,
            self.name,
            self.service,
            self.service_duration is not None,
            self.dog_name,
            self.dog_breed,
            self.preferred_date,
            self.preferred_time,
            self.groomer,
        ])

    def get_call_summary(self) -> str:
        if self.call_summary_parts:
            return " | ".join(self.call_summary_parts)
        return "No actions taken"

    def reset_booking_data(self):
        """Reset booking-specific fields for a new intent."""
        self.service = None
        self.service_duration = None
        self.service_price = None
        self.preferred_date = None
        self.preferred_time = None
        self.groomer = None
        self.booking_confirmed = False
        self.existing_event = None
        self.current_intent = None
