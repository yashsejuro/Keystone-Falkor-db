# Keystone

A graph-powered pull-request reviewer-routing and knowledge-risk application built on **FastAPI**, **FalkorDB**, and clean vanilla modern frontend technology (HTML, CSS, JavaScript).

Keystone analyzes codebases as connected data: traversing git histories, co-change topologies, and betweenness centrality to route pull requests to the best-qualified reviewers, eliminate knowledge monopolies, and explain decisions transparently.

---

## Judge Demo (3–5 Minute Flow)

```markdown
1. Select repo (e.g., pydantic) -> Observe live 4-tier Repository Coverage Panel.
2. Open "PR Explorer" -> Search, filter, and paginate without arbitrary truncation.
3. Select any PR and click "Analyze PR" -> Receive FalkorDB graph-backed candidate ranking.
4. Inspect "Evidence" tab -> See explain_path evidence, file overlaps, and interactive subgraph.
5. Demonstrate graph algorithm -> View betweenness centrality in Repository Health.
6. Run MCP tool -> keystone:rank_reviewers returns identical graph-scored candidate rankings.
7. Run preset Cypher query -> Confirm read-only guard, bounding LIMIT, and fast graph traversal.
8. Dispatch action -> Record a clearly labeled DRY_RUN or SHADOW entry in the Action Ledger.
Credentials: FALKOR_HOST, FALKOR_PORT, FALKOR_USER, FALKOR_PASS; GITHUB_TOKEN optional (required for live sync).
```

---

## The Primary User Journey

Keystone is organized around an intuitive 8-step journey across 3 focused application sections:

1. **Connect or select a repository** — Choose from registered codebases or connect any GitHub repository (`owner/name`).
2. **Monitor ingestion & freshness** — View real-time ingestion progress, graph telemetry, and data provenance.
3. **Select a pull request** — Browse PRs using debounced search and filters (All, Reviewed, Unreviewed, High Risk).
4. **Analyze the pull request** — Trigger deterministic, non-blocking graph reasoning.
5. **See recommended reviewers** — View primary and secondary reviewer candidates with composite scores.
6. **Understand why they were selected** — Read clear, human-readable justifications and risk flags.
7. **Inspect graph evidence** — Explore direct file overlaps, review history, co-change bridges, and an interactive light-theme subgraph.
8. **Approve a clearly labeled action** — Dispatch actions under explicit approval gates: `DRY_RUN`, `SHADOW`, or `LIVE`.

---

## Application Structure (3 Primary Sections)

### Section 1: Review Routing (Default Landing)
- **Repository Context Bar**: Switch between registered repositories or initiate a new connection.
- **Searchable PR Selector**: Paginated pull request browser with instant debounced search and status filters.
- **Reviewer Recommendations**:
  - **Primary Reviewer**: Prominently highlights the top graph-scored candidate, shared file count, recent reviews, coverage %, and clear bulleted reasoning.
  - **Secondary Reviewer**: Suggests an alternative candidate for backup and knowledge-sharing.
- **Risk Summary**: Surfaces architectural blast radius, bus-factor coverage gaps, and stale reviewer warnings.
- **Action Approval Gate**: Approves actions with explicit mode selection (`DRY_RUN`, `SHADOW`, `LIVE`).

### Section 2: Evidence
- **Narrative Explanation**: Plain-language justification explaining candidate selection.
- **Direct File Overlap**: Table of files changed in the PR that the candidate previously reviewed.
- **Co-Change Bridges**: Bridge files traversed on the `CO_CHANGES` graph to connect candidates who have reviewed related modules.
- **Shortest Path**: Step-by-step visual chain from PR to candidate reviewer.
- **Interactive Knowledge Subgraph**: High-contrast Vis.js network visualization with zoom, fit, and reset controls.

### Section 3: Repository Health & Ingestion
- **Repository Connection & Ingestion Panel**: Start background ingestion for any GitHub repository with live progress tracking, cancel, and retry capabilities.
- **Graph Freshness & Provenance**: Live node, edge, PR, and scored file counts with recorded GitHub API provenance.
- **Centrality Architecture**: Status (`current`, `stale`, or `unavailable`) and manual materialization trigger.
- **Bus-Factor Analysis**: Files where a single reviewer performed >60% of reviews (monopoly bottleneck risk).
- **Action Audit Ledger**: Server-side filtered and paginated audit history distinguishing simulation, shadow, and live execution.
- **Benchmark Validation**: Top-1 and Top-3 accuracy metrics compared against relational baselines.

---

## Design System (Light Theme)

Keystone features a focused, readable light theme designed for low cognitive load and clear visual hierarchy:

- **Application background**: `#F8FAFC`
- **Card background**: `#FFFFFF`
- **Primary text**: `#0F172A`
- **Secondary text**: `#475569`
- **Muted text**: `#64748B`
- **Border**: `#E2E8F0`
- **Primary accent**: `#2563EB`
- **Secondary accent**: `#4F46E5`
- **Success**: `#16A34A`
- **Warning**: `#D97706`
- **Danger**: `#DC2626`

