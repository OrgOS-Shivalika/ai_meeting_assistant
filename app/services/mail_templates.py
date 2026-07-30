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


def _login_url() -> str:
    return f"{settings.APP_PUBLIC_URL.rstrip('/')}/login"


def invite_subject(organization_name: Optional[str]) -> str:
    org = organization_name or "your team"
    return f"You've been added to {org} on OrgOS"


def invite_bodies(
    *,
    recipient_name: str,
    email: str,
    password: str,
    access_role: str,
    organization_name: Optional[str],
    invited_by_name: Optional[str],
) -> tuple[str, str]:
    """Return ``(text_body, html_body)`` for the invite email.

    The password is included because that is the flow this supports: an org
    admin sets it and the recipient needs it to sign in. Both bodies tell
    them to change it immediately, which is also enforced server-side —
    `must_change_password` blocks every endpoint except sign-in, identity
    and password change until they do.
    """
    org = organization_name or "your organization"
    role_title = _ROLE_TITLE.get(access_role, access_role)
    role_blurb = _ROLE_BLURB.get(access_role, "")
    invited_by = f"{invited_by_name} has added you" if invited_by_name else "You have been added"
    url = _login_url()

    text_body = f"""Hi {recipient_name},

{invited_by} to {org} on OrgOS as {role_title}.

{role_blurb}

Sign in here: {url}

  Email:    {email}
  Password: {password}

You will be asked to choose your own password the first time you sign in.
Until you do, this one works only for signing in. Please delete this email
once you have changed it.

If you weren't expecting this, you can ignore this message — or reply to let
us know.
"""

    html_body = f"""<div style="margin:0;padding:24px;background:#f6f6f7;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e5e7eb;border-radius:12px;padding:28px;">

    <p style="margin:0 0 4px;font-size:12px;font-weight:600;letter-spacing:.06em;text-transform:uppercase;color:#6b7280;">
      OrgOS
    </p>
    <h1 style="margin:0 0 16px;font-size:20px;line-height:1.3;color:#0f1523;">
      You've been added to {escape(org)}
    </h1>

    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      Hi {escape(recipient_name)}, {escape(invited_by.lower())} to
      <strong>{escape(org)}</strong> as <strong>{escape(role_title)}</strong>.
      {escape(role_blurb)}
    </p>

    <div style="margin:0 0 20px;padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
      <p style="margin:0 0 8px;font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:#6b7280;">
        Your sign-in details
      </p>
      <p style="margin:0 0 4px;font-size:14px;color:#0f1523;">
        <span style="color:#6b7280;">Email</span>&nbsp;&nbsp;{escape(email)}
      </p>
      <p style="margin:0;font-size:14px;color:#0f1523;">
        <span style="color:#6b7280;">Password</span>&nbsp;&nbsp;<code style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:14px;background:#ffffff;border:1px solid #d1d5db;border-radius:4px;padding:2px 6px;">{escape(password)}</code>
      </p>
    </div>

    <a href="{escape(url)}"
       style="display:inline-block;background:#4f46e5;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 20px;border-radius:8px;">
      Sign in
    </a>

    <p style="margin:20px 0 0;font-size:13px;line-height:1.6;color:#92400e;background:#fffbeb;border:1px solid #fde68a;border-radius:8px;padding:12px 14px;">
      You'll be asked to choose your own password the first time you sign in.
      Until then this one works only for signing in. Please delete this email
      once you've changed it.
    </p>

    <p style="margin:20px 0 0;font-size:12px;line-height:1.6;color:#9ca3af;">
      If you weren't expecting this, you can ignore this message.
    </p>
  </div>
</div>"""

    return text_body, html_body
