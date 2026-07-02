"""
extraction/entity_extractor.py
Extracts entities from documents using spaCy.
Entities: PERSON (contributors), ORG (teams), PRODUCT (systems/components)

This runs on every document in raw_documents and stores results in the
entities table for later use in the knowledge graph.
"""

import logging
import re
from typing import Optional

import spacy
from src.storage.database import get_connection

logger = logging.getLogger(__name__)

# Load once at module level — loading spaCy model is expensive, do it once
nlp = spacy.load("en_core_web_lg")


# Kafka-specific system/component names spaCy won't know about
KAFKA_SYSTEMS = {
    "zookeeper", "kraft", "kafka streams", "kafka connect",
    "schema registry", "ksqldb", "consumer group", "log compaction",
    "partition", "replication", "broker", "producer", "consumer",
    "topics", "offsets", "mirrormaker", "tiered storage",
}


def extract_entities(text: str, doc_id: int) -> list[dict]:
    """
    Runs spaCy NER + custom Kafka term detection on a piece of text.
    Returns a list of entity dicts ready to insert into the entities table.
    """
    if not text or len(text.strip()) < 10:
        return []

    # spaCy has a max length limit — truncate if needed
    text = text[:100000]
    doc = nlp(text)
    entities = []
    seen = set()  # avoid duplicate entities per document

    # ---- spaCy standard entities ----
    for ent in doc.ents:
        if ent.label_ not in ("PERSON", "ORG", "PRODUCT", "GPE"):
            continue

        clean_text = ent.text.strip()
        if len(clean_text) < 2:
            continue

        key = (clean_text.lower(), ent.label_)
        if key in seen:
            continue
        seen.add(key)

        entities.append({
            "doc_id": doc_id,
            "entity_text": clean_text,
            "entity_type": ent.label_,
            "confidence": 0.85,
        })

    # ---- Custom Kafka system detection ----
    text_lower = text.lower()
    for system_name in KAFKA_SYSTEMS:
        if system_name in text_lower:
            key = (system_name, "SYSTEM")
            if key in seen:
                continue
            seen.add(key)

            entities.append({
                "doc_id": doc_id,
                "entity_text": system_name,
                "entity_type": "SYSTEM",
                "confidence": 0.95,
            })

    # ---- Extract Jira ticket references e.g. KAFKA-1234 ----
    jira_refs = re.findall(r"\bKAFKA-\d+\b", text)
    for ref in set(jira_refs):
        key = (ref, "JIRA_REF")
        if key in seen:
            continue
        seen.add(key)
        entities.append({
            "doc_id": doc_id,
            "entity_text": ref,
            "entity_type": "JIRA_REF",
            "confidence": 1.0,
        })

    return entities


def insert_entities(conn, entities: list[dict]) -> int:
    """Batch inserts entities. Returns count inserted."""
    if not entities:
        return 0

    cursor = conn.cursor()
    inserted = 0

    for entity in entities:
        try:
            cursor.execute("""
                INSERT INTO entities (doc_id, entity_text, entity_type, confidence)
                VALUES (%(doc_id)s, %(entity_text)s, %(entity_type)s, %(confidence)s)
                ON CONFLICT DO NOTHING;
            """, entity)
            inserted += 1
        except Exception as e:
            logger.error(f"Entity insert failed: {e}")
            conn.rollback()
            continue

    conn.commit()
    cursor.close()
    return inserted


def run_entity_extraction(batch_size: int = 50):
    """
    Processes all unprocessed documents in raw_documents.
    Marks documents as processed after extraction so reruns skip them.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Add processed flag if it doesn't exist yet
    cursor.execute("""
        ALTER TABLE raw_documents
        ADD COLUMN IF NOT EXISTS entities_extracted BOOLEAN DEFAULT FALSE;
    """)
    conn.commit()

    # Fetch unprocessed documents in batches
    cursor.execute("""
        SELECT id, content FROM raw_documents
        WHERE entities_extracted = FALSE
        AND content IS NOT NULL
        AND LENGTH(content) > 10
        ORDER BY id
        LIMIT %s;
    """, (batch_size,))

    docs = cursor.fetchall()
    cursor.close()

    if not docs:
        logger.info("No unprocessed documents found")
        conn.close()
        return {"processed": 0, "entities_found": 0}

    total_processed = 0
    total_entities = 0

    logger.info(f"Processing {len(docs)} documents...")

    for doc_id, content in docs:
        entities = extract_entities(content, doc_id)
        count = insert_entities(conn, entities)
        total_entities += count

        # Mark as processed
        cur2 = conn.cursor()
        cur2.execute(
            "UPDATE raw_documents SET entities_extracted = TRUE WHERE id = %s",
            (doc_id,)
        )
        conn.commit()
        cur2.close()

        total_processed += 1

        if total_processed % 10 == 0:
            logger.info(f"  Processed {total_processed}/{len(docs)} docs | "
                        f"Entities found: {total_entities}")

    conn.close()
    logger.info(f"Done: {total_processed} docs processed, {total_entities} entities extracted")
    return {"processed": total_processed, "entities_found": total_entities}


if __name__ == "__main__":
    import json
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")

    # Process in batches until all docs are done
    total = {"processed": 0, "entities_found": 0}
    while True:
        result = run_entity_extraction(batch_size=50)
        total["processed"] += result["processed"]
        total["entities_found"] += result["entities_found"]
        if result["processed"] == 0:
            break

    print(json.dumps(total, indent=2))
