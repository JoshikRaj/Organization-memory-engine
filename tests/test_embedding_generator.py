import numpy as np
from src.extraction.embedding_generator import (
    generate_embedding,
    generate_batch_embeddings,
    chunk_text,
)


def test_embedding_shape():
    embedding = generate_embedding("Kafka replaced ZooKeeper with KRaft")
    assert embedding is not None
    assert embedding.shape == (384,)


def test_embedding_is_normalized():
    """Normalized embeddings have magnitude 1.0 — required for cosine similarity."""
    embedding = generate_embedding("test sentence")
    magnitude = np.linalg.norm(embedding)
    assert abs(magnitude - 1.0) < 0.001


def test_similar_texts_have_high_similarity():
    """Semantically similar texts should have high cosine similarity."""
    e1 = generate_embedding("ZooKeeper was replaced by KRaft in Kafka")
    e2 = generate_embedding("Kafka moved away from ZooKeeper to its own metadata system")
    similarity = np.dot(e1, e2)
    assert similarity > 0.7


def test_different_texts_have_low_similarity():
    """Unrelated texts should have low similarity."""
    e1 = generate_embedding("ZooKeeper metadata management Kafka")
    e2 = generate_embedding("quarterly revenue earnings financial report")
    similarity = np.dot(e1, e2)
    assert similarity < 0.5


def test_chunk_text_short_text():
    """Short text should return as single chunk."""
    text = "Short text"
    chunks = chunk_text(text)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_long_text():
    """Long text should be split into multiple chunks."""
    text = "word " * 1000  # 5000 chars
    chunks = chunk_text(text)
    assert len(chunks) > 1


def test_handles_empty_text():
    result = generate_embedding("")
    assert result is None


def test_batch_embeddings():
    texts = ["Kafka streams", "ZooKeeper quorum", "consumer group"]
    embeddings = generate_batch_embeddings(texts)
    assert len(embeddings) == 3
    assert all(e.shape == (384,) for e in embeddings)
