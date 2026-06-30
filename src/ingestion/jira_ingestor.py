"""
ingestion/jira_ingestor.py
Pulls issues from Apache's PUBLIC Jira — no API key needed.
Project used: KAFKA
"""

import hashlib
import json
import logging
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

APACHE_JIRA_BASE = "https://issues.apache.org/jira/rest/api/2"
TARGET_PROJECT = "KAFKA"


# ─── Step 2: Fetch a page of issues ─────────────────────────────────────────

def fetch_jira_issues(start_at: int = 0, max_results: int = 100) -> dict:
    """
    Fetches one page of Jira issues.
    start_at: pagination offset (0, 100, 200, ...)
    max_results: how many per request (Jira caps this at 100)
    """
    url = f"{APACHE_JIRA_BASE}/search"

    params = {
        "jql": f"project={TARGET_PROJECT} ORDER BY created DESC",
        "startAt": start_at,
        "maxResults": max_results,
        "fields": "summary,description,comment,reporter,created,resolutiondate,status,labels,priority",
    }

    response = requests.get(url, params=params, timeout=30)
    response.raise_for_status()  # crashes loudly if something's wrong — good, you want to know
    return response.json()


# ─── Step 3: Parse one issue into your schema ───────────────────────────────

def parse_issue(issue: dict) -> dict:
    """
    Converts raw Jira JSON into your raw_documents schema.
    """
    fields = issue.get("fields", {})

    title = fields.get("summary", "")
    description = fields.get("description", "") or ""

    comments_data = fields.get("comment", {}).get("comments", [])
    comments_text = "\n\n".join([
        f"[{c.get('author', {}).get('displayName', 'Unknown')}]: {c.get('body', '')}"
        for c in comments_data
    ])

    full_content = f"{title}\n\n{description}"
    if comments_text:
        full_content += f"\n\n--- COMMENTS ---\n{comments_text}"

    reporter = fields.get("reporter") or {}
    author = reporter.get("displayName", "Unknown")

    created_str = fields.get("created")
    created_at = None
    if created_str:
        try:
            created_at = datetime.strptime(created_str[:19], "%Y-%m-%dT%H:%M:%S")
        except ValueError:
            pass

    metadata = {
        "jira_key": issue.get("key"),
        "status": fields.get("status", {}).get("name"),
        "priority": fields.get("priority", {}).get("name"),
        "labels": fields.get("labels", []),
        "resolution_date": fields.get("resolutiondate"),
        "comment_count": len(comments_data),
        "project": TARGET_PROJECT,
    }

    content_hash = hashlib.sha256(full_content.encode()).hexdigest()

    return {
        "source": "jira",
        "content": full_content,
        "author": author,
        "timestamp": created_at,
        "metadata": metadata,
        "content_hash": content_hash,
        "source_id": issue.get("key"),
        "title": title,
    }


# ─── Step 4: Insert into PostgreSQL with deduplication ──────────────────────

def insert_document(conn, doc: dict) -> Optional[int]:
    """
    Inserts one document. Returns the new row ID, or None if duplicate.
    """
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


# ─── Step 5: Main loop that pulls up to max_issues ──────────────────────────

def run_jira_ingestion(max_issues: int = 1000):
    """
    Pulls up to max_issues from Apache Jira into PostgreSQL.
    Run with: python -m src.ingestion.jira_ingestor
    """
    logger.info(f"Starting Jira ingestion for project: {TARGET_PROJECT}")
    conn = get_connection()

    total_fetched = 0
    total_inserted = 0
    total_skipped = 0
    start_time = time.time()

    page = 0
    while total_fetched < max_issues:
        start_at = page * 100
        logger.info(f"Fetching page {page + 1} (offset {start_at})...")

        data = fetch_jira_issues(start_at=start_at, max_results=100)
        issues = data.get("issues", [])

        if not issues:
            logger.info("No more issues available")
            break

        for issue in issues:
            doc = parse_issue(issue)
            result = insert_document(conn, doc)

            if result:
                total_inserted += 1
                if total_inserted % 50 == 0:
                    logger.info(f"  Inserted {total_inserted} so far...")
            else:
                total_skipped += 1

            total_fetched += 1
            if total_fetched >= max_issues:
                break

        time.sleep(1)  # be respectful to Apache's servers
        page += 1

        total_available = data.get("total", 0)
        if start_at + 100 >= total_available:
            logger.info(f"Reached end of available issues ({total_available} total)")
            break

    conn.close()
    elapsed = round(time.time() - start_time, 2)

    logger.info("=" * 50)
    logger.info(f"Done in {elapsed}s | Fetched: {total_fetched} | Inserted: {total_inserted} | Skipped: {total_skipped}")
    logger.info("=" * 50)

    return {"fetched": total_fetched, "inserted": total_inserted, "skipped": total_skipped}


if __name__ == "__main__":
    result = run_jira_ingestion(max_issues=1000)
    print(json.dumps(result, indent=2))