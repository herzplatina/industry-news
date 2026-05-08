import logging
import os
import smtplib
import sys
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import markdown
from dotenv import load_dotenv
from jinja2 import Environment, FileSystemLoader
from markupsafe import Markup

logger = logging.getLogger(__name__)

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _render_html(markdown_content: str) -> str:
    html_body = markdown.markdown(markdown_content, extensions=["extra", "sane_lists"])
    env = Environment(loader=FileSystemLoader(str(TEMPLATES_DIR)), autoescape=True)
    template = env.get_template("digest.html")
    return template.render(
        date=datetime.now().strftime("%A, %B %d, %Y"),
        content=Markup(html_body),
    )


def send_digest(markdown_content: str, dry_run: bool = False, raw_sources: str | None = None) -> bool:
    load_dotenv()

    full_markdown = markdown_content
    if raw_sources:
        full_markdown += "\n\n---\n\n# Raw Sources\n\n<pre>\n" + raw_sources + "\n</pre>"

    html = _render_html(full_markdown)

    if dry_run:
        output_path = Path("digest_preview.html")
        output_path.write_text(html)
        logger.info("Dry run: HTML written to %s", output_path)
        return True

    sender = os.environ["GMAIL_SENDER_EMAIL"]
    password = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["DIGEST_RECIPIENT_EMAIL"]

    subject = f"Industry News Digest — {datetime.now().strftime('%b %d, %Y')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg.attach(MIMEText(full_markdown, "plain"))
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP("smtp.gmail.com", 587) as server:
        server.starttls()
        server.login(sender, password)
        server.send_message(msg)

    logger.info("Digest sent to %s", recipient)
    return True


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    sample_markdown = """## Key Developments

**Claude 4 Released** — Anthropic released Claude 4 with enhanced reasoning capabilities and improved code generation. [Anthropic Blog](https://anthropic.com/blog/claude-4)

**GPT-5 Turbo in API** — OpenAI made GPT-5 Turbo generally available with lower latency and reduced pricing. [OpenAI Blog](https://openai.com/blog/gpt5-turbo)

## Product Updates

**DeepMind AlphaFold 3 Update** — Google DeepMind released an update to AlphaFold improving protein-ligand interaction predictions. [DeepMind Blog](https://deepmind.google/blog/alphafold3)

## Worth Watching

**Enterprise AI adoption accelerating** — Multiple newsletters this week noted a shift from pilot programs to production deployments across Fortune 500 companies.
"""

    dry_run = "--dry-run" in sys.argv

    if dry_run:
        print("Rendering digest preview...\n")
        send_digest(sample_markdown, dry_run=True)
        print("Preview saved to digest_preview.html")
    else:
        print("Sending test digest email...\n")
        send_digest(sample_markdown)
        print("Test email sent.")
