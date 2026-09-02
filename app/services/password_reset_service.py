"""Self-service password reset.

The threat model this is written against, and how each part answers it:

* **Account enumeration.** `request_reset` returns the same thing whether or
  not the address belongs to anyone, and the mail is sent from a background
  task so an existing address does not take an SMTP round-trip longer than a
  missing one. A "no account with that email" message — or a 200ms timing
  difference — turns the login form into a membership oracle for whoever is
  probing it.
* **Database disclosure.** Only the SHA-256 of the token is stored. The raw
  value lives in the email and the URL and nowhere else, so a dump of this
  table yields nothing that can be redeemed.
* **Link reuse and lingering links.** Single-use (`used_at`), 30-minute TTL,
  and redemption burns every OTHER outstanding token for that account at the
  same moment. `invalidate_outstanding` is also called from the ordinary
  password-change paths, so an admin-issued reset kills any forgot-password
  link already in someone's inbox.
* **Session survival.** Redemption moves `password_set_at`, which this
  codebase already treats as the JWT revocation point — so resetting a
  password signs out every other live session. That is the point: the usual
  reason to reset is that someone else may be holding your credential.
* **Request flooding.** A per-account cap on how many links can be minted in
  a window. Mailbombing someone via a public endpoint is the abuse case.

What is deliberately NOT here: per-IP throttling. Behind Railway's proxy the
client address is whatever the last hop claims, so an IP counter would be both
bypassable and liable to lock out everyone behind one NAT. The per-account cap
is the honest control; an edge rate-limit is the right place for the rest.
"""

from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.db.models import PasswordResetToken, User
from app.services import mail_service, mail_templates
from app.services.auth_service import hash_password, verify_password
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

# Two purposes, one mechanism. Redemption is a single code path for both —
# two routes that each set a password is how one of them ends up skipping a
# check. Only the TTL and the email wording differ.
PURPOSE_RESET = "reset"
PURPOSE_INVITE = "invite"

# Short by intent. A reset link is a bearer credential for the account, and it
# sits in an inbox — the window where a stolen mailbox or a forwarded message
# is still redeemable should be minutes, not days.
TOKEN_TTL_MINUTES = 30

# An invitation is a different bet. The recipient is not sitting at the screen
# waiting for it; they may be on leave, or it may land on a Friday night. A
# 30-minute invite would expire unused for most new joiners and turn every
# provisioning into two admin actions. A week is the usual compromise, and the
# link still dies the moment it is used.
INVITE_TTL_MINUTES = 7 * 24 * 60

_TTL_BY_PURPOSE = {
    PURPOSE_RESET: TOKEN_TTL_MINUTES,
    PURPOSE_INVITE: INVITE_TTL_MINUTES,
}

# 256 bits of entropy, URL-safe. Guessing is not a threat at this size; the
# reason to care about the generator is that `random` is predictable from
# observed output and `secrets` is not.
_TOKEN_BYTES = 32

# Per-account flood control: at most this many links per window. Set above
# what a confused-but-legitimate person needs (click, miss the mail, retry)
# and far below what makes the endpoint useful as a mailbomb.
MAX_REQUESTS_PER_WINDOW = 3
RATE_WINDOW_MINUTES = 15


