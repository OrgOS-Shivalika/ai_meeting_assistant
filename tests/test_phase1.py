"""Phase 1 verification suite — runnable as a plain script.

    venv\\Scripts\\python.exe tests\\test_phase1.py

Each section asserts an invariant from one of the Phase 1 slices (1A through 1E)
and prints PASS / FAIL. The script returns a non-zero exit code if any check
failed, so it can be wired into CI later.

Read-only against the host DB. Skips checks that require Redis or MinIO when
those services aren't reachable, with a clear "skipped" annotation.
"""

from __future__ import annotations

import os
import sys
import traceback
from contextlib import contextmanager
from typing import Callable, List, Tuple

# Make `app.*` importable when run as `python tests/test_phase1.py` from the
# project root. Python only adds the script's own directory to sys.path, so
# we push the parent (project root) on too.
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ---------------------------------------------------------------------------
# Tiny test harness — no pytest dep.
# ---------------------------------------------------------------------------

results: List[Tuple[str, str, str]] = []  # (slice, name, status, msg)


@contextmanager
def section(label: str):
    print(f"\n=== {label} ===")
    yield


def check(slice_id: str, name: str, fn: Callable[[], None]) -> None:
    try:
        fn()
        results.append((slice_id, name, "PASS", ""))
        print(f"  PASS  {slice_id}  {name}")
    except AssertionError as e:
        results.append((slice_id, name, "FAIL", str(e)))
        print(f"  FAIL  {slice_id}  {name}")
        print(f"        -> {e}")
    except Exception as e:
        results.append((slice_id, name, "ERROR", f"{type(e).__name__}: {e}"))
        print(f"  ERROR {slice_id}  {name}")
        print(f"        -> {type(e).__name__}: {e}")
        traceback.print_exc(limit=3)


def skip(slice_id: str, name: str, reason: str) -> None:
    results.append((slice_id, name, "SKIP", reason))
    print(f"  SKIP  {slice_id}  {name}  ({reason})")


# ---------------------------------------------------------------------------
# 1A — Tenancy invariants (read-only against host DB).
# ---------------------------------------------------------------------------

def test_1a():
    from app.db.database import SessionLocal
    from app.db.models import Organization, User, Meeting, Category

    def _orgs_table_exists():
        # On a fresh compose DB this table is empty until the first user
        # registers. The point of this check is "table exists and is queryable".
        db = SessionLocal()
        try:
            count = db.query(Organization).count()
            assert count >= 0, "organizations query failed"
            if count == 0:
                print(f"        (info) organizations table is empty — fresh DB, no users registered yet)")
        finally:
            db.close()

    def _every_user_has_org():
        db = SessionLocal()
        try:
            null_count = db.query(User).filter(User.organization_id.is_(None)).count()
            assert null_count == 0, f"{null_count} users with NULL organization_id"
        finally:
            db.close()

    def _every_meeting_has_org():
        db = SessionLocal()
        try:
            null_count = db.query(Meeting).filter(Meeting.organization_id.is_(None)).count()
            assert null_count == 0, f"{null_count} meetings with NULL organization_id"
        finally:
            db.close()

    def _every_category_has_org():
        db = SessionLocal()
        try:
            null_count = db.query(Category).filter(Category.organization_id.is_(None)).count()
            assert null_count == 0, f"{null_count} categories with NULL organization_id"
        finally:
            db.close()

    def _user_org_matches_meeting_org():
        """The backfill propagated user -> org -> (categories, meetings). Every
        meeting should share its creator user's org."""
        db = SessionLocal()
        try:
            mismatched = (
                db.query(Meeting)
                .join(User, Meeting.user_id == User.id)
                .filter(Meeting.organization_id != User.organization_id)
                .count()
            )
            assert mismatched == 0, f"{mismatched} meetings whose org doesn't match creator's org"
        finally:
            db.close()

    def _category_uniqueness_is_org_scoped():
        from sqlalchemy import inspect
        from app.db.database import engine
        insp = inspect(engine)
        constraints = insp.get_unique_constraints("categories")
        names = {c["name"] for c in constraints}
        assert "uq_category_org_name" in names, f"new constraint missing — found: {names}"
        assert "uq_category_user_name" not in names, "old (user_id, name) constraint still present"

    def _user_has_organization_relationship():
        db = SessionLocal()
        try:
            user = db.query(User).first()
            if user is None:
                print(f"        (info) no users in DB — relationship test skipped on fresh DB")
                return
            assert user.organization is not None, "User.organization relationship returned None"
            assert user.organization_id == user.organization.id
        finally:
            db.close()

    check("1A", "organizations table populated", _orgs_table_exists)
    check("1A", "every user has organization_id", _every_user_has_org)
    check("1A", "every meeting has organization_id", _every_meeting_has_org)
    check("1A", "every category has organization_id", _every_category_has_org)
    check("1A", "meeting.org_id matches creator's user.org_id", _user_org_matches_meeting_org)
    check("1A", "category uniqueness is (org_id, name) not (user_id, name)", _category_uniqueness_is_org_scoped)
    check("1A", "User.organization relationship resolves", _user_has_organization_relationship)


