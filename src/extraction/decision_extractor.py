"""
extraction/decision_extractor.py
Uses an LLM (OpenAI) to identify architectural decisions inside Jira issues and Git commits.

A "decision" = someone chose X over Y for reason Z.
Examples:
  - "We chose KRaft over ZooKeeper to remove the external dependency"
  - "Switched to async replication to improve throughput at the cost of durability"

Run with: python -m src.extraction.decision_extractor
"""

import json
import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from openai import OpenAI

from src.storage.database import get_connection

load_dotenv()
logger = logging.getLogger(__name__)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

# ── Prompt template ────────────────────────────────────────────────────────────
DECISION_PROMPT = """You are analyzing Apache Kafka project documents to extract architectural decisions.

A decision is when the team chose one approach over another, with a stated reason.

Document text:
\"\"\"
{text}
\"\"\"

Extract any architectural or technical decisions from this text.
If there are no clear decisions, return an empty list.

Respond ONLY with valid JSON in this exact format:
{{
  "decisions": [
    {{
      "decision_text": "One sentence describing what was decided",
      "rationale": "Why this decision was made (or null if not stated)",
      "people_involved": ["Name1", "Name2"],
      "alternatives_considered": ["Alternative A", "Alternative B"]
    }}
  ]
}}
"""


def extract_decisions_llm(text: str, doc_id: int) -> list[dict]:
    """
    Sends text to OpenAI and parses the returned decisions.
    Returns a list of decision dicts ready to insert.
    """
    # Truncate to stay well within token limits (~3000 tokens ≈ 12000 chars)
    text = text[:12000]

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",          # cheap and fast — good enough for extraction
            messages=[
                {"role": "user", "content": DECISION_PROMPT.format(text=text)}
            ],
            temperature=0,               # deterministic output
            max_tokens=1000,
            response_format={"type": "json_object"},
        )

        raw = response.choices[0].message.content
        parsed = json.loads(raw)
        decisions_raw = parsed.get("decisions", [])

        results = []
        for d in decisions_raw:
            if not d.get("decision_text"):
                continue
            results.append({
                "doc_id": doc_id,
                "decision_text": d.get("decision_text", ""),
                "rationale": d.get("rationale"),
                "people_involved": d.get("people_involved", []),
                "alternatives_considered": d.get("alternatives_considered", []),
                "confidence": 0.8,
            })
        return results

    except json.JSONDecodeError as e:
        logger.warning(f"JSON parse failed for doc {doc_id}: {e}")
        return []
    except Exception as e:
        logger.error(f"LLM call failed for doc {doc_id}: {e}")
        return []


def insert_decisions(conn, decisions: list[dict]) -> int:
    """Batch inserts decisions. Returns count inserted."""
    if not decisions:
        return 0

    cursor = conn.cursor()
    inserted = 0

    for d in decisions:
        try:
            cursor.execute("""
                INSERT INTO decisions
                    (doc_id, decision_text, rationale, people_involved,
                     alternatives_considered, confidence)
                VALUES
                    (%(doc_id)s, %(decision_text)s, %(rationale)s,
                     %(people_involved)s, %(alternatives_considered)s, %(confidence)s);
            """, d)
            inserted += 1
        except Exception as e:
            logger.error(f"Decision insert failed: {e}")
            conn.rollback()
            continue

    conn.commit()
    cursor.close()
    return inserted


def run_decision_extraction(batch_size: int = 20):
    """
    Processes documents that haven't had decision extraction yet.
    Only runs on Jira issues (richer text = more decisions).
    Skips documents under 100 chars — not enough content for decisions.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Add a flag column to track which docs have been processed
    cursor.execute("""
        ALTER TABLE raw_documents
        ADD COLUMN IF NOT EXISTS decisions_extracted BOOLEAN DEFAULT FALSE;
    """)
    conn.commit()

    # Focus on Jira — commits are too short for reliable decision extraction
    cursor.execute("""
        SELECT id, content FROM raw_documents
        WHERE decisions_extracted = FALSE
        AND source = 'jira'
        AND content IS NOT NULL
        AND LENGTH(content) > 100
        ORDER BY id
        LIMIT %s;
    """, (batch_size,))

    docs = cursor.fetchall()
    cursor.close()

    if not docs:
        logger.info("No unprocessed Jira documents found")
        conn.close()
        return {"processed": 0, "decisions_found": 0}

    total_processed = 0
    total_decisions = 0

    logger.info(f"Processing {len(docs)} documents for decision extraction...")

    for doc_id, content in docs:
        decisions = extract_decisions_llm(content, doc_id)
        count = insert_decisions(conn, decisions)
        total_decisions += count

        # Mark as processed regardless of whether decisions were found
        cur2 = conn.cursor()
        cur2.execute(
            "UPDATE raw_documents SET decisions_extracted = TRUE WHERE id = %s",
            (doc_id,)
        )
        conn.commit()
        cur2.close()

        total_processed += 1

        if decisions:
            logger.info(f"  Doc {doc_id}: {count} decision(s) found")

        # Rate limit: ~3 req/sec to stay inside OpenAI free tier limits
        time.sleep(0.4)

    conn.close()
    logger.info(f"Done: {total_processed} docs | {total_decisions} decisions extracted")
    return {"processed": total_processed, "decisions_found": total_decisions}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")

    if not os.getenv("OPENAI_API_KEY"):
        print("ERROR: OPENAI_API_KEY not set in .env — add it and re-run")
        exit(1)

    total = {"processed": 0, "decisions_found": 0}
    while True:
        result = run_decision_extraction(batch_size=20)
        total["processed"] += result["processed"]
        total["decisions_found"] += result["decisions_found"]
        if result["processed"] == 0:
            break

    print(json.dumps(total, indent=2))
