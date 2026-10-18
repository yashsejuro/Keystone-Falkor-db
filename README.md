## Quick Start (10 seconds)

Elevator pitch (10s)
Keystone automatically routes pull requests to the best reviewers by querying a live FalkorDB graph (PR → File → REVIEWED → Reviewer) and producing a transparent score, an explainable graph path, and safe, auditable actions (DRY_RUN / SHADOW / LIVE).

Why this is unique (say this in one line)

- Real graph-first reasoning: recommendations come from FalkorDB PR, File, REVIEWED, TOUCHES and CO_CHANGES relationships — no hard-coded reviewers or demo fallbacks.
- Explainable evidence: every suggestion includes a visible shortest-path and file overlap evidence plus centrality-based risk signals.
- Same logic exposed to users and MCP tools: the web UI, MCP rank_reviewers, and explain_path all use identical graph-backed code.
- Safe operations: Cypher explorer is read-only and bounded; LIVE actions require explicit confirmation and repo whitelist.

What to show (assets to include in the repo and present to judges)

- assets/graph-overview.png — simple diagram of nodes & relationships (alt: "Graph map: PR → File → Person relationships")
- assets/demo-landing.png — screenshot of landing page with coverage panel (alt: "Landing page with repository coverage")
- assets/recommendation.png — screenshot showing reviewer, score, and evidence (alt: "Recommended reviewer with score and evidence")
- assets/graph-path.png — screenshot of the shortest path / Vis.js view (alt: "Shortest path from PR to reviewer")
- assets/mcp-output.png — screenshot of MCP rank_reviewers output (alt: "MCP rank_reviewers result")
- assets/cypher-result.png — screenshot of a safe Cypher query result (alt: "Cypher read-only result")
- assets/action-ledger.png — screenshot showing SHADOW or DRY_RUN ledger entry (alt: "Action ledger showing shadow mode")
- demo/video.mp4 or a short hosted video link (30–60s) showing the flow end-to-end

Minimal graph map (Mermaid) — render or export as PNG and add to assets/graph-overview.png:

```mermaid
graph LR
  PR[PullRequest] -->|TOUCHES| File[File]
  PR -->|AUTHORED_BY| Author[Person]
  Person -->|REVIEWED| PR
  File -->|CO_CHANGES| File2[File]
  File2 -->|REVIEWED_IN| PR2[PullRequest]
  PR2 -->|REVIEWED_BY| Reviewer[Person]
