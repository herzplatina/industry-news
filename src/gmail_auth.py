"""Shared Google OAuth for Gmail — one credential for both reading and sending.

Reading newsletters (``gmail.readonly``) and sending the digest (``gmail.send``)
use the same OAuth token, so there is no separate SMTP app password to manage or
let expire. The access token is refreshed automatically from the stored refresh
token on every run.
"""

import logging
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

logger = logging.getLogger(__name__)

# Both scopes on one token: read newsletters AND send the digest email.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "token.json"


def get_credentials() -> Credentials:
    """Return valid OAuth credentials, refreshing or minting the token as needed."""
    load_dotenv()
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"credentials.json not found at {CREDENTIALS_PATH}. "
                    "Download it from Google Cloud Console."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return creds


def get_gmail_service():
    """Build an authenticated Gmail API service client."""
    from googleapiclient.discovery import build

    return build("gmail", "v1", credentials=get_credentials())
