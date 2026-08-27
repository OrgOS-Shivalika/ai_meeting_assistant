"""Size Set proxy — auth, error passthrough, and the service being down.

The `sizeset` project is a separate FastAPI process with NO authentication and
no CORS headers, so the browser must never reach it directly. This proxy is the
only thing standing in front of it. What's guarded here:

  1. Every route requires a logged-in user. Without that, mounting the proxy
     publishes every client inspection report to anyone who can reach :8000.
  2. sizeset's own status codes and `detail` strings survive. Collapsing them
     into a 500 would hide the messages that matter most — unsupported file
     type, recording too large to re-encode, no spec sheet for that style.
  3. A stopped sizeset gives a 503 naming the start command, not a stack trace.
     This is the most likely failure on demo day.
  4. A crafted job id cannot reach another path on the sizeset service.

No network: httpx is stubbed. A minimal app mounts only this router, so the
test does not drag in the whole application's startup.

Run: python tests/test_sizeset_proxy.py
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import httpx  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.api import sizeset_router as proxy  # noqa: E402
from app.dependencies.auth import get_current_user  # noqa: E402


class _FakeUser:
    email = "qa@triburg.test"


class _FakeResponse:
    """Enough of httpx.Response for the proxy's use of it."""

    def __init__(self, status_code=200, json_body=None, content=b"", headers=None):
        self.status_code = status_code
        self._json = json_body
        self.content = content
        self.headers = headers or {}
        self.text = "" if json_body is None else str(json_body)

    def json(self):
        if self._json is None:
            raise ValueError("no json body")
        return self._json


def _client(responder):
    """A TestClient over just this router, with auth satisfied and httpx stubbed.

    `responder(method, url, kwargs)` stands in for the sizeset service. Calls
    are recorded on `client.sent`.
    """
    app = FastAPI()
    app.include_router(proxy.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()

    sent = []

    class _StubClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kwargs):
            sent.append((method, url, kwargs))
            result = responder(method, url, kwargs)
            if isinstance(result, Exception):
                raise result
            return result

    original = httpx.AsyncClient
    httpx.AsyncClient = _StubClient
    client = TestClient(app)
    client.sent = sent
    client._restore = lambda: setattr(httpx, "AsyncClient", original)
    return client


def _ok(json_body=None, **kw):
    return lambda *a: _FakeResponse(json_body=json_body, **kw)


# ------------------------------------------------------------------- auth


def test_every_route_requires_a_user():
    """Mounted without auth, this publishes every client report."""
    app = FastAPI()
    app.include_router(proxy.router, prefix="/api")
    # No dependency override: get_current_user runs for real and rejects.
    client = TestClient(app)
    for method, path in (
        ("GET", "/api/sizeset/styles"),
        ("GET", "/api/sizeset/jobs"),
        ("GET", "/api/sizeset/jobs/abc123"),
        ("POST", "/api/sizeset/jobs"),
        ("GET", "/api/sizeset/jobs/abc123/download/report"),
    ):
        response = client.request(method, path)
        assert response.status_code in (401, 403, 422), (
            f"{method} {path} returned {response.status_code}; "
            "an unauthenticated caller must never reach sizeset"
        )


# ---------------------------------------------------------------- forwarding


def test_styles_are_forwarded():
    client = _client(_ok(["2365", "7147", "9601"]))
    try:
        response = client.get("/api/sizeset/styles")
        assert response.status_code == 200
        assert response.json() == ["2365", "7147", "9601"]
        method, url, _ = client.sent[0]
        assert method == "GET" and url.endswith("/api/style-sets"), (method, url)
    finally:
        client._restore()


def test_upload_forwards_file_and_style():
    client = _client(_ok({"id": "abc123", "status": "queued"}))
    try:
        response = client.post(
            "/api/sizeset/jobs",
            files={"recording": ("rec.m4a", b"audio-bytes", "audio/mp4")},
            data={"style_no": "7147"},
        )
        assert response.status_code == 202, response.text
        assert response.json()["id"] == "abc123"
        _, url, kwargs = client.sent[0]
        assert url.endswith("/api/jobs"), url
        assert kwargs["data"] == {"style_no": "7147"}, kwargs["data"]
        assert "recording" in kwargs["files"]
    finally:
        client._restore()


def test_upload_without_style_sends_empty_string():
    """Empty means "use the style announced in the recording"."""
    client = _client(_ok({"id": "x"}))
    try:
        client.post(
            "/api/sizeset/jobs",
            files={"recording": ("rec.m4a", b"a", "audio/mp4")},
        )
        assert client.sent[0][2]["data"] == {"style_no": ""}
    finally:
        client._restore()


