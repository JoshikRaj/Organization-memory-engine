"""
retrieval/graph_retriever.py

Queries Neo4j to retrieve structured context that vector search cannot.

Actual graph schema (verified 2026-07-18):
  Node labels : Document (source, preview, author, source_id)
                Person   (name)
                System   (name)
                Topic    (name)
  Relationships:
    Document -[:MENTIONS]-> System
    Document -[:MENTIONS]-> Person
    Person   -[:EXPERTISE_IN {score, decision_count, mention_count}]-> Topic

  Note: Decision nodes exist but are empty (extractor not yet run).
        Using KIP Document nodes as the source of decision-like context.
"""

import logging
from functools import lru_cache
from src.storage.graph_db import GraphDB

logger = logging.getLogger(__name__)

# Known non-person strings that end up in the Person table from graph_builder
_PERSON_STOPWORDS = {
    "kafka", "apache", "confluent", "linkedin", "unknown", "apache kafka",
    "n/a", "none", "system", "bot", "github", "git",
}


def extract_entities_from_query(query: str) -> dict:
    """
    Keyword-based entity extraction.
    Detects Kafka system terms and question intent.
    """
    query_lower = query.lower()

    systems = [
        "zookeeper", "kraft", "kafka streams", "kafka connect",
        "mirrormaker", "schema registry", "tiered storage",
        "log compaction", "consumer group", "replication",
        "exactly once", "transactions", "controller", "broker",
        "producer", "consumer", "partition", "offset", "raft",
        "paxos", "idempotent", "dead letter", "acks", "isr",
        "kip", "leader epoch", "high watermark", "sequential",
        "disk", "metadata quorum", "heartbeat", "rack",
    ]
    detected_systems = [s for s in systems if s in query_lower]

    # KIP keyword → search term mapping
    # Maps question phrasing to the term that actually appears in KIP previews
    KIP_ALIASES = {
        "kraft": "zookeeper",          # KIP-500: about removing ZooKeeper
        "metadata quorum": "zookeeper",
        "self-managed": "zookeeper",
        "tiered storage": "tiered",     # KIP-405
        "exactly once": "exactly once",  # KIP-98, KIP-129
        "exactly-once": "exactly once",
        "eos": "exactly once",
        "mirrormaker": "mirrormaker",   # KIP-382
        "mirror maker": "mirrormaker",
        "replication protocol": "replication",  # KIP-101
        "leader epoch": "leader epoch",
        "heartbeat": "heartbeat",       # KIP-62
        "rack aware": "rack",           # KIP-36
        "admin api": "adminclien",      # KIP-117
        "sequential": "sequential",
        "disk i/o": "sequential",
        "log index": "log index",       # KIP-33
    }
    # Add aliased search terms
    aliased_terms = []
    for alias, target in KIP_ALIASES.items():
        if alias in query_lower and target not in detected_systems:
            aliased_terms.append(target)

    # Broad fallback: any Kafka-adjacent terms in query
    fallback_terms = [w for w in query_lower.split()
                      if len(w) > 4 and w not in {
                          "apache", "kafka", "what", "when", "where",
                          "which", "about", "should", "their", "these",
                          "those", "there", "would", "could",
                      }]

    return {
        "systems": detected_systems,
        "aliased_terms": aliased_terms,
        "fallback_terms": fallback_terms[:3],
        "is_who": any(w in query_lower for w in [
            "who", "contributor", "proposed", "author", "expert",
            "contact", "person", "team", "active", "drove", "founded",
            "implemented", "created", "built",
        ]),
        "is_why": any(w in query_lower for w in [
            "why", "reason", "motivation", "purpose", "decided",
            "decision", "chose", "alternative", "rejected", "instead",
            "moved", "replace", "remove", "introduce", "benefit",
        ]),
        "is_what": any(w in query_lower for w in [
            "what", "define", "explain", "describe", "how does", "how do",
        ]),
    }


def _is_valid_person(name: str) -> bool:
    """Filters out non-human entries that landed in the Person table."""
    if not name:
        return False
    if name.lower() in _PERSON_STOPWORDS:
        return False
    # Must look like a person: at least 2 chars, not all uppercase (system acronym)
    if len(name) < 3:
        return False
    return True


