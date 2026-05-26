"""Phase 8G — behavior catalog with engineered defaults across all 11 dimensions.

Three scope_kinds:

  - 'global'   — platform-wide floor. Exactly one published row.
                 Always slug='__default__'.
  - 'category' — a *department* (top-level scope).
                 Examples: engineering, sales, customer-success.
  - 'team'     — a *sub-team* under a department. Always carries
                 `parent_category_slug` pointing at its category.

Every category profile carries opinionated defaults across all 11
BehaviorProfile dimensions so users can install + use immediately
without configuring anything. Teams add sub-team-specific deltas
on top of their parent category's defaults.

Department classes:
  - technical         — engineering, security, IT, data-science
  - revenue           — sales, customer-success, marketing, partnerships
  - people            — hr (recruiting + people-ops; bias-aware)
  - executive         — executive, finance (board-grade, formal, audited)
  - compliance_heavy  — legal (audit-required, restricted residency)
  - creative          — design, marketing (narrative, exploratory)
  - operations        — operations, product (process-focused)

The resolver layers these top-down:
  global default → category template → team template
                 → category overrides → team overrides
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class BehaviorProfileDef:
    scope_kind: str
    slug: str
    display_name: str
    description: str
    version: str = "2.0.0"
    parent_category_slug: Optional[str] = None

    master_prompt: dict = field(default_factory=dict)
    enabled_agents: list = field(default_factory=list)
    retrieval_config: dict = field(default_factory=dict)
    memory_config: dict = field(default_factory=dict)
    output_config: dict = field(default_factory=dict)
    extraction_rules: dict = field(default_factory=dict)
    automation_rules: dict = field(default_factory=dict)
    evaluation_rules: dict = field(default_factory=dict)
    tone_and_personality: dict = field(default_factory=dict)
    compliance_and_guardrails: dict = field(default_factory=dict)
    tools_and_integrations: dict = field(default_factory=dict)
    intent: dict = field(default_factory=dict)


# ===========================================================================
# Shared prompt fragments
# ===========================================================================


_CITATION_RULES = (
    "Every factual claim MUST be followed by one or more [N] tags "
    "pointing to the source block(s) that support it.\n"
    "ONLY chunk blocks (MEETING or DOCUMENT) are citable.\n"
    "ENTITY and RELATIONSHIP blocks are reasoning context; do NOT "
    "cite them with [N].\n"
    "NEVER invent an [N] that isn't in the context.\n"
    "If two blocks support the same claim, cite both."
)

_GUARDRAILS = (
    "If the context blocks do not support a clear answer, respond "
    "exactly: \"I don't have enough information to answer that.\"\n"
    "Do NOT speculate, guess, or fall back to general knowledge.\n"
    "Do NOT echo personal information beyond what the context "
    "explicitly contains."
)


# ===========================================================================
# Department-class defaults — engineered 11-dim baselines
# ===========================================================================


def _dept_defaults(cls: str) -> dict:
    """Returns the intent-driven defaults for a department class.
    
    Technical internals (retrieval weights, graph depth, etc.) are 
    now automatically derived from these intents by the PolicyResolver 
    at runtime.
    """
    # 1. Platform-wide baseline intent
    intent = {
        "behavior": {
            "role_focus": "AI Meeting Assistant",
            "custom_instructions": "Lead with the answer. Surface decisions and blockers.",
            "communication_style": "professional",
            "response_depth": "standard"
        },
        "capabilities": {
            "summaries": True,
            "action_items": True,
            "decisions": True,
            "risk_detection": False,
            "technical_analysis": False,
            "architecture_review": False,
            "incident_detection": False,
            "follow_ups": True
        },
        "automations": {
            "slack_summary": True,
            "jira_tasks": False,
            "high_risk_escalation": False,
            "stakeholder_notification": False
        },
        "knowledge_access": {
            "meeting_history": True,
            "team_documents": True,
            "past_decisions": True,
            "architecture_docs": False,
            "incidents_outages": False
        },
        "privacy_safety": {
            "redact_pii": True,
            "restrict_external_sharing": True,
            "require_approval_before_escalation": False,
            "data_residency": "default"
        },
        "connected_tools": {
            "slack_enabled": True,
            "jira_enabled": False,
            "github_enabled": False,
            "notion_enabled": False,
            "crm_enabled": False
        }
    }

    # 2. Apply class-specific intent overrides
    if cls == "technical":
        intent["behavior"].update({
            "role_focus": "Technical Engineering Analyst",
            "communication_style": "concise",
            "response_depth": "comprehensive"
        })
        intent["capabilities"].update({
            "risk_detection": True,
            "technical_analysis": True,
            "architecture_review": True,
            "incident_detection": True
        })
        intent["knowledge_access"].update({
            "architecture_docs": True,
            "incidents_outages": True
        })
    elif cls == "revenue":
        intent["behavior"].update({
            "role_focus": "Revenue & Sales Analyst",
            "communication_style": "casual"
        })
        intent["capabilities"].update({
            "follow_ups": True
        })
        intent["automations"].update({
            "jira_tasks": True # Mapped to CRM in this context
        })
        intent["connected_tools"].update({
            "crm_enabled": True
        })
    elif cls == "people":
        intent["behavior"].update({
            "role_focus": "HR Operations Assistant",
            "communication_style": "empathetic"
        })
        intent["privacy_safety"].update({
            "require_approval_before_escalation": True
        })
    elif cls == "executive":
        intent["behavior"].update({
            "role_focus": "Executive Summarizer",
            "communication_style": "concise",
            "response_depth": "brief"
        })
        intent["automations"].update({
            "high_risk_escalation": True,
            "stakeholder_notification": True
        })
        intent["privacy_safety"].update({
            "data_residency": "restricted"
        })
    elif cls == "compliance_heavy":
        intent["behavior"].update({
            "role_focus": "Legal & Compliance Analyst",
            "communication_style": "professional"
        })
        intent["knowledge_access"].update({
            "past_decisions": True
        })
        intent["privacy_safety"].update({
            "data_residency": "restricted"
        })
    elif cls == "creative":
        intent["behavior"].update({
            "role_focus": "Creative Direction Assistant",
            "communication_style": "detailed"
        })
    elif cls == "operations":
        intent["behavior"].update({
            "role_focus": "Operations Analyst",
            "communication_style": "concise"
        })

    # Return only the 'intent' dimension. 
    # The technical dimensions will be resolution-empty in the template rows,
    # forcing the PolicyResolver to fill them based on the intent.
    return {"intent": intent}


def _merge_dims(base: dict, overrides: dict) -> dict:
    """Shallow-merge overrides onto a copy of base. Per-dimension dicts
    are shallow-merged too so a caller can override just one key
    (e.g. only `retrieval_config.top_k_final`) without erasing the
    rest of that dimension."""
    out: dict = {}
    for k, v in base.items():
        if k in overrides:
            ov = overrides[k]
            if isinstance(v, dict) and isinstance(ov, dict):
                merged = dict(v)
                merged.update(ov)
                out[k] = merged
            else:
                out[k] = ov
        else:
            out[k] = v
    # Any override keys not in base — pass through verbatim.
    for k, v in overrides.items():
        if k not in out:
            out[k] = v
    return out


def _category(
    *, slug: str, display_name: str, description: str,
    dept_class: str = "generic", **overrides,
) -> BehaviorProfileDef:
    dims = _merge_dims(_dept_defaults(dept_class), overrides)
    return BehaviorProfileDef(
        scope_kind="category", slug=slug,
        display_name=display_name, description=description,
        **dims,
    )


def _team(
    *, slug: str, parent_category_slug: str, display_name: str,
    description: str, **overrides,
) -> BehaviorProfileDef:
    """Team profile. Teams INHERIT from their parent category at
    resolve time — they only need to specify the dimensions where
    being this specific sub-team meaningfully changes behavior.
    Empty dimensions stay empty here and are filled by the cascade."""
    return BehaviorProfileDef(
        scope_kind="team", slug=slug,
        parent_category_slug=parent_category_slug,
        display_name=display_name, description=description,
        **overrides,
    )


# ===========================================================================
# GLOBAL DEFAULT
# ===========================================================================


GLOBAL_DEFAULT = BehaviorProfileDef(
    scope_kind="global",
    slug="__default__",
    display_name="Platform Default",
    description="The baseline AI cognition profile applied to every "
                "workspace before category + team templates and "
                "overrides layer on top.",
    intent={
        "behavior": {
            "role_focus": "AI Meeting Assistant",
            "custom_instructions": "Lead with the answer. Surface decisions and blockers.",
            "communication_style": "professional",
            "response_depth": "standard"
        },
        "capabilities": {
            "summaries": True,
            "action_items": True,
            "decisions": True,
            "risk_detection": False,
            "technical_analysis": False,
            "architecture_review": False,
            "incident_detection": False,
            "follow_ups": True
        },
        "automations": {
            "slack_summary": True,
            "jira_tasks": False,
            "high_risk_escalation": False,
            "stakeholder_notification": False
        },
        "knowledge_access": {
            "meeting_history": True,
            "team_documents": True,
            "past_decisions": True,
            "architecture_docs": False,
            "incidents_outages": False
        },
        "privacy_safety": {
            "redact_pii": True,
            "restrict_external_sharing": True,
            "require_approval_before_escalation": False,
            "data_residency": "default"
        },
        "connected_tools": {
            "slack_enabled": True,
            "jira_enabled": False,
            "github_enabled": False,
            "notion_enabled": False,
            "crm_enabled": False
        }
    }
)


# ===========================================================================
# CATEGORIES (departments) — engineered defaults across all 11 dimensions
# ===========================================================================


_CATEGORY_PROFILES = (
    _category(
        slug="engineering", display_name="Engineering",
        description="Software engineering. Technical depth, architecture, "
                    "blockers, system risks.",
        dept_class="technical",
    ),
    _category(
        slug="product", display_name="Product",
        description="Product management — strategy, roadmap, user research, metrics.",
        dept_class="operations",
    ),
    _category(
        slug="sales", display_name="Sales",
        description="Revenue: discovery, demo, pipeline, deal mechanics.",
        dept_class="revenue",
    ),
    _category(
        slug="customer-success", display_name="Customer Success",
        description="Post-sale: onboarding, QBRs, escalations, renewals.",
        dept_class="revenue",
    ),
    _category(
        slug="marketing", display_name="Marketing",
        description="Demand generation, content, brand, campaigns.",
        dept_class="creative",
    ),
    _category(
        slug="hr", display_name="HR",
        description="People operations: hiring, performance, compliance.",
        dept_class="people",
    ),
    _category(
        slug="finance", display_name="Finance",
        description="Accounting, FP&A, budget reviews, financial planning.",
        dept_class="executive",
    ),
    _category(
        slug="executive", display_name="Executive",
        description="C-suite + board: governance, strategy, leadership.",
        dept_class="executive",
    ),
    _category(
        slug="security", display_name="Security",
        description="InfoSec, incident response, vulnerability reviews, compliance.",
        dept_class="compliance_heavy",
    ),
    _category(
        slug="legal", display_name="Legal",
        description="Contracts, IP, regulatory, litigation, compliance counsel.",
        dept_class="compliance_heavy",
    ),
    _category(
        slug="operations", display_name="Operations",
        description="Business ops, supply chain, facilities, process improvement.",
        dept_class="operations",
    ),
    _category(
        slug="it", display_name="IT",
        description="Internal IT, helpdesk, endpoint management, corporate infrastructure.",
        dept_class="technical",
    ),
    _category(
        slug="partnerships", display_name="Partnerships",
        description="Business development, channel partners, alliances, integrations.",
        dept_class="revenue",
    ),
    _category(
        slug="design", display_name="Design",
        description="Brand design, visual identity, creative reviews.",
        dept_class="creative",
    ),
    _category(
        slug="data-science", display_name="Data Science",
        description="Analytics, experimentation, statistical modeling, insights.",
        dept_class="technical",
    ),
)


# ===========================================================================
# TEAMS — sub-team specializations on top of their parent category
# ===========================================================================
#
# Teams inherit the parent category's full 11-dimension profile at
# resolve time. Each team only specifies the dimensions where being
# this specific sub-team meaningfully shifts behavior.


_TEAM_PROFILES = (
    # ── Engineering ────────────────────────────────────────────────────────
    _team(
        slug="backend", parent_category_slug="engineering",
        display_name="Backend",
        description="Server-side systems: APIs, services, data plane.",
        intent={
            "behavior": {
                "role_focus": "Backend Engineering Analyst",
                "custom_instructions": "Focus on APIs, data integrity, and service scalability."
            }
        }
    ),
    _team(
        slug="frontend", parent_category_slug="engineering",
        display_name="Frontend",
        description="Web + mobile UI: design system, performance, UX.",
        intent={
            "behavior": {
                "role_focus": "Frontend Engineering Analyst",
                "custom_instructions": "Focus on UI/UX consistency, performance, and accessibility."
            }
        }
    ),
    _team(
        slug="devops", parent_category_slug="engineering",
        display_name="DevOps / SRE",
        description="Deploy pipeline, infra, reliability, incidents.",
        intent={
            "behavior": {
                "role_focus": "Site Reliability Engineer",
                "custom_instructions": "Prioritize infrastructure risks and incident root causes."
            },
            "capabilities": {
                "incident_detection": True,
                "risk_detection": True
            }
        }
    ),
    _team(
        slug="data", parent_category_slug="engineering",
        display_name="Data Engineering",
        description="Pipelines, warehousing, analytics infrastructure.",
    ),
    _team(
        slug="ml-engineering", parent_category_slug="engineering",
        display_name="ML Engineering",
        description="Model training, serving, evaluation infrastructure.",
    ),
    _team(
        slug="qa", parent_category_slug="engineering",
        display_name="QA / Quality Engineering",
        description="Test strategy, automation, release verification.",
    ),
    _team(
        slug="mobile", parent_category_slug="engineering",
        display_name="Mobile",
        description="iOS, Android, React Native — app delivery + store releases.",
    ),
    _team(
        slug="infra-platform", parent_category_slug="engineering",
        display_name="Platform / Infrastructure",
        description="Cloud platform, networking, shared services.",
    ),

    # ── Product ────────────────────────────────────────────────────────────
    _team(
        slug="product-management", parent_category_slug="product",
        display_name="Product Management",
        description="Strategy, roadmap, prioritization.",
    ),
    _team(
        slug="product-design", parent_category_slug="product",
        display_name="Product Design",
        description="UX, IA, interaction design, prototyping.",
    ),
    _team(
        slug="user-research", parent_category_slug="product",
        display_name="User Research",
        description="Interviews, usability tests, synthesis.",
    ),

    # ── Sales ──────────────────────────────────────────────────────────────
    _team(
        slug="sdr", parent_category_slug="sales",
        display_name="SDR / BDR",
        description="Outbound prospecting + qualification.",
    ),
    _team(
        slug="account-executive", parent_category_slug="sales",
        display_name="Account Executive",
        description="Mid-funnel: discovery, demo, negotiation.",
    ),
    _team(
        slug="enterprise-sales", parent_category_slug="sales",
        display_name="Enterprise Sales",
        description="Strategic accounts: long cycles, multi-stakeholder.",
    ),
    _team(
        slug="sales-engineering", parent_category_slug="sales",
        display_name="Sales Engineering",
        description="Technical pre-sales: scoping, POCs, integrations.",
        intent={
            "capabilities": {
                "technical_analysis": True
            }
        }
    ),
    _team(
        slug="channel-sales", parent_category_slug="sales",
        display_name="Channel Sales",
        description="Reseller + distribution partner motion.",
    ),
    _team(
        slug="sales-ops", parent_category_slug="sales",
        display_name="Sales Operations",
        description="Pipeline analytics, comp, enablement infrastructure.",
    ),

    # ── Customer Success ───────────────────────────────────────────────────
    _team(
        slug="csm", parent_category_slug="customer-success",
        display_name="Customer Success Manager",
        description="Account health, adoption, expansion.",
    ),
    _team(
        slug="support-tier-1", parent_category_slug="customer-success",
        display_name="Support — Tier 1",
        description="Front-line case handling, triage.",
    ),
    _team(
        slug="support-tier-2", parent_category_slug="customer-success",
        display_name="Support — Tier 2",
        description="Escalations, deep technical investigations.",
        intent={
            "capabilities": {
                "technical_analysis": True,
                "incident_detection": True
            }
        }
    ),
    _team(
        slug="onboarding", parent_category_slug="customer-success",
        display_name="Onboarding",
        description="New-customer activation + time-to-value.",
    ),
    _team(
        slug="customer-education", parent_category_slug="customer-success",
        display_name="Customer Education",
        description="Training, certifications, documentation programs.",
    ),

    # ── Marketing ──────────────────────────────────────────────────────────
    _team(
        slug="growth", parent_category_slug="marketing",
        display_name="Growth",
        description="Funnel, experiments, activation, retention.",
    ),
    _team(
        slug="content", parent_category_slug="marketing",
        display_name="Content",
        description="Editorial, blog, video, thought leadership.",
    ),
    _team(
        slug="brand", parent_category_slug="marketing",
        display_name="Brand",
        description="Positioning, voice, visual identity.",
    ),
    _team(
        slug="product-marketing", parent_category_slug="marketing",
        display_name="Product Marketing",
        description="Positioning, launches, competitive intel.",
    ),
    _team(
        slug="demand-gen", parent_category_slug="marketing",
        display_name="Demand Generation",
        description="Paid, organic, lifecycle — top-of-funnel.",
    ),

    # ── HR ─────────────────────────────────────────────────────────────────
    _team(
        slug="recruiting", parent_category_slug="hr",
        display_name="Recruiting",
        description="Talent acquisition: sourcing, interviews, offers.",
    ),
    _team(
        slug="people-ops", parent_category_slug="hr",
        display_name="People Operations",
        description="Performance, employee relations, comp reviews.",
    ),
    _team(
        slug="learning-and-development", parent_category_slug="hr",
        display_name="Learning & Development",
        description="Training programs, manager development, mentorship.",
    ),
    _team(
        slug="dei", parent_category_slug="hr",
        display_name="DEI",
        description="Diversity, equity, inclusion programs + reporting.",
    ),

    # ── Finance ────────────────────────────────────────────────────────────
    _team(
        slug="accounting", parent_category_slug="finance",
        display_name="Accounting",
        description="Books, close, reconciliation.",
    ),
    _team(
        slug="fp-and-a", parent_category_slug="finance",
        display_name="FP&A",
        description="Forecasting, budgeting, business reviews.",
    ),
    _team(
        slug="tax", parent_category_slug="finance",
        display_name="Tax",
        description="Federal, state, international tax planning + filings.",
    ),
    _team(
        slug="treasury", parent_category_slug="finance",
        display_name="Treasury",
        description="Cash management, banking, investments.",
    ),

    # ── Executive ──────────────────────────────────────────────────────────
    _team(
        slug="leadership", parent_category_slug="executive",
        display_name="Leadership",
        description="Exec team meetings, all-hands prep.",
    ),
    _team(
        slug="board-relations", parent_category_slug="executive",
        display_name="Board Relations",
        description="Board prep, investor updates, governance.",
    ),
    _team(
        slug="chief-of-staff", parent_category_slug="executive",
        display_name="Chief of Staff",
        description="Exec operations, planning, cross-functional coordination.",
    ),
    _team(
        slug="communications", parent_category_slug="executive",
        display_name="Communications",
        description="Internal comms, PR, IR talking points.",
    ),

    # ── Security ───────────────────────────────────────────────────────────
    _team(
        slug="security-engineering", parent_category_slug="security",
        display_name="Security Engineering",
        description="Hardening, code reviews, vulnerability management.",
    ),
    _team(
        slug="compliance", parent_category_slug="security",
        display_name="Compliance",
        description="SOC2, ISO, regulatory frameworks, audits.",
    ),
    _team(
        slug="appsec", parent_category_slug="security",
        display_name="Application Security",
        description="Code review, threat modeling, secure SDLC.",
    ),

    # ── Legal ──────────────────────────────────────────────────────────────
    _team(
        slug="contracts", parent_category_slug="legal",
        display_name="Contracts",
        description="MSA, SOW, vendor agreements, redlines.",
    ),
    _team(
        slug="ip", parent_category_slug="legal",
        display_name="IP & Trademark",
        description="Patents, trademarks, IP strategy.",
    ),
    _team(
        slug="regulatory", parent_category_slug="legal",
        display_name="Regulatory",
        description="Regulatory filings, government affairs, industry frameworks.",
    ),

    # ── Operations ─────────────────────────────────────────────────────────
    _team(
        slug="business-ops", parent_category_slug="operations",
        display_name="Business Operations",
        description="Strategy execution, cross-team process, OKRs.",
    ),
    _team(
        slug="supply-chain", parent_category_slug="operations",
        display_name="Supply Chain",
        description="Logistics, procurement, vendor management.",
    ),
    _team(
        slug="facilities", parent_category_slug="operations",
        display_name="Facilities",
        description="Office, real estate, physical infrastructure.",
    ),

    # ── IT ─────────────────────────────────────────────────────────────────
    _team(
        slug="helpdesk", parent_category_slug="it",
        display_name="IT Helpdesk",
        description="Employee support, ticket triage, endpoint setup.",
    ),
    _team(
        slug="endpoint-management", parent_category_slug="it",
        display_name="Endpoint Management",
        description="Device fleet, MDM, lifecycle.",
    ),

    # ── Partnerships ───────────────────────────────────────────────────────
    _team(
        slug="business-development", parent_category_slug="partnerships",
        display_name="Business Development",
        description="Strategic partnerships, alliances, exclusivity terms.",
    ),
    _team(
        slug="channel-partnerships", parent_category_slug="partnerships",
        display_name="Channel Partnerships",
        description="Reseller programs, integrator network.",
    ),

    # ── Data Science ───────────────────────────────────────────────────────
    _team(
        slug="experimentation", parent_category_slug="data-science",
        display_name="Experimentation",
        description="A/B tests, multivariate, holdout analysis.",
    ),
    _team(
        slug="analytics", parent_category_slug="data-science",
        display_name="Analytics",
        description="Reporting, dashboards, business intelligence.",
    ),
)


# ===========================================================================
# All-in-one
# ===========================================================================


CATALOG_PROFILES: tuple[BehaviorProfileDef, ...] = (
    GLOBAL_DEFAULT,
    *_CATEGORY_PROFILES,
    *_TEAM_PROFILES,
)


# ---------------------------------------------------------------------------
# Manifest hashing
# ---------------------------------------------------------------------------

_DIMENSION_FIELDS = (
    "master_prompt", "enabled_agents", "retrieval_config", "memory_config",
    "output_config", "extraction_rules", "automation_rules",
    "evaluation_rules", "tone_and_personality",
    "compliance_and_guardrails", "tools_and_integrations", "intent",
)


def manifest_payload(profile: BehaviorProfileDef) -> dict:
    out = {
        "scope_kind": profile.scope_kind,
        "slug": profile.slug,
        "version": profile.version,
        "display_name": profile.display_name,
        "description": profile.description,
        "parent_category_slug": profile.parent_category_slug,
    }
    for dim in _DIMENSION_FIELDS:
        out[dim] = getattr(profile, dim)
    return out


def manifest_hash(profile: BehaviorProfileDef) -> str:
    raw = json.dumps(manifest_payload(profile), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------


def global_default() -> BehaviorProfileDef:
    return GLOBAL_DEFAULT


def category_profile(slug: str) -> Optional[BehaviorProfileDef]:
    for p in _CATEGORY_PROFILES:
        if p.slug == slug:
            return p
    return None


def team_profile(slug: str) -> Optional[BehaviorProfileDef]:
    for p in _TEAM_PROFILES:
        if p.slug == slug:
            return p
    return None


def all_category_profiles() -> tuple[BehaviorProfileDef, ...]:
    return _CATEGORY_PROFILES


def all_team_profiles() -> tuple[BehaviorProfileDef, ...]:
    return _TEAM_PROFILES


def teams_under(category_slug: str) -> tuple[BehaviorProfileDef, ...]:
    return tuple(
        p for p in _TEAM_PROFILES
        if p.parent_category_slug == category_slug
    )
