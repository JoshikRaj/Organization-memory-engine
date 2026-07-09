"""
evaluation/baseline_scorer.py

Runs a SIMPLE keyword search baseline against your eval questions.
This is your Week 2 baseline — before RAG, before the knowledge graph.

Why do this now?
Because in interviews you say:
"My baseline keyword search scored 31%.
After adding semantic search it went to 54%.
After adding the knowledge graph it went to 73%."

That improvement story is what shows engineering rigor.
You can't tell that story without a baseline.
"""

import time
import logging
from datetime import datetime

import numpy as np
from sentence_transformers import SentenceTransformer

from src.storage.database import get_connection

logger = logging.getLogger(__name__)
model = SentenceTransformer("all-MiniLM-L6-v2")


def keyword_search(query: str, top_k: int = 3) -> list[str]:
    """Simple PostgreSQL full-text search — no AI, no vectors."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT content FROM raw_documents
        WHERE to_tsvector('english', content) @@ plainto_tsquery('english', %s)
        ORDER BY ts_rank(to_tsvector('english', content),
                         plainto_tsquery('english', %s)) DESC
        LIMIT %s;
    """, (query, query, top_k))
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return [row[0][:500] for row in rows]


def answer_similarity(expected: str, retrieved_context: str) -> float:
    """
    Measures how similar retrieved context is to the expected answer.
    Uses cosine similarity between sentence-transformer embeddings.
    Not perfect — but gives a consistent, comparable score.
    """
    if not retrieved_context:
        return 0.0

    e1 = model.encode(expected, normalize_embeddings=True)
    e2 = model.encode(retrieved_context[:1000], normalize_embeddings=True)
    return float(np.dot(e1, e2))


def run_baseline(similarity_threshold: float = 0.5):
    """
    Runs keyword search baseline against all eval questions.
    Marks a question correct if similarity >= threshold.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT id, question, expected_answer FROM eval_questions;")
    questions = cursor.fetchall()
    cursor.close()
    conn.close()

    run_id = f"baseline_keyword_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    correct = 0
    total = len(questions)
    results = []

    logger.info(f"Running baseline eval — {total} questions | run_id: {run_id}")

    for q_id, question, expected in questions:
        start = time.time()
        context_chunks = keyword_search(question, top_k=3)
        context = " ".join(context_chunks)
        latency_ms = int((time.time() - start) * 1000)

        similarity = answer_similarity(expected, context)
        is_correct = similarity >= similarity_threshold

        if is_correct:
            correct += 1

        results.append({
            "run_id": run_id,
            "question_id": q_id,
            "system_answer": context[:500] if context else "NO RESULTS",
            "is_correct": is_correct,
            "similarity_score": round(similarity, 4),
            "latency_ms": latency_ms,
            "retrieval_method": "keyword_bm25",
        })

    # Save all results
    conn = get_connection()
    cursor = conn.cursor()

    for r in results:
        cursor.execute("""
            INSERT INTO eval_results
                (run_id, question_id, system_answer, is_correct,
                 similarity_score, latency_ms, retrieval_method)
            VALUES (%(run_id)s, %(question_id)s, %(system_answer)s,
                    %(is_correct)s, %(similarity_score)s,
                    %(latency_ms)s, %(retrieval_method)s);
        """, r)

    accuracy = round(correct / total, 4) if total > 0 else 0.0
    avg_latency = round(sum(r["latency_ms"] for r in results) / total, 1) if total > 0 else 0.0

    cursor.execute("""
        INSERT INTO eval_runs
            (run_id, total_questions, correct_answers,
             accuracy, avg_latency_ms, retrieval_method, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (run_id, total, correct, accuracy, avg_latency, "keyword_bm25",
          "Week 2 baseline — keyword search only"))

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n{'='*50}")
    print(f"BASELINE EVAL RESULTS")
    print(f"{'='*50}")
    print(f"Total questions : {total}")
    print(f"Correct answers : {correct}")
    print(f"Accuracy        : {accuracy * 100:.1f}%")
    print(f"Avg latency     : {avg_latency} ms")
    print(f"Run ID          : {run_id}")
    print(f"{'='*50}")
    print(f"This is your Week 2 baseline.")
    print(f"Your goal: beat this with semantic search in Week 3.")
    print(f"{'='*50}\n")

    return {"accuracy": accuracy, "correct": correct, "total": total}


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s | %(levelname)s | %(message)s")
    run_baseline()
