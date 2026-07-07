"""
extraction/embedding_generator.py

Generates vector embeddings for every document in raw_documents.
Uses sentence-transformers (free, runs locally, no API cost).

Model: all-MiniLM-L6-v2
- 384 dimensions
- Runs on CPU (no GPU needed)
- ~14,000 sentences/second on CPU
- Good semantic understanding for technical text

Why not OpenAI embeddings?
- Cost: $0.0001 per 1K tokens * 1M tokens = $0.10 — not much,
  but adds an external dependency that can break or change pricing.
- Consistency: local model never changes. OpenAI can update their
  embedding model and break your similarity scores silently.
This is a tradeoff you explain in interviews.
"""

import logging
import time
from typing import Optional

import numpy as np
from sentence_transformers import SentenceTransformer

from src.storage.database import get_connection

logger = logging.getLogger(__name__)

# Load model once at module level — takes ~10 seconds first time
# Downloads ~90MB model to ~/.cache/huggingface/
logger.info("Loading sentence transformer model...")
model = SentenceTransformer("all-MiniLM-L6-v2")
logger.info("Model loaded")

EMBEDDING_DIM = 384


def chunk_text(text: str, max_chars: int = 1500) -> list[str]:
    """
    Splits long text into overlapping chunks for embedding.

    Why chunking?
    A 10,000 word Jira issue can't be embedded as one unit —
    the model has a token limit, and one embedding for 10,000 words
    loses detail. Smaller chunks = more precise retrieval.

    Why overlap?
    If a decision spans the boundary of two chunks, overlap ensures
    it's captured in at least one chunk fully.
    """
    if len(text) <= max_chars:
        return [text]

    chunks = []
    overlap = 200  # characters of overlap between chunks
    start = 0

    while start < len(text):
        end = start + max_chars
        chunk = text[start:end]

        # Try to break at a sentence boundary instead of mid-word
        if end < len(text):
            last_period = chunk.rfind(". ")
            if last_period > max_chars * 0.5:  # only if period is in second half
                chunk = chunk[:last_period + 1]

        chunks.append(chunk.strip())
        # Ensure forward progress — prevent infinite loop
        step = max(len(chunk) - overlap, 100)
        start += step

    return [c for c in chunks if len(c.strip()) > 20]


def generate_embedding(text: str) -> Optional[np.ndarray]:
    """
    Generates a single embedding vector for a piece of text.
    Returns numpy array of shape (384,) or None if text is empty.
    """
    if not text or len(text.strip()) < 10:
        return None

    try:
        embedding = model.encode(
            text,
            normalize_embeddings=True,  # normalize to unit length for cosine similarity
            show_progress_bar=False,
        )
        return embedding
    except Exception as e:
        logger.error(f"Embedding generation failed: {e}")
        return None


def generate_batch_embeddings(texts: list[str]) -> list[Optional[np.ndarray]]:
    """
    Generates embeddings for a batch of texts at once.
    Much faster than calling generate_embedding() in a loop.
    Batch processing is the key to handling 1000 docs efficiently.
    """
    if not texts:
        return []

    try:
        embeddings = model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=32,
            show_progress_bar=True,
        )
        return list(embeddings)
    except Exception as e:
        logger.error(f"Batch embedding failed: {e}")
        return [None] * len(texts)


def insert_embedding(conn, doc_id: int, embedding: np.ndarray) -> bool:
    """
    Updates a document row with its embedding vector.
    pgvector accepts Python lists directly.
    """
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE raw_documents
            SET embedding = %s::vector,
                embedding_generated = TRUE
            WHERE id = %s;
        """, (embedding.tolist(), doc_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        logger.error(f"Embedding insert failed for doc {doc_id}: {e}")
        return False
    finally:
        cursor.close()


def run_embedding_generation(batch_size: int = 100):
    """
    Generates embeddings for all documents that don't have one yet.

    Strategy:
    1. Fetch batch of unprocessed docs
    2. Chunk long docs (most will be single chunk)
    3. Generate embeddings in batch (fast)
    4. For multi-chunk docs, average the chunk embeddings
    5. Store in PostgreSQL
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, content FROM raw_documents
        WHERE embedding_generated = FALSE
        AND content IS NOT NULL
        AND LENGTH(content) > 10
        ORDER BY id
        LIMIT %s;
    """, (batch_size,))

    docs = cursor.fetchall()
    cursor.close()

    if not docs:
        logger.info("All documents already have embeddings")
        conn.close()
        return {"processed": 0, "failed": 0}

    logger.info(f"Generating embeddings for {len(docs)} documents...")
    start_time = time.time()

    total_processed = 0
    total_failed = 0

    # Process in sub-batches for memory efficiency
    sub_batch_size = 32
    for i in range(0, len(docs), sub_batch_size):
        sub_batch = docs[i:i + sub_batch_size]

        doc_ids = []
        representative_texts = []

        for doc_id, content in sub_batch:
            chunks = chunk_text(content)
            # Use first chunk as representative text
            # For short docs this is the full content
            representative_texts.append(chunks[0])
            doc_ids.append(doc_id)

        # Batch embed all representative texts at once
        embeddings = generate_batch_embeddings(representative_texts)

        for doc_id, embedding in zip(doc_ids, embeddings):
            if embedding is not None:
                success = insert_embedding(conn, doc_id, embedding)
                if success:
                    total_processed += 1
                else:
                    total_failed += 1
            else:
                total_failed += 1

        elapsed = round(time.time() - start_time, 2)
        logger.info(
            f"  Sub-batch {i // sub_batch_size + 1} done | "
            f"Processed: {total_processed} | "
            f"Failed: {total_failed} | "
            f"Time: {elapsed}s"
        )

    conn.close()

    total_time = round(time.time() - start_time, 2)
    logger.info(
        f"Embedding generation complete: "
        f"{total_processed} succeeded | "
        f"{total_failed} failed | "
        f"{total_time}s total"
    )

    return {"processed": total_processed, "failed": total_failed}


def test_semantic_search(query: str, top_k: int = 5):
    """
    Quick test to verify embeddings work for semantic search.
    Run this after embedding generation to confirm quality.
    """
    conn = get_connection()
    cursor = conn.cursor()

    query_embedding = generate_embedding(query)
    if query_embedding is None:
        print("Failed to generate query embedding")
        return

    cursor.execute("""
        SELECT
            id,
            source,
            LEFT(content, 200) as preview,
            1 - (embedding <=> %s::vector) as similarity
        FROM raw_documents
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """, (query_embedding.tolist(), query_embedding.tolist(), top_k))

    results = cursor.fetchall()
    cursor.close()
    conn.close()

    print(f"\n=== Semantic Search Results for: '{query}' ===")
    for i, (doc_id, source, preview, similarity) in enumerate(results):
        print(f"\n#{i+1} [similarity: {similarity:.3f}] [{source}] doc_id={doc_id}")
        print(f"  {preview[:200]}...")
    print()


if __name__ == "__main__":
    import json
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    # Step 1: Generate all embeddings
    total = {"processed": 0, "failed": 0}
    while True:
        result = run_embedding_generation(batch_size=100)
        total["processed"] += result["processed"]
        total["failed"] += result["failed"]
        if result["processed"] == 0:
            break

    print(json.dumps(total, indent=2))

    # Step 2: Test semantic search
    print("\nTesting semantic search...")
    test_semantic_search("ZooKeeper replacement metadata management")
    test_semantic_search("consumer group rebalancing performance issues")
    test_semantic_search("security authentication SSL TLS")
