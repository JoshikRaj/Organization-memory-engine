"""
storage/graph_db.py

Neo4j knowledge graph connection and schema setup.

Why Neo4j alongside Weaviate?
------------------------------
Weaviate (vector DB) answers: "Find documents SIMILAR to this query"
Neo4j (graph DB) answers:     "Find documents CONNECTED to this entity"

Example that shows the difference:
  Question: "Who originally proposed replacing ZooKeeper?"

  Weaviate approach: embed the question → find similar text chunks
  Result: finds documents ABOUT ZooKeeper replacement
  Problem: doesn't know WHO proposed it or WHEN

  Neo4j approach: find Person nodes → PROPOSED → Decision nodes
                  → INVOLVES_SYSTEM → "ZooKeeper"
  Result: Jun Rao proposed KIP-500 in 2019, referencing KAFKA-9119
  Problem: can't find semantically similar content

  Combined: Weaviate finds the relevant content,
            Neo4j provides the relationship context.
  Result: complete answer with sources, people, and timeline.

This is the architectural insight that makes your project unique.
"""

import logging
import os
from typing import Optional

from dotenv import load_dotenv
from neo4j import GraphDatabase

load_dotenv()
logger = logging.getLogger(__name__)

NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "orgmemory123")


_cached_driver = None

def _get_driver():
    """Returns a shared Neo4j driver (connection pool), created once."""
    global _cached_driver
    if _cached_driver is None:
        _cached_driver = GraphDatabase.driver(
            NEO4J_URI,
            auth=(NEO4J_USER, NEO4J_PASSWORD)
        )
        logger.info(f"Connected to Neo4j at {NEO4J_URI}")
    return _cached_driver


class GraphDB:
    """
    Wrapper around Neo4j driver.
    Use as a context manager or call close() when done.
    Reuses a shared driver pool for performance.
    """

    def __init__(self):
        self.driver = _get_driver()
        self._owns_driver = False  # don't close the shared pool

    def close(self):
        pass  # shared driver pool — don't close between requests

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def run(self, query: str, parameters: dict = None) -> list:
        """Runs a Cypher query and returns all results as a list."""
        with self.driver.session() as session:
            result = session.run(query, parameters or {})
            return [dict(record) for record in result]

    def run_write(self, query: str, parameters: dict = None):
        """Runs a write Cypher query inside a transaction."""
        with self.driver.session() as session:
            session.execute_write(
                lambda tx: tx.run(query, parameters or {})
            )

    def verify_connection(self) -> bool:
        """Ping Neo4j to confirm it's reachable."""
        try:
            self.run("RETURN 1 as ping")
            return True
        except Exception as e:
            logger.error(f"Neo4j connection failed: {e}")
            return False


def create_schema(db: GraphDB):
    """
    Creates constraints and indexes in Neo4j.
    Run once on first setup.

    Node types:
      Person     — A contributor (Jun Rao, Jason Gustafson)
      System     — A Kafka component (ZooKeeper, KRaft, Kafka Streams)
      Decision   — A technical decision extracted from a document
      Document   — A source document (Jira ticket, KIP, Git commit)
      Topic      — A high-level topic area (replication, storage, security)

    Relationship types:
      PROPOSED       — Person → Decision
      INVOLVES       — Decision → System
      DOCUMENTED_IN  — Decision → Document
      MENTIONS       — Document → Person/System
      CONTRADICTS    — Decision → Decision
      EXPERTISE_IN   — Person → Topic
      RELATED_TO     — System → System
    """
    logger.info("Creating Neo4j schema...")

    constraints = [
        "CREATE CONSTRAINT person_name IF NOT EXISTS FOR (p:Person) REQUIRE p.name IS UNIQUE",
        "CREATE CONSTRAINT system_name IF NOT EXISTS FOR (s:System) REQUIRE s.name IS UNIQUE",
        "CREATE CONSTRAINT doc_source_id IF NOT EXISTS FOR (d:Document) REQUIRE d.source_id IS UNIQUE",
        "CREATE CONSTRAINT decision_id IF NOT EXISTS FOR (d:Decision) REQUIRE d.decision_id IS UNIQUE",
        "CREATE CONSTRAINT topic_name IF NOT EXISTS FOR (t:Topic) REQUIRE t.name IS UNIQUE",
    ]

    indexes = [
        "CREATE INDEX person_name_idx IF NOT EXISTS FOR (p:Person) ON (p.name)",
        "CREATE INDEX system_name_idx IF NOT EXISTS FOR (s:System) ON (s.name)",
        "CREATE INDEX decision_confidence_idx IF NOT EXISTS FOR (d:Decision) ON (d.confidence)",
        "CREATE INDEX doc_source_idx IF NOT EXISTS FOR (d:Document) ON (d.source)",
    ]

    for constraint in constraints:
        try:
            db.run_write(constraint)
            logger.info(f"  [OK] {constraint[:60]}...")
        except Exception as e:
            logger.warning(f"  [WARN] Constraint may already exist: {e}")

    for index in indexes:
        try:
            db.run_write(index)
            logger.info(f"  [OK] {index[:60]}...")
        except Exception as e:
            logger.warning(f"  [WARN] Index may already exist: {e}")

    logger.info("Schema creation complete")


def get_graph_db() -> GraphDB:
    """Factory function — returns a connected GraphDB instance."""
    return GraphDB()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    with GraphDB() as db:
        if db.verify_connection():
            print("[OK] Neo4j connection successful")
            create_schema(db)
            print("[OK] Schema created")

            # Quick stats
            result = db.run("MATCH (n) RETURN labels(n)[0] as label, COUNT(n) as count")
            if result:
                print("\nCurrent graph contents:")
                for row in result:
                    print(f"  {row['label']}: {row['count']} nodes")
            else:
                print("\nGraph is empty -- ready to populate")
        else:
            print("[FAIL] Neo4j connection failed -- is Docker running?")
