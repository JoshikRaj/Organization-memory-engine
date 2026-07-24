"""
evaluation/semantic_scorer.py

Week 3 scorer: replaces keyword search with vector similarity (hybrid_search).

Same structure as baseline_scorer.py — same questions, same threshold, same
similarity metric — so scores are directly comparable.

Run after baseline_scorer to see the improvement:
  Week 2: python -m src.evaluation.baseline_scorer     -> 18%
  Week 3: python -m src.evaluation.semantic_scorer     -> TBD (expect 40-60%)
"""

import time
import logging
from datetime import datetime

import numpy as np
from sentence_transformers import SentenceTransformer

from src.storage.database import get_connection
from src.retrieval.semantic_retriever import hybrid_search

logger = logging.getLogger(__name__)
model = SentenceTransformer("all-MiniLM-L6-v2")


def answer_similarity(expected: str, retrieved_context: str) -> float:
    """
    Measures how similar retrieved context is to the expected answer.
    Identical to baseline_scorer — ensures apples-to-apples comparison.
    """
    if not retrieved_context:
        return 0.0
    e1 = model.encode(expected, normalize_embeddings=True)
    e2 = model.encode(retrieved_context[:1000], normalize_embeddings=True)
    return float(np.dot(e1, e2))


def run_semantic_eval(similarity_threshold: float = 0.5, top_k: int = 5):
    """
    Runs semantic (vector) search against all eval questions.
    Uses hybrid_search() which boosts KIP document scores.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT id, question, expected_answer FROM eval_questions;")
    questions = cursor.fetchall()
    cursor.close()
    conn.close()

    run_id = f"semantic_v3_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    correct = 0
    total = len(questions)
    results = []

    logger.info(f"Running semantic eval -- {total} questions | run_id: {run_id}")

    for q_id, question, expected in questions:
        start = time.time()

        # Semantic retrieval -- replaces keyword_search
        hits = hybrid_search(question, top_k=top_k, boost_kip=True)
        context = " ".join(h["content"] for h in hits)
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
            "retrieval_method": "semantic_hybrid_v3",
        })

        # Quick progress indicator
        if len(results) % 10 == 0:
            logger.info(f"  Progress: {len(results)}/{total} | Correct so far: {correct}")

    # Save all results to DB
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
    """, (run_id, total, correct, accuracy, avg_latency, "semantic_hybrid_v3",
          "Week 3 -- vector similarity search with KIP boost"))

    conn.commit()
    cursor.close()
    conn.close()

    print(f"\n{'='*55}")
    print(f"WEEK 3 SEMANTIC EVAL RESULTS")
    print(f"{'='*55}")
    print(f"Total questions  : {total}")
    print(f"Correct answers  : {correct}")
    print(f"Accuracy         : {accuracy * 100:.1f}%")
    print(f"Avg latency      : {avg_latency} ms")
    print(f"Run ID           : {run_id}")
    print(f"{'='*55}")

    # Compare to baseline
    baseline_acc = 18.0
    improvement = (accuracy * 100) - baseline_acc
    print(f"vs Week 2 baseline: {baseline_acc}% -> {accuracy * 100:.1f}% "
          f"({'+'if improvement >= 0 else ''}{improvement:.1f}pp)")
    print(f"{'='*55}\n")

    return {"accuracy": accuracy, "correct": correct, "total": total, "run_id": run_id}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    run_semantic_eval()
