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
    version: str = "1.0.0"
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
    """Returns a complete 11-dimension default dict for a category of
    the given class. Caller merges category-specific overrides on top
    via `dict | overrides`.

    All seven classes set every dimension so a fresh-install profile
    is fully usable out of the box (the user's "engineered defaults"
    requirement)."""
    base = {
        "master_prompt": {
            "system": (
                "You are the AI meeting assistant for {{org_name}}.\n"
                "You analyze meetings grounded in transcripts and "
                "documents."
            ),
            "behavior": (
                "Lead with the answer. Surface decisions, blockers, "
                "and open questions explicitly."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": "Use plain markdown. Bullet lists for enumerations.",
        },
        "enabled_agents": ["action-item-manager"],
        "retrieval_config": {
            "top_k_vector": 20, "top_k_final": 12,
            "max_graph_depth": 1, "rerank_strategy": "default",
            "sources_filter": "both", "include_archived": False,
        },
        "memory_config": {
            "consolidation_enabled": True,
            "recency_weight": 0.5, "importance_threshold": 0.3,
        },
        "output_config": {
            "format": "markdown", "max_length_tokens": 1500,
            "sections": ["summary", "decisions", "action_items"],
        },
        "extraction_rules": {
            "entities": ["person", "decision", "action_item", "risk"],
            "extract_action_items": True, "extract_decisions": True,
            "extract_timeline": False, "extract_crm_fields": False,
        },
        "automation_rules": {
            "post_meeting_summary": True,
            "sync_to_crm": False, "escalation_alert": False,
        },
        "evaluation_rules": {
            "eval_gate_enabled": False, "min_pass_rate": 0.0,
        },
        "tone_and_personality": {
            "formality": "professional", "verbosity": "concise",
        },
        "compliance_and_guardrails": {
            "redact_pii": True, "audit_trail_required": False,
            "bias_check_enabled": False, "data_residency": "default",
            "refused_topics": [],
        },
        "tools_and_integrations": {
            "allowed_tools": ["search_knowledge_base", "lookup_entity", "fetch_meeting"],
            "denied_tools": [], "model": "", "temperature": 0.3,
        },
    }

    if cls == "technical":
        base["retrieval_config"].update({
            "top_k_final": 14, "max_graph_depth": 2,
            "rerank_strategy": "importance_aware",
        })
        base["extraction_rules"]["entities"] = [
            "system", "service", "decision", "blocker", "risk", "owner",
        ]
        base["output_config"]["sections"] = [
            "decisions", "blockers", "risks", "action_items",
        ]
        base["tone_and_personality"] = {
            "formality": "professional", "verbosity": "precise",
        }
        base["tools_and_integrations"]["temperature"] = 0.25
    elif cls == "revenue":
        base["enabled_agents"] = ["sales-coach", "crm-extractor"]
        base["extraction_rules"]["entities"] = [
            "company", "buyer", "pain_point", "objection",
            "competitor", "action_item",
        ]
        base["extraction_rules"]["extract_crm_fields"] = True
        base["automation_rules"]["sync_to_crm"] = True
        base["tone_and_personality"] = {
            "formality": "casual", "verbosity": "concise",
        }
        base["output_config"]["sections"] = [
            "buying_signals", "objections", "next_steps",
        ]
        base["tools_and_integrations"]["temperature"] = 0.4
    elif cls == "people":
        base["enabled_agents"] = ["compliance-auditor", "action-item-manager"]
        base["extraction_rules"]["entities"] = [
            "person", "competency", "feedback", "decision",
        ]
        base["compliance_and_guardrails"].update({
            "redact_pii": True, "audit_trail_required": True,
            "bias_check_enabled": True,
            "refused_topics": [
                "protected_class_inferences", "salary_disclosure",
            ],
        })
        base["tone_and_personality"] = {
            "formality": "professional", "verbosity": "precise",
        }
        base["tools_and_integrations"]["temperature"] = 0.2
    elif cls == "executive":
        base["enabled_agents"] = ["executive-summarizer", "compliance-auditor"]
        base["retrieval_config"].update({
            "top_k_final": 15, "rerank_strategy": "importance_aware",
        })
        base["compliance_and_guardrails"].update({
            "audit_trail_required": True, "data_residency": "restricted",
        })
        base["tone_and_personality"] = {
            "formality": "formal", "verbosity": "very-concise",
        }
        base["output_config"]["sections"] = [
            "decisions_made", "open_questions", "asks_of_leadership",
        ]
        base["output_config"]["max_length_tokens"] = 1000
        base["tools_and_integrations"]["temperature"] = 0.2
    elif cls == "compliance_heavy":
        base["enabled_agents"] = ["compliance-auditor"]
        base["retrieval_config"].update({
            "top_k_final": 18, "max_graph_depth": 2,
        })
        base["compliance_and_guardrails"].update({
            "redact_pii": True, "audit_trail_required": True,
            "data_residency": "restricted",
            "refused_topics": [
                "legal_advice", "non_attorney_interpretation",
            ],
        })
        base["tone_and_personality"] = {
            "formality": "formal", "verbosity": "precise",
        }
        base["tools_and_integrations"]["temperature"] = 0.15
    elif cls == "creative":
        base["extraction_rules"]["entities"] = [
            "asset", "decision", "rationale", "iteration",
        ]
        base["tone_and_personality"] = {
            "formality": "casual", "verbosity": "narrative",
        }
        base["output_config"]["sections"] = [
            "creative_direction", "decisions", "iterations", "follow_ups",
        ]
        base["tools_and_integrations"]["temperature"] = 0.55
    elif cls == "operations":
        base["extraction_rules"]["entities"] = [
            "process", "vendor", "sla", "kpi", "bottleneck", "action_item",
        ]
        base["output_config"]["sections"] = [
            "process_changes", "bottlenecks", "metrics", "action_items",
        ]
        base["tone_and_personality"] = {
            "formality": "professional", "verbosity": "precise",
        }
    return base


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
    master_prompt={
        "system": (
            "You are the AI meeting assistant for {{org_name}}.\n"
            "You answer questions grounded in meeting transcripts and "
            "documents. You are precise, neutral, and concise."
        ),
        "behavior": (
            "Lead with the answer. Surface decisions, blockers, and "
            "open questions explicitly when they appear in context."
        ),
        "retrieval": "Use ONLY the numbered context blocks.",
        "citation": _CITATION_RULES,
        "guardrails": _GUARDRAILS,
        "output": "Use plain markdown. Bullet lists for enumerations.",
    },
    enabled_agents=["action-item-manager"],
    retrieval_config={
        "top_k_vector": 20, "top_k_final": 10,
        "max_graph_depth": 1, "rerank_strategy": "default",
        "sources_filter": "both", "include_archived": False,
    },
    memory_config={
        "consolidation_enabled": True,
        "recency_weight": 0.5, "importance_threshold": 0.3,
    },
    output_config={
        "format": "markdown", "max_length_tokens": 1500,
        "sections": ["summary", "action_items"],
    },
    extraction_rules={
        "entities": ["person", "decision", "action_item", "risk"],
        "extract_action_items": True, "extract_decisions": True,
        "extract_timeline": False, "extract_crm_fields": False,
    },
    automation_rules={
        "post_meeting_summary": True,
        "sync_to_crm": False, "escalation_alert": False,
    },
    evaluation_rules={"eval_gate_enabled": False, "min_pass_rate": 0.0},
    tone_and_personality={"formality": "professional", "verbosity": "concise"},
    compliance_and_guardrails={
        "redact_pii": True, "audit_trail_required": False,
        "bias_check_enabled": False, "data_residency": "default",
        "refused_topics": [],
    },
    tools_and_integrations={
        "allowed_tools": ["search_knowledge_base", "lookup_entity", "fetch_meeting"],
        "denied_tools": [], "model": "", "temperature": 0.3,
    },
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
        master_prompt={
            "system": (
                "You are the Engineering Analyst for {{org_name}}.\n"
                "You analyze engineering meetings — architecture, sprint "
                "work, incidents, design — grounded in transcripts and "
                "technical documents."
            ),
            "behavior": (
                "Be precise with technical language. Surface decisions, "
                "blockers, dependencies, and unresolved risks. "
                "Distinguish what was decided from what was discussed."
            ),
            "retrieval": (
                "Prefer DOCUMENT chunks (architecture/design docs) for "
                "definitional facts; prefer MEETING chunks for "
                "decisions + discussion."
            ),
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Lead with the answer. Then list relevant decisions, "
                "blockers, and risks as bullets, citing each."
            ),
        },
        enabled_agents=["technical-analyst"],
    ),
    _category(
        slug="product", display_name="Product",
        description="Product management — strategy, roadmap, user research, metrics.",
        dept_class="operations",
        master_prompt={
            "system": (
                "You are the Product Analyst for {{org_name}}.\n"
                "You analyze product meetings — roadmap, research, "
                "metrics review — surfacing user-impacting decisions."
            ),
            "behavior": (
                "Distinguish committed scope from explorations. "
                "Capture user feedback verbatim. Tie features to outcomes."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": "Sections: Decisions, User Feedback, Metrics, Follow-ups.",
        },
        enabled_agents=["technical-analyst", "action-item-manager"],
        extraction_rules={
            "entities": [
                "feature", "user_feedback", "decision", "metric",
                "experiment", "action_item",
            ],
        },
    ),
    _category(
        slug="sales", display_name="Sales",
        description="Revenue: discovery, demo, pipeline, deal mechanics.",
        dept_class="revenue",
        master_prompt={
            "system": (
                "You are the Sales Analyst for {{org_name}}.\n"
                "You analyze sales conversations to surface buying "
                "signals, objections, deal mechanics, and recommended "
                "next steps."
            ),
            "behavior": (
                "Identify buying signals (verbalized pain, budget, "
                "timeline, decision-maker references). Surface "
                "objections with the buyer's verbatim phrasing."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Buying Signals, Objections, Pain Points, "
                "CRM Fields, Recommended Next Steps."
            ),
        },
    ),
    _category(
        slug="customer-success", display_name="Customer Success",
        description="Post-sale: onboarding, QBRs, escalations, renewals.",
        dept_class="revenue",
        master_prompt={
            "system": (
                "You are the Customer Success Analyst for {{org_name}}.\n"
                "You analyze post-sale conversations to surface "
                "sentiment, retention risk, blockers, and required "
                "follow-ups."
            ),
            "behavior": (
                "Capture sentiment turning points verbatim. Flag "
                "retention risk explicitly. Distinguish the customer's "
                "stated issue from the inferred root cause."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Sentiment, Stated Issue, Inferred Root "
                "Cause, Retention Risk, Required Follow-ups."
            ),
        },
        enabled_agents=["customer-sentiment-analyzer", "action-item-manager"],
        tone_and_personality={"formality": "empathetic", "verbosity": "concise"},
        automation_rules={
            "post_meeting_summary": True, "sync_to_crm": True,
            "escalation_alert": True,
        },
        output_config={
            "sections": ["sentiment", "issue", "root_cause",
                         "retention_risk", "follow_ups"],
        },
    ),
    _category(
        slug="marketing", display_name="Marketing",
        description="Demand generation, content, brand, campaigns.",
        dept_class="creative",
        master_prompt={
            "system": (
                "You are the Marketing Analyst for {{org_name}}.\n"
                "You analyze marketing meetings — campaigns, content, "
                "positioning — to surface decisions and creative briefs."
            ),
            "behavior": (
                "Capture creative direction + campaign decisions clearly. "
                "Distinguish committed direction from exploration."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Creative Direction, Campaign Decisions, "
                "Brand Notes, Action Items."
            ),
        },
        extraction_rules={
            "entities": [
                "campaign", "asset", "channel", "decision", "action_item",
            ],
        },
    ),
    _category(
        slug="hr", display_name="HR",
        description="People operations: hiring, performance, compliance.",
        dept_class="people",
        master_prompt={
            "system": (
                "You are the HR Analyst for {{org_name}}.\n"
                "You analyze people-ops meetings — performance, hiring, "
                "employee relations — with strict bias awareness."
            ),
            "behavior": (
                "Distinguish observable behavior from inference. Quote "
                "feedback verbatim. Avoid speculation about employees. "
                "Do not infer protected-class attributes."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": (
                _GUARDRAILS + "\n\n"
                "Decline to compare employees on protected-class "
                "attributes (race, gender, age, religion, disability, "
                "national origin)."
            ),
            "output": (
                "Sections: Competency Ratings, Feedback Given, "
                "Employee Response, Action Items."
            ),
        },
        output_config={
            "sections": ["ratings", "feedback", "response", "action_items"],
        },
    ),
    _category(
        slug="finance", display_name="Finance",
        description="Accounting, FP&A, budget reviews, financial planning.",
        dept_class="executive",
        master_prompt={
            "system": (
                "You are the Finance Analyst for {{org_name}}.\n"
                "You analyze finance meetings with precision — numbers "
                "are quoted exactly, units always explicit."
            ),
            "behavior": (
                "Never round numbers without flagging it. Always state "
                "the unit + period. Cite source documents for figures."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Key Figures, Variance, Decisions, "
                "Forecasts, Action Items."
            ),
        },
        retrieval_config={"top_k_final": 16},
        extraction_rules={
            "entities": [
                "figure", "metric", "budget_line", "decision",
                "forecast", "owner",
            ],
        },
        output_config={
            "sections": ["figures", "variance", "decisions",
                         "forecasts", "action_items"],
        },
    ),
    _category(
        slug="executive", display_name="Executive",
        description="C-suite + board: governance, strategy, leadership.",
        dept_class="executive",
        master_prompt={
            "system": (
                "You are the Executive Summarizer for {{org_name}}.\n"
                "You produce board-ready summaries from leadership "
                "meetings."
            ),
            "behavior": (
                "Lead with the bottom line. Group by Decisions Made, "
                "Open Questions, Asks of Leadership. Aggressive "
                "concision — every bullet ≤ 20 words."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Decisions Made, Open Questions, Asks of "
                "Leadership. 0–5 bullets per section."
            ),
        },
        enabled_agents=["executive-summarizer"],
    ),
    _category(
        slug="security", display_name="Security",
        description="InfoSec, incident response, vulnerability reviews, compliance.",
        dept_class="compliance_heavy",
        master_prompt={
            "system": (
                "You are the Security Analyst for {{org_name}}.\n"
                "You analyze security meetings — incidents, vuln "
                "reviews, compliance — with audit-grade precision."
            ),
            "behavior": (
                "Capture severity, scope, mitigation, residual risk. "
                "Quote attack vectors verbatim. Flag unresolved threats."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Severity, Scope, Timeline, Mitigations, "
                "Residual Risk, Action Items."
            ),
        },
        enabled_agents=["compliance-auditor", "incident-investigator"],
        extraction_rules={
            "entities": [
                "incident", "vulnerability", "system", "severity",
                "mitigation", "owner",
            ],
            "extract_timeline": True,
        },
        output_config={
            "sections": ["severity", "scope", "timeline",
                         "mitigations", "residual_risk", "action_items"],
        },
    ),
    _category(
        slug="legal", display_name="Legal",
        description="Contracts, IP, regulatory, litigation, compliance counsel.",
        dept_class="compliance_heavy",
        master_prompt={
            "system": (
                "You are the Legal Analyst for {{org_name}}.\n"
                "You analyze legal meetings — contract review, IP, "
                "regulatory — with precise terminology."
            ),
            "behavior": (
                "Quote clauses verbatim. Distinguish opinion from "
                "precedent. Flag material risks + unsigned "
                "commitments. Never give legal advice."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Material Terms, Risks, Open Items, "
                "Owners, Next Steps."
            ),
        },
        extraction_rules={
            "entities": [
                "contract", "clause", "party", "risk",
                "obligation", "deadline",
            ],
        },
        output_config={
            "sections": ["material_terms", "risks", "open_items",
                         "owners", "next_steps"],
        },
    ),
    _category(
        slug="operations", display_name="Operations",
        description="Business ops, supply chain, facilities, process improvement.",
        dept_class="operations",
        master_prompt={
            "system": (
                "You are the Operations Analyst for {{org_name}}.\n"
                "You analyze ops meetings — process, capacity, supply "
                "chain, facilities — surfacing bottlenecks + KPI "
                "movement."
            ),
            "behavior": (
                "Quantify everything that's quantifiable. Surface SLA "
                "breaches + capacity constraints. Track action items "
                "back to owners."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Process Changes, Bottlenecks, KPIs, "
                "Action Items."
            ),
        },
    ),
    _category(
        slug="it", display_name="IT",
        description="Internal IT, helpdesk, endpoint management, corporate infrastructure.",
        dept_class="technical",
        master_prompt={
            "system": (
                "You are the IT Analyst for {{org_name}}.\n"
                "You analyze internal IT meetings — service tickets, "
                "endpoint management, system rollouts."
            ),
            "behavior": (
                "Capture incident timelines + remediation steps. Track "
                "ticket-to-resolution patterns. Flag recurring root "
                "causes."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Open Tickets, Resolutions, Recurring Issues, "
                "Rollouts, Action Items."
            ),
        },
        enabled_agents=["incident-investigator", "action-item-manager"],
        extraction_rules={
            "entities": [
                "system", "ticket", "endpoint", "owner", "sla",
            ],
            "extract_timeline": True,
        },
        output_config={
            "sections": ["tickets", "resolutions", "recurring",
                         "rollouts", "action_items"],
        },
    ),
    _category(
        slug="partnerships", display_name="Partnerships",
        description="Business development, channel partners, alliances, integrations.",
        dept_class="revenue",
        master_prompt={
            "system": (
                "You are the Partnerships Analyst for {{org_name}}.\n"
                "You analyze BD + partner conversations to surface "
                "deal mechanics, integration commitments, and joint "
                "go-to-market."
            ),
            "behavior": (
                "Capture mutual commitments verbatim. Identify "
                "decision owners on both sides. Surface unresolved "
                "scope or timeline risks."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Mutual Commitments, Decision Owners, "
                "Integration Scope, Risks, Next Steps."
            ),
        },
        extraction_rules={
            "entities": [
                "partner", "commitment", "integration", "deal_stage",
                "owner",
            ],
        },
        output_config={
            "sections": ["commitments", "owners", "integration_scope",
                         "risks", "next_steps"],
        },
    ),
    _category(
        slug="design", display_name="Design",
        description="Brand design, visual identity, creative reviews.",
        dept_class="creative",
        master_prompt={
            "system": (
                "You are the Design Analyst for {{org_name}}.\n"
                "You analyze design critiques + brand reviews — "
                "surface creative direction + decisions made."
            ),
            "behavior": (
                "Capture rationale behind design decisions verbatim. "
                "Distinguish committed direction from exploration."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Direction, Decisions, Iterations, Follow-ups."
            ),
        },
    ),
    _category(
        slug="data-science", display_name="Data Science",
        description="Analytics, experimentation, statistical modeling, insights.",
        dept_class="technical",
        master_prompt={
            "system": (
                "You are the Data Science Analyst for {{org_name}}.\n"
                "You analyze data-science meetings — experiment "
                "reviews, model evaluations, insights presentations."
            ),
            "behavior": (
                "Capture experiment hypotheses + outcomes. Quote "
                "confidence intervals + sample sizes when stated. Flag "
                "inconclusive results explicitly."
            ),
            "retrieval": "Use ONLY the numbered context blocks.",
            "citation": _CITATION_RULES,
            "guardrails": _GUARDRAILS,
            "output": (
                "Sections: Hypotheses, Outcomes, Confidence, "
                "Decisions, Follow-ups."
            ),
        },
        retrieval_config={"top_k_final": 15, "max_graph_depth": 2},
        extraction_rules={
            "entities": [
                "experiment", "metric", "hypothesis", "model", "owner",
            ],
        },
        output_config={
            "sections": ["hypotheses", "outcomes", "confidence",
                         "decisions", "follow_ups"],
        },
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
        extraction_rules={
            "entities": ["service", "api", "endpoint", "datastore", "owner", "incident"],
        },
        tone_and_personality={"verbosity": "precise"},
    ),
    _team(
        slug="frontend", parent_category_slug="engineering",
        display_name="Frontend",
        description="Web + mobile UI: design system, performance, UX.",
        extraction_rules={
            "entities": ["component", "page", "ux_decision", "performance_metric"],
        },
    ),
    _team(
        slug="devops", parent_category_slug="engineering",
        display_name="DevOps / SRE",
        description="Deploy pipeline, infra, reliability, incidents.",
        enabled_agents=["incident-investigator", "technical-analyst"],
        retrieval_config={"top_k_final": 18, "max_graph_depth": 2},
        extraction_rules={
            "entities": ["incident", "service", "severity", "owner", "runbook"],
            "extract_timeline": True,
        },
        automation_rules={"escalation_alert": True, "post_meeting_summary": True},
        output_config={
            "sections": ["incident", "severity", "timeline",
                         "mitigations", "runbook_updates", "action_items"],
        },
    ),
    _team(
        slug="data", parent_category_slug="engineering",
        display_name="Data Engineering",
        description="Pipelines, warehousing, analytics infrastructure.",
        extraction_rules={
            "entities": ["pipeline", "dataset", "schema", "sla", "owner"],
        },
    ),
    _team(
        slug="ml-engineering", parent_category_slug="engineering",
        display_name="ML Engineering",
        description="Model training, serving, evaluation infrastructure.",
        retrieval_config={"top_k_final": 16},
        extraction_rules={
            "entities": ["model", "dataset", "metric", "experiment", "owner"],
        },
    ),
    _team(
        slug="qa", parent_category_slug="engineering",
        display_name="QA / Quality Engineering",
        description="Test strategy, automation, release verification.",
        extraction_rules={
            "entities": ["test_case", "regression", "defect", "release", "owner"],
        },
    ),
    _team(
        slug="mobile", parent_category_slug="engineering",
        display_name="Mobile",
        description="iOS, Android, React Native — app delivery + store releases.",
        extraction_rules={
            "entities": ["platform", "build", "crash", "release", "store_review"],
        },
    ),
    _team(
        slug="infra-platform", parent_category_slug="engineering",
        display_name="Platform / Infrastructure",
        description="Cloud platform, networking, shared services.",
        retrieval_config={"top_k_final": 18, "max_graph_depth": 3},
        extraction_rules={
            "entities": ["service", "region", "deployment", "owner", "sla"],
        },
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
        extraction_rules={
            "entities": ["component", "user_flow", "design_decision", "iteration"],
        },
        tone_and_personality={"verbosity": "narrative"},
    ),
    _team(
        slug="user-research", parent_category_slug="product",
        display_name="User Research",
        description="Interviews, usability tests, synthesis.",
        extraction_rules={
            "entities": ["user", "insight", "quote", "behavior", "theme"],
        },
        tone_and_personality={"verbosity": "narrative"},
    ),

    # ── Sales ──────────────────────────────────────────────────────────────
    _team(
        slug="sdr", parent_category_slug="sales",
        display_name="SDR / BDR",
        description="Outbound prospecting + qualification.",
        extraction_rules={
            "entities": ["prospect", "company", "trigger", "objection", "next_step"],
        },
    ),
    _team(
        slug="account-executive", parent_category_slug="sales",
        display_name="Account Executive",
        description="Mid-funnel: discovery, demo, negotiation.",
        retrieval_config={"top_k_final": 15},
    ),
    _team(
        slug="enterprise-sales", parent_category_slug="sales",
        display_name="Enterprise Sales",
        description="Strategic accounts: long cycles, multi-stakeholder.",
        retrieval_config={"top_k_final": 18, "max_graph_depth": 2},
        compliance_and_guardrails={"audit_trail_required": True},
        output_config={
            "sections": ["stakeholders", "decision_criteria",
                         "objections", "competitive", "next_steps"],
        },
    ),
    _team(
        slug="sales-engineering", parent_category_slug="sales",
        display_name="Sales Engineering",
        description="Technical pre-sales: scoping, POCs, integrations.",
        enabled_agents=["technical-analyst", "sales-coach"],
        extraction_rules={
            "entities": [
                "technical_requirement", "integration", "blocker", "owner",
            ],
        },
    ),
    _team(
        slug="channel-sales", parent_category_slug="sales",
        display_name="Channel Sales",
        description="Reseller + distribution partner motion.",
        automation_rules={"sync_to_crm": True, "post_meeting_summary": True},
    ),
    _team(
        slug="sales-ops", parent_category_slug="sales",
        display_name="Sales Operations",
        description="Pipeline analytics, comp, enablement infrastructure.",
        retrieval_config={"top_k_final": 14},
        extraction_rules={
            "entities": ["metric", "process", "tool", "owner"],
        },
    ),

    # ── Customer Success ───────────────────────────────────────────────────
    _team(
        slug="csm", parent_category_slug="customer-success",
        display_name="Customer Success Manager",
        description="Account health, adoption, expansion.",
        enabled_agents=["customer-sentiment-analyzer", "sales-coach"],
        automation_rules={"sync_to_crm": True, "post_meeting_summary": True},
    ),
    _team(
        slug="support-tier-1", parent_category_slug="customer-success",
        display_name="Support — Tier 1",
        description="Front-line case handling, triage.",
        tone_and_personality={"formality": "empathetic", "verbosity": "concise"},
    ),
    _team(
        slug="support-tier-2", parent_category_slug="customer-success",
        display_name="Support — Tier 2",
        description="Escalations, deep technical investigations.",
        enabled_agents=["technical-analyst", "incident-investigator"],
        retrieval_config={"top_k_final": 16},
        automation_rules={"escalation_alert": True},
    ),
    _team(
        slug="onboarding", parent_category_slug="customer-success",
        display_name="Onboarding",
        description="New-customer activation + time-to-value.",
        automation_rules={"post_meeting_summary": True, "sync_to_crm": True},
        extraction_rules={
            "entities": [
                "milestone", "blocker", "activation_metric", "owner",
            ],
        },
    ),
    _team(
        slug="customer-education", parent_category_slug="customer-success",
        display_name="Customer Education",
        description="Training, certifications, documentation programs.",
        extraction_rules={
            "entities": ["course", "asset", "feedback", "owner"],
        },
    ),

    # ── Marketing ──────────────────────────────────────────────────────────
    _team(
        slug="growth", parent_category_slug="marketing",
        display_name="Growth",
        description="Funnel, experiments, activation, retention.",
        extraction_rules={
            "entities": ["experiment", "metric", "channel", "owner"],
        },
    ),
    _team(
        slug="content", parent_category_slug="marketing",
        display_name="Content",
        description="Editorial, blog, video, thought leadership.",
        tone_and_personality={"verbosity": "narrative"},
    ),
    _team(
        slug="brand", parent_category_slug="marketing",
        display_name="Brand",
        description="Positioning, voice, visual identity.",
        tone_and_personality={"verbosity": "narrative"},
    ),
    _team(
        slug="product-marketing", parent_category_slug="marketing",
        display_name="Product Marketing",
        description="Positioning, launches, competitive intel.",
        extraction_rules={
            "entities": ["positioning", "competitor", "launch", "messaging"],
        },
    ),
    _team(
        slug="demand-gen", parent_category_slug="marketing",
        display_name="Demand Generation",
        description="Paid, organic, lifecycle — top-of-funnel.",
        extraction_rules={
            "entities": ["campaign", "channel", "cac", "conversion_rate"],
        },
    ),

    # ── HR ─────────────────────────────────────────────────────────────────
    _team(
        slug="recruiting", parent_category_slug="hr",
        display_name="Recruiting",
        description="Talent acquisition: sourcing, interviews, offers.",
        enabled_agents=["interview-evaluator", "compliance-auditor"],
        evaluation_rules={"eval_gate_enabled": True, "min_pass_rate": 0.8},
        compliance_and_guardrails={
            "redact_pii": True, "audit_trail_required": True,
            "bias_check_enabled": True,
            "refused_topics": [
                "protected_class_inferences", "candidate_comparison_by_protected_class",
            ],
        },
        output_config={
            "sections": ["competencies", "evidence", "concerns",
                         "recommendation"],
        },
    ),
    _team(
        slug="people-ops", parent_category_slug="hr",
        display_name="People Operations",
        description="Performance, employee relations, comp reviews.",
        compliance_and_guardrails={
            "redact_pii": True, "audit_trail_required": True,
        },
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
        compliance_and_guardrails={
            "audit_trail_required": True, "bias_check_enabled": True,
        },
        tone_and_personality={"formality": "professional", "verbosity": "precise"},
    ),

    # ── Finance ────────────────────────────────────────────────────────────
    _team(
        slug="accounting", parent_category_slug="finance",
        display_name="Accounting",
        description="Books, close, reconciliation.",
        compliance_and_guardrails={"audit_trail_required": True},
    ),
    _team(
        slug="fp-and-a", parent_category_slug="finance",
        display_name="FP&A",
        description="Forecasting, budgeting, business reviews.",
        retrieval_config={"top_k_final": 18, "rerank_strategy": "importance_aware"},
    ),
    _team(
        slug="tax", parent_category_slug="finance",
        display_name="Tax",
        description="Federal, state, international tax planning + filings.",
        compliance_and_guardrails={
            "audit_trail_required": True, "data_residency": "restricted",
        },
    ),
    _team(
        slug="treasury", parent_category_slug="finance",
        display_name="Treasury",
        description="Cash management, banking, investments.",
        compliance_and_guardrails={"data_residency": "restricted"},
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
        compliance_and_guardrails={
            "audit_trail_required": True, "data_residency": "restricted",
        },
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
        compliance_and_guardrails={"audit_trail_required": True},
        tone_and_personality={"verbosity": "concise"},
    ),

    # ── Security ───────────────────────────────────────────────────────────
    _team(
        slug="security-engineering", parent_category_slug="security",
        display_name="Security Engineering",
        description="Hardening, code reviews, vulnerability management.",
        enabled_agents=["technical-analyst", "compliance-auditor"],
    ),
    _team(
        slug="compliance", parent_category_slug="security",
        display_name="Compliance",
        description="SOC2, ISO, regulatory frameworks, audits.",
        compliance_and_guardrails={
            "audit_trail_required": True, "redact_pii": True,
        },
    ),
    _team(
        slug="appsec", parent_category_slug="security",
        display_name="Application Security",
        description="Code review, threat modeling, secure SDLC.",
        enabled_agents=["technical-analyst", "compliance-auditor"],
        extraction_rules={
            "entities": ["vulnerability", "cve", "component", "owner", "severity"],
        },
    ),

    # ── Legal ──────────────────────────────────────────────────────────────
    _team(
        slug="contracts", parent_category_slug="legal",
        display_name="Contracts",
        description="MSA, SOW, vendor agreements, redlines.",
        retrieval_config={"top_k_final": 18, "max_graph_depth": 2},
        extraction_rules={
            "entities": [
                "contract", "clause", "party", "obligation", "deadline",
            ],
        },
    ),
    _team(
        slug="ip", parent_category_slug="legal",
        display_name="IP & Trademark",
        description="Patents, trademarks, IP strategy.",
        compliance_and_guardrails={"data_residency": "restricted"},
    ),
    _team(
        slug="regulatory", parent_category_slug="legal",
        display_name="Regulatory",
        description="Regulatory filings, government affairs, industry frameworks.",
        compliance_and_guardrails={
            "audit_trail_required": True, "data_residency": "restricted",
        },
    ),

    # ── Operations ─────────────────────────────────────────────────────────
    _team(
        slug="business-ops", parent_category_slug="operations",
        display_name="Business Operations",
        description="Strategy execution, cross-team process, OKRs.",
        extraction_rules={
            "entities": ["okr", "milestone", "owner", "blocker", "metric"],
        },
    ),
    _team(
        slug="supply-chain", parent_category_slug="operations",
        display_name="Supply Chain",
        description="Logistics, procurement, vendor management.",
        extraction_rules={
            "entities": ["vendor", "po", "delivery_date", "sla", "shipment"],
        },
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
        enabled_agents=["customer-sentiment-analyzer", "incident-investigator"],
        tone_and_personality={"formality": "empathetic"},
    ),
    _team(
        slug="endpoint-management", parent_category_slug="it",
        display_name="Endpoint Management",
        description="Device fleet, MDM, lifecycle.",
        extraction_rules={
            "entities": ["device", "user", "policy", "compliance_state"],
        },
    ),

    # ── Partnerships ───────────────────────────────────────────────────────
    _team(
        slug="business-development", parent_category_slug="partnerships",
        display_name="Business Development",
        description="Strategic partnerships, alliances, exclusivity terms.",
        retrieval_config={"top_k_final": 16},
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
        extraction_rules={
            "entities": [
                "experiment", "variant", "metric", "confidence", "owner",
            ],
        },
        evaluation_rules={"eval_gate_enabled": True, "min_pass_rate": 0.7},
    ),
    _team(
        slug="analytics", parent_category_slug="data-science",
        display_name="Analytics",
        description="Reporting, dashboards, business intelligence.",
        retrieval_config={"top_k_final": 14},
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
    "compliance_and_guardrails", "tools_and_integrations",
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