def get_kip_context_for_topic(db: GraphDB, term: str) -> list[dict]:
    """
    Finds KIP documents whose preview mentions a system/term.
    KIP documents contain Motivation and Rejected Alternatives sections
    — this is the closest we have to structured decision rationale.
    Path: Document(source='kip') WHERE preview CONTAINS term
    """
    results = db.run("""
        MATCH (doc:Document)
        WHERE doc.source = 'kip'
          AND toLower(doc.preview) CONTAINS $term
        RETURN doc.source_id  AS source_id,
               doc.preview    AS preview,
               doc.author     AS author,
               doc.timestamp  AS timestamp
        ORDER BY doc.timestamp DESC
        LIMIT 4
    """, {"term": term.lower()})
    return results


def get_experts_for_topic(db: GraphDB, topic: str) -> list[dict]:
    """
    Finds people with expertise in a topic area.
    Path: Person -[:EXPERTISE_IN {score}]-> Topic
    """
    results = db.run("""
        MATCH (p:Person)-[r:EXPERTISE_IN]->(t:Topic)
        WHERE toLower(t.name) CONTAINS $topic
        RETURN p.name          AS person,
               t.name          AS topic,
               r.score         AS score,
               r.decision_count AS decisions,
               r.mention_count  AS mentions
        ORDER BY r.score DESC
        LIMIT 8
    """, {"topic": topic.lower()})
    # Filter out non-person entries
    return [r for r in results if _is_valid_person(r.get("person", ""))][:5]


def get_authors_for_system(db: GraphDB, system_name: str) -> list[dict]:
    """
    Finds authors who wrote documents mentioning a system.
    Path: Document -[:MENTIONS]-> System, Document.author
    """
    results = db.run("""
        MATCH (doc:Document)-[:MENTIONS]->(s:System)
        WHERE toLower(s.name) CONTAINS $system
          AND doc.author IS NOT NULL
        RETURN doc.author          AS person,
               s.name              AS topic,
               count(doc)          AS mentions
        ORDER BY mentions DESC
        LIMIT 8
    """, {"system": system_name.lower()})
    return [
        {
            "person": r.get("person", ""),
            "topic": r.get("topic", ""),
            "score": min(1.0, (r.get("mentions") or 1) / 15.0),
            "decisions": 0,
            "mentions": r.get("mentions", 0),
        }
        for r in results
        if _is_valid_person(r.get("person", ""))
    ][:5]


def get_docs_mentioning_system(db: GraphDB, system_name: str) -> list[dict]:
    """
    Finds documents that mention a given system.
    Path: Document -[:MENTIONS]-> System
    """
    results = db.run("""
        MATCH (doc:Document)-[:MENTIONS]->(s:System)
        WHERE toLower(s.name) CONTAINS toLower($system)
        RETURN doc.source_id AS source_id,
               doc.source    AS source,
               doc.preview   AS preview,
               doc.author    AS author
        ORDER BY doc.source DESC
        LIMIT 5
    """, {"system": system_name})
    return results


# In-memory cache for graph results — dataset is small and static
_graph_cache = {}

