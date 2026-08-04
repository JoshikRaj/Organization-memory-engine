"""
evaluation/rag_scorer.py

Week 4 scorer -- uses full RAG pipeline (semantic + graph + LLM generation).
Target: 65-75% accuracy.

Run after semantic_scorer to see the full improvement story:
  Week 2: python -m src.evaluation.baseline_scorer   -> 18%
  Week 3: python -m src.evaluation.semantic_scorer   -> 36%
  Week 4: python -m src.evaluation.rag_scorer        -> TBD (target 65-75%)
"""

import time
import logging
from datetime import datetime

import numpy as np
from sentence_transformers import SentenceTransformer

from src.storage.database import get_connection
from src.retrieval.rag_pipeline import rag_answer

logger = logging.getLogger(__name__)
model = SentenceTransformer("all-MiniLM-L6-v2")


def answer_similarity(expected: str, generated: str) -> float:
    """Identical to baseline_scorer -- ensures apples-to-apples comparison."""
    if not generated:
        return 0.0
    e1 = model.encode(expected, normalize_embeddings=True)
    e2 = model.encode(generated[:1000], normalize_embeddings=True)
    return float(np.dot(e1, e2))


def run_rag_eval(similarity_threshold: float = 0.5):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, question, expected_answer FROM eval_questions;")
    questions = cursor.fetchall()
    cursor.close()
    conn.close()

    run_id = f"rag_v4_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    correct = 0
    total = len(questions)
    results = []

    logger.info(f"Running RAG eval -- {total} questions | run_id: {run_id}")

    for q_id, question, expected in questions:
        result = rag_answer(question)
        generated_answer = result["answer"]
        latency_ms = result["latency_ms"]

        similarity = answer_similarity(expected, generated_answer)
        is_correct = similarity >= similarity_threshold

        if is_correct:
            correct += 1

        results.append({
            "run_id": run_id,
            "question_id": q_id,
            "system_answer": generated_answer[:500],
            "is_correct": is_correct,
            "similarity_score": round(similarity, 4),
            "latency_ms": latency_ms,
            "retrieval_method": "rag_semantic_graph_v4",
        })

        if len(results) % 10 == 0:
            logger.info(
                f"  Progress: {len(results)}/{total} | Correct: {correct}"
            )

        # Respect Groq free-tier rate limit (30 RPM — use 3s spacing)
        time.sleep(3)

    # Save results
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

    accuracy = round(correct / total, 4)
    avg_latency = round(sum(r["latency_ms"] for r in results) / total, 1)

    cursor.execute("""
        INSERT INTO eval_runs
            (run_id, total_questions, correct_answers, accuracy,
             avg_latency_ms, retrieval_method, notes)
        VALUES (%s, %s, %s, %s, %s, %s, %s);
    """, (
        run_id, total, correct, accuracy, avg_latency,
        "rag_semantic_graph_v4",
        "Week 4 -- semantic + Neo4j graph + Gemini LLM generation"
    ))

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n{'='*55}")
    print(f"WEEK 4 RAG EVAL RESULTS")
    print(f"{'='*55}")
    print(f"Total questions  : {total}")
    print(f"Correct answers  : {correct}")
    print(f"Accuracy         : {accuracy * 100:.1f}%")
    print(f"Avg latency      : {avg_latency} ms")
    print(f"Run ID           : {run_id}")
    print(f"{'='*55}")
    improvement = accuracy * 100 - 36.0
    print(f"vs Week 3: 36% -> {accuracy * 100:.1f}% "
          f"({'+' if improvement >= 0 else ''}{improvement:.1f}pp)")
    print(f"{'='*55}\n")

    return {"accuracy": accuracy, "correct": correct, "total": total}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    run_rag_eval()
