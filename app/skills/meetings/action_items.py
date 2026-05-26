from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="action_items",
    name="Action Item Extraction",
    description="Extracts structured action items with owners and deadlines.",
    capabilities=['Action Items'],
    system_prompt=(
        "You are an expert in Action Item Extraction. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings"
    },
    emits_events=["meetings.action_items.completed"]
)

register_skill(skill)
