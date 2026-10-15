# Keystone

A knowledge-risk and reviewer-routing agent for codebases, built on FalkorDB.
It fires on PR events, decides using graph algorithms as tools, and explains
every answer as a highlighted subgraph path.

## Why graphs

FalkorDB's own hackathon page asks *"who knows about this system?"* — Keystone
is the agent that answers it, and then acts on the answer.

## What it does

Given a PR number, Keystone:
1. Finds every file the PR touches
2. Walks backward through the graph: files → past PRs → reviewers
3. Runs graph algorithms (betweenness, shortest path) as agent-callable tools
4. Scores candidates deterministically on shared files, recency, and overload
5. Flags bus-factor-1 files the PR touches (files where one person did >60%
   of reviews in the last 90 days)
6. Proposes actions (request review, add risk label) with an approval gate
7. Renders the decision as a highlighted subgraph path

## Backtest

The graph scorer is evaluated against three baselines on a 90-day time-based
split with zero leakage. Test set: 60 PRs merged after the cutoff, each with
at least one human reviewer.

| method | top-1 | top-3 |
|---|---|---|
| baseline_frequent | 40.0% | 73.3% |
| baseline_directory | 21.7% | 46.7% |
| vector_only | 21.7% | 46.7% |
| **graph_scorer** | **51.7%** | 63.3% |

**The graph scorer beats the strongest baseline by 12 points on top-1**, which
is the metric that matters for real use. It loses top-3 to a degenerate
baseline that returns the same three names on every PR.

The advantage concentrates where the problem is hardest:

- **Cross-module PRs (n=42):** graph_scorer 54.8% vs baseline 28.6% — 26 points
- **Single-file PRs (n=18):** baseline 66.7% vs graph_scorer 44.4% — baseline wins

On single-file PRs, "whoever always reviews this file" wins. On cross-module
PRs — where knowledge is distributed across people and files — the graph wins
by a wide margin. This is calibrated honesty, not cherry-picking.

## Graph schema

Nodes: Person, PullRequest, File
Edges:
- (Person)-[:AUTHORED]->(PullRequest)
- (Person)-[:REVIEWED {at, state}]->(PullRequest)
- (PullRequest)-[:TOUCHES]->(File)
- (File)-[:CO_CHANGES {weight}]-(File)

## Graph algorithms used

- `algo.betweenness.stream('File', 'CO_CHANGES')` — critical file ranking
- `shortestPath()` — explainability path from PR files to a candidate
- Recursive relationship traversal — multi-hop reviewer candidates

## Local setup

    pip install -r requirements.txt
    # set FALKOR_HOST, FALKOR_PORT, FALKOR_USER, FALKOR_PASS, GITHUB_TOKEN in .env
    python ingest.py       # one-time: ingest ~500 merged PRs from pydantic/pydantic
    streamlit run app.py

## Deployment

Streamlit app connects to FalkorDB Cloud.

## AI usage disclosure

No LLM runs in the decision path. The reviewer score is deterministic Python
and Cypher.
## Demo

[SCREENSHOT HERE — the localhost view of PR 13997]

The output above shows:
- 4-step plan trace
- davidhewitt ranked first (score 0.93, shared 3 files, 6 recent reviews)
- Two bus-factor files flagged as coverage gaps
- 4 proposed actions behind an approval gate
- Explainability path: 4 files shared between PR #13997 and davidhewitt