"""
tests/test_decision_extractor.py
Unit tests for the decision extractor.
The LLM call is mocked — no API key needed to run these tests.
"""

from unittest.mock import patch, MagicMock
from src.extraction.decision_extractor import (
    extract_decision_from_text,
    DecisionSchema
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_mock_response(json_str: str) -> MagicMock:
    """Builds a fake Gemini response object."""
    mock_response = MagicMock()
    mock_response.text = json_str
    return mock_response


# ── Tests ─────────────────────────────────────────────────────────────────────

@patch("src.extraction.decision_extractor.client")
def test_extracts_clear_decision(mock_client):
    """Should parse a valid decision out of LLM response."""
    mock_client.models.generate_content.return_value = make_mock_response('''{
        "contains_decision": true,
        "decision_text": "Replace ZooKeeper with KRaft for metadata management",
        "rationale": "ZooKeeper added operational complexity and limited scalability",
        "people_involved": ["Jun Rao", "Jason Gustafson"],
        "alternatives_considered": ["Keeping ZooKeeper", "Using etcd"],
        "confidence": 0.92
    }''')

    text = """
    After discussion, the team decided to replace ZooKeeper with KRaft
    for metadata management. The main reason was that ZooKeeper added
    operational complexity. Jun Rao proposed this change. We considered
    keeping ZooKeeper or switching to etcd but rejected both.
    """
    result = extract_decision_from_text(text)
    assert result is not None
    assert result.contains_decision is True
    assert result.decision_text is not None
    assert "KRaft" in result.decision_text
    assert result.confidence > 0.5
    assert "Jun Rao" in result.people_involved


@patch("src.extraction.decision_extractor.client")
def test_returns_no_decision_for_bug_report(mock_client):
    """Bug reports without resolution should not be flagged as decisions."""
    mock_client.models.generate_content.return_value = make_mock_response('''{
        "contains_decision": false,
        "decision_text": null,
        "rationale": null,
        "people_involved": [],
        "alternatives_considered": [],
        "confidence": 0.1
    }''')

    text = """
    NullPointerException when consumer group rebalances.
    Stack trace: java.lang.NullPointerException at KafkaConsumer.java:847
    Steps to reproduce: start consumer, send messages, rebalance.
    """
    result = extract_decision_from_text(text)
    assert result is not None
    assert result.contains_decision is False
    assert result.confidence < 0.6


@patch("src.extraction.decision_extractor.client")
def test_handles_llm_error_gracefully(mock_client):
    """Should return None on API failure, not crash."""
    mock_client.models.generate_content.side_effect = Exception("API timeout")

    result = extract_decision_from_text("Some content")
    assert result is None


def test_handles_empty_text():
    """Should return None for empty text without calling the API."""
    result = extract_decision_from_text("")
    assert result is None


@patch("src.extraction.decision_extractor.client")
def test_handles_invalid_json(mock_client):
    """Should return None when LLM returns invalid JSON."""
    mock_client.models.generate_content.return_value = make_mock_response(
        "This is not valid JSON at all"
    )

    result = extract_decision_from_text("Some content about a decision")
    assert result is None


@patch("src.extraction.decision_extractor.client")
def test_pydantic_validation(mock_client):
    """Verify Pydantic validates the schema correctly."""
    mock_client.models.generate_content.return_value = make_mock_response('''{
        "contains_decision": true,
        "decision_text": "Use async replication for higher throughput",
        "rationale": "Latency requirements outweigh durability needs",
        "people_involved": [],
        "alternatives_considered": ["Sync replication"],
        "confidence": 0.85
    }''')

    result = extract_decision_from_text("Long Jira discussion...")
    assert isinstance(result, DecisionSchema)
    assert result.confidence == 0.85
    assert result.alternatives_considered == ["Sync replication"]
