"""Email bodies.

Kept apart from `mail_service` so wording can change without touching the
transport, and so the transport stays testable without any template.

Inline CSS with a table-free layout on purpose: most mail clients strip
`<style>` blocks, and Outlook's rendering engine is unreliable with flexbox
and grid.
"""
from __future__ import annotations

from html import escape
from typing import Optional
from urllib.parse import quote, urlencode

from app.config.settings import settings
from app.utils.admin_enums import AccessRole

# What each role means, in the recipient's terms rather than ours. "You can
# see the meetings you attend" is useful; "MEMBER" is not.
_ROLE_BLURB = {
    AccessRole.MEMBER.value: "You can see the meetings you attend, along with their tasks and boards.",
    AccessRole.ADMIN.value: "You can manage the meetings, tasks and boards in the categories assigned to you.",
    AccessRole.ORG_ADMIN.value: "You have full access to every meeting, task and board in the organization.",
}

_ROLE_TITLE = {
    AccessRole.MEMBER.value: "Member",
    AccessRole.ADMIN.value: "Admin",
    AccessRole.ORG_ADMIN.value: "Organization Admin",
}

# Security: Time-limited context for support response window
_SUPPORT_RESPONSE_HOURS = 24


def _login_url() -> str:
    """Generate login URL with UTM tracking for analytics."""
    base_url = f"{settings.APP_PUBLIC_URL.rstrip('/')}/login"
    params = urlencode({
        "utm_source": "transactional_email",
        "utm_medium": "email",
        "utm_campaign": "account_access",
    })
    return f"{base_url}?{params}"


def _base_html_wrapper(
    *,
    title: str,
    subtitle: str,
    content: str,
    warning: Optional[str] = None,
    footer: Optional[str] = None,
) -> str:
    """Generate consistent HTML email wrapper with responsive design.
    
    Provides a single source of truth for email styling, reducing
    duplication and making future design changes simpler.
    """
    footer_html = ""
    if footer:
        footer_html = f"""
    <div style="margin:24px 0 0;padding-top:16px;border-top:1px solid #e5e7eb;">
      <p style="margin:0;font-size:12px;line-height:1.6;color:#9ca3af;">
        {footer}
      </p>
    </div>"""

    warning_html = ""
    if warning:
        warning_html = f"""
    <div style="margin:20px 0 0;padding:12px 14px;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;">
      <p style="margin:0;font-size:13px;line-height:1.6;color:#92400e;">
        {warning}
      </p>
    </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
</head>
<body style="margin:0;padding:0;background:#f6f6f7;">
  <div style="margin:0;padding:24px;background:#f6f6f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:28px;">

      <p style="margin:0 0 4px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;">
        OrgOS
      </p>
      <h1 style="margin:0 0 8px;font-size:20px;line-height:1.3;color:#0f1523;">
        {escape(title)}
      </h1>
      {f'<p style="margin:0 0 20px;font-size:14px;line-height:1.6;color:#6b7280;">{escape(subtitle)}</p>' if subtitle else ''}

      {content}
      {warning_html}
      {footer_html}
    </div>
  </div>
</body>
</html>"""


def reset_link_url(raw_token: str) -> str:
    """The URL in the reset email.

    `quote` the token even though `secrets.token_urlsafe` only emits
    `[A-Za-z0-9_-]`: relying on that here means a future change to the token
    alphabet silently produces broken links instead of an obvious error.
    """
    base = f"{settings.APP_PUBLIC_URL.rstrip('/')}/reset-password"
    return f"{base}?token={quote(raw_token, safe='')}"


def reset_link_subject(organization_name: Optional[str]) -> str:
    org = organization_name or "your team"
    return f"Reset your {org} password"


