"""Phase 7 internal contracts — the runtime configuration types.

Split between this file (internal types passed between resolver,
composer, publisher, runner) and `agent_api_schema.py` (HTTP request/
response shapes). Same convention as Phase 5's `rag_schema.py` vs
`rag_api_schema.py`.

Phase 7A only needs the enums + a few dataclasses for CRUD payloads.
The big ones — `ResolvedAgentConfig`, `RetrievalConfig`,
`ModularPrompt`, `ToolPermissions`, `ResolutionStep` — land in 7B/7C
once they're consumed. Stubbed here to anchor the type surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional

# ---------------------------------------------------------------------------
# Locked enums — match the CHECK constraints in the 7A migration verbatim.
# ---------------------------------------------------------------------------

AgentType = Literal[
    "rag_synth",
    "rag_planner",
    "graph_extractor",
    "transcript_analyzer",
    "importance_scorer",
    "summarizer",
    "live_copilot",
]

AgentStatus = Literal["active", "archived"]

VersionState = Literal["draft", "published", "archived"]

DeploymentAction = Literal["publish", "rollback", "unpublish", "eval_gate_failed"]

# `meeting_specific` is reserved for Phase 8 — the CHECK already permits
# it so 7A code paths can validate against the future enum without a
# schema bump.
ConfigScopeType = Literal["organization", "category", "team", "meeting_specific"]


# ---------------------------------------------------------------------------
# Modular prompt — the 8 sections. 7A only stores it on
# `agent_profiles.default_modular_prompt_json` (as a starter template);
# 7B carries it onto `prompt_versions` rows. Defined here now so the
# CRUD validators and the composer (7B) share one shape.
# ---------------------------------------------------------------------------

_SECTION_KEYS = (
    "system", "behavior", "team_rules", "meeting_type",
    "retrieval", "citation", "output", "guardrails",
)


@dataclass(frozen=True)
class ModularPrompt:
    """Eight modular sections. Any section may be empty (omitted at
    composition time). The composer (7B) concatenates in a fixed order
    with double-newline separators."""
    system:        str = ""
    behavior:      str = ""
    team_rules:    str = ""
    meeting_type:  str = ""
    retrieval:     str = ""
    citation:      str = ""
    output:        str = ""
    guardrails:    str = ""

    @classmethod
    def from_dict(cls, raw: Optional[dict]) -> "ModularPrompt":
        raw = raw or {}
        return cls(**{k: (raw.get(k) or "") for k in _SECTION_KEYS})

    def to_dict(self) -> dict[str, str]:
        return {k: getattr(self, k) for k in _SECTION_KEYS}

    @staticmethod
    def section_keys() -> tuple[str, ...]:
        return _SECTION_KEYS


# ---------------------------------------------------------------------------
# CRUD payload shapes — used internally by routers; HTTP schemas wrap them.
# ---------------------------------------------------------------------------


@dataclass
class AgentProfileCreate:
    slug: str
    display_name: str
    agent_type: AgentType
    description: Optional[str] = None
    default_modular_prompt: Optional[ModularPrompt] = None
    eval_gate_required: bool = False
    eval_fixture_set_id: Optional[str] = None
    eval_min_score: Optional[float] = None


@dataclass
class AgentProfilePatch:
    display_name: Optional[str] = None
    description: Optional[str] = None
    default_modular_prompt: Optional[ModularPrompt] = None
    eval_gate_required: Optional[bool] = None
    eval_fixture_set_id: Optional[str] = None
    eval_min_score: Optional[float] = None


@dataclass
class AgentPromptConfigCreate:
    agent_profile_id: str
    scope_type: ConfigScopeType
    scope_id: Optional[int] = None  # required iff scope_type in {category, team}


# ---------------------------------------------------------------------------
# Reserved type stubs — fleshed out in 7B/7C. Defined here so imports
# in router code that *touches* them are stable across slices.
# ---------------------------------------------------------------------------


@dataclass
class RetrievalConfig:
    """Per-agent retrieval knobs. Populated in 7B; in 7A every field
    stays at the defaults that mirror today's `settings.RAG_*` values."""
    top_k_vector: Optional[int] = None
    top_k_final: Optional[int] = None
    max_graph_depth: Optional[int] = None
    tier_widen_threshold: Optional[int] = None
    rerank_strategy: Optional[str] = None
    sources_filter: Optional[str] = None
    include_archived: Optional[bool] = None
    citation_strictness: Optional[str] = None
    entity_expansion_enabled: Optional[bool] = None
    embedding_model: Optional[str] = None
    importance_weight_overrides: dict[str, Optional[float]] = field(default_factory=dict)


@dataclass
class ModelConfig:
    """LLM call config. Populated in 7B."""
    model: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    response_format: Optional[str] = None


@dataclass
class ToolPermissions:
    """Allow/deny lists. Phase 7H plugs the registry in."""
    allowed: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
