"""Self-service password reset — the security properties, not the happy path.

Needs a live Postgres (the token table). Run with:

    export PYTHONIOENCODING=utf-8
    python tests/test_password_reset.py

Every probe account is deleted in `finally`, including on failure. Mail is
stubbed out at `mail_service.send_email` so nothing is actually sent, and the
stub records what WOULD have gone out — which is how the enumeration tests
tell "no email" from "email to the wrong place".
"""
from __future__ import annotations

import base64
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from main import app  # noqa: E402
from app.db.database import SessionLocal, get_db  # noqa: E402
from app.db.models import PasswordResetToken, User  # noqa: E402
from app.services import auth_service, mail_service, password_reset_service  # noqa: E402

PASSWORD = "Original-Passw0rd!"
NEW_PASSWORD = "Replacement-Passw0rd!"

_passed: list[str] = []
_failed: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    (_passed if condition else _failed).append(name if condition else f"{name} — {detail}")
    print(f"  {'ok  ' if condition else 'FAIL'} {name}" + (f"  ({detail})" if detail and not condition else ""))


# --- mail stub -------------------------------------------------------------
sent: list[dict] = []


def _fake_send_email(*, to, subject, text_body, html_body=None):
    sent.append({"to": to, "subject": subject, "text": text_body})
    return mail_service.SendResult(sent=True)


mail_service.send_email = _fake_send_email
password_reset_service.mail_service.send_email = _fake_send_email


