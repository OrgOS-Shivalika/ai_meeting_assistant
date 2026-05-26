from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="postmortem_generator",
    name="Blameless Postmortem",
    description="Generates blameless postmortems from incident timelines.",
    capabilities=['Incident Management', 'Documentation'],
    system_prompt=(
        "You are an expert in Blameless Postmortem. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "incidents"
    },
    emits_events=["incidents.postmortem_generator.completed"]
)

register_skill(skill)