def _hash_token(raw: str) -> str:
    """SHA-256 hex of a reset token.

    Plain SHA-256, not bcrypt, and that is deliberate: this input is 256 bits
    of `secrets` entropy, not a human-chosen password. There is no dictionary
    to attack and nothing for a slow KDF to buy — the hash exists so a leaked
    table is not a pile of live links, and a fast digest does that completely.
    """
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def invalidate_outstanding(
    db: Session, user_id, *, reason: str, purpose: Optional[str] = None
) -> int:
    """Burn every unused token for this account, or just one purpose\'s.

    Call from ANY path that changes a password. Without it, a forgot-password
    link already sitting in an inbox stays redeemable after an admin has
    reset the account — which is exactly the situation where someone is
    trying to lock an attacker out.

    `purpose=None` burns everything, which is what a password change wants.
    Re-inviting someone passes `PURPOSE_INVITE` so it supersedes the previous
    invitation without also killing a reset link they asked for themselves.

    Returns how many were burned, so callers can log it.
    """
    q = db.query(PasswordResetToken).filter(
        PasswordResetToken.user_id == user_id,
        PasswordResetToken.used_at.is_(None),
    )
    if purpose is not None:
        q = q.filter(PasswordResetToken.purpose == purpose)
    burned = q.update({PasswordResetToken.used_at: _now()}, synchronize_session=False)
    if burned:
        logger.info(
            "Invalidated %d outstanding reset token(s) for %s (%s)",
            burned, user_id, reason,
        )
    return burned


def _recent_request_count(db: Session, user_id) -> int:
    window_start = _now() - timedelta(minutes=RATE_WINDOW_MINUTES)
    return (
        db.query(func.count(PasswordResetToken.id))
        .filter(
            PasswordResetToken.user_id == user_id,
            PasswordResetToken.created_at >= window_start,
        )
        .scalar()
        or 0
    )


def create_reset_token(
    db: Session,
    user: User,
    *,
    requested_ip: Optional[str] = None,
    purpose: str = PURPOSE_RESET,
    rate_limit: bool = False,
) -> Optional[str]:
    """Mint a token and return the RAW value, or None if rate-limited.

    The raw token is returned exactly once and never persisted — the caller
    puts it in an email and drops it. There is deliberately no way to read an
    existing token back out.

    `rate_limit` is OFF by default and turned on only by `request_reset`. The
    cap exists because that endpoint is public and unauthenticated; an admin
    provisioning or re-inviting someone is already access-controlled, and
    throttling them would just block a legitimate resend.
    """
    if rate_limit and _recent_request_count(db, user.id) >= MAX_REQUESTS_PER_WINDOW:
        logger.warning(
            "Password reset rate-limited for %s (%d in %dm)",
            user.email, MAX_REQUESTS_PER_WINDOW, RATE_WINDOW_MINUTES,
        )
        return None

    ttl = _TTL_BY_PURPOSE.get(purpose, TOKEN_TTL_MINUTES)
    raw = secrets.token_urlsafe(_TOKEN_BYTES)
    db.add(
        PasswordResetToken(
            user_id=user.id,
            token_hash=_hash_token(raw),
            purpose=purpose,
            expires_at=_now() + timedelta(minutes=ttl),
            requested_ip=requested_ip,
        )
    )
    db.commit()
    return raw


def create_invite_token(db: Session, user: User) -> str:
    """Mint an activation link for a newly provisioned account.

    Supersedes any previous unused invitation for that person, so a re-invite
    leaves exactly one live link rather than a growing set of them.
    """
    invalidate_outstanding(
        db, user.id, reason="re-invited", purpose=PURPOSE_INVITE
    )
    raw = create_reset_token(db, user, purpose=PURPOSE_INVITE)
    # `rate_limit=False`, so this cannot return None.
    assert raw is not None
    return raw


def invite_url(raw_token: str) -> str:
    """The activation URL an admin can copy when email is unavailable."""
    return mail_templates.invite_link_url(raw_token)


def send_invite_link_email(
    user: User, raw_token: str, *, invited_by_name: Optional[str] = None
) -> mail_service.SendResult:
    """Email an activation LINK — never a password.

    Best-effort, like the invite mail it replaces: the account is already
    committed by the time this runs, so a mail failure must not undo it. The
    caller shows the link instead.
    """
    org = user.organization
    text_body, html_body = mail_templates.invite_link_bodies(
        recipient_name=user.name,
        invite_url=invite_url(raw_token),
        organization_name=org.name if org else None,
        invited_by_name=invited_by_name,
        ttl_hours=INVITE_TTL_MINUTES // 60,
    )
    result = mail_service.send_email(
        to=user.email,
        subject=mail_templates.invite_link_subject(org.name if org else None),
        text_body=text_body,
        html_body=html_body,
    )
    logger.info("Invite link email %s for %s", result.status, user.email)
    return result