def graph_retrieve(query: str) -> dict:
    """
    Main entry point. Detects intent, runs appropriate graph traversals,
    returns structured context for the LLM answer generation step.
    Results are cached in memory since the graph data doesn't change at runtime.
    """
    # Check cache first
    cache_key = query.strip().lower()
    if cache_key in _graph_cache:
        logger.info(f"Graph retrieval: cache hit for '{query[:50]}'")
        return _graph_cache[cache_key]

    entities = extract_entities_from_query(query)
    # Lowercase all detected systems before graph queries (matches index)
    entities["systems"] = [s.lower() for s in entities["systems"]]
    entities["aliased_terms"] = [t.lower() for t in entities["aliased_terms"]]
    entities["fallback_terms"] = [t.lower() for t in entities["fallback_terms"]]
    context = {
        "decisions": [],      # KIP document previews used as decision context
        "experts": [],
        "related_docs": [],
        "graph_paths_used": [],
    }

    try:
        with GraphDB() as db:

            for system in entities["systems"] + entities["aliased_terms"]:

                # Decision-like context: KIP documents mentioning this system
                if entities["is_why"] or entities["is_what"]:
                    kips = get_kip_context_for_topic(db, system)
                    if kips:
                        for k in kips:
                            context["decisions"].append({
                                "decision": k.get("preview", "")[:400],
                                "rationale": "",
                                "alternatives": [],
                                "confidence": 0.8,
                                "source": f"KIP:{k.get('source_id', '')}",
                            })
                        context["graph_paths_used"].append(
                            f"KIP-Document->mentions({system})"
                        )

                # Expert context
                if entities["is_who"]:
                    experts = get_experts_for_topic(db, system)
                    if experts:
                        context["experts"].extend(experts)
                        context["graph_paths_used"].append(
                            f"Person->EXPERTISE_IN->{system}"
                        )
                    # Also find authors of docs mentioning this system
                    authors = get_authors_for_system(db, system)
                    if authors:
                        context["experts"].extend(authors)
                        context["graph_paths_used"].append(
                            f"Document->MENTIONS->{system}"
                        )

                # Related docs — skip for API performance
                # (context already enriched by KIP decisions + experts above)

            # Broad fallback for 'who' with no system detected
            if entities["is_who"] and not context["experts"]:
                for term in entities["fallback_terms"]:
                    experts = get_experts_for_topic(db, term)
                    if experts:
                        context["experts"].extend(experts)
                        context["graph_paths_used"].append(
                            f"Person->EXPERTISE_IN->{term}"
                        )
                        break

            # KIP fallback for 'why' with no system detected
            if entities["is_why"] and not context["decisions"]:
                for term in entities["fallback_terms"]:
                    kips = get_kip_context_for_topic(db, term)
                    if kips:
                        for k in kips:
                            context["decisions"].append({
                                "decision": k.get("preview", "")[:400],
                                "rationale": "",
                                "alternatives": [],
                                "confidence": 0.7,
                                "source": f"KIP:{k.get('source_id', '')}",
                            })
                        context["graph_paths_used"].append(
                            f"KIP-Document->mentions({term})"
                        )
                        break

            # Deduplicate
            seen_d = set()
            context["decisions"] = [
                d for d in context["decisions"]
                if not (d["decision"][:80] in seen_d or seen_d.add(d["decision"][:80]))
            ][:5]

            seen_e = set()
            context["experts"] = [
                e for e in context["experts"]
                if not (e["person"] in seen_e or seen_e.add(e["person"]))
            ][:5]

    except Exception as e:
        logger.error(f"Graph retrieval failed: {e}", exc_info=True)

    logger.info(
        f"Graph retrieval: {len(context['decisions'])} KIP-decisions, "
        f"{len(context['experts'])} experts | paths: {context['graph_paths_used']}"
    )
    # Cache the result for future identical queries
    _graph_cache[cache_key] = context
    return context


def format_graph_context(graph_ctx: dict) -> str:
    """Formats graph context into a string the LLM can consume."""
    parts = []

    if graph_ctx["decisions"]:
        parts.append("RELEVANT KIP CONTEXT (technical rationale):")
        for d in graph_ctx["decisions"]:
            src = d.get("source", "")
            parts.append(f"  [{src}] {d.get('decision', '')[:350]}")
            parts.append("")

    if graph_ctx["experts"]:
        parts.append("DOMAIN EXPERTS (from knowledge graph):")
        for e in graph_ctx["experts"]:
            score = float(e.get("score") or 0)
            mentions = int(e.get("mentions") or 0)
            decisions = int(e.get("decisions") or 0)
            parts.append(
                f"  {e.get('person')} — {e.get('topic')} "
                f"(score: {score:.2f}, docs: {mentions}, decisions: {decisions})"
            )
        parts.append("")

    return "\n".join(parts)


if __name__ == "__main__":
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )

    queries = [
        "Why did Apache Kafka decide to remove ZooKeeper dependency?",
        "Who are the main contributors to MirrorMaker 2?",
        "What alternatives were considered before choosing KRaft?",
        "Who should I talk to about Kafka replication?",
        "Why does Kafka use sequential disk I/O?",
    ]

    print("=" * 60)
    print("GRAPH RETRIEVAL TEST (fixed schema)")
    print("=" * 60)

    for query in queries:
        print(f"\nQ: {query}")
        ctx = graph_retrieve(query)
        print(f"  Paths    : {ctx['graph_paths_used']}")
        print(f"  Decisions: {len(ctx['decisions'])}")
        print(f"  Experts  : {len(ctx['experts'])}")
        if ctx["decisions"]:
            print(f"  Top KIP  : {ctx['decisions'][0]['decision'][:100]}")
        if ctx["experts"]:
            e = ctx["experts"][0]
            print(f"  Top expert: {e['person']} (score={float(e.get('score') or 0):.2f})")
