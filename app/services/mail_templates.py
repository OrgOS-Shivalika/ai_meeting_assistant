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
from urllib.parse import urlencode

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


def _credentials_box(
    *,
    email: str,
    password: str,
    password_label: str = "Password",
    box_title: str = "Your sign-in details",
) -> str:
    """Generate consistent credentials display box."""
    return f"""<div style="margin:0 0 20px;padding:14px 16px;background:#f9fafb;border:1px solid #e5e7eb;border-radius:8px;">
      <p style="margin:0 0 8px;font-size:11px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:#6b7280;">
        {escape(box_title)}
      </p>
      <p style="margin:0 0 4px;font-size:14px;color:#0f1523;">
        <span style="color:#6b7280;">Email</span>&nbsp;&nbsp;{escape(email)}
      </p>
      <p style="margin:0;font-size:14px;color:#0f1523;">
        <span style="color:#6b7280;">{escape(password_label)}</span>&nbsp;&nbsp;<code style="font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:14px;background:#ffffff;border:1px solid #d1d5db;border-radius:4px;padding:2px 6px;">{escape(password)}</code>
      </p>
    </div>"""


def reset_subject(organization_name: Optional[str]) -> str:
    """Generate subject line for password reset email."""
    org = organization_name or "your team"
    return f"Your {org} password has been reset"


def reset_bodies(
    *,
    recipient_name: str,
    email: str,
    password: str,
    organization_name: Optional[str],
    reset_by_name: Optional[str],
) -> tuple[str, str]:
    """Return ``(text_body, html_body)`` for an admin-initiated reset.

    Not a reuse of the invite. The recipient already has an account, so a
    welcome reads as a duplicate signup; and two things need saying that an
    invite never has to say — that they have been signed out everywhere,
    and that they should raise it if they did not ask for this. An
    unexpected password reset is what an account takeover looks like from
    the inside, so the mail has to make that legible rather than bury it.

    No role blurb either: a reset does not change what they can reach, and
    restating it invites the reader to think it might have.
    """
    org = organization_name or "your organization"
    reset_by = (
        f"{reset_by_name} has reset your password"
        if reset_by_name
        else "Your password has been reset"
    )
    url = _login_url()

    # Improved text body with clearer action items and security context
    text_body = f"""Hi {recipient_name},

{reset_by} for {org} on OrgOS.

What this means:
• You've been signed out of all devices and sessions
• A temporary password has been generated for you
• You'll need to create a new password immediately

Sign in here: {url}

  Email:               {email}
  Temporary password:  {password}

Next steps:
1. Sign in using the temporary password above
2. Create your new password when prompted
3. Delete this email once you've completed these steps

Security notice:
If you didn't request this password reset, contact your organization
administrator immediately. This action was performed by someone with
admin privileges and could indicate unauthorized account access.

For your safety, this temporary password will only work for signing in
and must be changed before accessing any other features.

Need help? Reply to this email and our team will respond within
{_SUPPORT_RESPONSE_HOURS} hours.
"""

    # Build content sections
    greeting = f"""<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      Hi {escape(recipient_name)}, {escape(reset_by.lower())} for
      <strong>{escape(org)}</strong>.
    </p>
    
    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      You've been signed out of all devices and sessions. A temporary 
      password has been generated for you to regain access.
    </p>"""

    credentials = _credentials_box(
        email=email,
        password=password,
        password_label="Temporary password",
        box_title="Sign back in with",
    )

    cta = f"""<a href="{escape(url)}"
       style="display:inline-block;background:#4f46e5;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 20px;border-radius:8px;border:1px solid #4338ca;">
      Sign in to OrgOS
    </a>"""

    steps = """<p style="margin:20px 0 0;font-size:13px;line-height:1.6;color:#374151;">
      <strong>Next steps:</strong><br>
      1. Sign in using the temporary password<br>
      2. Create your new password when prompted<br>
      3. Delete this email for security
    </p>"""

    warning = """<strong>⚠️ Important:</strong> You'll be asked to choose a new 
      password immediately. Until then this one works only for signing in. 
      Please delete this email once you've changed it."""

    security_notice = """<strong>🔒 Didn't request this?</strong> Contact your 
      organization admin straight away — someone with admin access reset it 
      on your behalf. This could indicate unauthorized access."""

    # Build content with improved structure
    content = f"{greeting}{credentials}{cta}{steps}"
    
    html_body = _base_html_wrapper(
        title="Your password has been reset",
        subtitle="Account security action required",
        content=content,
        warning=warning,
        footer=f"Need help? Reply to this email and we'll respond within {_SUPPORT_RESPONSE_HOURS} hours.",
    )

    # Add security notice as separate styled block
    html_body = html_body.replace(
        "</div>\n  </div>\n</body>",
        f"""<div style="margin:20px 0 0;padding:12px 14px;background:#fef2f2;border:1px solid #fecaca;border-radius:8px;">
      <p style="margin:0;font-size:13px;line-height:1.6;color:#991b1b;">
        {security_notice}
      </p>
    </div>
  </div>
</body>""",
    )

    return text_body, html_body


