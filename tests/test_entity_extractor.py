"""
tests/test_entity_extractor.py
Unit tests for the spaCy entity extractor.
These tests run without a database — they only test the parsing logic.
"""

from src.extraction.entity_extractor import extract_entities


def test_extracts_person():
    text = "Jay Kreps proposed the KRaft protocol to replace ZooKeeper in Kafka."
    entities = extract_entities(text, doc_id=1)
    types = [e["entity_type"] for e in entities]
    texts = [e["entity_text"].lower() for e in entities]

    assert "PERSON" in types
    assert any("kreps" in t for t in texts)


def test_extracts_kafka_systems():
    text = "The migration from ZooKeeper to KRaft is now complete."
    entities = extract_entities(text, doc_id=2)
    types = [e["entity_type"] for e in entities]
    assert "SYSTEM" in types


def test_extracts_jira_references():
    text = "This was tracked in KAFKA-1234 and related to KAFKA-5678."
    entities = extract_entities(text, doc_id=3)
    jira_refs = [e for e in entities if e["entity_type"] == "JIRA_REF"]
    assert len(jira_refs) == 2


def test_handles_empty_text():
    entities = extract_entities("", doc_id=4)
    assert entities == []
