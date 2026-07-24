"""
storage/graph_builder.py

Populates the Neo4j knowledge graph from your existing PostgreSQL data.
Reads from: entities, decisions, raw_documents, experts tables
Writes to:  Neo4j nodes and relationships

The graph structure:
  (Person)-[:PROPOSED]->(Decision)-[:INVOLVES]->(System)
  (Decision)-[:DOCUMENTED_IN]->(Document)
  (Person)-[:EXPERTISE_IN]->(Topic)
  (Decision)-[:CONTRADICTS]->(Decision)  ← Week 3 Day 3

This is what enables multi-hop queries like:
  "Who proposed decisions that affect ZooKeeper?"
  → traverse Person → PROPOSED → Decision → INVOLVES → System(ZooKeeper)
"""

import logging
from datetime import datetime
from typing import Optional

from src.storage.database import get_connection
from src.storage.graph_db import GraphDB, create_schema

logger = logging.getLogger(__name__)


# ── Node creation functions ──────────────────────────────────────

def create_document_nodes(db: GraphDB, pg_conn) -> int:
    """
    Creates Document nodes from raw_documents table.
    Each document becomes a node with source, timestamp, and content preview.
    """
    cursor = pg_conn.cursor()
    cursor.execute("""
        SELECT id, source, author, timestamp,
               LEFT(content, 300) as preview,
               metadata->>'kip_number' as kip_number,
               metadata->>'jira_key' as jira_key,
               metadata->>'sha' as git_sha
        FROM raw_documents
        ORDER BY id;
    """)
    docs = cursor.fetchall()
    cursor.close()

    count = 0
    for doc_id, source, author, timestamp, preview, kip_num, jira_key, git_sha in docs:
        source_id = kip_num or jira_key or git_sha or str(doc_id)

        db.run_write("""
            MERGE (d:Document {source_id: $source_id})
            SET d.pg_id = $pg_id,
                d.source = $source,
                d.author = $author,
                d.timestamp = $timestamp,
                d.preview = $preview,
                d.updated_at = datetime()
        """, {
            "source_id": source_id,
            "pg_id": doc_id,
            "source": source,
            "author": author or "Unknown",
            "timestamp": str(timestamp) if timestamp else None,
            "preview": preview or "",
        })
        count += 1

    logger.info(f"Created/updated {count} Document nodes")
    return count


def create_person_nodes(db: GraphDB, pg_conn) -> int:
    """
    Creates Person nodes from the entities table.
    People are the most connected nodes — they link to decisions,
    documents, and topics through relationships.
    """
    cursor = pg_conn.cursor()
    cursor.execute("""
        SELECT DISTINCT entity_text, COUNT(*) as mention_count
        FROM entities
        WHERE entity_type = 'PERSON'
        AND LENGTH(entity_text) > 2
        GROUP BY entity_text
        HAVING COUNT(*) >= 2
        ORDER BY mention_count DESC;
    """)
    people = cursor.fetchall()
    cursor.close()

    count = 0
    for person_name, mention_count in people:
        db.run_write("""
            MERGE (p:Person {name: $name})
            SET p.mention_count = $mention_count,
                p.updated_at = datetime()
        """, {
            "name": person_name.strip(),
            "mention_count": mention_count,
        })
        count += 1

    logger.info(f"Created/updated {count} Person nodes")
    return count


def create_system_nodes(db: GraphDB, pg_conn) -> int:
    """
    Creates System nodes from entities table (SYSTEM type).
    Systems are the technical components — ZooKeeper, KRaft, etc.
    """
    cursor = pg_conn.cursor()
    cursor.execute("""
        SELECT DISTINCT entity_text, COUNT(*) as mention_count
        FROM entities
        WHERE entity_type IN ('SYSTEM', 'PRODUCT')
        AND LENGTH(entity_text) > 2
        GROUP BY entity_text
        HAVING COUNT(*) >= 2
        ORDER BY mention_count DESC;
    """)
    systems = cursor.fetchall()
    cursor.close()

    count = 0
    for system_name, mention_count in systems:
        db.run_write("""
            MERGE (s:System {name: $name})
            SET s.mention_count = $mention_count,
                s.updated_at = datetime()
        """, {
            "name": system_name.strip().lower(),
            "mention_count": mention_count,
        })
        count += 1

    logger.info(f"Created/updated {count} System nodes")
    return count


