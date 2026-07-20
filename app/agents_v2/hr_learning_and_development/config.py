"""Runtime knobs for the HR agent. NOT AI prompts — those live in prompts/."""

CONFIG = {
    # Harness safety rails (only used when harness_enabled=True in manifest)
    "max_iterations": 6,
    "max_tokens_per_loop": 25_000,
    "per_tool_timeout_seconds": 10,

    # If the master LLM call fails transiently, retry once. Non-fatal
    # failures still bubble up — this is only for network/API blips.
    "retry_on_llm_error": True,

    # How much of the KnowledgeContext to render into the master prompt.
    # Bigger = more context but more tokens. 3500 chars ≈ 900 tokens.
    "knowledge_block_max_chars": 3500,

    # Logging verbosity for this agent's execution path.
    "log_level": "INFO",
}
