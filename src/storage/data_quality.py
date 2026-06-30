"""
storage/data_quality.py
Quick report on what's in your database — run anytime to check progress.
"""

import logging

from src.storage.database import get_connection

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)


def run_quality_report():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT source, COUNT(*) AS total,
               MIN(timestamp) AS earliest,
               MAX(timestamp) AS latest,
               AVG(LENGTH(content)) AS avg_content_length
        FROM raw_documents
        GROUP BY source;
    """)
    rows = cursor.fetchall()

    print("\n=== Data Quality Report ===")
    for row in rows:
        print(f"Source: {row[0]:15} | Count: {row[1]:5} | "
              f"Range: {row[2]} to {row[3]} | Avg length: {int(row[4])} chars")

    cursor.execute("SELECT COUNT(*) FROM raw_documents WHERE content IS NULL OR content = '';")
    empty = cursor.fetchone()[0]
    print(f"\nEmpty content rows: {empty}")

    cursor.execute("SELECT COUNT(*) FROM raw_documents;")
    total = cursor.fetchone()[0]
    print(f"Total documents:    {total}")
    print("=" * 50)

    cursor.close()
    conn.close()


if __name__ == "__main__":
    run_quality_report()