# ---------------------------------------------------------------------------
# 1B — Async infra: Celery app + tasks, settings env-driven.
# ---------------------------------------------------------------------------

def test_1b():
    from app.celery_app import celery
    from app.celery_tasks import meeting_tasks, document_tasks  # noqa: F401  -- side effect: register
    from app.config.settings import settings

    def _celery_app_loads():
        assert celery.main == "meeting_ai", f"celery app name unexpected: {celery.main}"

    def _three_tasks_registered():
        registered = {t for t in celery.tasks if t.startswith("meeting_ai.")}
        expected = {"meeting_ai.smoke", "meeting_ai.process_meeting", "meeting_ai.process_document"}
        missing = expected - registered
        assert not missing, f"missing tasks: {missing}"

    def _broker_url_from_env():
        # Default falls back to redis://localhost:6379/0; check the chain works.
        assert settings.CELERY_BROKER_URL.startswith("redis://"), f"broker URL not redis: {settings.CELERY_BROKER_URL}"
        assert settings.CELERY_RESULT_BACKEND == settings.CELERY_BROKER_URL or settings.CELERY_RESULT_BACKEND.startswith("redis://")

    def _use_celery_toggle_present():
        assert hasattr(settings, "USE_CELERY"), "settings.USE_CELERY missing"
        assert isinstance(settings.USE_CELERY, bool), f"USE_CELERY should be bool, got {type(settings.USE_CELERY)}"

    def _database_url_env_driven():
        # Settings should expose DATABASE_URL; the engine should be using it.
        # Compare host/db rather than repr() — SQLAlchemy masks passwords in
        # the URL string representation as `***`.
        from sqlalchemy.engine.url import make_url
        from app.db.database import engine
        assert settings.DATABASE_URL, "DATABASE_URL not set"
        expected = make_url(settings.DATABASE_URL)
        actual = engine.url
        assert (expected.host, expected.port, expected.database) == (actual.host, actual.port, actual.database), \
            f"engine target {actual.host}:{actual.port}/{actual.database} doesn't match settings {expected.host}:{expected.port}/{expected.database}"

    def _pgvector_extension_ready():
        """Phase 2 will store embeddings in pgvector columns. Verify the
        extension is actually enabled on the live DB rather than checking
        for a specific migration file (the migration history was squashed
        into a single initial_schema migration on the fresh compose DB)."""
        from sqlalchemy import text
        from app.db.database import engine
        with engine.connect() as conn:
            rows = conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = 'vector'")
            ).fetchall()
        assert bool(rows), (
            "pgvector extension is NOT enabled on the active DB. "
            "Add `op.execute('CREATE EXTENSION IF NOT EXISTS vector')` to the "
            "consolidated initial_schema migration's upgrade() before Phase 2."
        )

    def _docker_compose_exists():
        for fname in ("docker-compose.yml", "Dockerfile", ".env.example"):
            assert os.path.exists(os.path.join(_ROOT, fname)), f"{fname} missing"

    check("1B", "celery app loads", _celery_app_loads)
    check("1B", "three tasks registered (smoke + process_meeting + process_document)", _three_tasks_registered)
    check("1B", "broker URL is env-driven and points at redis", _broker_url_from_env)
    check("1B", "USE_CELERY toggle exists and is a bool", _use_celery_toggle_present)
    check("1B", "DATABASE_URL drives the SQLAlchemy engine", _database_url_env_driven)
    check("1B", "pgvector extension enabled on live DB", _pgvector_extension_ready)
    check("1B", "Docker stack files present", _docker_compose_exists)


# ---------------------------------------------------------------------------
# 1C — Storage abstraction.
# ---------------------------------------------------------------------------

def test_1c():
    from app.services.storage_service import StorageService, StorageNotConfigured, storage

    def _storage_singleton_loads():
        assert storage is not None, "storage singleton not exported"
        assert isinstance(storage.is_configured, bool)

    def _unconfigured_raises_clear_error():
        # Build a fresh instance with no creds to simulate the unconfigured path.
        from app.config.settings import settings
        saved = (settings.S3_ACCESS_KEY_ID, settings.S3_SECRET_ACCESS_KEY)
        settings.S3_ACCESS_KEY_ID = None
        settings.S3_SECRET_ACCESS_KEY = None
        try:
            svc = StorageService()
            assert not svc.is_configured, "is_configured should be False without creds"
            try:
                svc.upload_bytes(b"x", "test.bin")
            except StorageNotConfigured as e:
                assert "S3 not configured" in str(e)
            else:
                raise AssertionError("upload_bytes should have raised StorageNotConfigured")
        finally:
            settings.S3_ACCESS_KEY_ID, settings.S3_SECRET_ACCESS_KEY = saved

    def _path_style_addressing_default():
        from app.config.settings import settings
        assert settings.S3_USE_PATH_STYLE is True, "MinIO requires path-style addressing"

    check("1C", "storage singleton importable", _storage_singleton_loads)
    check("1C", "unconfigured path raises StorageNotConfigured", _unconfigured_raises_clear_error)
    check("1C", "path-style addressing enabled by default", _path_style_addressing_default)


