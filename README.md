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

### Windows: one-click launch

1. Install stable Python 3.11, 3.12, or 3.13 once from https://www.python.org/downloads/.
2. Double-click `run_keystone.bat`.

The launcher creates a local virtual environment, installs dependencies, creates
`.env` from `.env.example` when needed, opens the browser, and starts Keystone.
On the first run, add `FALKOR_HOST`, `FALKOR_PORT`, `FALKOR_USER`,
`FALKOR_PASS`, and optionally `GITHUB_TOKEN` to `.env`, then double-click the
launcher again. Later runs reuse the existing environment.

### Ingest a repository from the UI

On the welcome screen, use **Connect real repository data**:

1. Paste a GitHub repository URL, for example `https://github.com/pydantic/pydantic`.
2. Choose how many merged PRs to import.
3. Click **Connect and ingest real PRs**.

Keystone fetches merged pull requests, changed files, authors, and submitted
reviews from the GitHub API. Ingestion runs in the background, skips PRs already
in the graph, and records a provenance marker containing the source repository
and import time. No synthetic PRs or reviewer records are created.

The current pre-existing graphs contain real connected FalkorDB data, but their
original ingestion source was not recorded. The UI labels them **Existing data,
source unmarked** rather than claiming they are newly imported or demo data.

### Terminal launch

    pip install -r requirements.txt
    # set FALKOR_HOST, FALKOR_PORT, FALKOR_USER, FALKOR_PASS, GITHUB_TOKEN in .env
    python app.py

### Connect MCP without editing JSON

When Keystone is running, its MCP tools are available over Streamable HTTP at:

    http://localhost:3000/mcp

Use the **Connect MCP** link in the navbar, then click **Connect to Claude**.
Keystone starts a temporary Cloudflare HTTPS tunnel and displays the complete
public URL, including `/mcp`, for copying into Claude's custom connector.
Users do not need to find or run a batch file.

The automatic tunnel is for demos and is not a 10-day service. For a stable
connection, create a Cloudflare named tunnel once, point it at Keystone, and set
`CLOUDFLARED_TUNNEL_TOKEN` plus `MCP_PUBLIC_URL` in `.env`. The same **Connect
to Claude** button will then start the named tunnel and return the stable URL.
For a real team deployment, run Keystone on a hosted machine with HTTPS and
authentication rather than exposing a personal laptop.

The existing `mcp_server.py` stdio entrypoint remains available for clients that
require local process configuration.

## Deployment

The FastAPI app connects to FalkorDB Cloud.

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