from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="key_takeaways",
    name="Executive Briefing",
    description="Produces extreme TL;DR summaries for executive consumption.",
    capabilities=['Summaries', 'Executive Reporting'],
    system_prompt=(
        "You are an expert in Executive Briefing. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "executive"
    },
    emits_events=["executive.key_takeaways.completed"]
)

register_skill(skill)
