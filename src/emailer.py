import base64
import logging
import os
from datetime import datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import markdown
from dotenv import load_dotenv
from googleapiclient.discovery import build
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

from src.gmail_auth import get_credentials

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_PT = timezone(timedelta(hours=-7))


def _render_html(markdown_content: str) -> str:
    html_body = markdown.markdown(markdown_content, extensions=["extra", "sane_lists"])
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("digest.html")
    return template.render(
        date=datetime.now().strftime("%A, %B %d, %Y"),
        content=Markup(html_body),
    )


def _prepare_and_send(
    markdown_content: str,
    subject: str,
    preview_path: Path,
    dry_run: bool,
    raw_sources: str | None,
) -> bool:
    full_markdown = markdown_content
    if raw_sources:
        full_markdown += "\n\n---\n\n# Raw Sources\n\n" + raw_sources

    html = _render_html(full_markdown)
    preview_path.write_text(html)

    if dry_run:
        logger.info("Dry run: HTML written to %s", preview_path)
        return True

    recipient = os.environ["DIGEST_RECIPIENT_EMAIL"]

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["To"] = recipient
    sender = os.environ.get("GMAIL_SENDER_EMAIL")
    if sender:
        msg["From"] = sender
    msg.attach(MIMEText(full_markdown, "plain"))
    msg.attach(MIMEText(html, "html"))

    # Send via the Gmail API using the same OAuth credential used for reading.
    service = build("gmail", "v1", credentials=get_credentials())
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()

    logger.info("Sent '%s' to %s", subject, recipient)
    return True


def send_digest(
    markdown_content: str,
    dry_run: bool = False,
    raw_sources: str | None = None,
) -> bool:
    load_dotenv()
    timestamp = datetime.now(_PT).strftime("%b %d, %Y %I:%M %p")
    subject = f"Industry News Digest — {timestamp} PT"
    return _prepare_and_send(
        markdown_content, subject, Path("digest_preview.html"), dry_run, raw_sources
    )


def send_arxiv_digest(
    markdown_content: str,
    dry_run: bool = False,
) -> bool:
    load_dotenv()
    timestamp = datetime.now(_PT).strftime("%b %d, %Y")
    subject = f"AI Research Digest — {timestamp}"
    return _prepare_and_send(
        markdown_content, subject, Path("arxiv_digest_preview.html"), dry_run, None
    )


def send_twitter_digest(
    markdown_content: str,
    dry_run: bool = False,
    raw_sources: str | None = None,
) -> bool:
    load_dotenv()
    timestamp = datetime.now(_PT).strftime("%b %d, %Y %I:%M %p")
    subject = f"Twitter Digest — {timestamp} PT"
    return _prepare_and_send(
        markdown_content,
        subject,
        Path("twitter_digest_preview.html"),
        dry_run,
        raw_sources,
    )
