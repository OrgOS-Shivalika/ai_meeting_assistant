from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional

class RetrievalConfig(BaseModel):
    sources: List[str] = Field(default_factory=list, description="Data sources for retrieval (e.g., 'architecture_docs', 'meeting_notes')")
    search_bias: Optional[str] = Field(default=None, description="Bias or focus area for semantic search")
    top_k: int = Field(default=10, description="Number of documents to retrieve")

class MemoryConfig(BaseModel):
    read_from_memory: bool = Field(default=True, description="Whether the skill should read from long-term memory")
    write_to_memory: bool = Field(default=False, description="Whether the skill should persist findings to long-term memory")
    memory_keys: List[str] = Field(default_factory=list, description="Specific memory keys to read/write")

class SkillDefinition(BaseModel):
    id: str = Field(..., description="Unique identifier for the skill (e.g., 'architecture_review')")
    name: str = Field(..., description="Human-readable name")
    description: str = Field(..., description="Detailed description of what the skill does")
    capabilities: List[str] = Field(default_factory=list, description="Capabilities this skill fulfills (e.g., ['Architecture Review'])")
    
    # Cognition & Execution
    system_prompt: str = Field(..., description="The core instruction set for the skill")
    
    # Dependencies & Resources
    retrieval_config: RetrievalConfig = Field(default_factory=RetrievalConfig, description="Retrieval requirements")
    memory_config: MemoryConfig = Field(default_factory=MemoryConfig, description="Memory interaction rules")
    required_tools: List[str] = Field(default_factory=list, description="External tools required (e.g., ['jira', 'github'])")
    
    # I/O & Orchestration
    input_schema: Dict[str, Any] = Field(default_factory=dict, description="Expected input variables for the prompt")
    output_schema: Dict[str, Any] = Field(default_factory=dict, description="Expected structured output format")
    emits_events: List[str] = Field(default_factory=list, description="Events this skill can trigger (e.g., ['architecture.risk_detected'])")
    
    # State
    enabled_by_default: bool = Field(default=True, description="Whether the skill is enabled by default when its capability is requested")