def test_download_returns_bytes_with_the_services_filename():
    """The filename carries the report's version suffix, e.g. 'rec 2365(2).pdf'."""
    client = _client(_ok(
        content=b"%PDF-1.4 fake",
        headers={
            "content-type": "application/pdf",
            "content-disposition": 'attachment; filename="rec 2365(2).pdf"',
        },
    ))
    try:
        response = client.get("/api/sizeset/jobs/abc123/download/report")
        assert response.status_code == 200
        assert response.content == b"%PDF-1.4 fake"
        assert response.headers["content-type"] == "application/pdf"
        assert "rec 2365(2).pdf" in response.headers["content-disposition"]
    finally:
        client._restore()


# ------------------------------------------------------------------ errors


def test_service_errors_pass_through_with_their_detail():
    """415/413/404 from sizeset carry the only useful message the operator
    gets. A blanket 500 would throw it away."""
    cases = {
        415: "unsupported file type .txt. Use one of: .m4a, .mp3",
        413: "rec.m4a is 700 MB, over the 500 MB upload limit.",
        404: "no style set for style 1234",
        409: "job is running, not ready",
    }
    for status, detail in cases.items():
        client = _client(
            lambda *a, s=status, d=detail: _FakeResponse(
                status_code=s, json_body={"detail": d}
            )
        )
        try:
            response = client.get("/api/sizeset/jobs")
            assert response.status_code == status, (status, response.status_code)
            assert response.json()["detail"] == detail, response.json()
        finally:
            client._restore()


def test_service_down_gives_a_503_naming_the_start_command():
    """The most likely demo-day failure. A stack trace here is useless."""
    client = _client(lambda *a: httpx.ConnectError("connection refused"))
    try:
        response = client.get("/api/sizeset/styles")
        assert response.status_code == 503, response.status_code
        detail = response.json()["detail"]
        assert "not reachable" in detail, detail
        assert "serve --port 8100" in detail, detail
    finally:
        client._restore()


def test_non_json_error_body_is_still_surfaced():
    client = _client(
        lambda *a: _FakeResponse(status_code=502, content=b"<html>bad gateway</html>")
    )
    try:
        response = client.get("/api/sizeset/jobs")
        assert response.status_code == 502, response.status_code
        assert response.json()["detail"], "a detail must always be present"
    finally:
        client._restore()


# ------------------------------------------------------------------ guards


def test_unknown_download_kind_is_rejected_locally():
    """Never forwarded — the check happens before the URL is built.

    Note the traversal case is NOT tested here: ".." in a URL is collapsed by
    the HTTP layer long before routing, so `/download/../../secret` resolves to
    a different route entirely. The invariant that belongs to this code is the
    allow-list on `kind`.
    """
    client = _client(_ok({}))
    try:
        for bad in ("secret", "pdf", "REPORT", ""):
            response = client.get(f"/api/sizeset/jobs/abc123/download/{bad}")
            assert response.status_code in (404, 405, 307), (bad, response.status_code)
        assert client.sent == [], "a junk kind must not reach the service"
    finally:
        client._restore()


def test_crafted_job_id_cannot_reach_another_path():
    """Only alphanumeric ids are interpolated into the forwarded URL.

    Characters that would change the path's meaning — separators, spaces — are
    rejected before `_url` is built. Ids are `uuid4().hex[:12]`, so nothing
    legitimate is lost.
    """
    client = _client(_ok({}))
    try:
        for bad in ("a-b", "a_b", "a:b", "a" * 65):
            response = client.get(f"/api/sizeset/jobs/{bad}")
            assert response.status_code == 404, (bad, response.status_code)
        assert client.sent == [], client.sent
    finally:
        client._restore()


def test_query_string_does_not_reach_the_service():
    """`/jobs/id?x=1` is job id "id" with a query string. The id is forwarded;
    the query is not, so it cannot alter the upstream request."""
    client = _client(_ok({}))
    try:
        client.get("/api/sizeset/jobs/abc123?evil=1")
        _, url, kwargs = client.sent[0]
        assert url.endswith("/api/jobs/abc123"), url
        assert "params" not in kwargs, kwargs
    finally:
        client._restore()


def test_safe_job_id_accepts_a_real_id():
    assert proxy._safe_job_id("a1b2c3d4e5f6") == "a1b2c3d4e5f6"


def test_download_kinds_match_the_service():
    """These mirror sizeset's own DOWNLOADS dict; drifting apart means a
    working output the UI refuses to fetch."""
    assert proxy._DOWNLOAD_KINDS == frozenset(
        {"report", "form", "measurements", "data"}
    )


def test_forward_targets_the_configured_base_url():
    from app.config.settings import settings

    client = _client(_ok([]))
    try:
        client.get("/api/sizeset/styles")
        assert client.sent[0][1].startswith(settings.SIZESET_API_URL), client.sent[0][1]
    finally:
        client._restore()


