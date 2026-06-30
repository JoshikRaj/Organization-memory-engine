"""
ingestion/git_ingestor.py
Pulls commit history from Apache Kafka's PUBLIC GitHub repo.
No auth needed, but rate-limited to 60 req/hr without a token.
"""

import hashlib
import json
import logging
import os
import time
from datetime import datetime
from typing import Optional

import requests
from dotenv import load_dotenv

from src.storage.database import get_connection

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"
TARGET_REPO = "apache/kafka"
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")  # optional but recommended


def get_headers() -> dict:
    headers = {"Accept": "application/vnd.github.v3+json"}
    if GITHUB_TOKEN:
        headers["Authorization"] = f"token {GITHUB_TOKEN}"
    return headers


# ─── Step 2: Fetch commits ──────────────────────────────────────────────────

def fetch_commits(page: int = 1, per_page: int = 100, retries: int = 3) -> list:
    """
    Fetches one page of commits from the apache/kafka repo.
    Retries on transient network errors with exponential backoff.
    """
    url = f"{GITHUB_API}/repos/{TARGET_REPO}/commits"
    params = {"page": page, "per_page": per_page}

    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=get_headers(), params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.ConnectionError,
                requests.exceptions.ChunkedEncodingError,
                requests.exceptions.Timeout) as e:
            if attempt == retries:
                logger.error(f"Failed after {retries} attempts on page {page}: {e}")
                raise
            wait = 2 ** attempt
            logger.warning(f"Attempt {attempt} failed for page {page}, retrying in {wait}s... ({e})")
            time.sleep(wait)


# ─── Step 3: Parse a commit into your schema ────────────────────────────────

def parse_commit(commit: dict) -> dict:
    """
    Converts raw GitHub commit JSON into your raw_documents schema.
    """
    commit_data = commit.get("commit", {})
    message = commit_data.get("message", "")
    author_info = commit_data.get("author", {})
    author_name = author_info.get("name", "Unknown")
    date_str = author_info.get("date")  # e.g. "2023-01-15T10:30:00Z"

    timestamp = None
    if date_str:
        try:
            timestamp = datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError:
            pass

    files_changed = commit.get("files", [])  # only present if fetched individually
    sha = commit.get("sha")

    metadata = {
        "sha": sha,
        "repo": TARGET_REPO,
        "url": commit.get("html_url"),
        "files_changed_count": len(files_changed),
    }

    content_hash = hashlib.sha256(f"{sha}{message}".encode()).hexdigest()

    return {
        "source": "git_commit",
        "content": message,
        "author": author_name,
        "timestamp": timestamp,
        "metadata": metadata,
        "content_hash": content_hash,
        "source_id": sha,
    }


# ─── Step 4: Insert + main loop ─────────────────────────────────────────────

def insert_document(conn, doc: dict) -> Optional[int]:
    cursor = conn.cursor()
    try:
        cursor.execute("""
            INSERT INTO raw_documents
                (source, content, author, timestamp, metadata, content_hash)
            VALUES
                (%(source)s, %(content)s, %(author)s, %(timestamp)s,
                 %(metadata)s::jsonb, %(content_hash)s)
            ON CONFLICT (content_hash) DO NOTHING
            RETURNING id;
        """, {**doc, "metadata": json.dumps(doc["metadata"])})
        result = cursor.fetchone()
        conn.commit()
        return result[0] if result else None
    except Exception as e:
        conn.rollback()
        logger.error(f"Insert failed for {doc.get('source_id')}: {e}")
        return None
    finally:
        cursor.close()


def run_git_ingestion(max_commits: int = 300):
    logger.info(f"Starting Git ingestion for repo: {TARGET_REPO}")
    conn = get_connection()

    total_fetched = 0
    total_inserted = 0
    total_skipped = 0
    page = 1
    start_time = time.time()

    while total_fetched < max_commits:
        logger.info(f"Fetching page {page} (commits {total_fetched + 1}-{min(total_fetched + 100, max_commits)})...")
        commits = fetch_commits(page=page, per_page=100)

        if not commits:
            logger.info("No more commits available")
            break

        for commit in commits:
            doc = parse_commit(commit)
            result = insert_document(conn, doc)

            if result:
                total_inserted += 1
                if total_inserted % 50 == 0:
                    logger.info(f"  Inserted {total_inserted} so far...")
            else:
                total_skipped += 1

            total_fetched += 1
            if total_fetched >= max_commits:
                break

        page += 1
        time.sleep(0.5)

    conn.close()
    elapsed = round(time.time() - start_time, 2)

    logger.info("=" * 50)
    logger.info(f"Done in {elapsed}s | Fetched: {total_fetched} | Inserted: {total_inserted} | Skipped: {total_skipped}")
    logger.info("=" * 50)

    return {"fetched": total_fetched, "inserted": total_inserted, "skipped": total_skipped}


if __name__ == "__main__":
    result = run_git_ingestion(max_commits=300)
    print(json.dumps(result, indent=2))