def create_decision_nodes(db: GraphDB, pg_conn) -> int:
    """
    Creates Decision nodes from the decisions table.
    These are the core nodes — everything connects through decisions.
    """
    cursor = pg_conn.cursor()
    cursor.execute("""
        SELECT d.id, d.decision_text, d.rationale,
               d.people_involved, d.alternatives_considered,
               d.confidence, r.timestamp,
               r.id as doc_pg_id,
               r.metadata->>'kip_number' as kip_number,
               r.metadata->>'jira_key' as jira_key,
               r.metadata->>'sha' as git_sha,
               r.source
        FROM decisions d
        JOIN raw_documents r ON d.doc_id = r.id
        WHERE d.confidence >= 0.6
        ORDER BY d.confidence DESC;
    """)
    decisions = cursor.fetchall()
    cursor.close()

    count = 0
    for row in decisions:
        (dec_id, dec_text, rationale, people, alternatives,
         confidence, timestamp, doc_pg_id, kip_num,
         jira_key, git_sha, source) = row

        doc_source_id = kip_num or jira_key or git_sha or str(doc_pg_id)

        db.run_write("""
            MERGE (d:Decision {decision_id: $decision_id})
            SET d.text = $text,
                d.rationale = $rationale,
                d.alternatives = $alternatives,
                d.confidence = $confidence,
                d.timestamp = $timestamp,
                d.source = $source,
                d.updated_at = datetime()
        """, {
            "decision_id": f"dec_{dec_id}",
            "text": dec_text or "",
            "rationale": rationale or "",
            "alternatives": alternatives or [],
            "confidence": float(confidence or 0),
            "timestamp": str(timestamp) if timestamp else None,
            "source": source,
        })

        # Link decision to its source document
        db.run_write("""
            MATCH (dec:Decision {decision_id: $decision_id})
            MATCH (doc:Document {source_id: $doc_source_id})
            MERGE (dec)-[:DOCUMENTED_IN]->(doc)
        """, {
            "decision_id": f"dec_{dec_id}",
            "doc_source_id": doc_source_id,
        })

        # Link decision to people involved
        for person_name in (people or []):
            if person_name and len(person_name.strip()) > 2:
                db.run_write("""
                    MERGE (p:Person {name: $name})
                    WITH p
                    MATCH (dec:Decision {decision_id: $decision_id})
                    MERGE (p)-[:PROPOSED]->(dec)
                """, {
                    "name": person_name.strip(),
                    "decision_id": f"dec_{dec_id}",
                })

        count += 1

    logger.info(f"Created/updated {count} Decision nodes with relationships")
    return count


def create_expertise_relationships(db: GraphDB, pg_conn) -> int:
    """
    Creates EXPERTISE_IN relationships from the experts table.
    Person → EXPERTISE_IN → Topic (with score as relationship property)
    """
    cursor = pg_conn.cursor()
    cursor.execute("""
        SELECT person_name, topic, expertise_score,
               decision_count, mention_count
        FROM experts
        WHERE expertise_score >= 0.1
        ORDER BY expertise_score DESC;
    """)
    experts = cursor.fetchall()
    cursor.close()

    count = 0
    for person_name, topic, score, decisions, mentions in experts:
        # Create Topic node
        db.run_write("""
            MERGE (t:Topic {name: $name})
        """, {"name": topic.strip().lower()})

        # Create Person → EXPERTISE_IN → Topic relationship
        db.run_write("""
            MERGE (p:Person {name: $person_name})
            WITH p
            MERGE (t:Topic {name: $topic})
            MERGE (p)-[r:EXPERTISE_IN]->(t)
            SET r.score = $score,
                r.decision_count = $decisions,
                r.mention_count = $mentions,
                r.updated_at = datetime()
        """, {
            "person_name": person_name,
            "topic": topic.strip().lower(),
            "score": float(score),
            "decisions": int(decisions),
            "mentions": int(mentions),
        })
        count += 1

    logger.info(f"Created/updated {count} EXPERTISE_IN relationships")
    return count


