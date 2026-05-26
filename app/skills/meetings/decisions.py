from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="decisions",
    name="Decision Logging",
    description="Records formal decisions made during discussions.",
    capabilities=['Decision Tracking'],
    system_prompt=(
        "You are an expert in Decision Logging. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings"
    },
    emits_events=["meetings.decisions.completed"]
)

register_skill(skill)
