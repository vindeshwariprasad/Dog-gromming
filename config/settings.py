import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# Google
GOOGLE_SERVICE_ACCOUNT_FILE = os.getenv(
    "GOOGLE_SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "service_account.json"),
)
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID", "")

# Groomer calendar IDs — set in .env as comma-separated "name:cal_id" pairs
# e.g. GROOMER_CALENDARS="Sarah:abc123,Mike:def456,Jessica:ghi789,Carlos:jkl012"
_raw_calendars = os.getenv("GROOMER_CALENDARS", "")
GROOMER_CALENDAR_IDS: dict[str, str] = {}
if _raw_calendars:
    for pair in _raw_calendars.split(","):
        name, cal_id = pair.strip().split(":", 1)
        GROOMER_CALENDAR_IDS[name.strip()] = cal_id.strip()

# Gemini
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Vapi
VAPI_SECRET = os.getenv("VAPI_SECRET", "")
VAPI_TRANSFER_NUMBER = os.getenv("VAPI_TRANSFER_NUMBER", "")

# Timezone
TIMEZONE = "Asia/Kolkata"

# Booking constraints
MAX_BOOKING_WEEKS_AHEAD = 4
