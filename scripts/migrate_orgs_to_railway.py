"""One-shot migration: copy TWO orgs' complete data from LOCAL Postgres
to RAILWAY Postgres.

Strategy:
  * Stream each table via server-side `COPY (SELECT ... WHERE org...) TO
    STDOUT WITH CSV HEADER` → pipe into `COPY <table> FROM STDIN` on the
    target. Fast, no in-memory materialization of vectors/JSONB.
  * Tables are ordered by FK dependency (parents first).
  * All inserts run inside ONE Railway transaction — if any table fails,
    the whole migration rolls back.
  * After copy, reset serial sequences on tables that use them, so future
    app-side inserts don't collide with migrated IDs.

Prereqs on the Railway side:
  * `CREATE EXTENSION vector;`
  * `alembic upgrade head` has been run (schema exists, tables empty).

Usage:
  python scripts/migrate_orgs_to_railway.py "<railway-postgres-url>"

If the URL argument is omitted the script prompts for it interactively.
"""
from __future__ import annotations

import io
import sys

import psycopg2

# ----------------------------------------------------------------------
# Configuration — the two orgs we're migrating
# ----------------------------------------------------------------------
LOCAL_URL = "postgresql://postgres:postgres@localhost:5433/meeting_ai"
ORG_IDS = (
    "18c012f4-e967-4e35-b2db-04aed20f8ae7",  # divyansh bhardwaj's Workspace
    "118c6fa2-cc74-4b1b-a359-8e85c18b3150",  # Raahulll's Workspace
)
_ORG_SQL = ",".join(f"'{o}'::uuid" for o in ORG_IDS)

# ----------------------------------------------------------------------
# Migration plan
#   (table_name, SELECT statement that filters to these two orgs)
# Ordered so parents are inserted before children.
# ----------------------------------------------------------------------
TABLES: list[tuple[str, str]] = [
    # ---- Roots: no dependencies ----
    ("organizations",
        f"SELECT * FROM organizations WHERE id IN ({_ORG_SQL})"),
    ("users",
        f"SELECT * FROM users WHERE organization_id IN ({_ORG_SQL})"),
    ("categories",
        f"SELECT * FROM categories WHERE organization_id IN ({_ORG_SQL})"),
    ("teams",
        f"SELECT t.* FROM teams t "
        f"JOIN categories c ON t.category_id = c.id "
        f"WHERE c.organization_id IN ({_ORG_SQL})"),

    # ---- Meetings + their dependents ----
    # Kanban is BEFORE tasks — tasks.board_id references kanban_boards.
    ("meetings",
        f"SELECT * FROM meetings WHERE organization_id IN ({_ORG_SQL})"),
    ("participants",
        f"SELECT p.* FROM participants p "
        f"JOIN meetings m ON p.meeting_id = m.id "
        f"WHERE m.organization_id IN ({_ORG_SQL})"),
    ("kanban_boards",
        f"SELECT * FROM kanban_boards WHERE organization_id IN ({_ORG_SQL})"),
    ("kanban_columns",
        f"SELECT kc.* FROM kanban_columns kc "
        f"JOIN kanban_boards kb ON kc.board_id = kb.id "
        f"WHERE kb.organization_id IN ({_ORG_SQL})"),
    ("tasks",
        f"SELECT t.* FROM tasks t "
        f"JOIN meetings m ON t.meeting_id = m.id "
        f"WHERE m.organization_id IN ({_ORG_SQL})"),
    ("task_activity",
        f"SELECT ta.* FROM task_activity ta "
        f"JOIN tasks t ON ta.task_id = t.id "
        f"JOIN meetings m ON t.meeting_id = m.id "
        f"WHERE m.organization_id IN ({_ORG_SQL})"),
    ("task_comments",
        f"SELECT tc.* FROM task_comments tc "
        f"JOIN tasks t ON tc.task_id = t.id "
        f"JOIN meetings m ON t.meeting_id = m.id "
        f"WHERE m.organization_id IN ({_ORG_SQL})"),
    ("meeting_chunks",
        f"SELECT * FROM meeting_chunks WHERE organization_id IN ({_ORG_SQL})"),
    ("closing_briefings",
        f"SELECT * FROM closing_briefings WHERE organization_id IN ({_ORG_SQL})"),
    ("graph_extraction_runs",
        f"SELECT * FROM graph_extraction_runs WHERE organization_id IN ({_ORG_SQL})"),
    ("importance_runs",
        f"SELECT * FROM importance_runs WHERE organization_id IN ({_ORG_SQL})"),

    # ---- Knowledge graph ----
    ("entities",
        f"SELECT * FROM entities WHERE organization_id IN ({_ORG_SQL})"),
    ("entity_mentions",
        f"SELECT * FROM entity_mentions WHERE organization_id IN ({_ORG_SQL})"),
    ("relationships",
        f"SELECT * FROM relationships WHERE organization_id IN ({_ORG_SQL})"),
    ("relationship_mentions",
        f"SELECT * FROM relationship_mentions WHERE organization_id IN ({_ORG_SQL})"),
    ("entity_merge_suggestions",
        f"SELECT * FROM entity_merge_suggestions WHERE organization_id IN ({_ORG_SQL})"),

    # ---- Documents ----
    ("category_documents",
        f"SELECT * FROM category_documents WHERE organization_id IN ({_ORG_SQL})"),
    ("team_documents",
        f"SELECT * FROM team_documents WHERE organization_id IN ({_ORG_SQL})"),
    ("document_chunks",
        f"SELECT * FROM document_chunks WHERE organization_id IN ({_ORG_SQL})"),

    # ---- Memory (Phase 3) ----
    ("org_memory_facts",
        f"SELECT * FROM org_memory_facts WHERE organization_id IN ({_ORG_SQL})"),

    # ---- Agent config / prompts / audit ----
    ("agent_profiles",
        f"SELECT * FROM agent_profiles WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_config_epochs",
        f"SELECT * FROM agent_config_epochs WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_eval_runs",
        f"SELECT * FROM agent_eval_runs WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_prompt_configs",
        f"SELECT * FROM agent_prompt_configs WHERE organization_id IN ({_ORG_SQL})"),
    ("prompt_versions",
        f"SELECT * FROM prompt_versions WHERE organization_id IN ({_ORG_SQL})"),
    ("prompt_deployments",
        f"SELECT * FROM prompt_deployments WHERE organization_id IN ({_ORG_SQL})"),
    ("prompt_test_runs",
        f"SELECT * FROM prompt_test_runs WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_performance_daily",
        f"SELECT * FROM agent_performance_daily WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_runtime_logs",
        f"SELECT * FROM agent_runtime_logs WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_tool_invocations",
        f"SELECT * FROM agent_tool_invocations WHERE organization_id IN ({_ORG_SQL})"),
    ("agent_audit_events",
        f"SELECT * FROM agent_audit_events WHERE organization_id IN ({_ORG_SQL})"),
    ("workspace_behavior_overrides",
        f"SELECT * FROM workspace_behavior_overrides WHERE organization_id IN ({_ORG_SQL})"),
    ("workspace_template_links",
        f"SELECT * FROM workspace_template_links WHERE organization_id IN ({_ORG_SQL})"),
    ("template_provisioning_jobs",
        f"SELECT * FROM template_provisioning_jobs WHERE organization_id IN ({_ORG_SQL})"),

    # ---- RAG audit ----
    ("rag_conversations",
        f"SELECT * FROM rag_conversations WHERE organization_id IN ({_ORG_SQL})"),
    ("rag_query_runs",
        f"SELECT * FROM rag_query_runs WHERE organization_id IN ({_ORG_SQL})"),
    ("rag_chunk_access_events",
        f"SELECT * FROM rag_chunk_access_events WHERE organization_id IN ({_ORG_SQL})"),
    ("rag_citation_click_events",
        f"SELECT * FROM rag_citation_click_events WHERE organization_id IN ({_ORG_SQL})"),
]