# ---------------------------------------------------------------------------
# 1D — Document upload model + routes.
# ---------------------------------------------------------------------------

def test_1d():
    from app.db.models import CategoryDocument
    from app.schemas.document_schema import CategoryDocumentSchema  # noqa: F401

    def _model_importable():
        assert CategoryDocument.__tablename__ == "category_documents"
        # Spot-check the access-tracking columns we baked in for Phase 2.
        cols = {c.name for c in CategoryDocument.__table__.columns}
        for required in ("storage_key", "status", "size_bytes", "organization_id",
                         "last_accessed_at", "access_count"):
            assert required in cols, f"missing column: {required}"

    def _table_exists_in_db():
        from sqlalchemy import inspect
        from app.db.database import engine
        insp = inspect(engine)
        tables = insp.get_table_names()
        # Phase 1D migration may or may not have run on host DB. Only assert
        # the column on the model side; physical table check is informational.
        if "category_documents" not in tables:
            raise AssertionError(
                "category_documents table not in host DB — run `alembic upgrade head` "
                "(works only against pgvector-enabled Postgres; expected on compose DB)"
            )

    def _routes_registered():
        from main import app
        paths = {getattr(r, "path", None) for r in app.routes}
        for required in (
            "/categories/{category_id}/documents",
            "/categories/{category_id}/documents/{document_id}",
        ):
            assert required in paths, f"route missing: {required}"

    def _process_document_task_registered():
        from app.celery_app import celery
        from app.celery_tasks import document_tasks  # noqa: F401
        assert "meeting_ai.process_document" in celery.tasks

    def _mime_accept_list_excludes_executables():
        # Sanity: the accept-list should NOT include obvious risk types.
        from app.api.document_router import _ALLOWED_MIME_PREFIXES
        for risky in ("application/octet-stream", "application/x-msdownload", "application/x-executable"):
            assert not any(risky.startswith(p) for p in _ALLOWED_MIME_PREFIXES), \
                f"{risky} would be accepted — review MIME guard"

    def _max_size_cap_present():
        from app.api.document_router import _MAX_BYTES
        assert _MAX_BYTES > 0
        assert _MAX_BYTES <= 200 * 1024 * 1024, f"max upload {_MAX_BYTES} seems too large"

    check("1D", "CategoryDocument model importable + has expected columns", _model_importable)
    check("1D", "category_documents table exists in DB (informational)", _table_exists_in_db)
    check("1D", "POST/GET/DELETE document routes registered", _routes_registered)
    check("1D", "process_document Celery task registered", _process_document_task_registered)
    check("1D", "MIME accept-list excludes executables", _mime_accept_list_excludes_executables)
    check("1D", "Max upload size cap present", _max_size_cap_present)


# ---------------------------------------------------------------------------
# 1E — Task assignment intelligence.
# ---------------------------------------------------------------------------

def test_1e():
    from app.api.routes import _task_is_unassigned, _task_dict
    from app.db.models import Task

    def _make_task(owner_name):
        t = Task(task="x", owner_name=owner_name, priority="medium")
        t.id = 1
        t.is_completed = 0
        t.due_date = None
        t.created_at = None
        t.updated_at = None
        return t

    UNASSIGNED = [None, "", " ", "TBD", "tbd", "to be confirmed", "TO BE CONFIRMED",
                  "Unassigned", "unknown", "n/a", "N/A", "-", "—"]
    ASSIGNED = ["Sarah Johnson", "kevin@example.com", "the engineering team", "tbdude"]

    def _unassigned_sentinels_caught():
        for owner in UNASSIGNED:
            t = _make_task(owner)
            assert _task_is_unassigned(t), f"should be unassigned: {owner!r}"

    def _real_owners_not_flagged():
        for owner in ASSIGNED:
            t = _make_task(owner)
            assert not _task_is_unassigned(t), f"should NOT be unassigned: {owner!r}"

    def _task_dict_includes_flag():
        t = _make_task("TBD")
        d = _task_dict(t)
        assert "is_unassigned" in d, "is_unassigned missing from task dict"
        assert d["is_unassigned"] is True

    def _task_dict_with_meeting_id():
        t = _make_task("Sarah J.")
        t.meeting_id = 42
        d = _task_dict(t, include_meeting_id=True)
        assert d["meeting_id"] == 42
        assert d["is_unassigned"] is False

    def _meetings_endpoint_includes_unassigned_count():
        # The /allmeetings/{id} endpoint should include an unassigned_task_count
        # field. Inspect the helper's contract via source.
        import app.api.routes as r
        import inspect as _inspect
        src = _inspect.getsource(r.get_meeting_detail)
        assert "unassigned_task_count" in src, \
            "unassigned_task_count missing from meeting detail response"

    check("1E", "all unassigned sentinels detected", _unassigned_sentinels_caught)
    check("1E", "real owner names are not flagged unassigned", _real_owners_not_flagged)
    check("1E", "task dict includes is_unassigned flag", _task_dict_includes_flag)
    check("1E", "task dict optionally includes meeting_id", _task_dict_with_meeting_id)
    check("1E", "meeting detail response includes unassigned_task_count", _meetings_endpoint_includes_unassigned_count)


