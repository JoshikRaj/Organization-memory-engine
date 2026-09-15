# 🧠 Org Memory Engine

> A production-grade RAG system that answers engineering decision questions with **92% accuracy** — built on 10 years of Apache Kafka's public engineering history.

[![Python](https://img.shields.io/badge/Python-3.11-blue)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-green)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-pgvector-blue)](https://github.com/pgvector/pgvector)
[![Neo4j](https://img.shields.io/badge/Neo4j-Knowledge_Graph-orange)](https://neo4j.com)
[![Streamlit](https://img.shields.io/badge/Streamlit-Dashboard-red)](https://streamlit.io)

---

## What it does

Ask any question about Kafka's engineering history in plain English. Get a sourced, specific answer in seconds.

```
Q: Why did Kafka replace ZooKeeper with KRaft?

A: Kafka replaced ZooKeeper with KRaft (KIP-500) because ZooKeeper added operational
   complexity, required separate expertise to manage, and created a bottleneck for
   metadata operations at scale. KRaft implements the Raft consensus protocol directly
   inside Kafka, enabling a single-process linearizable metadata layer with faster
   controller elections and no external dependency.

Sources: KIP-500 (0.74 similarity) · KIP-631 (0.74) · KAFKA-9519 (0.64)
Experts: Chia-Ping Tsai · Andrew Schofield · Matthias J. Sax
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     DATA SOURCES                            │
│  Apache Jira (997 issues) · GitHub (300 commits) · KIPs    │
└──────────────────┬──────────────────────────────────────────┘
                   │ Ingestion
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                  DUAL STORAGE LAYER                         │
│                                                             │
│  PostgreSQL + pgvector          Neo4j Knowledge Graph       │
│  ┌─────────────────────┐       ┌─────────────────────┐     │
│  │ raw_documents 1,309 │       │ Person nodes    164  │     │
│  │ entities      6,987 │       │ System nodes    271  │     │
│  │ experts         823 │       │ Topic nodes     174  │     │
│  │ decisions           │       │ Document nodes 1,309 │     │
│  │ embeddings  384-dim │       │ EXPERTISE_IN    801  │     │
│  └─────────────────────┘       │ MENTIONS      1,746  │     │
│                                └─────────────────────┘     │
└──────────────────┬──────────────────────────────────────────┘
                   │ Retrieval
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                    RAG PIPELINE                             │
│                                                             │
│  1. Semantic search  (pgvector cosine similarity)           │
│     + KIP boost ×1.35 (KIPs always surface first)          │
│                                                             │
│  2. Graph retrieval  (Neo4j — experts + decisions)          │
│                                                             │
│  3. LLM synthesis   (Groq · openai/gpt-oss-120B)           │
│     "Lead with architectural reason, not bug reports"       │
└──────────────────┬──────────────────────────────────────────┘
                   │ Serve
                   ▼
┌─────────────────────────────────────────────────────────────┐
│                   INTERFACES                                │
│                                                             │
│  FastAPI REST     Streamlit Dashboard    Slack Bot          │
│  localhost:8000   localhost:8501         Socket Mode        │
└─────────────────────────────────────────────────────────────┘
```

---

## Accuracy progression

| Version | Accuracy | What was added |
|---------|----------|----------------|
| v1 Keyword search | 12% | Baseline |
| v2 + KIP documents | 18% | Structured decision rationale |
| v3 + Semantic search | 36% | pgvector cosine similarity |
| v4 + Neo4j graph | 48% | Relationship traversal |
| **v4 + LLM synthesis** | **92%** | **Groq LLM answer generation** |

The jump from 48% → 92% came entirely from LLM synthesis. Retrieval alone plateaued. This is the core insight behind RAG architecture.

---

## Tech stack

| Layer | Technology | Why |
|-------|-----------|-----|
| Vector store | PostgreSQL + pgvector | Production-grade, no extra infra |
| Knowledge graph | Neo4j | Relationship traversal for expert routing |
| Embeddings | `all-MiniLM-L6-v2` | Fast, accurate, runs locally |
| NLP | spaCy `en_core_web_lg` | Entity extraction |
| LLM | Groq (120B model) | Fast inference, free tier |
| API | FastAPI | Auto-docs, type-safe |
| Dashboard | Streamlit | Rapid iteration |
| Slack | `slack_bolt` + Socket Mode | No public URL needed |
| Containers | Docker + named volumes | Data survives restarts |

---

## Quick start

### Prerequisites
- Docker Desktop
- Python 3.11+
- Groq API key (free at [console.groq.com](https://console.groq.com))

### 1. Clone and configure
```bash
git clone https://github.com/YOUR_USERNAME/org-memory-engine.git
cd org-memory-engine

cp .env.example .env
# Edit .env — add your GROQ_API_KEY
```

### 2. Start everything with one command
```bash
docker compose up
```

This starts PostgreSQL, Neo4j, the API, and the dashboard in the right order with health checks.

### 3. Ingest data (~15 minutes)
```bash
python -m src.ingestion.jira_ingestor      # 997 Jira issues
python -m src.ingestion.git_ingestor       # 300 Git commits
python -m src.ingestion.kip_ingestor       # 12 KIP documents

python -m src.extraction.entity_extractor  # 6,987 entities
python -m src.extraction.embedding_generator  # 1,309 vectors
python -m src.extraction.decision_extractor   # LLM extraction
python -m src.extraction.expert_identifier    # 823 expert scores

python -m src.storage.graph_builder        # Neo4j knowledge graph
python -m src.evaluation.eval_builder      # 50 eval questions
```

### 4. Open the dashboard
```
http://localhost:8501
```

### 5. (Optional) Start the Slack bot
```bash
# Add SLACK_BOT_TOKEN and SLACK_APP_TOKEN to .env first
python -m src.slack_bot.bot
```

---

## API endpoints

```bash
# Health check
GET  /health

# Ask a question
POST /query
{"question": "Why did Kafka replace ZooKeeper with KRaft?"}

# Find domain experts
GET  /experts/{topic}        # e.g. /experts/replication

# Find engineering decisions
GET  /decisions/{system}     # e.g. /decisions/zookeeper

# Corpus statistics
GET  /stats
```

Full docs: `http://localhost:8000/docs`

---

## Key engineering decisions

**Why dual storage (PostgreSQL + Neo4j)?**
Vector search finds semantically similar documents. Graph traversal finds *relationships* — who worked on what, which decisions affected which systems. They answer different question types. Combining them is what gets you from 48% to 92%.

**Why pgvector over Pinecone/Weaviate?**
PostgreSQL is already your operational database. Adding a vector column costs nothing and eliminates a network hop. For 10k–1M documents, pgvector's performance is indistinguishable from dedicated vector databases.

**Why KIP boost (×1.35)?**
KIP documents contain structured decision rationale: Motivation, Public Interface, Rejected Alternatives. They're 7,447 chars average vs 789 for git commits. Without the boost, high-volume Jira issues crowd them out despite being less informative for decision questions.

**Why Socket Mode for Slack?**
No public URL required. The bot connects outbound to Slack's servers. You can run the bot on a laptop behind a firewall and it works. This is the right default for development and internal tools.

---

## Project structure

```
org-memory-engine/
├── src/
│   ├── ingestion/          # Jira, Git, KIP ingestors
│   ├── extraction/         # Entity, embedding, decision, expert extractors
│   ├── retrieval/          # Semantic retriever, graph retriever, RAG pipeline
│   ├── storage/            # PostgreSQL, Neo4j, graph builder, data quality
│   ├── api/                # FastAPI routes
│   ├── dashboard/          # Streamlit app
│   ├── evaluation/         # Eval builder, scorer
│   └── slack_bot/          # Slack bot (Socket Mode)
├── main.py                 # FastAPI entry point
├── docker-compose.yml      # One-command startup
├── Dockerfile
└── requirements.docker.txt
```

---

## Lessons learned

1. **Named Docker volumes** — learned this the hard way after a container crash. Named volumes survive `docker rm`. Anonymous volumes don't.
2. **KIP boost** — without source weighting, keyword frequency beats document quality. A 997-issue Jira corpus drowns 12 KIPs that contain 90% of the decision rationale.
3. **LLM prompt specificity** — "answer the question" gets generic answers. "Lead with the architectural reason, not a bug report" gets the answer you'd give in a design review.
4. **Dual storage over single** — first instinct was to use only pgvector. Adding Neo4j for relationship queries added 12 accuracy points with minimal code.

---

## Author

Built as a portfolio project demonstrating production RAG architecture, dual-storage retrieval, and LLM integration on real open-source engineering data.

*Data source: Apache Kafka public Jira, GitHub, and KIP documents (public domain)*