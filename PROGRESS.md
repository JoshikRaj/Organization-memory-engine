# Benchmark Progress Log

This file tracks the measurable improvement of the Organization Memory Engine
across each development phase. Accuracy = % of 50 eval questions answered correctly
(similarity_score >= 0.5 threshold).

| Date       | Version | Method                          | Accuracy | Correct/50 | Notes                                      |
|------------|---------|---------------------------------|----------|------------|--------------------------------------------|
| Week 2 Day 5 | v1    | Keyword search, no KIPs         | 12%      | 6/50       | Baseline — jira + git_commit only          |
| Week 2 Fix   | v2    | Keyword search + KIP data       | 18%      | 9/50       | After KIP ingestion (12 KIPs, 1317 docs)   |
| Week 3       | v3    | Semantic search (pgvector + KIP boost) | 36%      | 18/50      | After vector similarity retrieval          |
| Week 4       | v4    | Semantic + Neo4j graph (no LLM) | 48%      | 24/50      | Graph context fallback; LLM target: 65%+   |

## Accuracy by Question Type

| Type     | v1 (12%) | v2 (18%) | v3 (36%) | v4 (48%, no LLM) | Notes                                         |
|----------|----------|----------|----------|------------------|-----------------------------------------------|
| factual  | 4/20 20% | 6/20 30% | 8/20 40% | 11/20 55%        | Graph adds KIP context for how/why questions  |
| decision | 2/20 10% | 3/20 15% | 5/20 25% | 8/20 40%         | KIP-500/KIP-98 now surface via graph traversal|
| expert   | 0/10  0% | 0/10  0% | 5/10 50% | 5/10 50%         | Graph expert names in fallback answer string  |

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

## Interview Talking Points

> "I measured improvement systematically across four versions. Adding KIP documents
> alone moved accuracy from 12% to 18% — before I touched the retrieval layer at all.
> That told me the bottleneck was data coverage, not algorithm quality. Only after
> fixing the data did I move to semantic search (+18pp) and graph-augmented retrieval
> (+12pp). Each improvement was measurable and explained — that's the engineering rigor."

## Score Progression (50-question eval, threshold 0.5)

```
12% ──► 18% ──► 36% ──► 48% ──► [65%+ target with LLM]
  +KIPs   +Semantic  +Graph     +LLM synthesis
```
