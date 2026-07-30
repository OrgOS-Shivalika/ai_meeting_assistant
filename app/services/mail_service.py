"""Outbound email over SMTP.

Deliberately thin: build a MIME message, open a connection, send, close.
No queue, no retries, no provider SDK — `smtplib` from the stdlib means
Gmail, SES, Postmark and Mailgun all work by configuration alone.

Two properties the callers depend on:

**Optional.** With ``SMTP_HOST`` unset :func:`is_configured` returns False
and :func:`send_email` reports ``skipped`` without raising. Local dev and
test environments have no mail server, and member creation must not depend
on one.

**Never raises.** :func:`send_email` returns a :class:`SendResult` instead.
An invite email failing is not a reason to fail the account creation that
triggered it — the account is already committed and the UI still shows the
password. Callers surface the outcome; they don't handle exceptions.
"""
from __future__ import annotations

import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import formataddr
from typing import Optional

from app.config.settings import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


@dataclass
class SendResult:
    """Outcome of one send attempt.

    ``skipped`` distinguishes "no mail server configured" from "the send
    failed" — the first is an expected deployment state, the second is a
    problem worth showing the user.
    """

    sent: bool
    skipped: bool = False
    error: Optional[str] = None

    @property
    def status(self) -> str:
        if self.sent:
            return "sent"
        return "skipped" if self.skipped else "failed"


def is_configured() -> bool:
    """True when there is enough config to attempt a send."""
    return bool(settings.SMTP_HOST and settings.SMTP_FROM)


def _connect():
    """Open an SMTP connection, implicit-TLS or STARTTLS per config."""
    if settings.SMTP_USE_SSL:
        return smtplib.SMTP_SSL(
            settings.SMTP_HOST,
            settings.SMTP_PORT,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
            context=ssl.create_default_context(),
        )
    client = smtplib.SMTP(
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        timeout=settings.SMTP_TIMEOUT_SECONDS,
    )
    if settings.SMTP_USE_TLS:
        client.starttls(context=ssl.create_default_context())
    return client


def send_email(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
) -> SendResult:
    """Send one email. Returns the outcome; never raises.

    Always includes a plain-text part, with HTML as an alternative — a
    text-only client, or a security gateway that strips HTML, still gets a
    readable message, which matters when the message carries credentials.
    """
    if not is_configured():
        logger.info(
            "Email skipped (SMTP not configured): to=%s subject=%r", to, subject
        )
        return SendResult(sent=False, skipped=True)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.SMTP_FROM_NAME, settings.SMTP_FROM))
    message["To"] = to
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    try:
        with _connect() as client:
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            client.send_message(message)
    except Exception as exc:
        # Log the type and message but not the body — it may hold a
        # credential, and logs are a different trust boundary from a mailbox.
        logger.warning(
            "Email send failed: to=%s subject=%r error=%s: %s",
            to, subject, type(exc).__name__, exc,
        )
        return SendResult(sent=False, error=f"{type(exc).__name__}: {exc}")

    logger.info("Email sent: to=%s subject=%r", to, subject)
    return SendResult(sent=True)
