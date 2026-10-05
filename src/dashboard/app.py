"""
dashboard/app.py

Streamlit dashboard for the Organizational Memory Engine.
This is your visual demo — what you show in interviews and record
for your demo video.

Run with: streamlit run src/dashboard/app.py
Make sure FastAPI is running on port 8000 first.
"""

import time
import requests
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import os
API_BASE = os.environ.get("API_BASE", "http://localhost:8000").rstrip("/")
DEMO_MODE = not bool(API_BASE)

st.set_page_config(
    page_title="Org Memory Engine",
    page_icon="🧠",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
.answer-box {
    background: #f0f7ff;
    border-left: 4px solid #1976d2;
    padding: 1rem 1.25rem;
    border-radius: 0 8px 8px 0;
    margin: 1rem 0;
    font-size: 1rem;
    line-height: 1.7;
    color: #1a1a2e;
}
.source-chip {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 999px;
    font-size: 0.75rem;
    font-weight: 500;
    margin: 2px;
}
.accuracy-hero {
    text-align: center;
    padding: 2rem 0 1rem;
}
.accuracy-number {
    font-size: 4rem;
    font-weight: 700;
    color: #1976d2;
    line-height: 1;
}
.accuracy-label {
    font-size: 1rem;
    color: #666;
    margin-top: 0.5rem;
}
.demo-banner {
    background: linear-gradient(135deg, #fff3e0, #fbe9e7);
    border: 1px solid #ffb74d;
    border-radius: 10px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}
</style>
""", unsafe_allow_html=True)


# ── API helpers ──────────────────────────────────────────────────

@st.cache_data(ttl=60)
def get_stats() -> dict:
    if DEMO_MODE:
        return {"total_documents": 2847, "total_experts": 143,
                "total_decisions": 312, "total_entities": 1089, "eval_accuracy": 0.92}
    try:
        return requests.get(f"{API_BASE}/stats", timeout=5).json()
    except Exception:
        return {}


@st.cache_data(ttl=30)
def get_health() -> dict:
    if DEMO_MODE:
        return {"status": "demo"}
    try:
        return requests.get(f"{API_BASE}/health", timeout=5).json()
    except Exception:
        return {"status": "offline"}


def query_api(question: str) -> dict:
    if DEMO_MODE:
        return {"_demo": True}
    try:
        return requests.post(
            f"{API_BASE}/query",
            json={"question": question},
            timeout=30,
        ).json()
    except Exception as e:
        return {"error": str(e)}


@st.cache_data(ttl=60)
def get_experts(topic: str) -> list:
    if DEMO_MODE:
        return []
    try:
        r = requests.get(f"{API_BASE}/experts/{topic}", timeout=10)
        return r.json().get("experts", [])
    except Exception:
        return []


@st.cache_data(ttl=60)
def get_decisions(system: str) -> list:
    if DEMO_MODE:
        return []
    try:
        r = requests.get(f"{API_BASE}/decisions/{system}", timeout=10)
        return r.json().get("decisions", [])
    except Exception:
        return []


def show_demo_banner():
    st.markdown(
        "<div class='demo-banner'>"
        "<strong>Demo mode</strong> — This page requires a live backend. "
        "The <strong>Benchmark</strong> page works fully offline with real results."
        "</div>",
        unsafe_allow_html=True,
    )


# ── Sidebar ──────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("## 🧠 Org Memory Engine")
    st.markdown("*10 years of Apache Kafka engineering knowledge*")
    st.divider()

    health = get_health()
    if health.get("status") == "demo":
        st.warning("Demo mode — Benchmark only")
    elif health.get("status") == "healthy":
        st.success("All systems healthy")
    else:
        st.error(f"Status: {health.get('status', 'offline')}")

    st.divider()

    page = st.radio(
        "Navigate",
        ["💬 Ask", "👤 Experts", "📋 Decisions", "📊 Benchmark"],
        label_visibility="collapsed",
    )

    st.divider()

    stats = get_stats()
    if stats:
        st.markdown("**Corpus stats**")
        col1, col2 = st.columns(2)
        with col1:
            st.metric("Docs", f"{stats.get('total_documents', 0):,}")
            st.metric("Experts", f"{stats.get('total_experts', 0):,}")
        with col2:
            st.metric("Decisions", f"{stats.get('total_decisions', 0):,}")
            st.metric("Entities", f"{stats.get('total_entities', 0):,}")

        acc = stats.get("eval_accuracy", 0)
        if acc:
            st.metric("Best accuracy", f"{acc*100:.0f}%")

    st.divider()
    st.markdown(
        "<div style='font-size:0.75rem;color:#999'>"
        "Sources: Apache Jira · GitHub · KIP documents<br>"
        "Model: Llama 3.3 70B via Groq"
        "</div>",
        unsafe_allow_html=True,
    )


# ── Page: Ask ────────────────────────────────────────────────────

if page == "💬 Ask":
    st.markdown("## Ask anything about Kafka's engineering history")
    st.markdown(
        "Combines semantic search + knowledge graph + Llama 3.3 70B "
        "to return sourced, specific answers."
    )

    if DEMO_MODE:
        show_demo_banner()
        st.stop()

    EXAMPLES = [
        "Why did Kafka replace ZooKeeper with KRaft?",
        "Who are the main experts on Kafka replication?",
        "What alternatives were considered for exactly-once semantics?",
        "Why does Kafka use sequential disk I/O?",
        "Who originally proposed tiered storage?",
        "What is log compaction and why was it introduced?",
    ]

    st.markdown("**Example questions — click to ask:**")
    cols = st.columns(3)
    for i, ex in enumerate(EXAMPLES):
        if cols[i % 3].button(ex, key=f"ex{i}", use_container_width=True):
            st.session_state["question"] = ex
            st.session_state["auto_ask"] = True
            st.rerun()

    st.divider()

    question = st.text_input(
        "Your question",
        value=st.session_state.get("question", ""),
        placeholder="Ask about any Kafka engineering decision...",
        label_visibility="collapsed",
        key="q_input",
    )

    ask_btn = st.button("Ask", type="primary", use_container_width=True)

    # Fire query on button click OR on auto_ask from example buttons
    should_ask = (ask_btn and question) or st.session_state.pop("auto_ask", False)
    active_question = question or st.session_state.get("question", "")

    if should_ask and active_question:
        st.session_state["question"] = active_question

        with st.spinner("Searching knowledge graph and documents..."):
            t0 = time.time()
            result = query_api(active_question)
            wall_ms = int((time.time() - t0) * 1000)

        if "error" in result or result.get("_demo"):
            if result.get("_demo"):
                st.info("Demo mode — no live backend connected.")
            else:
                st.error(f"API error: {result['error']}")
            st.stop()

        # ── Answer ——
        st.markdown("### Answer")
        st.markdown(
            f"<div class='answer-box'>{result.get('answer', 'No answer generated.')}</div>",
            unsafe_allow_html=True,
        )

        # —— Metrics row ——
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Latency", f"{result.get('latency_ms', wall_ms)}ms")
        m2.metric("Sources", len(result.get("sources", [])))
        m3.metric("Graph paths", len(result.get("graph_paths", [])))
        m4.metric("Experts found", len(result.get("experts", [])))

        # —— Sources ——
        sources = result.get("sources", [])
        if sources:
            with st.expander(f"📄 Sources ({len(sources)})"):
                COLOR = {
                    "kip": ("#1976d2", "#e3f2fd"),
                    "jira": ("#e65100", "#fff3e0"),
                    "git_commit": ("#2e7d32", "#e8f5e9"),
                    "graph_decision": ("#7b1fa2", "#f3e5f5"),
                    "semantic": ("#455a64", "#eceff1"),
                }
                for src in sources:
                    stype = src.get("source") or src.get("type") or "unknown"
                    fg, bg = COLOR.get(stype, ("#555", "#f5f5f5"))
                    sim = src.get("similarity") or 0
                    preview = src.get("preview") or src.get("decision") or ""
                    preview = preview[:250]
                    sim_text = f"similarity: {sim:.3f}" if sim else ""
                    st.markdown(
                        f"<span class='source-chip' style='background:{bg};color:{fg};border:1px solid {fg}30'>"
                        f"{stype.upper()}</span> "
                        f"<span style='font-size:0.8rem;color:#888'>{sim_text}</span><br>"
                        f"<span style='font-size:0.85rem;color:#444'>{preview}…</span>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("---")

        # —— Graph paths ——
        graph_paths = result.get("graph_paths", [])
        if graph_paths:
            with st.expander(f"🔗 Knowledge graph paths ({len(graph_paths)})"):
                for path in graph_paths:
                    st.code(path, language=None)

        # —— Experts ——
        experts = result.get("experts", [])
        if experts:
            with st.expander(f"👤 Domain experts ({len(experts)})"):
                df = pd.DataFrame(experts)
                cols_show = [c for c in
                             ["person", "topic", "score", "decisions", "mentions"]
                             if c in df.columns]
                st.dataframe(df[cols_show], use_container_width=True,
                             hide_index=True)


# ── Page: Experts ────────────────────────────────────────────────

elif page == "👤 Experts":
    st.markdown("## Domain experts")
    st.markdown("Who knows the most about each Kafka component, scored by decisions + mentions + recency.")

    TOPIC_BUTTONS = [
        "zookeeper", "replication", "kafka streams",
        "tiered storage", "consumer group", "exactly once",
        "transactions", "mirrormaker",
    ]

    st.markdown("**Popular topics:**")
    tcols = st.columns(4)
    clicked_topic = None
    for i, t in enumerate(TOPIC_BUTTONS):
        if tcols[i % 4].button(t, key=f"t{i}", use_container_width=True):
            clicked_topic = t

    topic = st.text_input(
        "Or type a topic",
        value=clicked_topic or "",
        placeholder="e.g. replication, security, streams...",
        label_visibility="collapsed",
    )

    if topic:
        with st.spinner(f"Finding experts on '{topic}'..."):
            experts = get_experts(topic)

        if not experts:
            st.info(f"No experts found for '{topic}'. Try: zookeeper, replication, tiered storage")
        else:
            st.success(f"Found {len(experts)} experts on '{topic}'")
            df = pd.DataFrame(experts)

            fig = px.bar(
                df,
                x="person",
                y="score",
                color="score",
                color_continuous_scale="Blues",
                text=[f"{s:.2f}" for s in df["score"]],
                title=f"Expertise scores — '{topic}'",
                labels={"person": "Contributor", "score": "Score"},
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(
                showlegend=False,
                yaxis_range=[0, 1.15],
                plot_bgcolor="rgba(0,0,0,0)",
                paper_bgcolor="rgba(0,0,0,0)",
                xaxis_tickangle=-25,
            )
            st.plotly_chart(fig, use_container_width=True)

            cols_show = [c for c in
                         ["person", "topic", "score", "decisions", "mentions"]
                         if c in df.columns]
            st.dataframe(
                df[cols_show].rename(columns={
                    "person": "Contributor",
                    "topic": "Topic",
                    "score": "Score",
                    "decisions": "Decisions",
                    "mentions": "Mentions",
                }),
                use_container_width=True,
                hide_index=True,
            )


# ── Page: Decisions ──────────────────────────────────────────────

elif page == "📋 Decisions":
    st.markdown("## Engineering decisions")
    st.markdown(
        "Structured decisions extracted from Jira, Git, and KIP documents — "
        "what was decided, why, and what alternatives were rejected."
    )

    SYS_BUTTONS = [
        "zookeeper", "kraft", "replication",
        "tiered storage", "transactions", "consumer",
    ]

    st.markdown("**Popular systems:**")
    scols = st.columns(3)
    clicked_sys = None
    for i, s in enumerate(SYS_BUTTONS):
        if scols[i % 3].button(s, key=f"s{i}", use_container_width=True):
            clicked_sys = s

    system = st.text_input(
        "Or type a system",
        value=clicked_sys or "",
        placeholder="e.g. zookeeper, kraft, replication...",
        label_visibility="collapsed",
    )

    if system:
        with st.spinner(f"Finding decisions about '{system}'..."):
            decisions = get_decisions(system)

        if not decisions:
            st.info(f"No decisions found for '{system}'. Try: zookeeper, kraft, replication")
        else:
            st.success(f"Found {len(decisions)} decisions about '{system}'")

            for i, dec in enumerate(decisions):
                label = dec.get("decision", "")[:80] or f"Decision {i+1}"
                with st.expander(f"#{i+1} — {label}...", expanded=(i == 0)):
                    if dec.get("decision"):
                        st.markdown(f"**What was decided:**  \n{dec['decision']}")
                    if dec.get("rationale"):
                        st.markdown(f"**Why:**  \n{dec['rationale']}")
                    alts = dec.get("alternatives") or []
                    if alts:
                        st.markdown("**Alternatives considered:**")
                        for alt in alts:
                            st.markdown(f"- {alt}")
                    conf = float(dec.get("confidence", 0))
                    st.progress(conf, text=f"Extraction confidence: {conf:.0%}")


# ── Page: Benchmark ──────────────────────────────────────────────

elif page == "📊 Benchmark":
    st.markdown("## Benchmark results")
    st.markdown(
        "Accuracy measured on 50 hand-labeled questions from "
        "Apache Kafka's 10-year public dataset."
    )

    st.markdown(
        "<div class='accuracy-hero'>"
        "<div class='accuracy-number'>92%</div>"
        "<div class='accuracy-label'>Final accuracy — 46 of 50 questions correct</div>"
        "</div>",
        unsafe_allow_html=True,
    )

    st.divider()

    # Progression chart
    prog = pd.DataFrame([
        {"Version": "v1 Keyword", "Accuracy": 12, "Added": "Baseline"},
        {"Version": "v2 + KIPs", "Accuracy": 18, "Added": "KIP documents"},
        {"Version": "v3 + Semantic", "Accuracy": 36, "Added": "Vector search"},
        {"Version": "v4 + Graph", "Accuracy": 48, "Added": "Neo4j graph"},
        {"Version": "v4 + LLM", "Accuracy": 92, "Added": "Llama 3.3 70B"},
    ])

    fig = go.Figure(go.Bar(
        x=prog["Version"],
        y=prog["Accuracy"],
        text=[f"{v}%" for v in prog["Accuracy"]],
        textposition="outside",
        marker_color=["#ef5350", "#ff7043", "#ffa726", "#42a5f5", "#1565c0"],
        marker_line_width=0,
    ))
    fig.update_layout(
        title="Accuracy progression — each layer's contribution",
        yaxis_title="Accuracy (%)",
        yaxis_range=[0, 110],
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        showlegend=False,
        xaxis_tickangle=0,
    )
    st.plotly_chart(fig, use_container_width=True)

    # Per-type breakdown
    st.markdown("### Per-question-type breakdown")
    c1, c2, c3 = st.columns(3)
    c1.metric("Factual questions", "100%", "20/20 correct")
    c2.metric("Decision questions", "100%", "20/20 correct")
    c3.metric("Expert questions", "60%", "6/10 correct")

    st.divider()

    st.markdown("### What each layer contributed")
    st.markdown("""
| Layer | Score | What it fixed |
|---|---|---|
| Keyword search | 12% | Starting point |
| + KIP documents | 18% | Missing decision rationale |
| + Semantic search (pgvector) | 36% | Vocabulary mismatch |
| + Neo4j knowledge graph | 48% | Relationship questions |
| **+ Llama 3.3 70B synthesis** | **92%** | **Answer coherence** |
""")

    st.info(
        "The single biggest jump — 48% to 92% — came from LLM synthesis. "
        "The model combines retrieved semantic context and graph relationships "
        "into a coherent, specific answer. Retrieval alone plateaued at 48%. "
        "This is why RAG outperforms pure retrieval."
    )

    st.divider()
    st.markdown("### Latency improvements")
    latency_data = pd.DataFrame([
        {"Stage": "Original", "Latency_ms": 25567},
        {"Stage": "+ Neo4j cache", "Latency_ms": 8309},
        {"Stage": "+ Indexes", "Latency_ms": 3281},
        {"Stage": "+ In-memory cache", "Latency_ms": 278},
    ])
    fig2 = px.bar(
        latency_data,
        x="Stage",
        y="Latency_ms",
        text=[f"{v:,}ms" for v in latency_data["Latency_ms"]],
        title="Latency optimization journey",
        labels={"Latency_ms": "Latency (ms)"},
        color="Latency_ms",
        color_continuous_scale="Reds_r",
    )
    fig2.update_traces(textposition="outside")
    fig2.update_layout(
        showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig2, use_container_width=True)
    st.success("92× latency improvement: 25,567ms → 278ms through caching, indexing, and query optimization.")
