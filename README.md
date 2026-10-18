### Judge demo (3–5 minute flow)
1. Open the app and select a repository.
2. Check the coverage panel; counts should appear only after a live repository/graph selection.
3. Open the PR Explorer and use the page-size selector + search box.
4. Select a PR and run Analyze.
5. Confirm the top reviewer appears above the fold with graph evidence and a path.
6. Open the MCP tool panel and run rank_reviewers + explain_path.
7. Run one safe Cypher query (read-only, bounded LIMIT).
8. Approve a SHADOW or DRY_RUN action and confirm the label is shown clearly.

---

# Keystone

A graph-powered pull-request reviewer-routing and knowledge-risk application built on **FastAPI**, **FalkorDB**, and clean vanilla modern frontend technology (HTML, CSS, JavaScript).

Keystone analyzes codebases as connected data: traversing git histories, co-change topologies, and betweenness centrality to route pull requests to the best-qualified reviewers, eliminate knowledge monopolies, and explain decisions transparently.

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

