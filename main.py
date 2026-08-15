"""
main.py — Application entry point

Starts the FastAPI server with CORS support.
Run with: python main.py
"""

import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.api.routes import router

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# App
app = FastAPI(
    title="Organization Memory Engine",
    description=(
        "Ask natural language questions about Apache Kafka's architecture, "
        "decisions, and contributors. Powered by semantic search (pgvector), "
        "knowledge graph (Neo4j), and LLM generation (Llama 3.3 70B via Groq)."
    ),
    version="4.0 (92% accuracy)",
)

# CORS — allow Streamlit dashboard and local dev
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(router)


@app.get("/")
def root():
    return {
        "service": "Organization Memory Engine",
        "version": "v4-LLM",
        "accuracy": "92%",
        "docs": "/docs",
    }


if __name__ == "__main__":
    logger.info("Starting Organization Memory Engine API...")
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=False,
    )
