from datetime import datetime, timezone, timedelta
from src.extraction.expert_identifier import calculate_expertise_score


def test_decision_count_increases_score():
    """More decisions = higher score."""
    score_low = calculate_expertise_score(
        decision_count=1, mention_count=5, last_active=None
    )
    score_high = calculate_expertise_score(
        decision_count=5, mention_count=5, last_active=None
    )
    assert score_high > score_low


def test_recent_activity_gives_bonus():
    """Active in last 180 days = higher score than inactive person."""
    recent = datetime.now(timezone.utc) - timedelta(days=30)
    old = datetime.now(timezone.utc) - timedelta(days=400)

    score_recent = calculate_expertise_score(1, 5, recent)
    score_old = calculate_expertise_score(1, 5, old)

    assert score_recent > score_old


def test_score_is_between_0_and_1():
    """Score should always be normalized between 0 and 1."""
    score = calculate_expertise_score(
        decision_count=100, mention_count=1000, last_active=None
    )
    assert 0.0 <= score <= 1.0


def test_zero_activity_gives_zero_score():
    """No decisions, no mentions = zero score."""
    score = calculate_expertise_score(
        decision_count=0, mention_count=0, last_active=None
    )
    assert score == 0.0


def test_decisions_worth_more_than_mentions():
    """1 decision should outweigh several mentions (weight=3.0 vs 1.0)."""
    score_decision = calculate_expertise_score(1, 0, None)
    score_mentions = calculate_expertise_score(0, 2, None)
    assert score_decision > score_mentions