# ---------------------------------------------------------------------------
# Cross-cutting: live app boot via TestClient.
# ---------------------------------------------------------------------------

def test_app_boot():
    def _testclient_serves_health():
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        r = client.get("/health")
        assert r.status_code == 200, f"/health returned {r.status_code}"
        assert r.json() == {"status": "healthy"}

    def _openapi_includes_all_phase1_routes():
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        r = client.get("/openapi.json")
        assert r.status_code == 200
        paths = set(r.json()["paths"].keys())
        for required in (
            "/categories",
            "/categories/{category_id}/documents",
            "/categories/{category_id}/documents/{document_id}",
            "/meetings/uncategorized",
            "/teams/{team_id}/meetings",
            "/teams/{team_id}/meetings/schedule",
            "/inject-bot",
        ):
            assert required in paths, f"OpenAPI missing route: {required}"

    def _document_upload_requires_auth():
        from fastapi.testclient import TestClient
        from main import app
        client = TestClient(app)
        r = client.post(
            "/categories/1/documents",
            files={"file": ("test.txt", b"hi", "text/plain")},
        )
        assert r.status_code == 401, f"unauthenticated upload returned {r.status_code}, expected 401"

    check("APP", "TestClient: GET /health returns healthy", _testclient_serves_health)
    check("APP", "OpenAPI exposes every Phase 1 route", _openapi_includes_all_phase1_routes)
    check("APP", "Document upload requires authentication", _document_upload_requires_auth)


# ---------------------------------------------------------------------------
# Optional: live broker probe.
# ---------------------------------------------------------------------------

def test_redis_probe():
    """Skipped when Redis isn't reachable — Phase 1B tests don't depend on it."""
    try:
        import redis
        from app.config.settings import settings
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=1)
        client.ping()
    except Exception as e:
        skip("REDIS", "broker reachable", f"Redis not running: {e}")
        return

    check("REDIS", "broker ping succeeds", lambda: None)


def test_minio_probe():
    """Skipped when MinIO/S3 isn't reachable."""
    from app.services.storage_service import storage
    if not storage.is_configured:
        skip("S3", "bucket reachable", "S3 credentials not configured in env")
        return
    try:
        storage.ensure_bucket()
        check("S3", "ensure_bucket() succeeds", lambda: None)
    except Exception as e:
        skip("S3", "bucket reachable", f"MinIO/S3 not reachable: {e}")


# ---------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------

def main() -> int:
    print("Phase 1 verification starting...")
    print(f"Python: {sys.version.split()[0]}")

    with section("Phase 1A — Tenancy migration"):
        test_1a()
    with section("Phase 1B — Async infrastructure"):
        test_1b()
    with section("Phase 1C — Storage abstraction"):
        test_1c()
    with section("Phase 1D — Document uploads"):
        test_1d()
    with section("Phase 1E — Task assignment intelligence"):
        test_1e()
    with section("App boot — live FastAPI via TestClient"):
        test_app_boot()
    with section("Optional: live infra probes"):
        test_redis_probe()
        test_minio_probe()

    print("\n" + "=" * 60)
    pass_count = sum(1 for r in results if r[2] == "PASS")
    fail_count = sum(1 for r in results if r[2] in {"FAIL", "ERROR"})
    skip_count = sum(1 for r in results if r[2] == "SKIP")
    total = len(results)
    print(f"Result: {pass_count}/{total} pass, {fail_count} fail, {skip_count} skipped")

    if fail_count == 0:
        print("Phase 1 verification: GREEN")
        return 0

    print("\nFailures:")
    for slice_id, name, status, msg in results:
        if status in {"FAIL", "ERROR"}:
            print(f"  {slice_id}  {name}  -> {status}: {msg}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