def send_reset_email(user: User, raw_token: str) -> mail_service.SendResult:
    """Email the reset link. Never raises — see the module docstring on
    enumeration: the caller must behave identically whether this works or not.
    """
    org = user.organization
    text_body, html_body = mail_templates.reset_link_bodies(
        recipient_name=user.name,
        reset_url=mail_templates.reset_link_url(raw_token),
        organization_name=org.name if org else None,
        ttl_minutes=TOKEN_TTL_MINUTES,
    )
    result = mail_service.send_email(
        to=user.email,
        subject=mail_templates.reset_link_subject(org.name if org else None),
        text_body=text_body,
        html_body=html_body,
    )
    logger.info("Password-reset link email %s for %s", result.status, user.email)
    return result


def request_reset(db: Session, email: str, *, requested_ip: Optional[str] = None) -> None:
    """Handle "I forgot my password" for an address that may not exist.

    Returns None in every case, on purpose. The caller has nothing to branch
    on, which is what stops the endpoint from becoming a membership oracle —
    there is no way to accidentally leak the answer into a response.
    """
    normalized = (email or "").strip().lower()
    if not normalized:
        return
    user = db.query(User).filter(func.lower(User.email) == normalized).first()
    if user is None:
        # Logged so a probing run is visible in the logs, where only operators
        # can see it — never surfaced to the caller.
        logger.info("Password reset requested for unknown address: %s", normalized)
        return

    raw = create_reset_token(
        db, user, requested_ip=requested_ip, rate_limit=True
    )
    if raw is None:
        return  # rate-limited; still silent to the caller
    send_reset_email(user, raw)


class ResetTokenInvalid(Exception):
    """Token is unknown, expired, or already used.

    ONE exception for all three. Telling the caller which would say whether a
    token ever existed, and an expired-vs-unknown distinction is enough to
    confirm an account was targeted.
    """


def consume_token(db: Session, raw_token: str, new_password: str) -> User:
    """Redeem a reset link and set the new password.

    Raises `ResetTokenInvalid` for anything wrong with the token, and
    `ValueError` when the new password is the one already on the account.
    """
    if not raw_token:
        raise ResetTokenInvalid()

    row = (
        db.query(PasswordResetToken)
        .filter(PasswordResetToken.token_hash == _hash_token(raw_token))
        .first()
    )
    if row is None or row.used_at is not None:
        raise ResetTokenInvalid()

    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        # A backend without timezone support would otherwise compare naive
        # local time against aware UTC and land hours off.
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= _now():
        raise ResetTokenInvalid()

    user = db.query(User).filter(User.id == row.user_id).first()
    if user is None:
        raise ResetTokenInvalid()

    if verify_password(new_password, user.password):
        # Not a security control — a reset that silently no-ops reads as
        # "it didn't work", and the person tries again.
        raise ValueError("New password must differ from the current one.")

    now = _now()
    user.password = hash_password(new_password)
    # `password_set_at` is this codebase's JWT revocation point: every token
    # minted before it is refused. Moving it is what makes a reset actually
    # sign out whoever else was holding a session.
    user.password_set_at = now
    # They have now chosen their own password, so the forced-change gate that
    # an admin-provisioned account carries is satisfied.
    user.must_change_password = False

    row.used_at = now
    # Burn the siblings too: several "forgot password" clicks produce several
    # live links, and redeeming one must not leave the rest usable.
    invalidate_outstanding(db, user.id, reason="reset redeemed")
    db.commit()

    logger.info("Password reset completed for %s", user.email)
    return user
