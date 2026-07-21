"""Smoke test — Recall webhook signature verification.

Fires three POSTs at the local backend and asserts:
  1. Unsigned request → 401 Invalid webhook signature
  2. Signed request with mismatched secret → 401
  3. Signed request with the real secret → 200

Prereqs:
  - FastAPI dev server running on http://localhost:8000
  - RECALL_WEBHOOK_SECRET set in the SAME environment the server reads.
    Export it (or add to .env) BEFORE starting the server.

Run:
    export RECALL_WEBHOOK_SECRET="whsec_yourfreshkey"
    make dev          # or however you start uvicorn
    # in another shell:
    python -m scripts.smoke_webhook_signature
"""
from __future__ import annotations

import json
import os
import sys

import requests
from svix.webhooks import Webhook

# Import settings first — it calls load_dotenv() so the same .env the
# FastAPI server reads becomes visible to this script.
from app.config.settings import settings  # noqa: F401,E402

MEETING_ID = int(os.getenv("SMOKE_MEETING_ID", "1"))
URL = f"http://localhost:8000/webhook/recall/{MEETING_ID}"

payload = {
    "event": "bot.status_change",
    "data": {"code": "smoke_test", "sub_code": None},
}
body = json.dumps(payload).encode("utf-8")


def sign(secret: str, msg_id: str = "msg_smoke_1") -> dict:
    """Return the three Svix headers for a body signed with `secret`."""
    wh = Webhook(secret)
    signature = wh.sign(msg_id=msg_id, timestamp=_now(), data=body.decode("utf-8"))
    return {
        "svix-id": msg_id,
        "svix-timestamp": str(int(_now().timestamp())),
        "svix-signature": signature,
    }


def _now():
    from datetime import datetime, timezone
    return datetime.now(timezone.utc)


def main() -> None:
    real_secret = os.getenv("RECALL_WEBHOOK_SECRET")
    if not real_secret:
        print("[FAIL] RECALL_WEBHOOK_SECRET must be set for this test.")
        sys.exit(1)

    print(f"POST {URL}")
    print("-" * 60)

    # 1. Unsigned
    r = requests.post(URL, data=body, headers={"content-type": "application/json"})
    ok = r.status_code == 401
    print(f"[{'OK' if ok else 'FAIL'}] Unsigned request → {r.status_code} (want 401)")

    # 2. Signed with wrong secret
    bad_headers = sign("whsec_" + "A" * 40)
    bad_headers["content-type"] = "application/json"
    r = requests.post(URL, data=body, headers=bad_headers)
    ok = r.status_code == 401
    print(f"[{'OK' if ok else 'FAIL'}] Wrong-secret signature → {r.status_code} (want 401)")

    # 3. Signed with the real secret
    good_headers = sign(real_secret)
    good_headers["content-type"] = "application/json"
    r = requests.post(URL, data=body, headers=good_headers)
    ok = r.status_code == 200
    print(f"[{'OK' if ok else 'FAIL'}] Valid signature → {r.status_code} (want 200)")
    if r.status_code != 200:
        print(f"    body: {r.text[:200]}")


if __name__ == "__main__":
    main()
