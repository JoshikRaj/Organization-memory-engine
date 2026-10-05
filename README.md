# 🧠 Org Memory Engine

> **92% accuracy** answering engineering decision questions — built on 10 years of Apache Kafka's public engineering history.

A production-grade RAG (Retrieval-Augmented Generation) system that ingests Jira tickets, Git commits, and KIP documents, stores them in a dual-database architecture (PostgreSQL + Neo4j), and answers questions about engineering decisions in real time — via a web dashboard and a live Slack bot.

---

## 🎯 What it does

Ask it anything about Kafka's engineering history:

| Question | Answer |
|----------|--------|
| *"Why did Kafka replace ZooKeeper with KRaft?"* | Cites KIP-500, explains the architectural motivation, names the contributors |
| *"Who are the top experts on Kafka replication?"* | Returns scored contributor list with decision + mention counts |
| *"What alternatives were considered for exactly-once semantics?"* | Pulls from KIP documents with confidence scores |

---

## 📊 Benchmark results

| Version | Accuracy | What was added |
|---------|----------|----------------|
| v1 — Keyword search | 12% | Baseline |
| v2 — + KIP documents | 18% | Decision rationale |
| v3 — + Semantic search (pgvector) | 36% | Vector similarity |
| v4 — + Neo4j knowledge graph | 48% | Relationship queries |
| **v4 — + LLM synthesis (Groq)** | **92%** | **Answer coherence** |

**The single biggest jump (48% → 92%) came from LLM synthesis** — retrieval alone plateaued. This is the core insight of modern RAG systems.

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Data Sources                              │
│   Apache Jira (997)  │  GitHub Commits (300)  │  KIPs (12)      │
└──────────────────────┬──────────────────────────────────────────┘
                       │ Ingestion
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                    PostgreSQL + pgvector                          │
│  raw_documents │ entities │ experts │ decisions │ eval_questions  │
│  embeddings (all-MiniLM-L6-v2, 384-dim)                         │
└──────────────────────┬──────────────────────────────────────────┘
                       │ Graph Builder
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│                       Neo4j Graph                                │
│  Person → EXPERTISE_IN → Topic                                   │
│  Document → MENTIONS → Person/System                             │
│  Decision → DOCUMENTED_IN → Document                             │
└──────────────────────┬──────────────────────────────────────────┘
                       │ RAG Pipeline
                       ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. hybrid_search()    pgvector cosine sim + KIP 1.35× boost     │
│  2. graph_retrieve()   Neo4j expert + decision lookup            │
│  3. generate_answer()  Groq LLM (120B) with directive prompt     │
└──────────────────────┬──────────────────────────────────────────┘
                       │
           ┌───────────┼───────────┐
           ▼           ▼           ▼
      FastAPI       Streamlit    Slack Bot
     REST API       Dashboard   (Socket Mode)
    port 8000       port 8501
```

---

## 🚀 Quick start

### Prerequisites
- Docker Desktop
- Python 3.11+
- Groq API key (free at [console.groq.com](https://console.groq.com))

### 1. Clone and configure

```bash
git clone https://github.com/YOUR_USERNAME/org-memory-engine.git
cd Organization-memory-engine
cp .env.example .env
# Edit .env with your credentials
```

### 2. Start infrastructure

```bash
docker compose up postgres neo4j -d
```

### 3. Install dependencies and run pipeline

```bash
python -m venv venv
venv\Scripts\activate        # Windows
# source venv/bin/activate   # Mac/Linux

pip install -r requirements.docker.txt
python -m spacy download en_core_web_lg

# Ingest data
python -m src.ingestion.jira_ingestor
python -m src.ingestion.git_ingestor
python -m src.ingestion.kip_ingestor

# Extract
python -m src.extraction.entity_extractor
python -m src.extraction.embedding_generator
python -m src.extraction.decision_extractor
python -m src.extraction.expert_identifier

# Build graph
python -m src.storage.graph_builder

# Load eval questions
python -m src.evaluation.eval_builder
```

### 4. Start the services

```bash
# Terminal 1 — API
python main.py

# Terminal 2 — Dashboard
streamlit run src/dashboard/app.py

# Terminal 3 — Slack bot (optional)
python -m src.slack_bot.bot
```

**Or start everything with Docker Compose:**

```bash
docker compose up --build
```

---

## 📁 Project structure

```
org-memory-engine/
├── src/
│   ├── ingestion/          # Jira, Git, KIP ingestors
│   ├── extraction/         # Entity, embedding, decision, expert extractors
│   ├── retrieval/          # Semantic search, graph retrieval, RAG pipeline
│   ├── storage/            # PostgreSQL + Neo4j clients, graph builder
│   ├── api/                # FastAPI routes
│   ├── dashboard/          # Streamlit UI
│   ├── evaluation/         # Eval dataset + scoring
│   └── slack_bot/          # Slack Socket Mode bot
├── main.py                 # FastAPI entry point
├── docker-compose.yml      # One-command startup
├── Dockerfile
└── requirements.docker.txt
```

---

## 🔌 API reference

```bash
# Health check
GET  /health

# Ask a question (full RAG pipeline)
POST /query
{"question": "Why did Kafka replace ZooKeeper with KRaft?"}

# Find domain experts
GET  /experts/{topic}

# Find engineering decisions
GET  /decisions/{system}

# Corpus statistics
GET  /stats
```

---

## 💬 Slack bot

Invite `@Org Memory Bot` to any channel and ask:

```
@Org Memory Bot why did Kafka replace ZooKeeper with KRaft?
```

The bot replies in-thread with the answer, top 3 sources, and expert names.

---

## 🗄️ Data

- **1,309 documents** — 997 Jira issues + 300 Git commits + 12 KIP proposals
- **6,987 entities** — people, systems, topics
- **823 expert-topic pairs** — scored by decisions + mentions + recency
- **50 eval questions** — hand-labeled across factual, decision, and expert categories

---

## 🛠️ Tech stack

| Layer | Technology |
|-------|-----------|
| Vector DB | PostgreSQL 16 + pgvector |
| Graph DB | Neo4j |
| Embeddings | `all-MiniLM-L6-v2` (sentence-transformers) |
| NLP | spaCy `en_core_web_lg` |
| LLM | Groq `openai/gpt-oss-120b` |
| API | FastAPI + uvicorn |
| Dashboard | Streamlit + Plotly |
| Slack | slack-bolt (Socket Mode) |
| Containers | Docker Compose |

---

## 📝 Environment variables

```env
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=memory_engine
POSTGRES_USER=postgres
POSTGRES_PASSWORD=pass

NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=orgmemory123

GROQ_API_KEY=gsk_...
GITHUB_TOKEN=github_pat_...   # optional, raises rate limit

SLACK_BOT_TOKEN=xoxb-...      # optional
SLACK_APP_TOKEN=xapp-...      # optional
```

---

## 📄 License

MIT