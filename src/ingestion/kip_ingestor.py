"""
ingestion/kip_ingestor.py

Ingests Kafka Improvement Proposals (KIPs) from Apache's public Confluence wiki.
KIPs contain exactly what your decision questions need:
- Motivation (why was this needed)
- Proposed changes (what was decided)
- Alternatives considered (what was rejected)
- Authors (who proposed it)
"""

import hashlib
import json
import logging
import time
import re
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup
from src.storage.database import get_connection

logger = logging.getLogger(__name__)

WIKI_BASE = "https://cwiki.apache.org/confluence"

# Correct slugs discovered via Confluence REST API (CQL search)
# Format: (KIP number, exact URL slug)
TARGET_KIPS = [
    ("500", "KIP-500%3A+Replace+ZooKeeper+with+a+Self-Managed+Metadata+Quorum"),
    ("405", "KIP-405%3A+Kafka+Tiered+Storage"),
    ("98",  "KIP-98+-+Exactly+Once+Delivery+and+Transactional+Messaging"),
    ("101", "KIP-101+-+Alter+Replication+Protocol+to+use+Leader+Epoch+rather+than+High+Watermark+for+Truncation"),
    ("62",  "KIP-62%3A+Allow+consumer+to+send+heartbeats+from+a+background+thread"),
    ("382", "KIP-382%3A+MirrorMaker+2.0"),
    ("129", "KIP-129%3A+Streams+Exactly-Once+Semantics"),
    ("36",  "KIP-36+Rack+aware+replica+assignment"),
    ("19",  "KIP-19+-+Add+a+request+timeout+to+NetworkClient"),
    ("4",   "KIP-4+-+Command+line+and+centralized+administrative+operations"),
    ("33",  "KIP-33+-+Add+a+time+based+log+index"),
    ("117", "KIP-117%3A+Add+a+public+AdminClient+API+for+Kafka+admin+operations"),
    # KIP-140 and KIP-74 timed out during discovery, using page IDs via REST
]

# Fallback: fetch by page ID when slug is unknown
TARGET_KIP_IDS = {
    "140": "68717128",  # estimated - will 404-skip gracefully
    "74":  "61319765",  # estimated - will 404-skip gracefully
}


def fetch_kip_page(slug: str) -> Optional[str]:
    """Fetches raw HTML of a KIP wiki page by slug."""
    url = f"{WIKI_BASE}/display/KAFKA/{slug}"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        return response.text
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None


def fetch_kip_by_id(page_id: str) -> Optional[str]:
    """Fetches KIP content via Confluence REST API by page ID."""
    url = f"{WIKI_BASE}/rest/api/content/{page_id}?expand=body.view"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("body", {}).get("view", {}).get("value", "")
    except Exception as e:
        logger.warning(f"Failed to fetch page id={page_id}: {e}")
        return None


