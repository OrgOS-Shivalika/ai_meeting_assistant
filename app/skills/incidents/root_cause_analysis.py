from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="root_cause_analysis",
    name="Root Cause Analysis (RCA)",
    description="Extracts root cause hypotheses and contributing factors.",
    capabilities=['Incident Management', 'RCA'],
    system_prompt=(
        "You are an expert in Root Cause Analysis (RCA). Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "incidents"
    },
    emits_events=["incidents.root_cause_analysis.completed"]
)

register_skill(skill)
