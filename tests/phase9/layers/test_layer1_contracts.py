"""Phase 9 Layer 1 — Contract Runtime Tests.

Verifies:
- Schema validation
- Malformed JSON handling
- Missing field handling
- Typed output consistency
- Observability of failures
"""
import pytest
import json
from pydantic import ValidationError
from app.services.cognition.contracts import (
    ExtractionSummary, 
    ExtractionContractRuntime,
    ExtractionActionItem
)

def test_contract_valid_extraction():
    """Layer 1.1: Valid structured extraction."""
    valid_data = {
        "title": "Strategy Sync",
        "summary": "Discussed Q3 goals.",
        "cleaned_transcript": [{"speaker": "Alice", "text": "Hello"}],
        "decisions": [{"decision": "Approve budget", "made_by": "Alice"}],
        "action_items": [
            {"task": "Update deck", "owner": "Bob", "priority": "high"}
        ],
        "risks": [{"risk": "Tight timeline", "severity": "medium"}]
    }
    
    result = ExtractionContractRuntime.validate_and_parse(ExtractionSummary, valid_data)
    assert isinstance(result, ExtractionSummary)
    assert result.title == "Strategy Sync"
    assert len(result.action_items) == 1
    assert result.action_items[0].task == "Update deck"

def test_contract_malformed_json():
    """Layer 1.2: Malformed JSON string."""
    malformed_str = '{"title": "Broken", "summary": "Missing closing brace"' # No closing brace
    
    with pytest.raises(ValueError) as excinfo:
        ExtractionContractRuntime.validate_and_parse(ExtractionSummary, malformed_str)
    assert "Invalid JSON" in str(excinfo.value)

def test_contract_missing_required_fields():
    """Layer 1.3: JSON missing mandatory fields (e.g., title)."""
    incomplete_data = {
        "summary": "Missing title field"
    }
    
    with pytest.raises(ValidationError) as excinfo:
        ExtractionContractRuntime.validate_and_parse(ExtractionSummary, incomplete_data)
    # Pydantic v2 error contains 'title' and 'Field required'
    assert "title" in str(excinfo.value)

def test_contract_type_mismatch():
    """Layer 1.4: JSON with wrong types (e.g., action_items as string instead of list)."""
    wrong_types = {
        "title": "Type Mismatch",
        "summary": "Summary",
        "action_items": "should be a list"
    }
    
    with pytest.raises(ValidationError) as excinfo:
        ExtractionContractRuntime.validate_and_parse(ExtractionSummary, wrong_types)
    assert "action_items" in str(excinfo.value)

def test_contract_hallucinated_fields():
    """Layer 1.5: Verify that extra fields are handled (ignored by default in Pydantic models)."""
    extra_fields = {
        "title": "Extra Fields",
        "summary": "Summary",
        "hallucinated_field": "This should be ignored",
        "unsupported_metadata": {"key": "value"}
    }
    
    result = ExtractionContractRuntime.validate_and_parse(ExtractionSummary, extra_fields)
    assert isinstance(result, ExtractionSummary)
    assert not hasattr(result, "hallucinated_field")

def test_contract_empty_output():
    """Layer 1.6: Verify empty input handling."""
    with pytest.raises(ValidationError):
        ExtractionContractRuntime.validate_and_parse(ExtractionSummary, None)

def test_partial_action_item_defaults():
    """Layer 1.7: Verify defaults for optional fields in nested models."""
    partial_task = {
        "task": "Just a task"
    }
    result = ExtractionContractRuntime.validate_and_parse(ExtractionActionItem, partial_task)
    assert result.task == "Just a task"
    assert result.priority == "medium" # Default
    assert result.status == "pending" # Default
    assert result.owner is None