def invite_subject(organization_name: Optional[str]) -> str:
    """Generate subject line for team invitation email."""
    org = organization_name or "your team"
    return f"You've been invited to join {org} on OrgOS"


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
    invited_by = f"{invited_by_name} has invited you" if invited_by_name else "You've been invited"
    url = _login_url()

    # Improved text body with clearer onboarding structure
    text_body = f"""Hi {recipient_name},

{invited_by} to join {org} on OrgOS.

Your role: {role_title}
{role_blurb}

Getting started:
1. Sign in at: {url}
2. Use the credentials below
3. Create your own password when prompted

  Email:    {email}
  Password: {password}

Important: This password is temporary and will only work for signing in.
You'll be prompted to create your own password immediately. For security,
please delete this email once you've set your new password.

What you can do as {role_title}:
{role_blurb}

If you weren't expecting this invitation, you can safely ignore this 
message. Your account won't be created until you sign in, and the 
invitation will expire automatically.
"""

    # Build content sections
    greeting = f"""<p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      Hi {escape(recipient_name)}, {escape(invited_by.lower())} to join
      <strong>{escape(org)}</strong> as <strong>{escape(role_title)}</strong>.
    </p>
    
    <p style="margin:0 0 16px;font-size:14px;line-height:1.6;color:#374151;">
      {escape(role_blurb)}
    </p>"""

    credentials = _credentials_box(
        email=email,
        password=password,
        box_title="Your sign-in details",
    )

    cta = f"""<a href="{escape(url)}"
       style="display:inline-block;background:#4f46e5;color:#ffffff;font-size:14px;font-weight:600;text-decoration:none;padding:11px 20px;border-radius:8px;border:1px solid #4338ca;">
      Accept invitation & sign in
    </a>"""

    role_info = f"""<div style="margin:20px 0 0;padding:14px 16px;background:#f0f9ff;border:1px solid #bae6fd;border-radius:8px;">
      <p style="margin:0 0 4px;font-size:12px;font-weight:600;letter-spacing:.05em;text-transform:uppercase;color:#0369a1;">
        Your role: {escape(role_title)}
      </p>
      <p style="margin:0;font-size:13px;line-height:1.6;color:#0c4a6e;">
        {escape(role_blurb)}
      </p>
    </div>"""

    warning = """<strong>⚠️ Important:</strong> You'll be asked to choose your 
      own password the first time you sign in. Until then this one works only 
      for signing in. Please delete this email once you've changed it."""

    content = f"{greeting}{credentials}{cta}{role_info}"
    
    html_body = _base_html_wrapper(
        title=f"You've been added to {escape(org)}",
        subtitle=f"Welcome to OrgOS as {escape(role_title)}",
        content=content,
        warning=warning,
        footer="If you weren't expecting this invitation, you can safely ignore this message.",
    )

    return text_body, html_body