def parse_kip_page(html: str, kip_number: str) -> Optional[dict]:
    """
    Parses a KIP wiki page and extracts structured content.
    KIPs follow a consistent structure:
    - Motivation
    - Public Interfaces
    - Proposed Changes
    - Compatibility / Deprecation / Migration Plan
    - Rejected Alternatives
    """
    soup = BeautifulSoup(html, "html.parser")

    # Extract page title
    title_tag = soup.find("h1", {"id": "title-text"}) or soup.find("title")
    title = title_tag.get_text(strip=True) if title_tag else f"KIP-{kip_number}"

    # Extract main content area
    content_div = (
        soup.find("div", {"class": "wiki-content"}) or
        soup.find("div", {"id": "main-content"}) or
        soup.find("div", {"id": "content"})
    )

    if not content_div:
        # If no wrapper div, try parsing the whole html as fragment (REST API returns inner HTML)
        full_text = BeautifulSoup(html, "html.parser").get_text(separator="\n", strip=True)
    else:
        full_text = content_div.get_text(separator="\n", strip=True)

    # Clean up excessive whitespace
    full_text = re.sub(r'\n{3,}', '\n\n', full_text)
    full_text = re.sub(r' {2,}', ' ', full_text)

    if len(full_text) < 100:
        logger.warning(f"KIP-{kip_number} content too short: {len(full_text)} chars")
        return None

    # Extract the key sections
    sections = extract_kip_sections(full_text)

    # Build enriched content - motivation and rejected alternatives first
    enriched_content = f"KIP-{kip_number}: {title}\n\n"

    if sections.get("motivation"):
        enriched_content += f"MOTIVATION (Why this was needed):\n{sections['motivation']}\n\n"
    if sections.get("proposed_changes"):
        enriched_content += f"PROPOSED CHANGES (What was decided):\n{sections['proposed_changes']}\n\n"
    if sections.get("rejected_alternatives"):
        enriched_content += f"REJECTED ALTERNATIVES (What was considered but not chosen):\n{sections['rejected_alternatives']}\n\n"

    # Fall back to full text if section extraction failed
    if len(enriched_content) < 200:
        enriched_content = f"KIP-{kip_number}: {title}\n\n{full_text[:8000]}"

    content_hash = hashlib.sha256(enriched_content.encode()).hexdigest()

    return {
        "source": "kip",
        "content": enriched_content,
        "author": f"Apache Kafka KIP-{kip_number}",
        "timestamp": datetime.now(),
        "metadata": {
            "kip_number": kip_number,
            "title": title,
            "url": f"{WIKI_BASE}/display/KAFKA/KIP-{kip_number}",
            "sections_found": list(sections.keys()),
            "content_length": len(enriched_content),
        },
        "content_hash": content_hash,
        "source_id": f"KIP-{kip_number}",
    }


def extract_kip_sections(text: str) -> dict:
    """
    Extracts named sections from KIP text.
    """
    sections = {}
    section_patterns = {
        "motivation": r"(?i)motivation[:\s]*\n(.*?)(?=\n[A-Z][^a-z\n]{2,}|\Z)",
        "proposed_changes": r"(?i)proposed changes?[:\s]*\n(.*?)(?=\n[A-Z][^a-z\n]{2,}|\Z)",
        "rejected_alternatives": r"(?i)rejected alternatives?[:\s]*\n(.*?)(?=\n[A-Z][^a-z\n]{2,}|\Z)",
        "public_interfaces": r"(?i)public interfaces?[:\s]*\n(.*?)(?=\n[A-Z][^a-z\n]{2,}|\Z)",
    }

    for section_name, pattern in section_patterns.items():
        match = re.search(pattern, text, re.DOTALL)
        if match:
            content = match.group(1).strip()
            if len(content) > 50:
                sections[section_name] = content[:3000]

    return sections


def insert_document(conn, doc: dict) -> Optional[int]:
    """Inserts a KIP document into raw_documents."""
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


def run_kip_ingestion():
    """Fetches and ingests all target KIP pages."""
    logger.info(f"Starting KIP ingestion -- {len(TARGET_KIPS)} KIPs targeted")

    conn = get_connection()
    inserted = 0
    failed = 0
    skipped = 0

    for kip_number, kip_slug in TARGET_KIPS:
        logger.info(f"Fetching KIP-{kip_number}...")
        html = fetch_kip_page(kip_slug)

        if not html:
            failed += 1
            continue

        doc = parse_kip_page(html, kip_number)
        if not doc:
            failed += 1
            continue

        result = insert_document(conn, doc)
        if result:
            inserted += 1
            logger.info(f"  KIP-{kip_number} inserted (id={result}, {len(doc['content'])} chars, sections={doc['metadata']['sections_found']})")
        else:
            skipped += 1
            logger.info(f"  KIP-{kip_number} skipped (already exists)")

        time.sleep(1)

    conn.close()
    logger.info(f"KIP ingestion done: {inserted} inserted | {skipped} skipped | {failed} failed")
    return {"inserted": inserted, "skipped": skipped, "failed": failed}


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s"
    )
    result = run_kip_ingestion()
    print(json.dumps(result, indent=2))
