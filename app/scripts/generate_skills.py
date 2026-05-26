import os

SKILLS = {
    "engineering": [
        ("architecture_review", "Architecture Review", "Reviews system architecture for scalability, modularity, and best practices.", ["Architecture Review"]),
        ("code_review", "Code Quality & Review", "Analyzes code for bugs, style, and anti-patterns.", ["Code Review", "Quality Assurance"]),
        ("dependency_mapping", "Dependency Mapping", "Maps system dependencies and identifies coupling risks.", ["Architecture Review", "Risk Detection"]),
        ("api_review", "API Contract Analysis", "Reviews API contracts for REST/GraphQL best practices and breaking changes.", ["API Review"]),
        ("security_audit", "Technical Security Audit", "Scans technical discussions and code for security vulnerabilities.", ["Security Audit", "Risk Detection"]),
        ("performance_profiling", "Performance Profiling", "Identifies performance bottlenecks and scaling constraints.", ["Performance Analysis"])
    ],
    "incidents": [
        ("incident_detection", "Incident Detection", "Detects active or brewing incidents from discussions and logs.", ["Risk Detection", "Incident Management"]),
        ("root_cause_analysis", "Root Cause Analysis (RCA)", "Extracts root cause hypotheses and contributing factors.", ["Incident Management", "RCA"]),
        ("postmortem_generator", "Blameless Postmortem", "Generates blameless postmortems from incident timelines.", ["Incident Management", "Documentation"]),
        ("impact_assessment", "Impact Assessment", "Assesses blast radius and user impact of an incident.", ["Incident Management", "Risk Detection"]),
        ("mitigation_planning", "Mitigation Planning", "Extracts remediation steps and action items for incident recovery.", ["Incident Management", "Action Items"])
    ],
    "meetings": [
        ("summaries", "Meeting Summarization", "Generates high-level meeting recaps and key highlights.", ["Summaries"]),
        ("action_items", "Action Item Extraction", "Extracts structured action items with owners and deadlines.", ["Action Items"]),
        ("decisions", "Decision Logging", "Records formal decisions made during discussions.", ["Decision Tracking"]),
        ("sentiment_analysis", "Meeting Sentiment Analysis", "Analyzes participant sentiment and engagement levels.", ["Sentiment Analysis"]),
        ("agenda_tracking", "Agenda Adherence", "Tracks whether the meeting stayed on topic relative to the agenda.", ["Meeting Analytics"])
    ],
    "product": [
        ("feature_extraction", "Feature Request Extraction", "Identifies user feature requests and enhancement ideas.", ["Product Analytics"]),
        ("user_pain_points", "User Pain Points", "Extracts friction points and UX complaints.", ["Product Analytics", "User Research"]),
        ("competitor_analysis", "Competitor Mentions", "Tracks mentions of competitors and market alternatives.", ["Market Intelligence"]),
        ("roadmap_alignment", "Roadmap Alignment", "Evaluates how discussions align with current product roadmap.", ["Product Strategy"]),
        ("success_metrics", "Success Criteria", "Extracts KPIs and success metrics for initiatives.", ["Product Strategy", "Analytics"])
    ],
    "executive": [
        ("strategic_alignment", "Strategic Goal Alignment", "Maps project discussions to company-level strategic goals.", ["Executive Reporting", "Strategy"]),
        ("risk_rollup", "Executive Risk Rollup", "Aggregates critical risks into a high-level executive summary.", ["Executive Reporting", "Risk Detection"]),
        ("investment_areas", "Investment & Budget", "Tracks discussions related to budget, hiring, and capital allocation.", ["Executive Reporting", "Finance"]),
        ("blocker_escalation", "Escalation Detection", "Identifies critical blockers requiring executive intervention.", ["Executive Reporting", "Action Items"]),
        ("key_takeaways", "Executive Briefing", "Produces extreme TL;DR summaries for executive consumption.", ["Summaries", "Executive Reporting"])
    ],
    "compliance": [
        ("pii_detection", "PII & Sensitive Data", "Detects mentions or exposure of PII, PHI, and credentials.", ["Compliance", "Security Audit"]),
        ("policy_violation", "Internal Policy Check", "Flags potential violations of internal corporate policies.", ["Compliance", "Risk Detection"]),
        ("regulatory_audit", "Regulatory Audit", "Audits discussions against regulatory frameworks (e.g., SOC2, GDPR).", ["Compliance", "Audit"]),
        ("access_control", "Access & Permissions", "Tracks discussions around user access, roles, and authorization.", ["Compliance", "Security Audit"]),
        ("data_retention", "Data Retention Rules", "Monitors compliance with data lifecycle and retention policies.", ["Compliance", "Data Governance"])
    ]
}

TEMPLATE = '''from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="{skill_id}",
    name="{name}",
    description="{description}",
    capabilities={capabilities},
    system_prompt=(
        "You are an expert in {name}. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={{
        "top_k": 10,
        "search_bias": "{domain}"
    }},
    emits_events=["{domain}.{skill_id}.completed"]
)

register_skill(skill)
'''

def main():
    base_dir = "app/skills"
    
    # Create domains
    for domain, skills in SKILLS.items():
        domain_dir = os.path.join(base_dir, domain)
        os.makedirs(domain_dir, exist_ok=True)
        
        init_lines = []
        for skill_id, name, description, capabilities in skills:
            file_path = os.path.join(domain_dir, f"{skill_id}.py")
            content = TEMPLATE.format(
                skill_id=skill_id,
                name=name,
                description=description,
                capabilities=repr(capabilities),
                domain=domain
            )
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            
            init_lines.append(f"from .{skill_id} import skill as {skill_id}_skill")
            
        with open(os.path.join(domain_dir, "__init__.py"), "w", encoding="utf-8") as f:
            f.write("\n".join(init_lines) + "\n")

    # Master __init__.py
    master_init = os.path.join(base_dir, "__init__.py")
    with open(master_init, "w", encoding="utf-8") as f:
        f.write('"""Master registry import for all skills."""\n')
        for domain in SKILLS.keys():
            f.write(f"import app.skills.{domain}\n")
            
if __name__ == "__main__":
    main()
