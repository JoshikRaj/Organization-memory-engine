"""
extraction/expert_identifier.py

Identifies domain experts by analyzing:
1. Who is mentioned in documents about each topic (mention_count)
2. Who is listed in extracted decisions for each topic (decision_count)
3. How recently they were active (recency bonus)
4. Combined into a single expertise_score per person per topic

This answers questions like:
  "Who knows the most about ZooKeeper?"
  "Who should a new engineer ask about replication?"
  "Who originally drove the KRaft migration?"

Zero LLM calls. Zero API cost. Pure SQL aggregation + Python scoring.
This is intentional — not every problem needs an LLM.
That judgment is what interviewers respect.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from src.storage.database import get_connection

logger = logging.getLogger(__name__)


# ── Scoring weights ───────────────────────────────────────────────
# These are the levers you tune. Write these down —
# interviewers will ask "how did you calculate expertise score?"
# and you need a real answer, not "I just made it up."

DECISION_WEIGHT = 3.0     # being in a decision = 3x more valuable than a mention
MENTION_WEIGHT = 1.0      # being mentioned in a document
RECENCY_BONUS = 0.2       # bonus for activity in last 6 months
MAX_SCORE = 10.0          # cap score for normalization


def calculate_expertise_score(
    decision_count: int,
    mention_count: int,
    last_active: Optional[datetime],
) -> float:
    """
    Calculates a normalized expertise score for one person on one topic.

    Formula:
        raw = (decision_count * DECISION_WEIGHT) + (mention_count * MENTION_WEIGHT)
        bonus = RECENCY_BONUS if active in last 180 days
        score = min(raw + bonus, MAX_SCORE) / MAX_SCORE  → 0.0 to 1.0

    Why this formula?
    Decisions require active participation and judgment — they're worth more
    than just being mentioned. Recency matters because an expert who left
    2 years ago is less useful than one who was active last month.
    """
    raw = (decision_count * DECISION_WEIGHT) + (mention_count * MENTION_WEIGHT)

    recency_bonus = 0.0
    if last_active:
        now = datetime.now(timezone.utc)
        if last_active.tzinfo is None:
            last_active = last_active.replace(tzinfo=timezone.utc)
        days_since_active = (now - last_active).days
        if days_since_active <= 180:
            recency_bonus = RECENCY_BONUS

    score = min(raw + recency_bonus, MAX_SCORE) / MAX_SCORE
    return round(score, 4)


def build_mention_scores(conn) -> dict:
    """
    Step 1: Count how many times each person is mentioned
    in documents that also mention each system/topic.

    Returns: {(person_name, topic): (mention_count, last_active)}
    """
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            p.entity_text AS person_name,
            s.entity_text AS topic,
            COUNT(DISTINCT p.doc_id) AS mention_count,
            MAX(r.timestamp) AS last_active
        FROM entities p
        JOIN entities s ON p.doc_id = s.doc_id
        JOIN raw_documents r ON p.doc_id = r.id
        WHERE p.entity_type = 'PERSON'
          AND s.entity_type IN ('SYSTEM', 'PRODUCT', 'ORG')
          AND p.entity_text != s.entity_text
          AND LENGTH(p.entity_text) > 2
          AND LENGTH(s.entity_text) > 2
        GROUP BY p.entity_text, s.entity_text
        HAVING COUNT(DISTINCT p.doc_id) >= 2
        ORDER BY mention_count DESC;
    """)

    rows = cursor.fetchall()
    cursor.close()

    mention_scores = {}
    for person_name, topic, mention_count, last_active in rows:
        mention_scores[(person_name.strip(), topic.strip())] = {
            "mention_count": mention_count,
            "last_active": last_active,
        }

    logger.info(f"Found {len(mention_scores)} person-topic mention pairs")
    return mention_scores


def build_decision_scores(conn) -> dict:
    """
    Step 2: Count how many decisions each person was involved in
    for each topic area.

    Returns: {(person_name, topic): decision_count}
    """
    cursor = conn.cursor()

    # decisions.people_involved is a TEXT[] array in PostgreSQL
    # unnest() expands it into individual rows — one per person
    cursor.execute("""
        SELECT
            TRIM(unnest(d.people_involved)) AS person_name,
            s.entity_text AS topic,
            COUNT(DISTINCT d.id) AS decision_count
        FROM decisions d
        JOIN entities s ON d.doc_id = s.doc_id
        WHERE s.entity_type IN ('SYSTEM', 'PRODUCT', 'ORG')
          AND array_length(d.people_involved, 1) > 0
          AND d.confidence >= 0.6
        GROUP BY person_name, s.entity_text
        HAVING COUNT(DISTINCT d.id) >= 1
        ORDER BY decision_count DESC;
    """)

    rows = cursor.fetchall()
    cursor.close()

    decision_scores = {}
    for person_name, topic, decision_count in rows:
        if person_name and topic:
            decision_scores[(person_name.strip(), topic.strip())] = decision_count

    logger.info(f"Found {len(decision_scores)} person-topic decision pairs")
    return decision_scores


