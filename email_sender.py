"""Email delivery via Gmail SMTP."""

import os
import ssl
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger("briefing.email")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


def send_email(subject: str, html_body: str) -> None:
    """Send an HTML email to RECIPIENT_EMAIL via Gmail SMTP.

    Raises on failure so the caller can decide whether to retry.
    """
    gmail_address = os.getenv("GMAIL_ADDRESS")
    gmail_password = os.getenv("GMAIL_APP_PASSWORD")
    recipient = os.getenv("RECIPIENT_EMAIL")

    if not all([gmail_address, gmail_password, recipient]):
        raise RuntimeError(
            "Missing email config: GMAIL_ADDRESS, GMAIL_APP_PASSWORD or RECIPIENT_EMAIL"
        )

    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = gmail_address
    message["To"] = recipient
    message.attach(MIMEText(html_body, "html", "utf-8"))

    context = ssl.create_default_context()
    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=context) as server:
            server.login(gmail_address, gmail_password)
            server.sendmail(gmail_address, recipient, message.as_string())
        logger.info("Email sent to %s", recipient)
    except Exception as exc:  # noqa: BLE001
        logger.error("Failed to send email: %s", exc)
        raise
