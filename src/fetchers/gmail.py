import base64
import logging
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

import yaml
from bs4 import BeautifulSoup
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH = PROJECT_ROOT / "token.json"
SENDERS_PATH = PROJECT_ROOT / "config" / "senders.yaml"


def _load_senders() -> list[dict]:
    with open(SENDERS_PATH) as f:
        return yaml.safe_load(f)["senders"]


def _get_gmail_service():
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
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def _build_query(senders: list[dict], hours: int) -> str:
    emails = [s["email"] for s in senders if s.get("email")]
    names = [s["name"] for s in senders if s.get("name") and not s.get("email")]

    from_parts = []
    for email in emails:
        from_parts.append(f"from:{email}")
    for name in names:
        from_parts.append(f'from:"{name}"')

    from_clause = " OR ".join(from_parts)
    return f"({from_clause}) newer_than:{max(hours // 24, 1)}d"


def _decode_body(payload: dict) -> tuple[str, str]:
    """Extract body text and HTML from a message payload."""
    body_text = ""
    body_html = ""

    if payload.get("mimeType", "").startswith("multipart/"):
        for part in payload.get("parts", []):
            t, h = _decode_body(part)
            if t:
                body_text = t
            if h:
                body_html = h
    else:
        data = payload.get("body", {}).get("data", "")
        if data:
            decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if payload.get("mimeType") == "text/plain":
                body_text = decoded
            elif payload.get("mimeType") == "text/html":
                body_html = decoded

    return body_text, body_html


import re
from urllib.parse import urlparse, parse_qs, unquote


def _extract_urls(html: str) -> list[str]:
    """Extract meaningful article URLs from newsletter HTML."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    seen = set()

    for a in soup.find_all("a", href=True):
        url = a["href"]

        # Unwrap Substack/Beehiiv redirect wrappers
        if "substack.com/redirect" in url or "t.co/" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            if "url" in qs:
                url = unquote(qs["url"][0])

        # Skip non-article URLs
        if any(skip in url for skip in [
            "unsubscribe", "manage-preferences", "email-settings",
            "mailto:", "javascript:", "#", "beacon", "pixel",
            "list-manage.com", "mailchimp.com",
        ]):
            continue

        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            continue
        if not parsed.netloc:
            continue

        if url not in seen:
            seen.add(url)
            urls.append(url)

    return urls[:30]


_BOILERPLATE_PATTERNS = re.compile(
    r"^View this post on the web at https?://\S+\s*",
    re.MULTILINE,
)


def _clean_body(text: str) -> str:
    """Remove email boilerplate and clean up newsletter body text."""
    # Strip Substack/Beehiiv "view on web" header
    text = _BOILERPLATE_PATTERNS.sub("", text).strip()
    # Strip long redirect URLs inline (they add noise without value)
    text = re.sub(r"\[\s*https://substack\.com/redirect/\S+\s*\]", "", text)
    return text


def _truncate(text: str, max_chars: int = 5000) -> str:
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "..."


def fetch_gmail_newsletters(hours: int = 24) -> list[dict]:
    senders = _load_senders()
    service = _get_gmail_service()
    query = _build_query(senders, hours)
    logger.info("Gmail query: %s", query)

    newsletters = []
    try:
        response = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
        message_ids = [m["id"] for m in response.get("messages", [])]
        logger.info("Found %d messages matching query", len(message_ids))

        for msg_id in message_ids:
            msg = service.users().messages().get(userId="me", id=msg_id, format="full").execute()
            headers = {h["name"].lower(): h["value"] for h in msg["payload"].get("headers", [])}

            body_text, body_html = _decode_body(msg["payload"])

            if body_html and not body_text:
                body_text = BeautifulSoup(body_html, "html.parser").get_text(separator=" ", strip=True)

            urls = _extract_urls(body_html) if body_html else []

            newsletters.append({
                "subject": headers.get("subject", "No Subject"),
                "sender": headers.get("from", "Unknown"),
                "date": headers.get("date", "Unknown"),
                "body_text": _truncate(_clean_body(body_text)),
                "urls": urls,
            })
    except Exception:
        logger.exception("Failed to fetch Gmail newsletters")

    return newsletters


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    print("Fetching Gmail newsletters (last 72 hours for testing)...\n")

    try:
        newsletters = fetch_gmail_newsletters(hours=72)
        print(f"Found {len(newsletters)} newsletters:\n")
        for n in newsletters:
            print(f"  From: {n['sender']}")
            print(f"  Subject: {n['subject']}")
            print(f"  Date: {n['date']}")
            print(f"  Body preview: {n['body_text'][:200]}...")
            print()
    except FileNotFoundError as e:
        print(f"Setup required: {e}")
    except Exception as e:
        print(f"Error: {e}")
