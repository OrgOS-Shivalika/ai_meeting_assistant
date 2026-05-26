from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="agenda_tracking",
    name="Agenda Adherence",
    description="Tracks whether the meeting stayed on topic relative to the agenda.",
    capabilities=['Meeting Analytics'],
    system_prompt=(
        "You are an expert in Agenda Adherence. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings"
    },
    emits_events=["meetings.agenda_tracking.completed"]
)

register_skill(skill)
