"""Phase 5F evaluation cases.

Each case is a structured dict describing:
  - the question to ask
  - the scope to ask it at (symbolic — resolved against the fixture)
  - retrieval assertions (must_contain_entity, expected_relationship,
    must_contain_chunk_from_meeting, etc.) — graded in BOTH stub and
    real modes
  - synthesis assertions (must_contain_text, expected_status,
    min_citations) — graded in real mode ONLY (stub mode skips synth
    grading because the synth response is canned)

The symbolic scope ids reference fields on `CanonicalFixture`:
  - team_backend, team_frontend, team_sales
  - cat_engineering, cat_sales
Use `auto` or `global` (no id needed) for org-wide queries.

Adding a case:
  1. Append a new dict to `CASES`.
  2. Pick a unique `id` (kebab-case, used in CLI filters + report).
  3. Reference entities by their canonical_name (lowercase trim).
  4. Reference relationships as (subject, predicate, object) tuples
     of canonical names.
"""
from __future__ import annotations

from typing import Literal, TypedDict


SymbolicScope = Literal[
    "auto",
    "global",
    "team_backend", "team_frontend", "team_sales",
    "cat_engineering", "cat_sales",
]


class ExpectedRelationship(TypedDict, total=False):
    subject: str
    predicate: str
    object: str


class SynthExpectations(TypedDict, total=False):
    # Substrings the answer must contain (case-insensitive).
    must_contain_text: list[str]
    # Substrings the answer must NOT contain.
    must_not_contain_text: list[str]
    # Acceptable final statuses. Default: ['completed'].
    expected_status_one_of: list[str]
    # Minimum number of valid citations.
    min_citations: int


class EvalCase(TypedDict, total=False):
    id: str
    description: str
    query: str
    scope: SymbolicScope
    sources: Literal["all", "meetings", "documents"]
    # Retrieval assertions (graded in stub + real)
    must_contain_entity_canonical: list[str]
    must_not_contain_entity_canonical: list[str]
    must_contain_relationship: list[ExpectedRelationship]
    must_contain_chunk_from_meeting_title_contains: list[str]
    must_contain_chunk_from_document_name_contains: list[str]
    must_have_context: bool  # True = bundle.has_context must be True
    # Synthesis assertions (graded in real mode only)
    synth: SynthExpectations


CASES: list[EvalCase] = [
    # -----------------------------------------------------------------------
    # Factual queries — should anchor and surface the right entity + chunk
    # -----------------------------------------------------------------------
    {
        "id": "helios-leader-at-team-scope",
        "description": "Anchored at team Backend; expects Alice + Helios + the leads relationship.",
        "query": "Who is leading the Helios project?",
        "scope": "team_backend",
        "must_contain_entity_canonical": ["helios", "alice"],
        "must_contain_relationship": [
            {"subject": "alice", "predicate": "leads", "object": "helios"},
        ],
        "must_contain_chunk_from_meeting_title_contains": ["Q3 Planning"],
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["Alice"],
            "must_not_contain_text": ["I don't have enough information"],
            "min_citations": 1,
        },
    },
    {
        "id": "helios-depends-on-phoenix",
        "description": "Should surface the Helios-depends_on-Phoenix relationship + the doc chunk that describes it.",
        "query": "What does Helios depend on?",
        "scope": "team_backend",
        "must_contain_entity_canonical": ["helios", "phoenix"],
        "must_contain_relationship": [
            {"subject": "helios", "predicate": "depends_on", "object": "phoenix"},
        ],
        "must_contain_chunk_from_document_name_contains": ["Backend Architecture"],
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["Phoenix"],
            "min_citations": 1,
        },
    },
    {
        "id": "graph-expansion-from-alice",
        "description": (
            "Critical: query anchors on Alice only; Helios should "
            "appear via graph expansion (Alice -> leads -> Helios)."
        ),
        "query": "What is Alice working on?",
        "scope": "team_backend",
        "must_contain_entity_canonical": ["alice", "helios"],
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["Helios"],
            "min_citations": 1,
        },
    },
    # -----------------------------------------------------------------------
    # Cross-source synthesis — the Helios topic appears in BOTH meetings and
    # documents; the answer should be able to cite either.
    # -----------------------------------------------------------------------
    {
        "id": "oauth2-cross-source",
        "description": "OAuth2 is mentioned in both Q3 planning meeting and the Backend Architecture doc.",
        "query": "What did we decide about OAuth2?",
        "scope": "team_backend",
        "must_contain_entity_canonical": ["oauth2"],
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["OAuth"],
            "min_citations": 1,
        },
    },
    # -----------------------------------------------------------------------
    # Document-only path
    # -----------------------------------------------------------------------
    {
        "id": "enterprise-tier-pricing",
        "description": "Sales Playbook doc, category Sales scope.",
        "query": "What's our enterprise tier pricing?",
        "scope": "cat_sales",
        "must_contain_entity_canonical": ["enterprise tier"],
        "must_contain_chunk_from_document_name_contains": ["Sales Playbook"],
        "must_have_context": True,
        "synth": {
            "must_contain_text": ["enterprise"],
            "min_citations": 1,
        },
    },
    # -----------------------------------------------------------------------
    # Scope routing — same canonical entity name (Alice) exists at two
    # scopes; the team-scoped query should only see the team-scoped Alice.
    # -----------------------------------------------------------------------
    {
        "id": "scope-routing-alice-isolation",
        "description": (
            "Alice exists at team Backend AND at category Sales scope. "
            "Asking at team scope must surface team-scope relationships only."
        ),
        "query": "Tell me about Alice's commitments",
        "scope": "team_backend",
        "must_contain_entity_canonical": ["alice"],
        "must_have_context": True,
    },
    # -----------------------------------------------------------------------
    # Tier widening — empty team Enterprise Sales should widen to category
    # -----------------------------------------------------------------------
    {
        "id": "tier-widen-from-empty-team",
        "description": "Team Enterprise Sales has no chunks; should widen to category Sales.",
        "query": "What's the NorthStar customer status?",
        "scope": "team_sales",
        "must_contain_entity_canonical": ["northstar"],
        "must_have_context": True,
    },
    # -----------------------------------------------------------------------
    # Auto scope — let the planner decide
    # -----------------------------------------------------------------------
    {
        "id": "auto-scope-broad-question",
        "description": "Org-wide question; planner should pick a sensible scope.",
        "query": "Summarize what we're building",
        "scope": "auto",
        "must_have_context": True,
        # Skip strict entity check — auto scope is fuzzy by design.
    },
    # -----------------------------------------------------------------------
    # Source filter — restrict to documents only
    # -----------------------------------------------------------------------
    {
        "id": "documents-only-filter",
        "description": "sources='documents' must exclude meeting chunks entirely.",
        "query": "What are the Helios authentication details?",
        "scope": "team_backend",
        "sources": "documents",
        "must_contain_chunk_from_document_name_contains": ["Backend Architecture"],
        "must_have_context": True,
    },
    # -----------------------------------------------------------------------
    # No-context guard — query something the fixture genuinely doesn't know.
    # We don't require status=no_context because tier widening may surface
    # SOMETHING; we just require the answer doesn't fabricate.
    # -----------------------------------------------------------------------
    {
        "id": "no-fabrication-on-unknown-topic",
        "description": "Query has no real signal in the fixture — answer must not fabricate.",
        "query": "What did we decide about the time-travel feature?",
        "scope": "global",
        "synth": {
            "expected_status_one_of": ["no_context", "completed"],
            "must_not_contain_text": ["time-travel feature works by", "the time-travel"],
        },
    },
]
