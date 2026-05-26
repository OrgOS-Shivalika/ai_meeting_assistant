from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="summaries",
    name="Meeting Summarization",
    description="Generates high-level meeting recaps and key highlights.",
    capabilities=['Summaries'],
    system_prompt=(
        "You are an expert in Meeting Summarization. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings"
    },
    emits_events=["meetings.summaries.completed"]
)

register_skill(skill)