def b64(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


def make_user(db, org_id, tag: str) -> User:
    u = User(
        name=f"reset probe {tag}",
        email=f"reset-probe-{tag}-{uuid.uuid4().hex[:8]}@probetest.com",
        password=auth_service.hash_password(PASSWORD),
        organization_id=org_id,
        access_role="MEMBER",
        must_change_password=False,
    )
    db.add(u)
    db.commit()
    return u


def token_in_last_email() -> str:
    """Pull the raw token out of the link in the most recent email."""
    return sent[-1]["text"].split("reset-password?token=")[1].split()[0]


def main() -> int:
    db = SessionLocal()
    app.dependency_overrides[get_db] = lambda: db
    client = TestClient(app)
    org_id = db.query(User).filter(User.email == "demo@triburg.com").first().organization_id
    created: list[uuid.UUID] = []

    try:
        # -- no account enumeration ----------------------------------------
        print("\nNo account enumeration")
        user = make_user(db, org_id, "enum")
        created.append(user.id)
        sent.clear()
        real = client.post("/public/auth/forgot-password", json={"email": user.email})
        missing = client.post(
            "/public/auth/forgot-password",
            json={"email": "definitely-nobody@probetest.com"},
        )
        check("same status for real and unknown address",
              real.status_code == missing.status_code == 202,
              f"{real.status_code} vs {missing.status_code}")
        check("same body for real and unknown address",
              real.json() == missing.json(),
              f"{real.json()} vs {missing.json()}")
        check("body names no account", "exists" in real.json().get("message", "").lower())
        check("mail went only to the real address",
              [m["to"] for m in sent] == [user.email],
              str([m["to"] for m in sent]))

        # -- the token is never stored in the clear ------------------------
        print("\nToken storage")
        raw = token_in_last_email()
        row = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == user.id).first()
        check("raw token absent from the row",
              raw not in (row.token_hash or ""), "raw token found in token_hash")
        check("stored value is a sha256 hex digest",
              len(row.token_hash) == 64 and all(c in "0123456789abcdef" for c in row.token_hash))
        check("no column anywhere holds the raw token",
              not any(raw in str(getattr(row, c.name)) for c in row.__table__.columns))
        check("expiry is ~30 minutes out",
              timedelta(minutes=25) < (row.expires_at - datetime.now(timezone.utc)) < timedelta(minutes=35),
              str(row.expires_at))

        # -- redemption ----------------------------------------------------
        print("\nRedemption")
        before_hash = user.password
        r = client.post("/public/auth/reset-password",
                        json={"token": raw, "new_password": b64(NEW_PASSWORD)})
        check("valid token accepted", r.status_code == 200, f"{r.status_code} {r.text[:120]}")
        db.refresh(user)
        check("password actually changed", user.password != before_hash)
        check("new password verifies", auth_service.verify_password(NEW_PASSWORD, user.password))
        check("old password no longer works",
              not auth_service.verify_password(PASSWORD, user.password))
        check("password_set_at moved (revokes live JWTs)",
              user.password_set_at is not None
              and (datetime.now(timezone.utc) - user.password_set_at) < timedelta(minutes=1))
        check("response does NOT sign the caller in",
              "access_token=ey" not in r.headers.get("set-cookie", ""),
              r.headers.get("set-cookie", ""))

        # -- single use ----------------------------------------------------
        print("\nSingle use and expiry")
        r2 = client.post("/public/auth/reset-password",
                         json={"token": raw, "new_password": b64("Third-Passw0rd!")})
        check("same token refused the second time", r2.status_code == 400, str(r2.status_code))
        check("still the new password after the refused replay",
              auth_service.verify_password(NEW_PASSWORD, db.query(User).get(user.id).password))

        expired_user = make_user(db, org_id, "expired")
        created.append(expired_user.id)
        raw_expired = password_reset_service.create_reset_token(db, expired_user)
        exp_row = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == expired_user.id).first()
        exp_row.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        db.commit()
        r3 = client.post("/public/auth/reset-password",
                         json={"token": raw_expired, "new_password": b64(NEW_PASSWORD)})
        check("expired token refused", r3.status_code == 400, str(r3.status_code))
        check("expired and unknown give the SAME message",
              r3.json().get("detail") == r2.json().get("detail"),
              f"{r3.json().get('detail')!r} vs {r2.json().get('detail')!r}")

        r4 = client.post("/public/auth/reset-password",
                         json={"token": "x" * 40, "new_password": b64(NEW_PASSWORD)})
        check("garbage token refused with the same message",
              r4.status_code == 400 and r4.json().get("detail") == r2.json().get("detail"))

        # -- redeeming one link burns the others ---------------------------
        print("\nSibling links")
        multi = make_user(db, org_id, "multi")
        created.append(multi.id)
        first = password_reset_service.create_reset_token(db, multi)
        second = password_reset_service.create_reset_token(db, multi)
        check("two distinct links minted", first != second)
        r5 = client.post("/public/auth/reset-password",
                         json={"token": second, "new_password": b64(NEW_PASSWORD)})
        check("newest link redeems", r5.status_code == 200, str(r5.status_code))
        r6 = client.post("/public/auth/reset-password",
                         json={"token": first, "new_password": b64("Another-Passw0rd!")})
        check("older sibling link is dead", r6.status_code == 400, str(r6.status_code))

        # -- a password change elsewhere kills outstanding links -----------
        print("\nOutstanding links die when the password changes elsewhere")
        elsewhere = make_user(db, org_id, "elsewhere")
        created.append(elsewhere.id)
        pending = password_reset_service.create_reset_token(db, elsewhere)
        from app.services import admin_service
        admin_service.change_password(db, elsewhere, PASSWORD, NEW_PASSWORD)
        r7 = client.post("/public/auth/reset-password",
                         json={"token": pending, "new_password": b64("Yet-Another-P4ss!")})
        check("link issued before an unrelated password change is dead",
              r7.status_code == 400, str(r7.status_code))

        # -- rate limiting --------------------------------------------------
        print("\nRate limiting")
        flood = make_user(db, org_id, "flood")
        created.append(flood.id)
        sent.clear()
        codes = [
            client.post("/public/auth/forgot-password", json={"email": flood.email}).status_code
            for _ in range(6)
        ]
        minted = db.query(PasswordResetToken).filter(
            PasswordResetToken.user_id == flood.id).count()
        check("every request still answers 202 (no signal to the caller)",
              set(codes) == {202}, str(codes))
        check(f"only {password_reset_service.MAX_REQUESTS_PER_WINDOW} links minted for 6 requests",
              minted == password_reset_service.MAX_REQUESTS_PER_WINDOW, f"minted {minted}")
        check("no mailbomb — emails capped too",
              len(sent) == password_reset_service.MAX_REQUESTS_PER_WINDOW, f"{len(sent)} sent")

        # -- password rules still apply ------------------------------------
        print("\nPassword rules")
        weak = make_user(db, org_id, "weak")
        created.append(weak.id)
        raw_weak = password_reset_service.create_reset_token(db, weak)
        r8 = client.post("/public/auth/reset-password",
                         json={"token": raw_weak, "new_password": b64("short")})
        check("too-short password rejected", r8.status_code == 422, str(r8.status_code))
        r9 = client.post("/public/auth/reset-password",
                         json={"token": raw_weak, "new_password": b64(PASSWORD)})
        check("reusing the current password rejected", r9.status_code == 400, str(r9.status_code))
        check("token survives a rejected attempt",
              client.post("/public/auth/reset-password",
                          json={"token": raw_weak, "new_password": b64(NEW_PASSWORD)}
                          ).status_code == 200)

        # -- provisioning: an invitation, never a password ------------------
        print("\nProvisioning sends a link, not a password")
        from app.schemas.admin_schema import MemberCreateRequest
        from app.services import admin_service

        actor = db.query(User).filter(User.email == "demo@triburg.com").first()
        sent.clear()
        new_email = f"invite-probe-{uuid.uuid4().hex[:8]}@probetest.com"
        member, invite_url, _linked, mail_result = admin_service.create_member(
            db, actor,
            MemberCreateRequest(email=new_email, access_role="MEMBER"),
        )
        created.append(uuid.UUID(str(member["id"])))
        body = sent[-1]["text"] if sent else ""
        check("an invitation was emailed", bool(sent) and sent[-1]["to"] == new_email)
        check("the email carries a link, not a credential",
              "/reset-password?token=" in body and "welcome=1" in body)
        # Whitespace-normalised: the sentence wraps in the plain-text body,
        # so a raw substring check fails on a line break rather than on the
        # thing it is supposed to be testing.
        check("the email says no password is ever sent",
              "never send passwords by email" in " ".join(body.split()))
        check("the API returns the link for the admin to pass on",
              "/reset-password?token=" in (invite_url or ""), str(invite_url))

        fresh = db.query(User).filter(User.id == member["id"]).first()
        check("the account has no password anyone knows",
              not any(auth_service.verify_password(guess, fresh.password)
                      for guess in ("", "password", new_email, PASSWORD, invite_url)))
        check("account is gated until activation", bool(fresh.must_change_password))

        # The invitation must actually work, and give a LONGER window than a
        # self-service reset — a new joiner is not sitting at the screen.
        invite_raw = body.split("reset-password?token=")[1].split("&")[0]
        inv_row = (db.query(PasswordResetToken)
                   .filter(PasswordResetToken.user_id == fresh.id).first())
        check("invite token is stored with purpose=invite",
              inv_row.purpose == password_reset_service.PURPOSE_INVITE, str(inv_row.purpose))
        check("invite window is days, not minutes",
              (inv_row.expires_at - datetime.now(timezone.utc)) > timedelta(days=6))
        r10 = client.post("/public/auth/reset-password",
                          json={"token": invite_raw, "new_password": b64(NEW_PASSWORD)})
        check("the invitation actually activates the account",
              r10.status_code == 200, f"{r10.status_code} {r10.text[:120]}")
        db.refresh(fresh)
        check("their chosen password now works",
              auth_service.verify_password(NEW_PASSWORD, fresh.password))
        check("activation clears the forced-change gate", not fresh.must_change_password)

        # -- admin reset: a link too, and a short one ----------------------
        print("\nAdmin-initiated reset sends a link, not a password")
        sent.clear()
        _m, reset_url, _mail = admin_service.reset_password(db, actor, fresh.id)
        rbody = sent[-1]["text"] if sent else ""
        check("reset email carries a link", "/reset-password?token=" in rbody)
        check("reset link returned to the admin",
              "/reset-password?token=" in (reset_url or ""))
        db.refresh(fresh)
        check("the old password is dead immediately",
              not auth_service.verify_password(NEW_PASSWORD, fresh.password))
        live = (db.query(PasswordResetToken)
                .filter(PasswordResetToken.user_id == fresh.id,
                        PasswordResetToken.used_at.is_(None)).first())
        check("admin reset issues a RESET token, not an invite",
              live.purpose == password_reset_service.PURPOSE_RESET, str(live.purpose))
        check("and a short window (<= 30 min)",
              (live.expires_at - datetime.now(timezone.utc)) < timedelta(minutes=31))

    finally:
        app.dependency_overrides.pop(get_db, None)
        for uid in created:
            db.query(PasswordResetToken).filter(
                PasswordResetToken.user_id == uid).delete()
            db.query(User).filter(User.id == uid).delete()
        db.commit()
        left = db.query(User).filter(User.email.like("reset-probe-%")).count() + db.query(User).filter(User.email.like("invite-probe-%")).count()
        print(f"\nprobe accounts cleaned up: {left} left")
        db.close()

    print("=" * 60)
    if _failed:
        print(f"FAILED {len(_failed)}/{len(_passed) + len(_failed)}")
        for f in _failed:
            print("  -", f)
        return 1
    print(f"PASSED {len(_passed)}/{len(_passed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
