"""Phase 7 HTTP request/response shapes.

Strict-envelope Pydantic. Validation in this file mirrors the
constraints in the 7A migration's CHECK clauses — kept in sync
manually (no codegen).
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.agent_schema import (
    AgentStatus, AgentType, ConfigScopeType, DeploymentAction,
    ModularPrompt, VersionState,
)


# ---------------------------------------------------------------------------
# AgentProfile shapes
# ---------------------------------------------------------------------------

_SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]{1,62}[a-z0-9]$")
_ALL_AGENT_TYPES = (
    "rag_synth", "rag_planner", "graph_extractor", "transcript_analyzer",
    "importance_scorer", "summarizer", "live_copilot",
)


class ModularPromptIn(BaseModel):
    """8 modular sections as inputs. All optional — omitted keys
    render to empty strings at composition time."""
    model_config = ConfigDict(extra="forbid")

    system:       Optional[str] = None
    behavior:     Optional[str] = None
    team_rules:   Optional[str] = None
    meeting_type: Optional[str] = None
    retrieval:    Optional[str] = None
    citation:     Optional[str] = None
    output:       Optional[str] = None
    guardrails:   Optional[str] = None

    def to_modular_prompt(self) -> ModularPrompt:
        return ModularPrompt.from_dict(self.model_dump(exclude_none=False))


class AgentProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slug: str = Field(..., min_length=3, max_length=64)
    display_name: str = Field(..., min_length=1, max_length=200)
    agent_type: str = Field(..., max_length=32)
    description: Optional[str] = None
    default_modular_prompt: Optional[ModularPromptIn] = None
    eval_gate_required: bool = False
    eval_fixture_set_id: Optional[UUID] = None
    eval_min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    @field_validator("slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase, start with a letter, end with "
                "letter/digit, and use only [a-z0-9_-]"
            )
        return v

    @field_validator("agent_type")
    @classmethod
    def _agent_type_known(cls, v: str) -> str:
        if v not in _ALL_AGENT_TYPES:
            raise ValueError(
                f"agent_type must be one of {sorted(_ALL_AGENT_TYPES)}"
            )
        return v


class AgentProfilePatchRequest(BaseModel):
    """Partial update. None means "leave unchanged"."""
    model_config = ConfigDict(extra="forbid")

    display_name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    default_modular_prompt: Optional[ModularPromptIn] = None
    eval_gate_required: Optional[bool] = None
    eval_fixture_set_id: Optional[UUID] = None
    eval_min_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class AgentProfileDuplicateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_slug: str = Field(..., min_length=3, max_length=64)
    new_display_name: str = Field(..., min_length=1, max_length=200)

    @field_validator("new_slug")
    @classmethod
    def _slug_shape(cls, v: str) -> str:
        if not _SLUG_RE.match(v):
            raise ValueError(
                "slug must be lowercase, start with a letter, end with "
                "letter/digit, and use only [a-z0-9_-]"
            )
        return v


class AgentProfileResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    slug: str
    display_name: str
    description: Optional[str]
    agent_type: str
    status: AgentStatus
    default_modular_prompt_json: dict
    eval_gate_required: bool
    eval_fixture_set_id: Optional[UUID]
    eval_min_score: Optional[float]
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# AgentPromptConfig shapes
# ---------------------------------------------------------------------------

_CONFIG_SCOPE_TYPES = ("organization", "category", "team", "meeting_specific")


class AgentPromptConfigCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_profile_id: UUID
    scope_type: str = Field(..., max_length=32)
    scope_id: Optional[int] = Field(default=None, ge=1)

    @field_validator("scope_type")
    @classmethod
    def _scope_type_known(cls, v: str) -> str:
        if v not in _CONFIG_SCOPE_TYPES:
            raise ValueError(
                f"scope_type must be one of {sorted(_CONFIG_SCOPE_TYPES)}"
            )
        # 7A does not accept meeting_specific from the API — the column
        # space is reserved but Phase 8 turns it on. Block at the API
        # layer until then.
        if v == "meeting_specific":
            raise ValueError(
                "scope_type 'meeting_specific' is reserved for a later phase"
            )
        return v

    def model_post_init(self, __context) -> None:  # type: ignore[override]
        # Cross-field validation mirrors the DB CHECK.
        if self.scope_type in ("organization", "meeting_specific"):
            if self.scope_id is not None:
                raise ValueError(
                    f"scope_id must be null when scope_type='{self.scope_type}'"
                )
        else:  # category, team
            if self.scope_id is None:
                raise ValueError(
                    f"scope_id is required when scope_type='{self.scope_type}'"
                )


class AgentPromptConfigResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    agent_profile_id: UUID
    scope_type: ConfigScopeType
    scope_id: Optional[int]
    active_version_id: Optional[UUID]
    status: AgentStatus
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime


# ---------------------------------------------------------------------------
# Filters / list query params
# ---------------------------------------------------------------------------


class AgentProfileListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_type: Optional[str] = None
    status: Optional[AgentStatus] = None
    limit: int = Field(default=50, ge=1, le=200)


class AgentPromptConfigListFilters(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_profile_id: Optional[UUID] = None
    scope_type: Optional[ConfigScopeType] = None
    status: Optional[AgentStatus] = None
    limit: int = Field(default=50, ge=1, le=200)


# ---------------------------------------------------------------------------
# Agent types catalog — drives the UI's "create agent" dropdown
# ---------------------------------------------------------------------------


class AgentTypeDescriptor(BaseModel):
    """One entry per supported agent_type."""
    model_config = ConfigDict(extra="forbid")

    agent_type: str
    display_name: str
    description: str
    bound_service: str
    reserved: bool = False  # true for live_copilot until Phase 8


# ---------------------------------------------------------------------------
# Phase 7B — Prompt versions
# ---------------------------------------------------------------------------


class RetrievalConfigIn(BaseModel):
    """Per-version retrieval knobs. All fields optional — None means
    "use the lower-priority layer's value" (resolver semantics). Bounds
    mirror the plan §5.4 limits."""
    model_config = ConfigDict(extra="forbid")

    top_k_vector: Optional[int] = Field(default=None, ge=1, le=200)
    top_k_final: Optional[int] = Field(default=None, ge=1, le=50)
    max_graph_depth: Optional[int] = Field(default=None, ge=0, le=3)
    tier_widen_threshold: Optional[int] = Field(default=None, ge=0, le=50)
    rerank_strategy: Optional[
        Literal["auto", "legacy_weighted", "importance_aware"]
    ] = None
    sources_filter: Optional[
        Literal["all", "meetings_only", "documents_only"]
    ] = None
    include_archived: Optional[bool] = None
    citation_strictness: Optional[
        Literal["strict", "relaxed", "off"]
    ] = None
    entity_expansion_enabled: Optional[bool] = None
    embedding_model: Optional[str] = Field(default=None, max_length=128)
    importance_weight_overrides: Optional[dict[str, float]] = None

    @field_validator("importance_weight_overrides")
    @classmethod
    def _weights_known_keys(cls, v):
        if v is None:
            return v
        allowed = {"access", "citation", "recency", "anchor_density",
                   "confidence", "centrality"}
        bogus = set(v.keys()) - allowed
        if bogus:
            raise ValueError(
                f"importance_weight_overrides keys must be subset of "
                f"{sorted(allowed)}; got extras {sorted(bogus)}"
            )
        for k, weight in v.items():
            if not (0.0 <= weight <= 1.0):
                raise ValueError(
                    f"importance_weight_overrides[{k}]={weight} "
                    f"must be in [0, 1]"
                )
        return v


class ModelConfigIn(BaseModel):
    """LLM call config. All fields optional."""
    model_config = ConfigDict(extra="forbid")

    model: Optional[str] = Field(default=None, max_length=128)
    temperature: Optional[float] = Field(default=None, ge=0.0, le=2.0)
    max_tokens: Optional[int] = Field(default=None, ge=1, le=32_000)
    response_format: Optional[Literal["text", "json_object"]] = None


class ToolPermissionsIn(BaseModel):
    """Allow/deny lists. Deny is sticky (any layer wins)."""
    model_config = ConfigDict(extra="forbid")

    allowed: list[str] = Field(default_factory=list)
    denied: list[str] = Field(default_factory=list)


class VariablesSchemaItem(BaseModel):
    """One declared runtime variable. Validated at publish time
    against the system's catalog of known variables per agent_type."""
    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=64)
    required: bool = False
    description: Optional[str] = None
    sample: Optional[str] = None


