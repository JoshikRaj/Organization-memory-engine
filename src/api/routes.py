"""
api/routes.py

FastAPI router with five endpoints:
  GET  /health           — service health check
  GET  /stats            — data source statistics
  POST /query            — ask a question, get a RAG-powered answer
  GET  /experts/{topic}  — find domain experts for a topic
  GET  /decisions/{system} — find engineering decisions for a system
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.storage.database import get_connection
from src.retrieval.rag_pipeline import rag_answer

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Request / Response Models ────────────────────────────────────

class QueryRequest(BaseModel):
    question: str = Field(..., min_length=3, max_length=500,
                          description="Natural language question about Apache Kafka")


class SourceInfo(BaseModel):
    type: str
    source: Optional[str] = None
    similarity: Optional[float] = None
    preview: Optional[str] = None
    decision: Optional[str] = None
    confidence: Optional[float] = None


class ExpertInfo(BaseModel):
    person: str
    topic: Optional[str] = None
    score: Optional[float] = None
    decisions: Optional[int] = None
    mentions: Optional[int] = None


class QueryResponse(BaseModel):
    question: str
    answer: str
    sources: list[SourceInfo]
    graph_paths: list[str]
    experts: list[ExpertInfo]
    latency_ms: int


class HealthResponse(BaseModel):
    status: str
    postgres: str
    neo4j: str
    version: str


class StatsResponse(BaseModel):
    total_documents: int
    by_source: dict
    total_entities: int
    total_experts: int
    total_decisions: int = 0
    eval_accuracy: Optional[float] = None
    eval_run_id: Optional[str] = None


class ExpertsResponse(BaseModel):
    topic: str
    experts: list[dict]
    total: int


class DecisionInfo(BaseModel):
    decision: Optional[str] = None
    rationale: Optional[str] = None
    alternatives: list[str] = []
    confidence: float = 0.0
    people: list[str] = []


class DecisionsResponse(BaseModel):
    system: str
    decisions: list[dict]
    total: int


# ── Endpoints ────────────────────────────────────────────────────

@router.get("/health", response_model=HealthResponse)
def health_check():
    """Service health check — verifies PostgreSQL and Neo4j connectivity."""
    pg_status = "unhealthy"
    neo4j_status = "unhealthy"

    # Check PostgreSQL
    try:
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT 1;")
        cursor.close()
        conn.close()
        pg_status = "healthy"
    except Exception as e:
        logger.error(f"PostgreSQL health check failed: {e}")

    # Check Neo4j
    try:
        from src.storage.graph_db import GraphDB
        with GraphDB() as db:
            db.run("RETURN 1 AS ok")
        neo4j_status = "healthy"
    except Exception as e:
        logger.error(f"Neo4j health check failed: {e}")

    overall = "healthy" if pg_status == "healthy" and neo4j_status == "healthy" else "degraded"

    return HealthResponse(
        status=overall,
        postgres=pg_status,
        neo4j=neo4j_status,
        version="v4-LLM",
    )


@router.get("/stats", response_model=StatsResponse)
def get_stats():
    """Returns data source statistics and latest eval accuracy."""
    try:
        conn = get_connection()
        cursor = conn.cursor()

        # Total documents
        cursor.execute("SELECT COUNT(*) FROM raw_documents;")
        total_docs = cursor.fetchone()[0]

        # By source
        cursor.execute("""
            SELECT source, COUNT(*) FROM raw_documents
            GROUP BY source ORDER BY COUNT(*) DESC;
        """)
        by_source = {row[0]: row[1] for row in cursor.fetchall()}

        # Total entities
        total_entities = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM entities;")
            total_entities = cursor.fetchone()[0]
        except Exception:
            conn.rollback()

        # Total experts
        total_experts = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM experts;")
            total_experts = cursor.fetchone()[0]
        except Exception:
            conn.rollback()

        # Total decisions
        total_decisions = 0
        try:
            cursor.execute("SELECT COUNT(*) FROM decisions;")
            total_decisions = cursor.fetchone()[0]
        except Exception:
            conn.rollback()

        # Best eval accuracy
        eval_accuracy = None
        eval_run_id = None
        try:
            cursor.execute("""
                SELECT run_id, accuracy FROM eval_runs
                ORDER BY accuracy DESC LIMIT 1;
            """)
            row = cursor.fetchone()
            if row:
                eval_run_id = row[0]
                eval_accuracy = float(row[1])
        except Exception:
            conn.rollback()

        cursor.close()
        conn.close()

        return StatsResponse(
            total_documents=total_docs,
            by_source=by_source,
            total_entities=total_entities,
            total_experts=total_experts,
            total_decisions=total_decisions,
            eval_accuracy=eval_accuracy,
            eval_run_id=eval_run_id,
        )

    except Exception as e:
        logger.error(f"Stats query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    """
    Ask a question about Apache Kafka.
    Uses the full RAG pipeline: semantic search + Neo4j graph + LLM generation.
    """
    try:
        result = rag_answer(req.question)

        return QueryResponse(
            question=result["question"],
            answer=result["answer"],
            sources=[SourceInfo(**s) for s in result["sources"]],
            graph_paths=result["graph_paths"],
            experts=[ExpertInfo(**e) for e in result["experts"]],
            latency_ms=result["latency_ms"],
        )

    except Exception as e:
        logger.error(f"Query failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Query failed: {str(e)}")


@router.get("/experts/{topic}", response_model=ExpertsResponse)
def get_experts_for_topic(topic: str):
    """
    Find domain experts for a given topic.
    Queries the experts table ranked by expertise_score.
    """
    try:
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
            LIMIT 20;
        """, (f"%{topic}%",))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        experts = []
        for row in rows:
            experts.append({
                "person": row[0],
                "topic": row[1],
                "score": round(float(row[2]), 4) if row[2] else 0.0,
                "decisions": row[3] or 0,
                "mentions": row[4] or 0,
                "last_active": str(row[5]) if row[5] else "unknown",
            })

        return ExpertsResponse(
            topic=topic,
            experts=experts,
            total=len(experts),
        )

    except Exception as e:
        logger.error(f"Expert query failed for '{topic}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/decisions/{system}", response_model=DecisionsResponse)
def get_decisions_for_system(system: str):
    """
    Find engineering decisions related to a system/component.
    Queries the decisions table joined with raw_documents for context.
    """
    try:
        conn = get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT
                d.decision_text,
                d.rationale,
                d.alternatives_considered,
                d.confidence,
                d.people_involved
            FROM decisions d
            JOIN raw_documents r ON d.doc_id = r.id
            WHERE (LOWER(d.decision_text) LIKE LOWER(%s)
                   OR LOWER(r.content) LIKE LOWER(%s)
                   OR LOWER(COALESCE(d.rationale, '')) LIKE LOWER(%s))
              AND d.confidence >= 0.6
            ORDER BY d.confidence DESC
            LIMIT 20;
        """, (f"%{system}%", f"%{system}%", f"%{system}%"))

        rows = cursor.fetchall()
        cursor.close()
        conn.close()

        decisions = []
        for row in rows:
            decisions.append({
                "decision": row[0] or "",
                "rationale": row[1] or "",
                "alternatives": row[2] if row[2] else [],
                "confidence": round(float(row[3]), 2) if row[3] else 0.0,
                "people": row[4] if row[4] else [],
            })

        return DecisionsResponse(
            system=system,
            decisions=decisions,
            total=len(decisions),
        )

    except Exception as e:
        logger.error(f"Decision query failed for '{system}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