---

## Architecture & Performance Enhancements

- **Non-blocking Event Loop**: All synchronous FalkorDB queries, external GitHub calls, and LLM operations execute via threadpools (`run_in_threadpool`), preventing event loop starvation.
- **Deduplicated Investigation**: Single-pass data gathering in `run_keystone()` completely eliminates redundant calls to `get_pr`, `pr_criticality`, `bus_factor_files`, and duplicate `explain_path`.
- **Precomputed Centrality**: Normal API queries read precomputed `File.centrality` values rather than executing expensive `CALL algo.betweenness` at request time.
- **Server-Side PR Pagination**: PRs are paginated and filtered directly in Cypher with parameterization and database indexes.
- **Cypher Security Guard**: Protects `/api/cypher` by enforcing read-only constraints, rejecting mutation keywords (`CREATE`, `MERGE`, `DELETE`, `SET`), blocking heavy algorithm procedures, restricting traversal hops, and enforcing row limits.
- **Metadata Caching**: Short-lived thread-safe TTL cache (`METADATA_CACHE`) for status endpoints with invalidation upon ingestion.

---

## Setup & Running Locally

### 1. Requirements
- Python 3.11, 3.12, or 3.13
- A running FalkorDB instance (local or FalkorDB Cloud)
- (Optional) GitHub Personal Access Token (for repository ingestion and live actions)

### 2. Configuration (`.env`)
Copy the example environment configuration:

```bash
cp .env.example .env
```

Populate the database credentials in `.env`:

```ini
FALKOR_HOST=your-falkordb-host
FALKOR_PORT=6379
FALKOR_USER=
FALKOR_PASS=your-falkordb-password
GITHUB_TOKEN=your-github-token

# Optional action dispatch settings
KEYSTONE_WRITE_REPOS=owner/repo
KEYSTONE_SANDBOX_REPO=yashsejuro/keystone-sandbox
```

### 3. Install Dependencies & Launch

```bash
# Create virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Start the application
python app.py
```

The application will be live at: **`http://localhost:3000`**

---

## Repository Ingestion Workflow

To ingest a new repository:

1. Navigate to **3. Repository Health** in the application.
2. Under **Connect and Ingest GitHub Repository**, enter the repository slug in `owner/name` format (e.g. `fastapi/fastapi`).
3. Select your target PR limit (e.g., 50, 100, 250, 500).
4. Click **Connect & Ingest**.
5. The background worker will:
   - Validate repository existence on GitHub.
   - Register a collision-safe graph name (`keystone_{owner}_{name}_{hash}`).
   - Create indexes on `(:Person.login)`, `(:PullRequest.number)`, and `(:File.path)`.
   - Paginate merged pull requests, changed files, and reviews.
   - Bulk-insert nodes and relationships using Cypher `UNWIND`.
   - Record ingestion provenance metadata.
   - Automatically compute and store `File.centrality` post-ingest.
   - Invalidate metadata caches.

Ingestion is **manual on demand** (not continuously streaming), **resumable**, and **idempotent**.

---

## Action Execution Modes

Keystone distinguishes four clear execution states:

| Mode | Behavior | Upstream Notification |
|:-----|:---------|:----------------------|
| `DRY_RUN` | Simulated locally. No network calls. | None |
| `SHADOW` | Logged into tracking sandbox issue. Usernames formatted as code. | None |
| `LIVE` | Dispatched to GitHub API (`requested_reviewers` / `labels`). Requires confirmation and repo whitelist in `KEYSTONE_WRITE_REPOS`. | Yes (upstream assignees) |
| `FAILED` | Recorded when authorization or network dispatch fails. | None |

---

## Running Automated Tests

Keystone includes a comprehensive automated test suite covering validation, Cypher security, action ledgers, ingestion, centrality, and API integration:

```bash
# Run the complete test suite
pytest tests/ -v
```

All tests use mocks for external services and do not require real database or GitHub credentials.

---

## Running Benchmarks

To reproduce backtest accuracy numbers comparing graph-based scoring against relational baselines:

```bash
python backtest.py
```

Results are saved to `benchmark_results.json` and served truthfully by `/api/benchmark`.

---

## Known Limitations & Production Recommendations

1. **Ingestion Scheduling**: Ingestion is triggered via user request or API call. For continuous ingestion, deploy an external cron job or GitHub webhook listener that calls `POST /api/ingest`.
2. **GitHub Rate Limits**: Unauthenticated GitHub API calls are limited to 60 req/hr. Always configure `GITHUB_TOKEN` in `.env` to receive 5,000 req/hr.
3. **In-Process Job Manager**: The current job manager runs in background threads within the application process. For multi-instance clustered deployments, use Redis or Celery to coordinate background jobs.
4. **HTTPS in Production**: When deploying publicly, host behind a reverse proxy (e.g. Nginx or Cloudflare) with HTTPS enabled and configure basic authentication or OAuth for admin routes.