FROM python:3.11-slim

# System deps for psycopg2, spacy, torch
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    libpq-dev \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps (cached layer — only rebuilds when requirements change)
COPY requirements.docker.txt .
RUN pip install --no-cache-dir -r requirements.docker.txt

# Download spacy model
RUN python -m spacy download en_core_web_lg

# Pre-download sentence-transformer model (bakes into image — faster startup)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')"

# Copy source
COPY . .

EXPOSE 8000 8501