# Tables whose primary key is a serial/bigserial and needs a sequence bump
# after we insert rows with explicit IDs. UUID-keyed tables are omitted.
SEQUENCE_TABLES: list[tuple[str, str]] = [
    ("meetings", "id"),
    ("categories", "id"),
    ("teams", "id"),
    ("tasks", "id"),
    ("participants", "id"),
    ("meeting_chunks", "id"),
    ("closing_briefings", "id"),
    ("importance_runs", "id"),
    ("graph_extraction_runs", "id"),
    ("kanban_boards", "id"),
    ("kanban_columns", "id"),
    ("category_documents", "id"),
    ("team_documents", "id"),
    ("document_chunks", "id"),
    ("agent_performance_daily", "id"),
    ("agent_runtime_logs", "id"),
    ("agent_tool_invocations", "id"),
    ("agent_audit_events", "id"),
    ("agent_eval_runs", "id"),
    ("task_activity", "id"),
    ("task_comments", "id"),
    ("workspace_behavior_overrides", "id"),
    ("workspace_template_links", "id"),
    ("template_provisioning_jobs", "id"),
    ("rag_query_runs", "id"),
    ("rag_chunk_access_events", "id"),
    ("rag_citation_click_events", "id"),
]


def preflight_railway(railway_conn) -> bool:
    """Warn (but don't block) if any target table already has rows.
    Rerunning against a non-empty target risks duplicate-key errors mid-run
    and a rollback — user should truncate first if this fires."""
    with railway_conn.cursor() as cur:
        hot = []
        for tbl, _ in TABLES:
            try:
                cur.execute(f"SELECT count(*) FROM {tbl}")
                n = cur.fetchone()[0]
                if n > 0:
                    hot.append((tbl, n))
            except psycopg2.errors.UndefinedTable:
                railway_conn.rollback()
                print(f"  ! table {tbl} missing on Railway — did alembic upgrade run?")
                return False
    if hot:
        print("\n  Warning — these Railway tables already contain rows:")
        for tbl, n in hot:
            print(f"    {tbl}: {n}")
        ans = input("\n  Continue anyway? (y/N): ").strip().lower()
        return ans == "y"
    return True


