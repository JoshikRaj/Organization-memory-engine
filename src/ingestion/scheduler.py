"""
ingestion/scheduler.py
Runs ingestion jobs on a schedule. For dev, you'll trigger manually,
but this proves the pipeline is "production-ready" — runs unattended.
"""

import logging
import os
from datetime import datetime

from apscheduler.schedulers.blocking import BlockingScheduler

from src.ingestion.jira_ingestor import run_jira_ingestion
from src.ingestion.git_ingestor import run_git_ingestion

LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(f"{LOG_DIR}/ingestion.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger(__name__)


def run_full_ingestion_cycle():
    """Runs all ingestors in sequence. This is what gets scheduled."""
    logger.info("=" * 60)
    logger.info(f"INGESTION CYCLE STARTED — {datetime.now().isoformat()}")
    logger.info("=" * 60)

    try:
        jira_result = run_jira_ingestion(max_issues=1000)
        logger.info(f"Jira result: {jira_result}")
    except Exception as e:
        logger.error(f"Jira ingestion failed: {e}")

    try:
        git_result = run_git_ingestion(max_commits=300)
        logger.info(f"Git result: {git_result}")
    except Exception as e:
        logger.error(f"Git ingestion failed: {e}")

    logger.info("INGESTION CYCLE COMPLETE")
    logger.info("=" * 60)


def start_scheduler():
    scheduler = BlockingScheduler()
    # Runs every 24 hours. For testing, change to minutes=5 temporarily.
    scheduler.add_job(run_full_ingestion_cycle, "interval", hours=24, id="daily_ingestion")

    logger.info("Scheduler started — ingestion will run every 24 hours")
    logger.info("Press Ctrl+C to stop")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped")


if __name__ == "__main__":
    # Run once immediately, then start the schedule
    run_full_ingestion_cycle()
    start_scheduler()