def upsert_expert(conn, person_name: str, topic: str,
                  decision_count: int, mention_count: int,
                  last_active: Optional[datetime], score: float) -> bool:
    """
    Inserts or updates one expert-topic record.
    Uses ON CONFLICT to update if record already exists.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO experts
                (person_name, topic, expertise_score,
                 decision_count, mention_count, last_active, updated_at)
            VALUES
                (%s, %s, %s, %s, %s, %s, NOW())
            ON CONFLICT (person_name, topic)
            DO UPDATE SET
                expertise_score = EXCLUDED.expertise_score,
                decision_count = EXCLUDED.decision_count,
                mention_count = EXCLUDED.mention_count,
                last_active = EXCLUDED.last_active,
                updated_at = NOW();
        """, (person_name, topic, score, decision_count, mention_count, last_active))

        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Upsert failed for {person_name}/{topic}: {e}")
        return False
    finally:
        cursor.close()


def run_expert_identification():
    """
    Main function. Combines mention scores + decision scores
    into a single expertise score per person per topic.
    Stores results in the experts table.
    """
    logger.info("Starting expert identification...")
    conn = get_connection()

    # Step 1: Get mention-based scores
    mention_scores = build_mention_scores(conn)

    # Step 2: Get decision-based scores
    decision_scores = build_decision_scores(conn)

    # Step 3: Merge all person-topic pairs
    all_pairs = set(mention_scores.keys()) | set(decision_scores.keys())
    logger.info(f"Total unique person-topic pairs to score: {len(all_pairs)}")

    total_inserted = 0
    total_failed = 0

    for person_name, topic in all_pairs:
        # Skip noise — single character names, numbers, etc.
        if len(person_name) < 3 or len(topic) < 3:
            continue

        mention_data = mention_scores.get((person_name, topic), {})
        mention_count = mention_data.get("mention_count", 0)
        last_active = mention_data.get("last_active")
        decision_count = decision_scores.get((person_name, topic), 0)

        score = calculate_expertise_score(
            decision_count=decision_count,
            mention_count=mention_count,
            last_active=last_active,
        )

        # Only store if score is meaningful
        if score < 0.05:
            continue

        success = upsert_expert(
            conn=conn,
            person_name=person_name,
            topic=topic,
            decision_count=decision_count,
            mention_count=mention_count,
            last_active=last_active,
            score=score,
        )

        if success:
            total_inserted += 1
        else:
            total_failed += 1

    conn.close()
    logger.info(
        f"Expert identification complete: "
        f"{total_inserted} experts stored | "
        f"{total_failed} failed"
    )

    return {
        "total_pairs_evaluated": len(all_pairs),
        "experts_stored": total_inserted,
        "failed": total_failed,
    }


def query_experts_for_topic(topic: str, top_k: int = 5) -> list[dict]:
    """
    Query function — answers "who knows the most about X?"
    This is what the RAG layer will call in Week 4.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            person_name,
            topic,
            expertise_score,
            decision_count,
            mention_count,
            last_active
        FROM experts
        WHERE LOWER(topic) LIKE LOWER(%s)
        ORDER BY expertise_score DESC
        LIMIT %s;
    """, (f"%{topic}%", top_k))

    rows = cursor.fetchall()
    cursor.close()
    conn.close()

    results = []
    for row in rows:
        results.append({
            "person": row[0],
            "topic": row[1],
            "score": row[2],
            "decisions_involved_in": row[3],
            "times_mentioned": row[4],
            "last_active": str(row[5]) if row[5] else "unknown",
        })

    return results


def print_expert_report():
    """
    Prints a human-readable expert report.
    Run this after identification to verify results look right.
    """
    conn = get_connection()
    cursor = conn.cursor()

    print("\n" + "=" * 60)
    print("TOP EXPERTS BY TOPIC")
    print("=" * 60)

    # Get top topics by expert count
    cursor.execute("""
        SELECT topic, COUNT(*) as expert_count
        FROM experts
        GROUP BY topic
        ORDER BY expert_count DESC
        LIMIT 10;
    """)
    top_topics = cursor.fetchall()

    for topic, count in top_topics:
        print(f"\n[*] Topic: {topic} ({count} experts)")

        cursor.execute("""
            SELECT person_name, expertise_score, decision_count, mention_count
            FROM experts
            WHERE topic = %s
            ORDER BY expertise_score DESC
            LIMIT 3;
        """, (topic,))

        experts = cursor.fetchall()
        for person, score, decisions, mentions in experts:
            print(f"   >> {person:<25} score={score:.3f}  "
                  f"decisions={decisions}  mentions={mentions}")

    print("\n" + "=" * 60)
    cursor.close()
    conn.close()


if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    result = run_expert_identification()
    print(json.dumps(result, indent=2))

    print_expert_report()

    # Test the query function
    print("\n=== Query Test: Who knows ZooKeeper? ===")
    experts = query_experts_for_topic("zookeeper", top_k=3)
    for e in experts:
        print(f"  {e['person']} — score: {e['score']} | "
              f"decisions: {e['decisions_involved_in']} | "
              f"mentions: {e['times_mentioned']}")