class PromptVersionCreateRequest(BaseModel):
    """Create a new DRAFT version under a config. Versions only become
    immutable once published."""
    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = Field(default=None, max_length=120)
    modular_prompt: Optional[ModularPromptIn] = None
    variables_schema: list[VariablesSchemaItem] = Field(default_factory=list)
    retrieval_config: Optional[RetrievalConfigIn] = None
    model_cfg: Optional[ModelConfigIn] = Field(
        default=None, alias="model_config_payload",
    )
    # ^ Pydantic v2 reserves `model_config` on the class itself; we
    #   accept the user-facing key under an alias to avoid the clash.
    tool_permissions: Optional[ToolPermissionsIn] = None
    meta: Optional[dict] = None


class PromptVersionPatchRequest(BaseModel):
    """Edit a DRAFT version. Refused with 409 if state != 'draft'."""
    model_config = ConfigDict(extra="forbid")

    label: Optional[str] = Field(default=None, max_length=120)
    modular_prompt: Optional[ModularPromptIn] = None
    variables_schema: Optional[list[VariablesSchemaItem]] = None
    retrieval_config: Optional[RetrievalConfigIn] = None
    model_cfg: Optional[ModelConfigIn] = Field(
        default=None, alias="model_config_payload",
    )
    tool_permissions: Optional[ToolPermissionsIn] = None
    meta: Optional[dict] = None


class PromptVersionPublishRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: Optional[str] = Field(default=None, max_length=500)


class PromptConfigRollbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    to_version_id: UUID
    reason: Optional[str] = Field(default=None, max_length=500)


class PromptVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    organization_id: UUID
    agent_prompt_config_id: UUID
    version_number: int
    label: Optional[str]
    modular_prompt_json: dict
    variables_schema_json: list
    retrieval_config_json: dict
    model_config_json: dict
    tool_permissions_json: dict
    meta_json: dict
    state: VersionState
    published_at: Optional[datetime]
    published_by: Optional[UUID]
    eval_score: Optional[float]
    eval_run_id: Optional[UUID]
    seeded_from_filesystem: bool
    created_by: Optional[UUID]
    created_at: datetime
    updated_at: datetime


class PromptVersionSummary(BaseModel):
    """Slim summary for list views — omits the big JSONB blobs."""
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    version_number: int
    label: Optional[str]
    state: VersionState
    published_at: Optional[datetime]
    published_by: Optional[UUID]
    eval_score: Optional[float]
    seeded_from_filesystem: bool
    created_by: Optional[UUID]
    created_at: datetime


class PromptDeploymentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    organization_id: UUID
    agent_prompt_config_id: UUID
    action: DeploymentAction
    from_version_id: Optional[UUID]
    to_version_id: Optional[UUID]
    actor_user_id: Optional[UUID]
    reason: Optional[str]
    metadata_json: dict
    created_at: datetime


# ---------------------------------------------------------------------------
# Diff
# ---------------------------------------------------------------------------


class SectionDiff(BaseModel):
    """Diff for one of the 8 modular sections (or any other text key)."""
    model_config = ConfigDict(extra="forbid")

    a: str
    b: str
    unified_diff: str


class KeyDiff(BaseModel):
    """Diff for one key in the retrieval / model / tool-permissions
    bundles. a/b carry the JSON-serializable raw values (any type)."""
    model_config = ConfigDict(extra="forbid")

    a: object = None
    b: object = None


class ToolPermissionsDiff(BaseModel):
    model_config = ConfigDict(extra="forbid")

    added_allowed: list[str] = Field(default_factory=list)
    removed_allowed: list[str] = Field(default_factory=list)
    added_denied: list[str] = Field(default_factory=list)
    removed_denied: list[str] = Field(default_factory=list)


class VersionDiffResponse(BaseModel):
    """The full version-to-version diff. `from_version` is `a`,
    `to_version` is `b` — admins typically compare an older version
    against a newer candidate."""
    model_config = ConfigDict(extra="forbid")

    from_version_id: UUID
    to_version_id: UUID
    modular_prompt_diff: dict[str, SectionDiff]
    retrieval_config_diff: dict[str, KeyDiff]
    model_config_diff: dict[str, KeyDiff]
    tool_permissions_diff: ToolPermissionsDiff
    variables_schema_changed: bool
    label_changed: bool
