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

import contextlib
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


@contextlib.contextmanager
def connection():
    """One authenticated SMTP connection, for a caller sending several in a row.

    `send_email` opens its own per message - connect, STARTTLS, LOGIN, send,
    quit - which is right for a single transactional send and wrong for a
    sweep. Ten notifications meant ten TLS handshakes and ten logins in 34
    seconds, and Gmail started refusing the connection outright
    (`ConnectionRefusedError: [Errno 111]`). Measured on 2026-09-08: of 10
    pending notifications, 1 was delivered.

    Yields None when SMTP is not configured, so callers can use the same
    shape either way - `send_email` already handles the unconfigured case.
    """
    if not is_configured():
        yield None
        return
    client = None
    try:
        client = _connect()
        if settings.SMTP_USER and settings.SMTP_PASSWORD:
            client.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        yield client
    except Exception as exc:
        # Could not establish the shared connection at all. Yield None and let
        # every send fall back to its own - slow, but it still delivers.
        logger.warning(
            "Shared SMTP connection failed (%s: %s) - falling back to one "
            "connection per message", type(exc).__name__, exc,
        )
        yield None
    finally:
        if client is not None:
            try:
                client.quit()
            except Exception:
                pass


def send_email(
    *,
    to: str,
    subject: str,
    text_body: str,
    html_body: Optional[str] = None,
    client=None,
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

    def _own_connection() -> None:
        with _connect() as c:
            if settings.SMTP_USER and settings.SMTP_PASSWORD:
                c.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            c.send_message(message)

    try:
        if client is None:
            _own_connection()
        else:
            try:
                client.send_message(message)
            except Exception as shared_exc:
                # A shared connection that dies mid-batch would otherwise take
                # every remaining message with it, and the sweep stamps
                # `emailed_at` even on failure - so those would be lost, not
                # retried. One retry on a fresh connection bounds the damage to
                # nothing worse than the old per-message behaviour.
                logger.info(
                    "Shared SMTP connection failed for %s (%s) - retrying on "
                    "its own", to, type(shared_exc).__name__,
                )
                _own_connection()
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
