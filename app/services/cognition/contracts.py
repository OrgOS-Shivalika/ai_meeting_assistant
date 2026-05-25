"""Phase 9.4 — Extraction Contract Runtime.

This module provides the "hard cognition" layer: typed schemas, validation,
and repair logic for LLM outputs. It ensures that the "AI Operating System"
operates on structured, reliable data primitives.
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional, Type, TypeVar
from pydantic import BaseModel, Field, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

# ---------------------------------------------------------------------------
# Core Extraction Schemas
# ---------------------------------------------------------------------------

class ExtractionDecision(BaseModel):
    decision: str
    made_by: Optional[str] = None
    context: Optional[str] = None

class ExtractionActionItem(BaseModel):
    task: str
    owner: Optional[str] = None
    due_date: Optional[str] = None # ISO 8601
    priority: str = "medium" # low|medium|high
    status: str = "pending"

class ExtractionRisk(BaseModel):
    risk: str
    severity: str = "medium" # low|medium|high

class ExtractionSummary(BaseModel):
    title: str
    summary: str
    cleaned_transcript: list[dict[str, str]] = Field(default_factory=list)
    decisions: list[ExtractionDecision] = Field(default_factory=list)
    action_items: list[ExtractionActionItem] = Field(default_factory=list)
    risks: list[ExtractionRisk] = Field(default_factory=list)

# ---------------------------------------------------------------------------
# Contract Runtime
# ---------------------------------------------------------------------------

class ExtractionContractRuntime:
    """Governs the extraction of structured data from LLM responses."""

    @staticmethod
    def validate_and_parse(model: Type[T], data: Any) -> T:
        """Validate raw dict data against a Pydantic model. 
        Raises ValidationError on failure."""
        if isinstance(data, str):
            try:
                data = json.loads(data)
            except json.JSONDecodeError as e:
                logger.error("Failed to decode JSON for contract validation: %s", e)
                raise ValueError(f"Invalid JSON: {e}") from e
        
        return model.model_validate(data)

    @staticmethod
    def repair_output(model: Type[T], raw_data: str, error: Exception) -> Optional[T]:
        """Future: Implement automated repair via LLM feedback loops.
        For now, logs the failure for observability (9.4 requirement)."""
        logger.warning(
            "Contract validation failed for %s. Error: %s. Raw data: %s",
            model.__name__, str(error), raw_data[:500]
        )
        # 9.4 Tracing (Phase 7I/Phase 9 runtime_logs placeholder)
        # In a real implementation, we would write to the runtime_logs table here.
        return None

    @classmethod
    def process_extraction(cls, model: Type[T], raw_response: str) -> T:
        """The main entry point for cognitive extractions.
        Validates the response and returns the typed object."""
        try:
            return cls.validate_and_parse(model, raw_response)
        except (ValidationError, ValueError, TypeError) as e:
            repaired = cls.repair_output(model, raw_response, e)
            if repaired:
                return repaired
            # If repair fails or is not implemented, we still need to satisfy 
            # the contract or fail explicitly.
            raise
