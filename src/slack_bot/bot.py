"""
slack_bot/bot.py

Org Memory Slack Bot — connects your knowledge engine to Slack.

How it works:
  1. Someone @mentions the bot in any channel
  2. Bot extracts the question from the message
  3. Calls your local FastAPI /query endpoint (same one your dashboard uses)
  4. Formats the answer with sources and posts it back to Slack

Run with:
  python -m src.slack_bot.bot

Requirements in .env:
  SLACK_BOT_TOKEN=xoxb-...
  SLACK_APP_TOKEN=xapp-...   (Socket Mode token)
"""

import logging
import os
import re

import requests
from dotenv import load_dotenv
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")
SLACK_BOT_TOKEN = os.getenv("SLACK_BOT_TOKEN")
SLACK_APP_TOKEN = os.getenv("SLACK_APP_TOKEN")

app = App(token=SLACK_BOT_TOKEN)


# ── Helper: strip @mention from text ──────────────────────────────

def extract_question(text: str, bot_user_id: str) -> str:
    """
    Removes the @BotName mention and cleans up the question text.
    Input:  "<@U12345> why did Kafka move away from ZooKeeper?"
    Output: "why did Kafka move away from ZooKeeper?"
    """
    # Remove @mention patterns like <@U12345>
    clean = re.sub(r"<@[A-Z0-9]+>", "", text).strip()
    # Collapse multiple spaces
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


# ── Helper: call your FastAPI /query endpoint ─────────────────────

def query_knowledge_engine(question: str) -> dict:
    """
    Calls POST /query on your FastAPI server.
    Returns the full response dict or raises on error.
    """
    response = requests.post(
        f"{API_BASE_URL}/query",
        json={"question": question},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


# ── Helper: format the response into Slack blocks ─────────────────

def format_slack_response(question: str, result: dict) -> list:
    """
    Formats the API response into rich Slack Block Kit blocks.
    Clean, scannable, no wall of text.
    """
    answer = result.get("answer", "No answer found.")
    sources = result.get("sources", [])
    experts = result.get("experts", [])
    latency = result.get("latency_ms", 0)

    blocks = [
        # Question header
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": "🧠 Org Memory Engine",
                "emoji": True,
            },
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Question:* {question}",
            },
        },
        {"type": "divider"},
        # Answer
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Answer:*\n{answer}",
            },
        },
    ]

    # Sources (top 3)
    if sources:
        source_lines = []
        for i, src in enumerate(sources[:3], 1):
            src_type = src.get("source", src.get("type", "unknown")).upper()
            preview = src.get("preview", "")[:120]
            similarity = src.get("similarity")
            sim_str = f" _{similarity:.0%} match_" if similarity else ""
            source_lines.append(f"{i}. *[{src_type}]*{sim_str} — {preview}…")

        blocks.append({"type": "divider"})
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*📚 Sources:*\n" + "\n".join(source_lines),
            },
        })

    # Experts
    if experts:
        expert_names = [e.get("person", "") for e in experts[:3]]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*👤 Domain experts:* {' · '.join(expert_names)}",
            },
        })

    # Footer
    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": (
                    f"⚡ {latency}ms · "
                    f"Powered by pgvector + Neo4j + Groq Llama · "
                    f"<{API_BASE_URL}/docs|API Docs>"
                ),
            }
        ],
    })

    return blocks


# ── Event handler: respond to @mentions ───────────────────────────

@app.event("app_mention")
def handle_mention(event, say, client):
    """
    Fires whenever someone @mentions the bot.
    Extracts the question, queries the knowledge engine, posts the answer.
    """
    channel = event["channel"]
    thread_ts = event.get("thread_ts", event["ts"])  # reply in thread
    text = event.get("text", "")
    bot_user_id = client.auth_test()["user_id"]

    question = extract_question(text, bot_user_id)

    if not question:
        say(
            text="Please ask me a question! e.g. _@OrgMemoryBot why did Kafka replace ZooKeeper?_",
            thread_ts=thread_ts,
            channel=channel,
        )
        return

    # Show typing indicator
    client.reactions_add(channel=channel, name="hourglass_flowing_sand", timestamp=event["ts"])

    logger.info(f"Question received: {question!r}")

    try:
        result = query_knowledge_engine(question)
        blocks = format_slack_response(question, result)

        client.chat_postMessage(
            channel=channel,
            thread_ts=thread_ts,
            blocks=blocks,
            text=result.get("answer", "Answer ready."),  # fallback for notifications
        )

    except requests.exceptions.ConnectionError:
        say(
            text=(
                "⚠️ Can't reach the knowledge engine API. "
                "Make sure `python main.py` is running on port 8000."
            ),
            thread_ts=thread_ts,
            channel=channel,
        )
        logger.error("ConnectionError: FastAPI server not reachable")

    except requests.exceptions.Timeout:
        say(
            text="⏱️ The query timed out (>60s). Try a simpler question.",
            thread_ts=thread_ts,
            channel=channel,
        )

    except Exception as e:
        say(
            text=f"❌ Something went wrong: `{e}`",
            thread_ts=thread_ts,
            channel=channel,
        )
        logger.exception(f"Unexpected error handling mention: {e}")

    finally:
        # Remove hourglass reaction
        try:
            client.reactions_remove(
                channel=channel, name="hourglass_flowing_sand", timestamp=event["ts"]
            )
        except Exception:
            pass


# ── Health check: respond to DMs with "ping" ──────────────────────

@app.message("ping")
def handle_ping(message, say):
    """Quick health check — DM the bot 'ping' to verify it's alive."""
    say("🟢 Org Memory Bot is alive! Try mentioning me in a channel with a question.")


# ── Entry point ───────────────────────────────────────────────────

if __name__ == "__main__":
    if not SLACK_BOT_TOKEN:
        raise ValueError("SLACK_BOT_TOKEN not set in .env")
    if not SLACK_APP_TOKEN:
        raise ValueError("SLACK_APP_TOKEN not set in .env")

    logger.info("Starting Org Memory Slack Bot (Socket Mode)...")
    logger.info(f"Connecting to knowledge engine at: {API_BASE_URL}")

    handler = SocketModeHandler(app, SLACK_APP_TOKEN)
    handler.start()
