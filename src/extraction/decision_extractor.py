"""
extraction/decision_extractor.py

This is the CORE differentiator of the entire project.

While every RAG chatbot finds documents, this module extracts DECISIONS —
the actual choices made, why they were made, who made them, and what
alternatives were considered.

This is what lets us answer:
  "Why did Apache Kafka move away from ZooKeeper?"
  instead of just:
  "Find documents that mention ZooKeeper"
"""

import json
import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai
from pydantic import BaseModel, Field

from src.storage.database import get_connection

load_dotenv()
logger = logging.getLogger(__name__)

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))


# ── Pydantic schema ──────────────────────────────────────────────
# This is the structured output we force the LLM to return.
# Pydantic validates it — if the LLM returns garbage JSON, we catch it.

class DecisionSchema(BaseModel):
    contains_decision: bool = Field(
        description="True if this text contains a clear technical or architectural decision"
    )
    decision_text: Optional[str] = Field(
        None,
        description="One sentence summary of the decision made"
    )
    rationale: Optional[str] = Field(
        None,
        description="Why this decision was made — the reasoning behind it"
    )
    people_involved: list[str] = Field(
        default_factory=list,
        description="Names of people who proposed or approved this decision"
    )
    alternatives_considered: list[str] = Field(
        default_factory=list,
        description="Other options that were considered but rejected"
    )
    confidence: float = Field(
        default=0.0,
        description="Your confidence this is a real decision, 0.0 to 1.0"
    )


# ── Extraction prompt ────────────────────────────────────────────
# This prompt is everything.

DECISION_EXTRACTION_PROMPT = """You are analyzing organizational communication to extract technical decisions.

A DECISION is when a team or person:
- Chooses one technical approach over another
- Deprecates or replaces a component
- Agrees to a design that will be implemented
- Rejects a proposal with a stated reason

NOT a decision:
- Bug reports without resolution
- Questions without answers
- General discussion without conclusion
- Status updates

Analyze the following text and extract any decision present.

TEXT:
{text}

Respond ONLY with a JSON object. No explanation, no markdown, just raw JSON.
Use this exact structure:
{{
  "contains_decision": true or false,
  "decision_text": "one sentence — what was decided",
  "rationale": "why this was decided",
  "people_involved": ["Name1", "Name2"],
  "alternatives_considered": ["option A", "option B"],
  "confidence": 0.0 to 1.0
}}

If no decision is present, set contains_decision to false and all other fields to null or empty."""


# ── LLM call function ────────────────────────────────────────────

def extract_decision_from_text(text: str) -> Optional[DecisionSchema]:
    """
    Calls Gemini Flash to extract a decision from text.
    Returns a validated DecisionSchema or None if extraction fails.

    Uses Google Gemini (free tier: 15 RPM, 1M tokens/day) instead of
    OpenAI to avoid API costs during development.
    """
    # Truncate to ~2000 tokens to save cost
    # Most decisions are captured in the first part of the text anyway
    text = text[:6000]

    if not text.strip():
        return None

    try:
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=[
                DECISION_EXTRACTION_PROMPT.format(text=text)
            ],
            config={
                "system_instruction": "You extract structured data from text. Always respond with valid JSON only.",
                "temperature": 0.1,
                "max_output_tokens": 500,
            },
        )

        raw = response.text.strip()

        # Strip markdown code blocks if LLM adds them despite instructions
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]

        parsed = json.loads(raw)
        return DecisionSchema(**parsed)

    except json.JSONDecodeError as e:
        logger.warning(f"LLM returned invalid JSON: {e}")
        return None
    except Exception as e:
        logger.error(f"Decision extraction failed: {e}")
        return None


# ── Database insertion ────────────────────────────────────────────

def insert_decision(conn, doc_id: int, decision: DecisionSchema) -> Optional[int]:
    """Inserts a validated decision into the decisions table."""
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO decisions
                (doc_id, decision_text, rationale, people_involved,
                 alternatives_considered, confidence)
            VALUES
                (%s, %s, %s, %s, %s, %s)
            RETURNING id;
        """, (
            doc_id,
            decision.decision_text,
            decision.rationale,
            decision.people_involved,
            decision.alternatives_considered,
            decision.confidence,
        ))
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else None
    except Exception as e:
        conn.rollback()
        logger.error(f"Decision insert failed for doc {doc_id}: {e}")
        return None
    finally:
        cursor.close()


# ── Main extraction loop ─────────────────────────────────────────

def run_decision_extraction(batch_size: int = 50):
    """
    Processes all documents that haven't had decision extraction yet.
    Only ~30% of documents will contain real decisions — that's expected.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Add tracking column if not exists
    cursor.execute("""
        ALTER TABLE raw_documents
        ADD COLUMN IF NOT EXISTS decision_extracted BOOLEAN DEFAULT FALSE;
    """)
    conn.commit()

    # Fetch unprocessed docs — prioritize Jira issues (more likely to have decisions)
    cursor.execute("""
        SELECT id, content, source FROM raw_documents
        WHERE decision_extracted = FALSE
        AND content IS NOT NULL
        AND LENGTH(content) > 50
        ORDER BY
            CASE WHEN source = 'jira' THEN 0 ELSE 1 END,
            id
        LIMIT %s;
    """, (batch_size,))

    docs = cursor.fetchall()
    cursor.close()

    if not docs:
        logger.info("No unprocessed documents found")
        conn.close()
        return {"processed": 0, "decisions_found": 0}

    total_processed = 0
    total_decisions = 0
    total_cost_estimate = 0.0

    logger.info(f"Processing {len(docs)} documents for decision extraction...")

    for doc_id, content, source in docs:
        decision = extract_decision_from_text(content)

        if decision and decision.contains_decision and decision.confidence >= 0.6:
            result = insert_decision(conn, doc_id, decision)
            if result:
                total_decisions += 1
                logger.debug(f"  Decision found in doc {doc_id}: {decision.decision_text[:80]}")

        # Mark as processed regardless of whether a decision was found
        cur2 = conn.cursor()
        cur2.execute(
            "UPDATE raw_documents SET decision_extracted = TRUE WHERE id = %s",
            (doc_id,)
        )
        conn.commit()
        cur2.close()

        total_processed += 1
        total_cost_estimate += 0.0005  # rough cost estimate per doc

        if total_processed % 10 == 0:
            logger.info(
                f"  Progress: {total_processed}/{len(docs)} | "
                f"Decisions: {total_decisions} | "
                f"Est. cost: ${total_cost_estimate:.3f}"
            )

        # Rate limiting — Gemini free tier allows 15 req/min
        time.sleep(4)

    conn.close()
    logger.info(
        f"Done: {total_processed} docs | "
        f"{total_decisions} decisions extracted | "
        f"Est. cost: ${total_cost_estimate:.3f}"
    )

    return {
        "processed": total_processed,
        "decisions_found": total_decisions,
        "estimated_cost_usd": round(total_cost_estimate, 3),
    }


if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    total = {"processed": 0, "decisions_found": 0}
    while True:
        result = run_decision_extraction(batch_size=50)
        total["processed"] += result["processed"]
        total["decisions_found"] += result["decisions_found"]
        if result["processed"] == 0:
            break

    print(json.dumps(total, indent=2))
