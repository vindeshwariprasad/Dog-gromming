import logging
from functools import lru_cache
from google.oauth2.service_account import Credentials

from config.settings import GOOGLE_SERVICE_ACCOUNT_FILE

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/spreadsheets",
]


@lru_cache(maxsize=1)
def get_google_credentials() -> Credentials:
    """Load and cache Google service account credentials."""
    logger.info("Loading Google service account credentials from %s", GOOGLE_SERVICE_ACCOUNT_FILE)
    credentials = Credentials.from_service_account_file(
        GOOGLE_SERVICE_ACCOUNT_FILE,
        scopes=SCOPES,
    )
    return credentials
