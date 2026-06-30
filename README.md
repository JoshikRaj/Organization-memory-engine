# Organizational Memory Engine

A system that ingests organizational data (Jira, Git, Slack, Confluence) and lets you ask
natural language questions like *"why did we choose Kafka over RabbitMQ in 2022?"* —
getting back sourced, confidence-scored answers instead of digging through dead Slack threads.

Built and benchmarked on Apache Software Foundation's public 10-year dataset.

## Status: Week 1 — Data Ingestion ✅

## Architecture

1. **Ingestion** — Pulls from Jira, Git commits (Slack/Confluence planned)
2. **Extraction** — Entity + decision extraction via spaCy + LLM (Week 2)
3. **Storage** — Neo4j knowledge graph + Weaviate vector store (Week 3)
4. **Retrieval** — Temporal RAG with contradiction detection (Week 4)
5. **API** — FastAPI + Slack bot (Week 5)

## Data Sources

| Source | Project | Status |
|--------|---------|--------|
| Apache Jira | KAFKA | ✅ ~1000 issues ingested |
| GitHub | apache/kafka | ✅ ~300 commits ingested |
| Mailing lists | dev@kafka.apache.org | Planned |

## Running locally

```bash
# 1. Start PostgreSQL
docker run -e POSTGRES_PASSWORD=pass -p 5432:5432 -d postgres

# 2. Set up environment
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env  # fill in your values

# 3. Run ingestion
python -m src.ingestion.jira_ingestor
python -m src.ingestion.git_ingestor

# 4. Check data quality
python -m src.storage.data_quality

# 5. Run tests
pytest tests/ -v
```

## Tech Stack

- **Ingestion:** Python, requests, APScheduler
- **Storage:** PostgreSQL (raw), Neo4j (graph), Weaviate (vectors) — coming Week 3
- **ML:** spaCy, sentence-transformers, OpenAI/Claude API — coming Week 2
- **API:** FastAPI, Slack Bolt SDK — coming Week 5

## Why this project exists

Every engineering team loses institutional knowledge when people leave. This project treats
that as a retrieval + reasoning problem, not just a search problem — distinguishing
"find documents about X" from "explain why we decided X and who was involved."