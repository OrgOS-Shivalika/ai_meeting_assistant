"""@mentions in task comments — parsing, and the two security rules.

Offline, assert-based, no DB and no pytest. `validate_and_normalize` needs a
Session, so it gets a fake that records the filters it was handed — which is
the point: the ORG FILTER is the entire tenant boundary for this feature and a
test that only checked "unknown ids are rejected" would still pass if someone
dropped it.

    python tests/test_mentions.py
"""
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import HTTPException  # noqa: E402

from app.services.kanban import mentions  # noqa: E402

ORG = uuid.uuid4()
OTHER_ORG = uuid.uuid4()
ALICE, BOB = uuid.uuid4(), uuid.uuid4()

checks, failures = 0, []


def check(label, cond):
    global checks
    checks += 1
    print(("  PASS  " if cond else "  FAIL  ") + label)
    if not cond:
        failures.append(label)


class _FakeSession:
    """Answers the single query `validate_and_normalize` issues.

    Records `saw_org_filter` so the test can assert the tenant filter was
    actually applied, not merely that the right rows came back.
    """

    def __init__(self, users):
        self.users = users            # {uuid: (name, org)}
        self.saw_org_filter = None

    def query(self, *cols):
        return self

    def filter(self, *conds):
        for c in conds:
            left = getattr(c, "left", None)
            if left is not None and left.name == "organization_id":
                self.saw_org_filter = c.right.value
            if left is not None and left.name == "id":
                # `IN (...)` — pull the requested ids off the clause.
                self.requested = list(c.right.value)
        return self

    def all(self):
        org = self.saw_org_filter
        return [
            (uid, self.users[uid][0])
            for uid in getattr(self, "requested", [])
            if uid in self.users and self.users[uid][1] == org
        ]


def session():
    return _FakeSession({ALICE: ("Alice Real", ORG), BOB: ("Bob Other", OTHER_ORG)})


print("\n[parsing]")
check("finds a mention", len(mentions.parse_mentions(f"hi @[A]({ALICE}) there")) == 1)
check("plain text yields none", mentions.parse_mentions("no mentions here") == [])
check("an email address is not a mention",
      mentions.parse_mentions("write to a@b.com please") == [])
check("two mentions both found",
      len(mentions.parse_mentions(f"@[A]({ALICE}) and @[B]({BOB})")) == 2)

print("\n[strip — the activity feed has no renderer]")
check("flattened to @Name",
      mentions.strip_mentions(f"x @[Alice]({ALICE}) y") == "x @Alice y")
check("plain text untouched", mentions.strip_mentions("nothing") == "nothing")
check("no raw markup survives",
      "@[" not in mentions.strip_mentions(f"@[Alice]({ALICE})"))

print("\n[ids]")
check("extracts the uuid", mentions.mentioned_user_ids(f"@[A]({ALICE})") == [ALICE])
check("de-duplicates a repeated mention",
      mentions.mentioned_user_ids(f"@[A]({ALICE}) @[A]({ALICE})") == [ALICE])

print("\n[RULE 1 — the tenant boundary]")
s = session()
mentions.validate_and_normalize(s, f"@[A]({ALICE})", organization_id=ORG)
check("the lookup IS filtered by organization_id", s.saw_org_filter == ORG)

try:
    mentions.validate_and_normalize(s, f"@[B]({BOB})", organization_id=ORG)
    check("a user from ANOTHER ORG is rejected", False)
except HTTPException as exc:
    check("a user from ANOTHER ORG is rejected", exc.status_code == 400)

try:
    mentions.validate_and_normalize(
        s, f"@[X]({uuid.uuid4()})", organization_id=ORG)
    check("an unknown user is rejected", False)
except HTTPException as exc:
    check("an unknown user is rejected", exc.status_code == 400)
    # Same message for both, so the response cannot be used to probe for
    # accounts in other organizations.
    check("foreign and unknown are indistinguishable",
          "not a member of this organization" in exc.detail)

try:
    mentions.validate_and_normalize(s, "@[X](" + "-" * 36 + ")", organization_id=ORG)
    check("a pattern-shaped non-uuid is rejected", False)
except HTTPException as exc:
    check("a pattern-shaped non-uuid is rejected", exc.status_code == 400)

print("\n[RULE 2 — the client's display name is never trusted]")
out = mentions.validate_and_normalize(
    session(), f"@[Chief Executive]({ALICE})", organization_id=ORG)
check("name rewritten from the database", f"@[Alice Real]({ALICE})" in out)
check("the spoofed name is gone", "Chief Executive" not in out)

print("\n[limits]")
try:
    body = " ".join(f"@[A]({ALICE})" for _ in range(mentions.MAX_MENTIONS_PER_COMMENT + 1))
    mentions.validate_and_normalize(session(), body, organization_id=ORG)
    check("too many mentions rejected", False)
except HTTPException as exc:
    check("too many mentions rejected", exc.status_code == 400)

check("a body with no mentions is returned untouched",
      mentions.validate_and_normalize(session(), "plain", organization_id=ORG) == "plain")

print("\n" + "=" * 58)
if failures:
    print(f"FAILED {len(failures)}/{checks}")
    for f in failures:
        print("  - " + f)
    sys.exit(1)
print(f"PASSED {checks}/{checks}")