def create_document_mentions(db: GraphDB, pg_conn) -> int:
    """
    Creates MENTIONS relationships between Documents and Systems.
    Document → MENTIONS → System
    This enables: "find all documents that mention ZooKeeper"
    via graph traversal instead of text search.
    """
    cursor = pg_conn.cursor()
    cursor.execute("""
        SELECT DISTINCT
            e.doc_id,
            r.metadata->>'kip_number' as kip_number,
            r.metadata->>'jira_key' as jira_key,
            r.metadata->>'sha' as git_sha,
            e.entity_text,
            e.entity_type,
            e.confidence
        FROM entities e
        JOIN raw_documents r ON e.doc_id = r.id
        WHERE e.entity_type IN ('SYSTEM', 'PRODUCT')
        AND e.confidence >= 0.8
        LIMIT 5000;
    """)
    mentions = cursor.fetchall()
    cursor.close()

    count = 0
    for doc_id, kip_num, jira_key, git_sha, entity_text, entity_type, confidence in mentions:
        doc_source_id = kip_num or jira_key or git_sha or str(doc_id)

        db.run_write("""
            MATCH (doc:Document {source_id: $doc_source_id})
            MERGE (s:System {name: $system_name})
            MERGE (doc)-[r:MENTIONS]->(s)
            SET r.confidence = $confidence
        """, {
            "doc_source_id": doc_source_id,
            "system_name": entity_text.strip().lower(),
            "confidence": float(confidence),
        })
        count += 1

    logger.info(f"Created/updated {count} MENTIONS relationships")
    return count


def run_graph_build():
    """
    Full graph build — runs all node/relationship creation in order.
    Safe to run multiple times — MERGE prevents duplicates.
    """
    pg_conn = get_connection()

    with GraphDB() as db:
        if not db.verify_connection():
            logger.error("Neo4j not reachable — is Docker running?")
            return

        create_schema(db)

        logger.info("Building knowledge graph...")
        start = datetime.now()

        docs = create_document_nodes(db, pg_conn)
        people = create_person_nodes(db, pg_conn)
        systems = create_system_nodes(db, pg_conn)
        decisions = create_decision_nodes(db, pg_conn)
        expertise = create_expertise_relationships(db, pg_conn)
        mentions = create_document_mentions(db, pg_conn)

        elapsed = (datetime.now() - start).seconds

        # Final stats
        stats = db.run("""
            MATCH (n)
            RETURN labels(n)[0] as label, COUNT(n) as count
            ORDER BY count DESC
        """)

        rel_stats = db.run("""
            MATCH ()-[r]->()
            RETURN type(r) as rel_type, COUNT(r) as count
            ORDER BY count DESC
        """)

        print(f"\n{'='*55}")
        print(f"KNOWLEDGE GRAPH BUILD COMPLETE ({elapsed}s)")
        print(f"{'='*55}")
        print(f"\nNODES:")
        for row in stats:
            print(f"  {row['label']:<15} {row['count']:>6} nodes")
        print(f"\nRELATIONSHIPS:")
        for row in rel_stats:
            print(f"  {row['rel_type']:<20} {row['count']:>6} edges")
        print(f"{'='*55}\n")

    pg_conn.close()
    return {
        "documents": docs,
        "people": people,
        "systems": systems,
        "decisions": decisions,
        "expertise_relationships": expertise,
        "mention_relationships": mentions,
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    run_graph_build()