def reset_link_bodies(
    *,
    recipient_name: str,
    reset_url: str,
    organization_name: Optional[str],
    ttl_minutes: int,
) -> tuple[str, str]:
    """Return ``(text_body, html_body)`` for a SELF-service reset link.

    Distinct from the admin-initiated reset mail this replaced, which
    announced a change already made. This one is a request the recipient
    may not have made,
    so the two messages have opposite jobs:

    * No credential is enclosed and nothing has changed yet — say so, because
      a reset mail that reads as "your password has been changed" panics
      someone whose account is fine.
    * "If this wasn't you, ignore it" has to be the prominent line, and it
      has to be TRUE: no action means no change. That is what makes the
      endpoint safe to expose publicly, and the mail should say it plainly
      rather than telling the reader to contact an admin over a non-event.
    """
    org = organization_name or "your organization"

    text_body = f"""Hi {recipient_name},

Someone asked to reset the password for your {org} account on OrgOS.

Reset it here (the link works once, for {ttl_minutes} minutes):
{reset_url}

Nothing has changed yet. Your current password still works, and it stays
that way unless you open the link above and choose a new one.

Didn't ask for this?
Ignore this email. The link expires on its own and no action is taken.
There is no need to contact anyone — a reset request by itself cannot
change your password or reveal it to whoever asked.

Once you do set a new password, you'll be signed out everywhere else.

Need help? Reply to this email and our team will respond within
{_SUPPORT_RESPONSE_HOURS} hours.
"""

    greeting = f"""<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      Hi {escape(recipient_name)}, someone asked to reset the password for your
      <strong>{escape(org)}</strong> account.
    </p>

    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      <strong>Nothing has changed yet.</strong> Your current password still
      works, and it stays that way unless you choose a new one below.
    </p>"""

    cta = f"""<a href="{escape(reset_url)}"
       style="display:inline-block;background:#4f46e5;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 20px;border-radius:8px;border:1px solid #4338ca;">
      Choose a new password
    </a>

    <p style="margin:16px 0 0;font-size:12px;line-height:1.6;color:#6b7280;">
      This link works once and expires in {ttl_minutes} minutes. If the button
      doesn't work, paste this into your browser:<br>
      <span style="word-break:break-all;color:#4f46e5;">{escape(reset_url)}</span>
    </p>"""

    aftermath = """<p style="margin:20px 0 0;font-size:13px;line-height:1.6;color:#374151;">
      Once you set a new password you'll be signed out everywhere else, on
      every device.
    </p>"""

    warning = f"""<strong>Didn't ask for this?</strong> Ignore this email — the
      link expires in {ttl_minutes} minutes and nothing happens. A reset
      request on its own cannot change your password or show it to anyone."""

    html_body = _base_html_wrapper(
        title="Reset your password",
        subtitle="A password reset was requested",
        content=f"{greeting}{cta}{aftermath}",
        warning=warning,
        footer=f"Need help? Reply to this email and we'll respond within {_SUPPORT_RESPONSE_HOURS} hours.",
    )
    return text_body, html_body


def invite_link_url(raw_token: str) -> str:
    """Where an activation link points.

    The SAME page as a password reset. Setting your first password and
    replacing a forgotten one are the same act from the recipient's side, and
    a second screen would be a second place for the token handling to drift.
    """
    base = f"{settings.APP_PUBLIC_URL.rstrip('/')}/reset-password"
    return f"{base}?token={quote(raw_token, safe='')}&welcome=1"


def invite_link_subject(organization_name: Optional[str]) -> str:
    org = organization_name or "your team"
    return f"You've been invited to {org} on OrgOS"


def invite_link_bodies(
    *,
    recipient_name: str,
    invite_url: str,
    organization_name: Optional[str],
    invited_by_name: Optional[str],
    ttl_hours: int,
) -> tuple[str, str]:
    """Return ``(text_body, html_body)`` for an activation invitation.

    Replaces the old invite mail, which enclosed a generated password. Mailing a password puts a live credential into a system nobody
    here controls — readable at every hop, sitting in backups, and still
    readable months later in a mailbox that outlives the employment. This
    message carries a single-use link instead, so the only password the
    account ever has is one its owner chose and the server has never seen.

    No credentials box, and nothing to "delete this email once you're done":
    there is nothing sensitive to delete once the link is spent.
    """
    org = organization_name or "your organization"
    inviter = f"{invited_by_name} has invited you" if invited_by_name else "You've been invited"
    days = max(1, ttl_hours // 24)

    text_body = f"""Hi {recipient_name},

{inviter} to join {org} on OrgOS.

Set your password and get started:
{invite_url}

The link works once and expires in {days} day{'s' if days != 1 else ''}.

You'll choose your own password — nobody at {org} can see it, and we never
send passwords by email.

If the link has expired by the time you get to it, ask whoever invited you
to send a new one.

Need help? Reply to this email and our team will respond within
{_SUPPORT_RESPONSE_HOURS} hours.
"""

    greeting = f"""<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      Hi {escape(recipient_name)}, {escape(inviter.lower())} to join
      <strong>{escape(org)}</strong> on OrgOS.
    </p>"""

    cta = f"""<a href="{escape(invite_url)}"
       style="display:inline-block;background:#4f46e5;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 20px;border-radius:8px;border:1px solid #4338ca;">
      Set your password
    </a>

    <p style="margin:16px 0 0;font-size:12px;line-height:1.6;color:#6b7280;">
      This link works once and expires in {days} day{'s' if days != 1 else ''}.
      If the button doesn't work, paste this into your browser:<br>
      <span style="word-break:break-all;color:#4f46e5;">{escape(invite_url)}</span>
    </p>"""

    assurance = f"""<p style="margin:20px 0 0;font-size:13px;line-height:1.6;color:#374151;">
      You'll choose your own password. Nobody at {escape(org)} can see it, and
      we never send passwords by email.
    </p>"""

    html_body = _base_html_wrapper(
        title=f"Join {escape(org)} on OrgOS",
        subtitle="You've been invited",
        content=f"{greeting}{cta}{assurance}",
        warning="""<strong>Link expired?</strong> Ask whoever invited you to send
          a new one — invitations are single-use and time-limited by design.""",
        footer=f"Need help? Reply to this email and we'll respond within {_SUPPORT_RESPONSE_HOURS} hours.",
    )
    return text_body, html_body
