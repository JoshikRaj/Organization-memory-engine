"""
tests/test_decision_extractor.py
Unit tests for the decision extractor.
The LLM call is mocked — no API key needed to run these tests.
"""

from unittest.mock import patch, MagicMock
from src.extraction.decision_extractor import extract_decisions_llm, insert_decisions


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_mock_response(decisions: list) -> MagicMock:
    """Builds a fake OpenAI response object."""
    import json
    mock_response = MagicMock()
    mock_response.choices[0].message.content = json.dumps({"decisions": decisions})
    return mock_response


# ── Tests ─────────────────────────────────────────────────────────────────────

@patch("src.extraction.decision_extractor.client")
def test_extracts_decision_from_text(mock_client):
    """Should parse a valid decision out of LLM response."""
    mock_client.chat.completions.create.return_value = make_mock_response([
        {
            "decision_text": "Replace ZooKeeper with KRaft for metadata management",
            "rationale": "Remove external dependency and simplify operations",
            "people_involved": ["Jun Rao"],
            "alternatives_considered": ["Keep ZooKeeper", "Use etcd"],
        }
    ])

    results = extract_decisions_llm("We decided to use KRaft...", doc_id=1)

    assert len(results) == 1
    assert results[0]["doc_id"] == 1
    assert "KRaft" in results[0]["decision_text"]
    assert results[0]["rationale"] is not None
    assert "Jun Rao" in results[0]["people_involved"]


@patch("src.extraction.decision_extractor.client")
def test_returns_empty_when_no_decisions(mock_client):
    """Should return empty list when LLM finds no decisions."""
    mock_client.chat.completions.create.return_value = make_mock_response([])

    results = extract_decisions_llm("Fixed a typo in the README.", doc_id=2)
    assert results == []


@patch("src.extraction.decision_extractor.client")
def test_handles_llm_error_gracefully(mock_client):
    """Should return empty list on API failure, not crash."""
    mock_client.chat.completions.create.side_effect = Exception("API timeout")

    results = extract_decisions_llm("Some content", doc_id=3)
    assert results == []


@patch("src.extraction.decision_extractor.client")
def test_multiple_decisions_in_one_doc(mock_client):
    """Should handle documents containing multiple decisions."""
    mock_client.chat.completions.create.return_value = make_mock_response([
        {
            "decision_text": "Use async replication for higher throughput",
            "rationale": "Latency requirements outweigh durability needs",
            "people_involved": [],
            "alternatives_considered": ["Sync replication"],
        },
        {
            "decision_text": "Set default partition count to 3",
            "rationale": "Balance between parallelism and overhead",
            "people_involved": ["Neha Narkhede"],
            "alternatives_considered": ["1 partition", "6 partitions"],
        },
    ])

    results = extract_decisions_llm("Long Jira discussion...", doc_id=4)
    assert len(results) == 2
    assert all(r["doc_id"] == 4 for r in results)
