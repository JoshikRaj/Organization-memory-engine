# Benchmark Progress Log

This file tracks the measurable improvement of the Organization Memory Engine
across each development phase. Accuracy = % of 50 eval questions answered correctly
(similarity_score >= 0.5 threshold).

| Date       | Version | Method                          | Accuracy | Correct/50 | Notes                                      |
|------------|---------|---------------------------------|----------|------------|-------------------------------------------|
| Week 2 Day 5 | v1    | Keyword search, no KIPs         | 12%      | 6/50       | Baseline — jira + git_commit only          |
| Week 2 Fix   | v2    | Keyword search + KIP data       | 18%      | 9/50       | After KIP ingestion (12 KIPs, 1317 docs)   |
| Week 3       | v3    | Semantic search (pgvector + KIP boost) | 36%      | 18/50      | After vector similarity retrieval          |
| Week 4       | v4    | Semantic + Neo4j graph (no LLM) | 48%      | 24/50      | Graph context fallback only                |
| Week 4 Final | v4-LLM | Semantic + Neo4j + Llama 3.3 70B | **92%** | **46/50**  | Full RAG pipeline via Groq                 |

## Accuracy by Question Type

| Type     | v1 (12%) | v2 (18%) | v3 (36%) | v4 no-LLM (48%) | v4-LLM (92%) | Notes                                         |
|----------|----------|----------|----------|------------------|---------------|-----------------------------------------------|
| factual  | 4/20 20% | 6/20 30% | 8/20 40% | 11/20 55%        | 20/20 100%    | LLM synthesises precise definitions from docs |
| decision | 2/20 10% | 3/20 15% | 5/20 25% | 8/20 40%         | 20/20 100%    | KIP graph + LLM reasoning = huge leap         |
| expert   | 0/10  0% | 0/10  0% | 5/10 50% | 5/10 50%         | 6/10 60%      | Hard expert questions still challenging        |

## Data Sources

| Source     | Docs  | Added       |
|------------|-------|-------------|
| jira       | 998   | Week 1      |
| git_commit | 307   | Week 1      |
| kip        | 12    | Week 2 Fix  |

## Key Learnings

- **Data > Algorithms**: Adding KIP documents improved decision coverage before
  touching retrieval architecture. The bottleneck was data coverage, not algorithm
  quality.
- **KIP impact**: KIPs contain Motivation + Rejected Alternatives — exactly what
  decision questions test. 12 KIPs cover ZooKeeper removal, Tiered Storage,
  Exactly-Once, MirrorMaker 2.0, consumer heartbeats, and more.
- **Expert gap**: Contributor attribution requires author metadata from
  commits/PRs/JIRAs mapped to topics — addressed in Week 3.
- **LLM is the multiplier**: Graph-augmented retrieval alone reached 48%. Adding
  LLM synthesis nearly doubled accuracy to 92%. The LLM doesn't just retrieve —
  it reasons over combined semantic + graph context to produce precise answers.
- **Groq + Llama 3.3 70B**: Switched from Gemini (rate-limited) to Groq's free
  tier. Llama 3.3 70B is fast (~1s latency) and highly capable for RAG tasks.

## Interview Talking Points

> "I measured improvement systematically across five versions. Each architectural
> change produced measurable gains: KIP data (+6pp), semantic search (+18pp),
> Neo4j graph retrieval (+12pp), and LLM synthesis (+44pp). The final system
> achieves 92% accuracy on a 50-question eval set covering factual, decision,
> and expert-identification questions — up from 12% baseline. That's 7.7×
> improvement through systematic engineering."

## Score Progression (50-question eval, threshold 0.5)

```
12% ──► 18% ──► 36% ──► 48% ──► 92%
  +KIPs   +Semantic  +Graph    +LLM (Llama 3.3 70B)
```