def relax_fk_checks(railway_conn) -> None:
    """Disable FK / trigger validation for this session so we don't have
    to hand-order 40+ tables perfectly. Constraints are still declared
    and will be enforced by future INSERTs — this ONLY affects the
    ongoing bulk COPY. Requires superuser or `replication` role, which
    Railway's default postgres user has."""
    with railway_conn.cursor() as cur:
        cur.execute("SET session_replication_role = replica")


def copy_table(local_conn, railway_conn, table: str, query: str) -> int:
    """Server-side COPY: SELECT ... TO STDOUT locally, FROM STDIN to Railway.
    Uses CSV with headers so column order is explicit — safer than binary
    when local and Railway schemas were built independently."""
    buf = io.StringIO()
    with local_conn.cursor() as lcur:
        lcur.copy_expert(
            f"COPY ({query}) TO STDOUT WITH (FORMAT CSV, HEADER TRUE)",
            buf,
        )
    buf.seek(0)
    header_line = buf.readline().rstrip("\r\n")
    if not header_line:
        return 0
    payload = buf.read()
    if not payload.strip():
        return 0

    # Reassemble a mini CSV (header + payload) and stream into Railway.
    cols = [c.strip() for c in header_line.split(",")]
    cols_sql = ", ".join(f'"{c}"' for c in cols)
    injected = io.StringIO(header_line + "\n" + payload)
    with railway_conn.cursor() as rcur:
        rcur.copy_expert(
            f"COPY {table} ({cols_sql}) FROM STDIN WITH (FORMAT CSV, HEADER TRUE)",
            injected,
        )
        return rcur.rowcount


def bump_sequences(railway_conn) -> None:
    """After bulk COPY with explicit PK values, the underlying sequence
    still points at its old max. Left alone, the app's next INSERT would
    hand out an id that already exists → unique-violation. Advance each
    sequence past the highest imported id.

    Skips tables whose PK is a UUID or has no attached sequence — MAX()
    isn't defined for uuid and pg_get_serial_sequence returns NULL for
    non-serials."""
    bumped = 0
    with railway_conn.cursor() as cur:
        for tbl, pk in SEQUENCE_TABLES:
            cur.execute(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name=%s AND column_name=%s",
                (tbl, pk),
            )
            row = cur.fetchone()
            if not row or row[0] not in ("integer", "bigint", "smallint"):
                continue
            cur.execute(f"SELECT pg_get_serial_sequence('{tbl}', '{pk}')")
            seq = cur.fetchone()[0]
            if not seq:
                continue
            cur.execute(
                f"SELECT setval(%s, COALESCE((SELECT MAX({pk}) FROM {tbl}), 1), true)",
                (seq,),
            )
            bumped += 1
    print(f"  Sequences advanced ({bumped} tables)")


def main() -> None:
    if len(sys.argv) > 1:
        railway_url = sys.argv[1]
    else:
        railway_url = input("Railway Postgres URL: ").strip()
    if not railway_url:
        print("No Railway URL given. Aborting.")
        sys.exit(1)

    print(f"\nMigrating orgs:")
    for o in ORG_IDS:
        print(f"  - {o}")
    print(f"\nLocal:   {LOCAL_URL}")
    print(f"Railway: {railway_url[:60]}...\n")

    local = psycopg2.connect(LOCAL_URL)
    railway = psycopg2.connect(railway_url)
    railway.autocommit = False

    try:
        if not preflight_railway(railway):
            print("\nAborted by user (or preflight failed).")
            return

        # Turn off FK / trigger validation for this session so table
        # ordering doesn't have to be perfect. Constraints are still
        # declared, still enforced by the app afterwards.
        relax_fk_checks(railway)
        print("  FK checks relaxed for this session (bulk COPY)")

        total = 0
        for tbl, query in TABLES:
            try:
                n = copy_table(local, railway, tbl, query)
            except Exception as e:
                print(f"  ! {tbl:40s} FAILED: {e}")
                raise
            marker = f"{n:>6d}" if n else "  0"
            print(f"  {tbl:40s} rows copied: {marker}")
            total += n

        railway.commit()
        print(f"\n✓ Data committed. Total rows: {total}")

        # Sequence bump is in its own transaction so a failure here
        # doesn't cost us the 8k rows we just landed. Safe to re-run
        # by hand if it errors — advancing a sequence is idempotent.
        try:
            bump_sequences(railway)
            railway.commit()
        except Exception as seq_err:
            railway.rollback()
            print(f"\n! sequence bump failed (data is safe): {seq_err}")
            print("  Re-run just this step, or bump each table's sequence manually.")
    except Exception as e:
        railway.rollback()
        print(f"\n✗ Rolled back due to error: {e}")
        raise
    finally:
        local.close()
        railway.close()


if __name__ == "__main__":
    main()
