"""
retrieval/rag_pipeline.py

Combines semantic search + graph retrieval + LLM answer generation.

Full RAG pipeline:
  1. Semantic search  -> finds similar content (pgvector)
  2. Graph retrieval  -> finds structured relationships (Neo4j)
  3. Context merge    -> combines both into one context block
  4. LLM generation  -> generates sourced answer from merged context

Uses Gemini (google-genai) instead of OpenAI -- same API key already in .env.
Falls back to best semantic hit if LLM fails.
"""

import logging
import os
import time
from typing import Optional

from dotenv import load_dotenv
from google import genai

from src.retrieval.semantic_retriever import hybrid_search
from src.retrieval.graph_retriever import graph_retrieve, format_graph_context

load_dotenv()
logger = logging.getLogger(__name__)

_client: Optional[genai.Client] = None

def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _client


ANSWER_PROMPT = """You are an expert on Apache Kafka with access to engineering discussions, KIP documents, and contributor history.

Answer the question using ONLY the context provided below. Be specific. Include names, technical terms, and reasons where available. Keep your answer under 150 words.

SEMANTIC CONTEXT (from document search):
{semantic_context}

GRAPH CONTEXT (from knowledge graph):
{graph_context}

QUESTION: {question}

ANSWER:"""


def generate_answer(
    question: str,
    semantic_hits: list[dict],
    graph_ctx: dict,
) -> str:
    """
    Generates a final answer using Gemini with combined semantic + graph context.
    Falls back to best semantic hit content if LLM is unavailable.
    """
    semantic_parts = []
    for hit in semantic_hits[:5]:
        label = f"[{hit['source'].upper()}]"
        semantic_parts.append(f"{label} {hit['content'][:400]}")
    semantic_context = "\n\n".join(semantic_parts)

    graph_context = format_graph_context(graph_ctx)

    if not semantic_context and not graph_context:
        return "Insufficient context to answer this question."

    prompt = ANSWER_PROMPT.format(
        semantic_context=semantic_context or "No relevant documents found.",
        graph_context=graph_context or "No graph relationships found.",
        question=question,
    )

    # Retry with exponential backoff for Gemini free-tier rate limits (429s)
    max_retries = 3
    base_delay = 10  # seconds

    for attempt in range(max_retries):
        try:
            client = get_client()
            response = client.models.generate_content(
                model="gemini-2.0-flash",
                contents=[prompt],
            )
            return response.text.strip()

        except Exception as e:
            is_rate_limit = "429" in str(e) or "Too Many Requests" in str(e)
            if is_rate_limit and attempt < max_retries - 1:
                delay = base_delay * (2 ** attempt)  # 10s, 20s, 40s
                logger.warning(
                    f"Rate limited (attempt {attempt + 1}/{max_retries}) "
                    f"-- retrying in {delay}s"
                )
                time.sleep(delay)
                continue
            else:
                logger.warning(f"LLM generation failed ({e.__class__.__name__}) -- using combined context fallback")
        # Smarter fallback: combine semantic content + graph expert/KIP context
        # This ensures expert names and KIP rationale are still included in the answer
        fallback_parts = []

        # Best semantic hit
        if semantic_hits:
            fallback_parts.append(semantic_hits[0]["content"][:350])

        # Expert names from graph (crucial for expert-type questions)
        experts = graph_ctx.get("experts", [])
        if experts:
            names = ", ".join(e["person"] for e in experts[:4])
            fallback_parts.append(f"Key contributors: {names}")

        # KIP rationale from graph (crucial for decision-type questions)
        decisions = graph_ctx.get("decisions", [])
        if decisions and decisions[0].get("decision"):
            fallback_parts.append(decisions[0]["decision"][:300])

        return " | ".join(fallback_parts) if fallback_parts else "Insufficient context."


def rag_answer(question: str) -> dict:
    """
    Full RAG pipeline -- call this for any question.
    Returns answer + sources + latency metadata.
    """
    start = time.time()

    # Step 1: Semantic retrieval
    semantic_hits = hybrid_search(question, top_k=5, boost_kip=True)

    # Step 2: Graph retrieval
    graph_ctx = graph_retrieve(question)

    # Step 3: Generate answer
    answer = generate_answer(question, semantic_hits, graph_ctx)

    latency_ms = int((time.time() - start) * 1000)

    sources = []
    for hit in semantic_hits[:3]:
        sources.append({
            "type": "semantic",
            "source": hit["source"],
            "similarity": hit["similarity"],
            "preview": hit["content"][:100],
        })
    for dec in graph_ctx.get("decisions", [])[:2]:
        sources.append({
            "type": "graph_decision",
            "decision": (dec.get("decision") or "")[:100],
            "confidence": dec.get("confidence", 0),
        })

    return {
        "question": question,
        "answer": answer,
        "sources": sources,
        "graph_paths": graph_ctx.get("graph_paths_used", []),
        "latency_ms": latency_ms,
        "experts": graph_ctx.get("experts", []),
    }


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    test_questions = [
        "Why did Apache Kafka decide to remove ZooKeeper dependency?",
        "Who are the main contributors to MirrorMaker 2?",
        "What alternatives were considered before choosing KRaft over ZooKeeper?",
    ]

    for q in test_questions:
        print(f"\n{'='*60}")
        print(f"Q: {q}")
        result = rag_answer(q)
        print(f"\nA: {result['answer']}")
        print(f"\nSources: {len(result['sources'])} | "
              f"Graph paths: {result['graph_paths']} | "
              f"Latency: {result['latency_ms']}ms")
        if result["experts"]:
            print(f"Experts: {[e['person'] for e in result['experts']]}")
