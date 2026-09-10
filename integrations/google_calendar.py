import logging
from datetime import datetime, date, timedelta, time
from zoneinfo import ZoneInfo

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.service_account import Credentials

from config.settings import GROOMER_CALENDAR_IDS, TIMEZONE
from config.shop_data import SHOP_HOURS, GROOMERS

logger = logging.getLogger(__name__)

IST = ZoneInfo(TIMEZONE)

# Day name mapping for SHOP_HOURS lookup
_DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class CalendarClient:
    def __init__(self, credentials: Credentials):
        self.service = build("calendar", "v3", credentials=credentials)
        self.calendar_ids = GROOMER_CALENDAR_IDS

    def _groomer_calendar_id(self, groomer_name: str) -> str | None:
        return self.calendar_ids.get(groomer_name)

    def _get_shop_hours_for_date(self, d: date) -> tuple[time, time] | None:
        """Return (open_time, close_time) for a date, or None if closed."""
        day_name = _DAY_NAMES[d.weekday()]
        hours = SHOP_HOURS.get(day_name)
        if hours is None:
            return None
        open_h, open_m = map(int, hours[0].split(":"))
        close_h, close_m = map(int, hours[1].split(":"))
        return time(open_h, open_m), time(close_h, close_m)

    def get_available_slots(
        self, target_date: date, service_duration_minutes: int, preferred_groomer: str | None = None
    ) -> dict[str, list[dict]]:
        """
        Return available time slots per groomer for a given date and service duration.

        Returns:
            {groomer_name: [{"start": "10:00", "end": "10:30"}, ...]}
        """
        hours = self._get_shop_hours_for_date(target_date)
        if hours is None:
            return {}

        open_time, close_time = hours

        # Build the time range for freebusy query
        day_start = datetime.combine(target_date, open_time, tzinfo=IST)
        day_end = datetime.combine(target_date, close_time, tzinfo=IST)

        # Determine which groomers to check
        if preferred_groomer and preferred_groomer in self.calendar_ids:
            groomers_to_check = {preferred_groomer: self.calendar_ids[preferred_groomer]}
        else:
            groomers_to_check = self.calendar_ids

        # Batch freebusy query for all relevant groomers
        items = [{"id": cal_id} for cal_id in groomers_to_check.values()]
        try:
            freebusy_result = (
                self.service.freebusy()
                .query(
                    body={
                        "timeMin": day_start.isoformat(),
                        "timeMax": day_end.isoformat(),
                        "timeZone": TIMEZONE,
                        "items": items,
                    }
                )
                .execute()
            )
        except HttpError as e:
            logger.error("Freebusy query failed: %s", e)
            return {}

        calendars_busy = freebusy_result.get("calendars", {})

        # Generate all possible slot starts on the half-hour grid
        slot_starts = []
        current = day_start
        while current + timedelta(minutes=service_duration_minutes) <= day_end:
            slot_starts.append(current)
            current += timedelta(minutes=30)

        # For each groomer, find free slots
        available = {}
        for groomer_name, cal_id in groomers_to_check.items():
            busy_periods = calendars_busy.get(cal_id, {}).get("busy", [])
            busy_ranges = []
            for bp in busy_periods:
                bs = datetime.fromisoformat(bp["start"]).astimezone(IST)
                be = datetime.fromisoformat(bp["end"]).astimezone(IST)
                busy_ranges.append((bs, be))

            free_slots = []
            for slot_start in slot_starts:
                slot_end = slot_start + timedelta(minutes=service_duration_minutes)
                # Check if this slot overlaps with any busy period
                is_free = True
                for bs, be in busy_ranges:
                    if slot_start < be and slot_end > bs:
                        is_free = False
                        break
                if is_free:
                    free_slots.append({
                        "start": slot_start.strftime("%H:%M"),
                        "end": slot_end.strftime("%H:%M"),
                        "start_dt": slot_start.isoformat(),
                        "end_dt": slot_end.isoformat(),
                    })

            if free_slots:
                available[groomer_name] = free_slots

        return available

    def create_event(
        self,
        groomer_name: str,
        summary: str,
        start_dt: str,
        end_dt: str,
        description: str,
    ) -> dict:
        """
        Create a calendar event on the specified groomer's calendar.

        Returns:
            {"success": True, "event_id": "...", "calendar_id": "..."} or
            {"success": False, "error": "..."}
        """
        cal_id = self._groomer_calendar_id(groomer_name)
        if not cal_id:
            return {"success": False, "error": f"Unknown groomer: {groomer_name}"}

        event_body = {
            "summary": summary,
            "description": description,
            "start": {"dateTime": start_dt, "timeZone": TIMEZONE},
            "end": {"dateTime": end_dt, "timeZone": TIMEZONE},
        }

        try:
            event = (
                self.service.events()
                .insert(calendarId=cal_id, body=event_body)
                .execute()
            )
            event_id = event["id"]
            logger.info("Created event %s on calendar %s (%s)", event_id, groomer_name, cal_id)
            return {"success": True, "event_id": event_id, "calendar_id": cal_id}
        except HttpError as e:
            logger.error("Failed to create event: %s", e)
            return {"success": False, "error": str(e)}

    def delete_event(self, groomer_name: str, event_id: str) -> dict:
        """Delete a calendar event."""
        cal_id = self._groomer_calendar_id(groomer_name)
        if not cal_id:
            return {"success": False, "error": f"Unknown groomer: {groomer_name}"}

        try:
            self.service.events().delete(calendarId=cal_id, eventId=event_id).execute()
            logger.info("Deleted event %s from calendar %s", event_id, groomer_name)
            return {"success": True}
        except HttpError as e:
            logger.error("Failed to delete event: %s", e)
            return {"success": False, "error": str(e)}

    def check_conflict(
        self, groomer_name: str, start_dt: str, end_dt: str, exclude_event_id: str | None = None
    ) -> bool:
        """
        Check if there's a conflicting event on the groomer's calendar.
        Returns True if there IS a conflict.
        """
        cal_id = self._groomer_calendar_id(groomer_name)
        if not cal_id:
            return False

        try:
            events_result = (
                self.service.events()
                .list(
                    calendarId=cal_id,
                    timeMin=start_dt,
                    timeMax=end_dt,
                    singleEvents=True,
                )
                .execute()
            )
            events = events_result.get("items", [])
            # Exclude the event we just created (if checking post-booking)
            if exclude_event_id:
                events = [e for e in events if e["id"] != exclude_event_id]
            return len(events) > 0
        except HttpError as e:
            logger.error("Conflict check failed: %s", e)
            return False  # Fail open — don't block booking on check failure

    def find_events_by_phone(
        self, phone: str, time_min: datetime | None = None
    ) -> list[dict]:
        """
        Search all groomer calendars for events containing a phone number.
        Returns list of {groomer_name, event_id, summary, start, end, description}.
        """
        if time_min is None:
            time_min = datetime.now(IST)

        results = []
        for groomer_name, cal_id in self.calendar_ids.items():
            try:
                events_result = (
                    self.service.events()
                    .list(
                        calendarId=cal_id,
                        timeMin=time_min.isoformat(),
                        q=phone,
                        singleEvents=True,
                        orderBy="startTime",
                        maxResults=10,
                    )
                    .execute()
                )
                for event in events_result.get("items", []):
                    start = event.get("start", {}).get("dateTime", "")
                    end = event.get("end", {}).get("dateTime", "")
                    results.append({
                        "groomer_name": groomer_name,
                        "event_id": event["id"],
                        "summary": event.get("summary", ""),
                        "start": start,
                        "end": end,
                        "description": event.get("description", ""),
                    })
            except HttpError as e:
                logger.error("Event search failed for %s: %s", groomer_name, e)
                continue

        # Sort by start time
        results.sort(key=lambda x: x["start"])
        return results