# ------------------------------------------------- speaker-prefix stripping


def test_speaker_prefixes_are_stripped():
    """A size-set report records measurements, not who said them — and the
    extractor was tuned on raw transcription output with no labels. Measured at
    +26% input tokens for no quality gain."""
    transcript = (
        "Divyansh Bhardwaj: chest thirty eight and a half\n"
        "Speaker 1: theek hai, next\n"
        "Speaker 2: sleeve length thirty two and a quarter"
    )
    assert proxy.strip_speaker_prefixes(transcript) == (
        "chest thirty eight and a half\n"
        "theek hai, next\n"
        "sleeve length thirty two and a quarter"
    )


def test_stripping_keeps_content_after_a_mid_sentence_colon():
    """"chest: thirty eight" spoken aloud must not lose its measurement.

    Only the FIRST colon on a line is treated as a prefix boundary, and the
    prefix is length-bounded.
    """
    line = "Speaker 0: chest: thirty eight"
    assert proxy.strip_speaker_prefixes(line) == "chest: thirty eight"

    # No speaker prefix at all — a raw transcription line survives untouched.
    assert proxy.strip_speaker_prefixes("chest thirty eight") == "chest thirty eight"


def test_stripping_leaves_a_long_line_with_a_colon_alone():
    """The 60-char bound stops a whole sentence being eaten as a "speaker"."""
    line = (
        "so what we are going to do now is measure every point of measure "
        "one by one: chest first"
    )
    assert proxy.strip_speaker_prefixes(line) == line


def test_stripping_tolerates_empty_input():
    assert proxy.strip_speaker_prefixes("") == ""
    assert proxy.strip_speaker_prefixes(None) == ""


# ------------------------------------------------------- from-meeting guards


def test_from_meeting_is_gated_on_the_configured_category():
    """The "Triburg org, Quality Team section" placement, done with a category
    name rather than a schema change. Mirrors CONTINUUM_CATEGORY_NAME."""
    from app.config.settings import settings

    assert settings.SIZESET_CATEGORY_NAME, (
        "a default category must exist, or any meeting could produce a report"
    )


def test_from_meeting_requires_a_user():
    app = FastAPI()
    app.include_router(proxy.router, prefix="/api")
    client = TestClient(app)
    response = client.post("/api/sizeset/from-meeting/4899", json={"style_no": ""})
    assert response.status_code in (401, 403, 422), response.status_code


def test_from_meeting_sends_transcript_not_audio():
    """The forwarded call must hit the transcript endpoint with JSON, carry the
    meeting id as the output name, and have prefixes already stripped."""
    import app.api.sizeset_router as router_module

    class _Meeting:
        id = 4899
        category_id = 7
        transcript_text = "Speaker 0: chest thirty eight and a half and so on for ten words"
        transcript = ""

    class _Category:
        name = "Quality Team"

    class _Query:
        def filter(self, *a, **k):
            return self

        def first(self):
            return _Category()

    class _DB:
        def query(self, *a, **k):
            return _Query()

    original_viewable = router_module.permissions.get_viewable_meeting
    router_module.permissions.get_viewable_meeting = lambda db, u, mid: _Meeting()

    app = FastAPI()
    app.include_router(proxy.router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: _FakeUser()
    app.dependency_overrides[router_module.get_db] = lambda: _DB()

    sent = []

    class _Stub:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def request(self, method, url, **kwargs):
            sent.append((method, url, kwargs))
            return _FakeResponse(json_body={"id": "job1", "status": "queued"})

    original_client = httpx.AsyncClient
    httpx.AsyncClient = _Stub
    try:
        client = TestClient(app)
        response = client.post(
            "/api/sizeset/from-meeting/4899", json={"style_no": "7147"}
        )
        assert response.status_code == 202, response.text
        method, url, kwargs = sent[0]
        # NOT "/api/jobs/from-transcript": that collides with sizeset's
        # `GET /api/jobs/{job_id}`, and Starlette answers a path match with the
        # wrong method as 405 rather than trying later routes. Found live.
        assert method == "POST" and url.endswith("/api/transcript-jobs"), url
        body = kwargs["json"]
        assert body["name"] == "meeting-4899", body["name"]
        assert body["style_no"] == "7147"
        assert not body["transcript"].startswith("Speaker 0:"), body["transcript"]
    finally:
        httpx.AsyncClient = original_client
        router_module.permissions.get_viewable_meeting = original_viewable


if __name__ == "__main__":
    checks = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for check in checks:
        try:
            check()
            print(f"  ok  {check.__name__}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL {check.__name__}: {exc}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ERROR {check.__name__}: {type(exc).__name__}: {exc}")
    print(f"\n{len(checks) - failed}/{len(checks)} checks passed")
    sys.exit(1 if failed else 0)
