from app.skills.base import SkillDefinition
from app.skills.registry import register_skill

skill = SkillDefinition(
    id="sentiment_analysis",
    name="Meeting Sentiment Analysis",
    description="Analyzes participant sentiment and engagement levels.",
    capabilities=['Sentiment Analysis'],
    system_prompt=(
        "You are an expert in Meeting Sentiment Analysis. Your task is to process the input "
        "and provide structured insights related to this domain."
    ),
    retrieval_config={
        "top_k": 10,
        "search_bias": "meetings"
    },
    emits_events=["meetings.sentiment_analysis.completed"]
)

register_skill(skill)
