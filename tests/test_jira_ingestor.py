"""
tests/test_jira_ingestor.py
Basic sanity tests for the Jira ingestor.
"""

import pytest
from src.ingestion.jira_ingestor import fetch_jira_issues, parse_issue


def test_fetch_jira_issues_returns_data():
    """API call should return issues with expected structure."""
    data = fetch_jira_issues(start_at=0, max_results=2)

    assert "issues" in data
    assert len(data["issues"]) > 0
    assert "key" in data["issues"][0]


def test_parse_issue_returns_valid_schema():
    """Parsed issue should match our raw_documents schema."""
    data = fetch_jira_issues(start_at=0, max_results=1)
    issue = data["issues"][0]
    parsed = parse_issue(issue)

    assert parsed["source"] == "jira"
    assert isinstance(parsed["content"], str)
    assert len(parsed["content"]) > 0
    assert parsed["author"] is not None
    assert "jira_key" in parsed["metadata"]
    assert len(parsed["content_hash"]) == 64  # sha256 hex length


def test_parse_issue_handles_missing_description():
    """Should not crash if an issue has no description."""
    fake_issue = {
        "key": "TEST-1",
        "fields": {
            "summary": "Test issue",
            "description": None,
            "comment": {"comments": []},
            "reporter": None,
            "created": "2023-01-01T10:00:00.000+0000",
            "status": {"name": "Open"},
        },
    }
    parsed = parse_issue(fake_issue)
    assert parsed["content"] is not None
    assert parsed["author"] == "Unknown"
