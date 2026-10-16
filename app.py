"""Keystone — Knowledge-risk and reviewer-routing agent built on FalkorDB.
Multi-graph aware. Deterministic graph scoring with human approval gate.
"""
import os
import uuid
import json
from datetime import datetime, timezone
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from graph_client import (
    node_count, edge_count, get_connection_status, get_graph,
    list_repos, DEFAULT_REPO, REPOS, REPO_SLUGS, graph_provenance,
    validate_repo, is_valid_repo
)
from agent import run_keystone, plan
from tools import (
    get_pr, explain_path, bus_factor_files, critical_files,
    default_cutoff, reviewer_candidates, graph_stats, sample_pr,
    list_recent_prs, pr_criticality
)
from scoring import score_reviewers
from mcp_server import mcp as keystone_mcp

try:
    from narration import narrate
except Exception:
    def narrate(decision, pr):
        return decision.get("rationale", "")

app = FastAPI(title="Keystone", description="Graph-based PR Reviewer Routing & Knowledge Risk Agent")

# Action Audit Ledger for verified actions
ACTION_LEDGER: list[dict] = []
WRITE_REPOS_CONFIG = os.getenv("KEYSTONE_WRITE_REPOS", "").strip()
ALLOWED_WRITE_REPOS = [r.strip().lower() for r in WRITE_REPOS_CONFIG.split(",") if r.strip()]
SANDBOX_REPO = os.getenv("KEYSTONE_SANDBOX_REPO", "yashsejuro/keystone-sandbox").strip()

# Mount FastMCP HTTP app at /mcp for external MCP clients
try:
    mcp_sub = keystone_mcp.http_app(path="/")
    app.mount("/mcp", mcp_sub)
except Exception:
    pass

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Keystone — Graph-Powered PR Reviewer Routing & Knowledge Risk</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    :root {
      color-scheme: dark;
      --bg-0: #020617;
      --bg-1: #0b1220;
      --bg-2: #0f172a;
      --line: #1e293b;
      --line-strong: #334155;
      --text-main: #e2e8f0;
      --text-muted: #94a3b8;
      --brand: #6366f1;
      --brand-soft: #312e81;
      --ok: #22c55e;
      --warn: #f59e0b;
      --danger: #f43f5e;
    }
    body { font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif; background: radial-gradient(1200px 500px at 10% -10%, #1e1b4b 0%, transparent 55%), var(--bg-0); color: var(--text-main); }
    code, pre, .font-mono { font-family: 'JetBrains Mono', monospace; }
    #network-canvas { width: 100%; height: 460px; background-color: #030712; border-radius: 0.75rem; }
    details summary { cursor: pointer; list-style: none; }
    details summary::-webkit-details-marker { display: none; }
    button:focus-visible, input:focus-visible, select:focus-visible, textarea:focus-visible, a:focus-visible {
      outline: 2px solid #818cf8;
      outline-offset: 2px;
    }
    .surface { background: linear-gradient(180deg, rgba(15, 23, 42, 0.95), rgba(2, 6, 23, 0.95)); border: 1px solid var(--line); border-radius: 0.9rem; }
    .muted { color: var(--text-muted); }
    .hidden-visually { position: absolute; left: -9999px; top: auto; width: 1px; height: 1px; overflow: hidden; }
    .hidden-visually:focus { left: 1rem; top: 1rem; width: auto; height: auto; z-index: 100; padding: 0.5rem 0.75rem; background: #111827; border-radius: 0.5rem; border: 1px solid #4f46e5; color: #fff; }
    #toast-region { position: fixed; right: 1rem; bottom: 1rem; z-index: 60; display: flex; flex-direction: column; gap: 0.5rem; max-width: 24rem; }
    .toast { border-radius: 0.75rem; padding: 0.75rem 0.875rem; border: 1px solid var(--line-strong); background: #111827; color: #e2e8f0; font-size: 0.75rem; box-shadow: 0 10px 20px rgba(2, 6, 23, 0.5); }
    .toast.error { border-color: #7f1d1d; background: #2b1118; color: #fecdd3; }
    .toast.success { border-color: #14532d; background: #052e1f; color: #bbf7d0; }
    /* Sleek scrollbar */
    ::-webkit-scrollbar { width: 6px; height: 6px; }
    ::-webkit-scrollbar-track { background: #030712; }
    ::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 3px; }
    ::-webkit-scrollbar-thumb:hover { background: #334155; }
  </style>
</head>
<body class="text-slate-100 min-h-screen flex flex-col antialiased">
  <a class="hidden-visually" href="#main-content">Skip to main content</a>

  <header class="border-b border-slate-800/80 bg-slate-950/90 backdrop-blur sticky top-0 z-30 px-4 sm:px-6 py-3">
    <div class="max-w-7xl mx-auto flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-lg bg-indigo-600/20 border border-indigo-500/40 flex items-center justify-center text-indigo-300 font-bold text-base shadow-sm">
          K
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <span class="font-bold text-base text-white tracking-tight">Keystone</span>
            <span class="text-[11px] font-mono text-indigo-300 bg-indigo-950/60 border border-indigo-800/60 px-2 py-0.5 rounded">Graph PR copilot</span>
          </div>
          <p class="text-[11px] text-slate-400">Find the right reviewers, surface risk early, and keep PRs moving.</p>
        </div>
      </div>

      <div class="flex items-center space-x-3">
        <div class="flex items-center space-x-2 text-xs bg-slate-950 border border-slate-800 px-3 py-1.5 rounded-lg shadow-sm">
          <span class="text-slate-400 font-medium">Repository:</span>
          <select aria-label="Select repository" id="repo-select" onchange="onRepoChange(this.value)"
                  class="font-mono font-semibold text-indigo-300 bg-transparent focus:outline-none cursor-pointer">
            <option value="pydantic">pydantic (1,309 nodes)</option>
            <option value="fastapi">fastapi (active graph)</option>
          </select>
        </div>

        <div id="conn-pill" class="flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-950/40 border border-emerald-800/50 text-emerald-300">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span id="conn-text">FalkorDB Connected</span>
        </div>
      </div>
    </div>
  </header>

  <main id="main-content" class="max-w-7xl mx-auto px-4 sm:px-6 py-5 flex-1 w-full grid grid-cols-1 lg:grid-cols-12 gap-6">

    <div class="lg:col-span-4 space-y-4">
      <section class="surface p-5 space-y-3">
        <p class="text-[10px] uppercase tracking-[0.16em] text-indigo-300 font-semibold">Overview</p>
        <h1 class="text-lg font-semibold text-white">Production-ready reviewer routing for GitHub pull requests</h1>
        <p class="text-xs text-slate-400">Use real graph data to pick reviewers, explain the recommendation, and approve actions with a full audit trail.</p>
        <div class="grid grid-cols-2 gap-2 text-xs">
          <button onclick="switchTab('decision')" class="px-3 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-lg text-left">Start with routing</button>
          <button onclick="switchTab('health')" class="px-3 py-2 bg-slate-800 hover:bg-slate-700 text-slate-100 rounded-lg text-left">View risk signals</button>
        </div>
      </section>

      <div class="surface p-5 shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-xs font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-1.5">
            <span>Select Pull Request</span>
          </h2>
          <span class="text-[10px] text-emerald-400 font-mono" id="pr-feed-count">Loading PRs...</span>
        </div>

        <div>
          <label for="pr-select" class="block text-xs font-medium text-slate-400 mb-1">Target pull request</label>
          <select id="pr-select" onchange="onSelectPrFromDropdown(this.value)"
                  class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3 py-2 text-xs text-indigo-300 font-mono focus:outline-none focus:border-indigo-500 truncate cursor-pointer">
            <option value="13997">#13997: Support explicit by_alias</option>
          </select>
        </div>

        <!-- Manual PR Input -->
        <div>
          <label for="pr-input" class="block text-xs font-medium text-slate-400 mb-1">Or enter PR number</label>
          <div class="flex gap-2">
            <input type="number" id="pr-input" value="13997" min="1"
                   class="flex-1 bg-slate-950 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-white focus:outline-none focus:border-indigo-500 font-mono font-semibold">
            <button onclick="runInvestigation()" class="px-3.5 py-1.5 bg-slate-800 hover:bg-slate-700 text-xs text-white rounded-lg transition font-medium cursor-pointer">
              Analyze
            </button>
          </div>
        </div>

        <div>
          <button id="run-btn" onclick="runInvestigation()"
                  class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 px-4 rounded-lg text-xs shadow-md transition flex items-center justify-center space-x-2 cursor-pointer">
            <span id="btn-icon">🚀</span>
            <span id="btn-label">Run Knowledge Analysis</span>
          </button>
        </div>

        <!-- Benchmark Presets -->
        <div class="pt-3 border-t border-slate-800">
          <div class="flex items-center justify-between mb-2">
            <label class="text-xs font-medium text-slate-400">Quick benchmark PRs:</label>
            <span id="preset-repo-tag" class="text-[10px] font-mono text-indigo-400">pydantic</span>
          </div>
          <div id="benchmark-buttons-container" class="grid grid-cols-2 gap-2 text-xs">
            <!-- Dynamically populated -->
          </div>
        </div>
      </div>

      <div class="surface p-5 shadow-sm space-y-3.5">
        <div class="flex items-center justify-between">
          <h2 class="text-xs font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-1.5">
            <span>📊</span>
            <span>PR Impact Telemetry</span>
          </h2>
          <span id="blast-badge" class="text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/60 text-amber-300 border border-amber-800/60">
            High Impact
          </span>
        </div>

        <div class="grid grid-cols-2 gap-2.5">
          <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3">
            <div class="text-[11px] text-slate-400">Code Churn</div>
            <div id="stat-churn" class="text-base font-bold font-mono text-white mt-0.5">+74 / -15</div>
            <div id="stat-files-count" class="text-[10px] text-slate-500 mt-0.5">4 files touched</div>
          </div>
          <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3">
            <div class="text-[11px] text-slate-400">Blast Radius</div>
            <div id="stat-blast-text" class="text-base font-bold font-mono text-amber-400 mt-0.5">0.486 peak</div>
            <div class="text-[10px] text-slate-500 mt-0.5">betweenness centrality</div>
          </div>
        </div>

        <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 space-y-1.5 text-xs">
          <div class="flex items-center justify-between text-slate-400">
            <span>Bus Factor Exposure:</span>
            <span id="stat-bf-exposure" class="font-mono font-semibold text-rose-400">2 files flagged</span>
          </div>
          <div class="flex items-center justify-between text-slate-400">
            <span>Candidate Reviewers:</span>
            <span id="stat-pool-depth" class="font-mono font-semibold text-indigo-300">9 evaluated</span>
          </div>
          <div class="flex items-center justify-between text-slate-400">
            <span>Knowledge Distribution:</span>
            <span id="stat-coverage-rate" class="font-mono font-semibold text-emerald-400">75% top match</span>
          </div>
        </div>

        <div class="text-[11px] text-slate-500 italic pt-1">
          Identifies architectural risk & reviewer knowledge gaps before merge.
        </div>
      </div>

    </div>

    <!-- Right Column: Tabs (8 cols) -->
    <div class="lg:col-span-8 space-y-4">

      <!-- Navigation Tabs -->
      <div role="tablist" aria-label="Keystone views" class="flex border-b border-slate-800 space-x-1 overflow-x-auto text-xs sm:text-sm">
        <button role="tab" aria-selected="true" aria-controls="tab-decision" onclick="switchTab('decision')" id="tab-btn-decision" class="px-3.5 py-2.5 font-medium border-b-2 border-indigo-500 text-indigo-400 whitespace-nowrap cursor-pointer">
          🎯 Review Routing & Actions
        </button>
        <button role="tab" aria-selected="false" aria-controls="tab-explain" onclick="switchTab('explain')" id="tab-btn-explain" class="px-3.5 py-2.5 font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap cursor-pointer">
          🗺️ Multi-Hop Traversal
        </button>
        <button role="tab" aria-selected="false" aria-controls="tab-network" onclick="switchTab('network')" id="tab-btn-network" class="px-3.5 py-2.5 font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap cursor-pointer">
          🕸️ Graph Subgraph
        </button>
        <button role="tab" aria-selected="false" aria-controls="tab-health" onclick="switchTab('health')" id="tab-btn-health" class="px-3.5 py-2.5 font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap cursor-pointer">
          📈 Codebase Knowledge Health
        </button>
        <button role="tab" aria-selected="false" aria-controls="tab-ledger" onclick="switchTab('ledger')" id="tab-btn-ledger" class="px-3.5 py-2.5 font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap cursor-pointer flex items-center space-x-1.5">
          <span>📜 Action Ledger</span>
          <span id="ledger-badge" class="px-1.5 py-0.2 rounded bg-indigo-900/80 text-indigo-300 text-[10px] font-mono">0</span>
        </button>
        <button role="tab" aria-selected="false" aria-controls="tab-diagnostics" onclick="switchTab('diagnostics')" id="tab-btn-diagnostics" class="px-3.5 py-2.5 font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap cursor-pointer">
          🔧 Diagnostic Console
        </button>
      </div>

      <!-- Tab 1: Decision & Actions -->
      <div id="tab-decision" role="tabpanel" class="space-y-4">

        <!-- PR Details Header -->
        <div id="pr-card" class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
          <div class="flex items-start justify-between">
            <div>
              <div class="flex items-center space-x-2">
                <span id="pr-badge-num" class="font-mono text-xs px-2.5 py-0.5 rounded bg-indigo-900/60 border border-indigo-700/60 text-indigo-300 font-semibold">PR #13997</span>
                <span id="pr-badge-state" class="text-xs px-2 py-0.5 rounded bg-emerald-900/60 border border-emerald-700/60 text-emerald-300 font-medium">MERGED</span>
                <span id="pr-repo-indicator" class="text-xs text-slate-400 font-mono">pydantic</span>
              </div>
              <h3 id="pr-title" class="text-base font-semibold text-white mt-1.5">Loading PR details...</h3>
              <p class="text-xs text-slate-400 mt-1">
                Author: <span id="pr-author" class="font-mono text-slate-200 font-medium">...</span> &middot;
                Files: <span id="pr-files-count" class="font-mono text-slate-200">...</span> &middot;
                Lines: <span id="pr-lines-changed" class="font-mono text-slate-300">...</span>
              </p>
            </div>
          </div>
          
          <!-- Detailed File Breakdown with Coverage Tagging -->
          <div>
            <div class="text-[11px] font-medium text-slate-400 mb-1.5">Touched Files & Reviewer Context:</div>
            <div id="pr-files-list" class="flex flex-wrap gap-1.5"></div>
          </div>
        </div>

        <!-- Reviewer Pairing Recommendation Card -->
        <div class="border border-indigo-700/50 bg-indigo-950/20 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <span class="text-[10px] uppercase font-bold tracking-wider text-indigo-400">Recommended Routing Strategy</span>
              <h3 class="text-base font-bold text-white mt-0.5">Optimal Dual-Reviewer Pairing</h3>
            </div>
            <span class="text-xs font-mono px-2.5 py-1 rounded bg-indigo-900/60 text-indigo-300 border border-indigo-700/60">
              Deterministic Graph Selection
            </span>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4" id="pairing-container">
            <!-- Dynamically populated with Primary and Secondary Reviewer -->
          </div>

          <p id="rationale-text" class="text-xs text-indigo-200/90 italic bg-indigo-950/40 p-3 rounded-lg border border-indigo-800/40"></p>
        </div>

        <!-- Knowledge Risk Flags Alert -->
        <div id="risk-container" class="space-y-2"></div>

        <!-- Ranked Candidates Table -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>👥</span>
                <span>All Evaluated Reviewer Candidates</span>
              </h3>
              <p class="text-xs text-slate-400">Scored across direct file history, structural affinity, recency, and fatigue</p>
            </div>
            <span class="text-[11px] text-slate-400 font-mono">Ranked by Score</span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="text-slate-400 border-b border-slate-800 uppercase font-semibold">
                <tr>
                  <th class="py-2 px-2.5">Rank</th>
                  <th class="py-2 px-2.5">Reviewer</th>
                  <th class="py-2 px-2.5 text-right">Graph Score</th>
                  <th class="py-2 px-2.5 text-right">Coverage</th>
                  <th class="py-2 px-2.5 text-right">Shared Files</th>
                  <th class="py-2 px-2.5 text-right">Bridge Files</th>
                  <th class="py-2 px-2.5 text-right">90d Reviews</th>
                  <th class="py-2 px-2.5">Last Active</th>
                  <th class="py-2 px-2.5 text-center">Path</th>
                </tr>
              </thead>
              <tbody id="reviewers-body" class="divide-y divide-slate-800/60 font-mono"></tbody>
            </table>
          </div>
        </div>

        <!-- Proposed Review Plan (Actions based on graph findings) -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>⚡</span>
                <span>Action Plan & Human Approval Gate</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Keystone directly acts on connected data. Approve proposed actions below to execute.</p>
            </div>
            <span class="text-xs px-2.5 py-0.5 rounded bg-amber-950/60 border border-amber-800/60 text-amber-300 font-medium">Awaiting Your Approval</span>
          </div>

          <div id="actions-container" class="space-y-2.5"></div>
          
          <div class="flex gap-3">
            <button id="apply-plan-btn" onclick="applyApprovedPlan()" class="flex-1 bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold py-2.5 rounded-lg transition cursor-pointer">
              Approve & Execute Selected Actions
            </button>
            <button onclick="switchTab('ledger')" class="px-4 bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold py-2.5 rounded-lg transition cursor-pointer">
              View Audit Ledger
            </button>
          </div>
        </div>

      </div>

      <!-- Tab 2: Explainability & Multi-Hop -->
      <div id="tab-explain" role="tabpanel" class="hidden space-y-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between flex-wrap gap-2">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>🗺️</span>
                <span>Multi-Hop Traversal Path Explainability</span>
              </h3>
              <p id="explain-header" class="text-xs text-slate-400 mt-1">Tracing how candidate connects to touched files via graph traversals</p>
            </div>
            
            <!-- Candidate Switcher Segment -->
            <div id="candidate-selector-segment" class="flex gap-1.5 bg-slate-950 p-1 rounded-lg border border-slate-800 text-xs"></div>
          </div>

          <!-- Breadcrumbs Walk -->
          <div id="graph-walk" class="bg-slate-950 border border-slate-800 rounded-lg p-5 space-y-4"></div>

          <!-- Formula Breakdown -->
          <div class="bg-slate-950 border border-slate-800/90 rounded-lg p-4 space-y-3">
            <h4 class="text-xs font-semibold text-indigo-300 uppercase tracking-wider">Deterministic Formula Components (Zero LLM Hallucination):</h4>
            <div class="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs font-mono">
              <div class="p-2.5 rounded bg-slate-900 border border-slate-800">
                <div class="text-slate-400 text-[11px]">Direct File Overlap</div>
                <div class="text-sm font-bold text-white mt-0.5">30% weight</div>
                <div class="text-slate-500 text-[10px] mt-1">Shared files / max</div>
              </div>
              <div class="p-2.5 rounded bg-slate-900 border border-slate-800">
                <div class="text-slate-400 text-[11px]">Structural Affinity</div>
                <div class="text-sm font-bold text-white mt-0.5">30% weight</div>
                <div class="text-slate-500 text-[10px] mt-1">Co-change &times; Centrality</div>
              </div>
              <div class="p-2.5 rounded bg-slate-900 border border-slate-800">
                <div class="text-slate-400 text-[11px]">Recent Activity</div>
                <div class="text-sm font-bold text-white mt-0.5">20% weight</div>
                <div class="text-slate-500 text-[10px] mt-1">90-day review count</div>
              </div>
              <div class="p-2.5 rounded bg-slate-900 border border-slate-800">
                <div class="text-slate-400 text-[11px]">Exponential Recency</div>
                <div class="text-sm font-bold text-white mt-0.5">20% weight</div>
                <div class="text-slate-500 text-[10px] mt-1">e^(-&Delta;t / 60 days)</div>
              </div>
            </div>
            <p class="text-[11px] text-slate-400 italic">Workload overload dampener applies a 0.7&times; multiplier if recent reviews &gt; 20 to protect against reviewer burnout.</p>
          </div>

          <div class="mt-4 pt-4 border-t border-slate-800">
            <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Direct Shared Files:</h4>
            <div id="explain-files" class="space-y-2"></div>
          </div>

          <div class="mt-4 pt-4 border-t border-slate-800">
            <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Structural Co-Change Bridges:</h4>
            <div id="explain-bridges" class="space-y-2"></div>
          </div>
        </div>
      </div>

      <!-- Tab 3: Graph Visualizer -->
      <div id="tab-network" role="tabpanel" class="hidden space-y-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>🕸️</span>
                <span>Interactive Subgraph Neighborhood</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Force network of PR, touched files, historical PRs, and candidate reviewers</p>
            </div>
            <div class="flex items-center space-x-2 text-[11px] font-mono">
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-indigo-500"></span><span>PR</span></span>
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-cyan-400"></span><span>File</span></span>
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-emerald-500"></span><span>Reviewer</span></span>
            </div>
          </div>

          <div id="network-canvas" class="border border-slate-800 shadow-inner"></div>

          <div id="node-inspector" class="bg-slate-950 border border-slate-800 p-3 rounded-lg text-xs hidden">
            <div class="font-semibold text-indigo-300" id="inspector-title">Node Details</div>
            <div class="text-slate-400 mt-1" id="inspector-desc"></div>
          </div>

          <div class="flex justify-between items-center text-xs text-slate-400 pt-1">
            <span>Drag nodes or scroll to zoom &middot; Powered by FalkorDB relationship discovery</span>
            <button onclick="rebuildGraphVisualization()" class="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs transition cursor-pointer">
              ↺ Reset Physics Layout
            </button>
          </div>
        </div>
      </div>

      <!-- Tab 4: Codebase Knowledge Health -->
      <div id="tab-health" role="tabpanel" class="hidden space-y-4">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-rose-300 flex items-center space-x-2">
                <span>⚠️</span>
                <span>Bus-Factor Risk Files</span>
              </h3>
              <span class="text-[11px] text-slate-500 font-mono">>60% single reviewer</span>
            </div>
            <p class="text-xs text-slate-400">Identifies files where review knowledge is concentrated in a single person.</p>
            <div id="bus-factor-list" class="space-y-2 max-h-96 overflow-y-auto pr-1"></div>
          </div>

          <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-indigo-300 flex items-center space-x-2">
                <span>🌐</span>
                <span>Critical Infrastructure Files</span>
              </h3>
              <span class="text-[11px] text-slate-500 font-mono">Betweenness Centrality</span>
            </div>
            <p class="text-xs text-slate-400">Calculates load-bearing bridge files across the repository structure.</p>
            <div id="critical-files-list" class="space-y-2 max-h-96 overflow-y-auto pr-1"></div>
          </div>
        </div>
      </div>

      <!-- Tab 5: Action Audit Ledger & Status Dashboard -->
      <div id="tab-ledger" role="tabpanel" class="hidden space-y-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-5">
          <div class="flex items-center justify-between flex-wrap gap-2">
            <div>
              <div class="flex items-center space-x-2">
                <span class="text-[10px] font-mono uppercase tracking-wider text-indigo-400 font-bold bg-indigo-950/80 px-2 py-0.5 rounded border border-indigo-800/60">Agent Impact & Dispatch</span>
                <span id="ledger-count-pill" class="text-xs px-2.5 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/60 text-emerald-300 font-mono">0 Actions</span>
              </div>
              <h3 class="text-base font-semibold text-white flex items-center space-x-2 mt-1">
                <span>Action Dispatch & Impact Dashboard</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Differentiates live repository executions from safe shadow-mode logging to prevent upstream notification spam.</p>
            </div>
            <div class="flex items-center space-x-2">
              <button onclick="clearActionLedger()" class="text-xs px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 transition cursor-pointer">Reset Ledger</button>
            </div>
          </div>

          <!-- Status Dashboard Cards: Live vs Shadow Differentiation -->
          <div class="grid grid-cols-1 sm:grid-cols-3 gap-3">
            <div class="bg-slate-950 border border-emerald-900/60 rounded-lg p-3.5 space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-semibold text-emerald-400 uppercase tracking-wider">Live Actions</span>
                <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-emerald-950 text-emerald-300 border border-emerald-800">Direct PR</span>
              </div>
              <div id="live-actions-count" class="text-2xl font-bold font-mono text-emerald-300">0</div>
              <p class="text-[11px] text-slate-400">Executed on allowed write repos with direct reviewer assignment & labels.</p>
            </div>

            <div class="bg-slate-950 border border-purple-900/60 rounded-lg p-3.5 space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-semibold text-purple-400 uppercase tracking-wider">Shadow Actions</span>
                <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-purple-950 text-purple-300 border border-purple-800">Isolated</span>
              </div>
              <div id="shadow-actions-count" class="text-2xl font-bold font-mono text-purple-300">0</div>
              <p class="text-[11px] text-slate-400">Logged to tracking issue on <span id="sandbox-repo-label" class="font-mono text-slate-300">keystone-sandbox</span> with logins as code.</p>
            </div>

            <div class="bg-slate-950 border border-slate-800 rounded-lg p-3.5 space-y-1.5">
              <div class="flex items-center justify-between">
                <span class="text-[11px] font-semibold text-indigo-400 uppercase tracking-wider">Safety Enforcement</span>
                <span class="text-[10px] font-mono px-1.5 py-0.2 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">Active</span>
              </div>
              <div class="text-xs font-mono text-slate-200 font-semibold pt-1">Zero Upstream Spam</div>
              <p class="text-[11px] text-slate-400">Upstream repositories are strictly sandboxed unless added to KEYSTONE_WRITE_REPOS.</p>
            </div>
          </div>

          <!-- Filter Controls -->
          <div class="flex items-center justify-between border-b border-slate-800 pb-2 text-xs">
            <div class="flex space-x-2">
              <button id="filter-ledger-all" onclick="filterLedger('all')" class="px-2.5 py-1 rounded bg-indigo-600 text-white font-medium cursor-pointer">All Actions</button>
              <button id="filter-ledger-live" onclick="filterLedger('LIVE')" class="px-2.5 py-1 rounded bg-slate-800 text-slate-300 hover:text-white cursor-pointer">Live Only</button>
              <button id="filter-ledger-shadow" onclick="filterLedger('SHADOW')" class="px-2.5 py-1 rounded bg-slate-800 text-slate-300 hover:text-white cursor-pointer">Shadow Only</button>
            </div>
            <span id="ledger-filter-status" class="text-slate-400 text-[11px] font-mono">Showing all entries</span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs font-mono">
              <thead class="text-slate-400 border-b border-slate-800 uppercase font-semibold">
                <tr>
                  <th class="py-2.5 px-3">Action ID</th>
                  <th class="py-2.5 px-3">Time</th>
                  <th class="py-2.5 px-3">Mode</th>
                  <th class="py-2.5 px-3">Target & PR</th>
                  <th class="py-2.5 px-3">Action</th>
                  <th class="py-2.5 px-3">Destination / Safeguard</th>
                  <th class="py-2.5 px-3">Causal Reason</th>
                  <th class="py-2.5 px-3 text-right">Status</th>
                </tr>
              </thead>
              <tbody id="ledger-table-body" class="divide-y divide-slate-800/60">
                <tr><td colspan="8" class="py-6 text-center text-slate-500 font-sans text-xs">No actions executed yet. Use the "Review Routing & Actions" tab to approve proposed actions.</td></tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>

      <!-- Tab 6: Diagnostic & Cypher Console -->
      <div id="tab-diagnostics" role="tabpanel" class="hidden space-y-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>🔧</span>
                <span>FalkorDB OpenCypher & FastMCP Console</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Run live Cypher queries and test FastMCP tool endpoints</p>
            </div>
            <span class="text-xs text-indigo-400 font-mono">OpenCypher / MCP</span>
          </div>

          <div class="flex flex-wrap gap-2 text-xs">
            <button onclick="setCypherQuery('CALL algo.betweenness({nodeLabels: [\\'File\\'], relationshipTypes: [\\'CO_CHANGES\\']}) YIELD node, score RETURN node.path, score ORDER BY score DESC LIMIT 10')" class="bg-slate-950 hover:bg-slate-800 border border-indigo-700/60 text-indigo-300 px-3 py-1.5 rounded transition cursor-pointer">
              ⚡ Betweenness Centrality
            </button>
            <button onclick="setCypherQuery('MATCH (p:Person)-[:REVIEWED]->(pr:PullRequest) WHERE p.is_bot = false RETURN p.login, count(DISTINCT pr) AS reviews ORDER BY reviews DESC LIMIT 10')" class="bg-slate-950 hover:bg-slate-800 border border-slate-800 px-3 py-1.5 rounded transition cursor-pointer">
              Top Human Reviewers
            </button>
            <button onclick="setCypherQuery('MATCH ()-[c:CO_CHANGES]->() RETURN count(c) AS co_edges, sum(c.weight) AS total_strength')" class="bg-slate-950 hover:bg-slate-800 border border-slate-800 px-3 py-1.5 rounded transition cursor-pointer">
              Co-Change Stats
            </button>
          </div>

          <div class="space-y-2">
            <textarea id="cypher-input" rows="3" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-xs font-mono text-indigo-200 focus:outline-none focus:border-indigo-500">CALL algo.betweenness({nodeLabels: ['File'], relationshipTypes: ['CO_CHANGES']}) YIELD node, score RETURN node.path, score ORDER BY score DESC LIMIT 10</textarea>
            <button onclick="executeCypher()" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-4 py-2 rounded-lg font-medium transition cursor-pointer flex items-center space-x-1.5">
              <span>⚡</span>
              <span>Execute Cypher Query</span>
            </button>
          </div>

          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
            <div class="flex items-center justify-between text-xs text-slate-400">
              <span id="cypher-status">Ready</span>
              <span id="cypher-count" class="font-mono">0 rows</span>
            </div>
            <div class="overflow-x-auto max-h-60">
              <table class="w-full text-left text-xs font-mono">
                <tbody id="cypher-table-body" class="divide-y divide-slate-800">
                  <tr><td class="text-slate-500 py-3">Run query to view results.</td></tr>
                </tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

    </div>

  </main>
  <div id="toast-region" aria-live="polite" aria-atomic="false"></div>

  <script>
    let currentResult = null;
    let networkInstance = null;
    let currentRepo = 'pydantic';
    let availablePRs = [];
    let currentSelectedCandidate = null;
    let runInProgress = false;
    let allowedWriteRepos = [];
    let sandboxRepo = 'yashsejuro/keystone-sandbox';
    let fullLedgerData = [];
    let currentLedgerFilter = 'all';

    const BENCHMARKS = {
      'pydantic': [
        { num: 13997, label: '#13997', desc: 'JSON Schema & Aliases' },
        { num: 14000, label: '#14000', desc: 'Harden CI & Base' },
        { num: 13995, label: '#13995', desc: 'JsonValue Serialization' },
        { num: 13989, label: '#13989', desc: 'Root Model Copy' },
      ],
      'fastapi': [
        { num: 16503, label: '#16503', desc: 'Frontend fallback checks' },
        { num: 16504, label: '#16504', desc: 'Release version 0.143.2' },
        { num: 16487, label: '#16487', desc: 'Bump pydantic-ai-slim' },
        { num: 16049, label: '#16049', desc: 'Core routing & deps' },
      ]
    };

    function notify(message, variant = 'default') {
      const region = document.getElementById('toast-region');
      if (!region) return;
      const el = document.createElement('div');
      el.className = `toast ${variant}`;
      el.setAttribute('role', 'status');
      el.innerText = message;
      region.appendChild(el);
      setTimeout(() => {
        el.remove();
      }, 4000);
    }

    function setRunButtonState(isBusy, labelText = "Run Knowledge Analysis", iconText = "🚀") {
      const btn = document.getElementById('run-btn');
      const icon = document.getElementById('btn-icon');
      const label = document.getElementById('btn-label');
      if (!btn || !icon || !label) return;
      btn.disabled = isBusy;
      btn.setAttribute('aria-busy', isBusy ? 'true' : 'false');
      icon.innerText = iconText;
      label.innerText = labelText;
    }

    function getActivePrNumber() {
      return parseInt(document.getElementById('pr-input').value) || 13997;
    }

    async function init() {
      const params = new URLSearchParams(window.location.search);
      if (params.get('repo')) currentRepo = params.get('repo');
      try {
        await fetchStatus();
        await fetchPRs(currentRepo);
        
        if (params.get('pr')) {
          document.getElementById('pr-input').value = params.get('pr');
        } else if (availablePRs.length > 0) {
          document.getElementById('pr-input').value = availablePRs[0].number;
        }
        
        await fetchInsights();
        await fetchLedger();
        await runInvestigation();
      } catch (err) {
        console.error("Initialization failed", err);
        notify("Keystone couldn't finish loading. Check FalkorDB connection and try again.", "error");
      }
    }

    async function fetchStatus() {
      try {
        const res = await fetch(`/api/status?repo=${encodeURIComponent(currentRepo)}`);
        const data = await res.json();
        if (!res.ok || data.error) {
          throw new Error(data.error || "Status request failed");
        }
        
        const repos = data.repos || ['pydantic', 'fastapi'];
        const topSelect = document.getElementById('repo-select');
        
        topSelect.innerHTML = repos.map(r => `<option value="${r}">${r} (${r === 'pydantic' ? '1,309 nodes' : 'active graph'})</option>`).join('');

        if (repos.includes(currentRepo)) {
          topSelect.value = currentRepo;
        } else {
          currentRepo = repos[0];
          topSelect.value = currentRepo;
        }

        allowedWriteRepos = data.allowed_write_repos || allowedWriteRepos;
        sandboxRepo = data.sandbox_repo || sandboxRepo;
        const sbLabel = document.getElementById('sandbox-repo-label');
        if (sbLabel) sbLabel.innerText = sandboxRepo;

        document.getElementById('preset-repo-tag').innerText = currentRepo;

        const pill = document.getElementById('conn-pill');
        const txt = document.getElementById('conn-text');
        if (data.is_live) {
          pill.className = "flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-950/40 border border-emerald-800/50 text-emerald-300";
          txt.innerText = "FalkorDB Connected";
        } else {
          pill.className = "flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-amber-950/40 border border-amber-800/50 text-amber-300";
          txt.innerText = "FalkorDB Offline";
        }

        renderBenchmarkButtons();
      } catch (err) {
        console.error("Status error", err);
        notify("Unable to load repository status.", "error");
      }
    }

    function renderBenchmarkButtons() {
      const container = document.getElementById('benchmark-buttons-container');
      const list = BENCHMARKS[currentRepo] || BENCHMARKS['pydantic'];
      container.innerHTML = list.map(b => `
        <button onclick="selectPr(${b.num})" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition cursor-pointer">
          <span class="font-mono text-indigo-400 font-semibold block text-xs">${b.label}</span>
          <span class="text-slate-400 truncate block text-[11px]">${b.desc}</span>
        </button>
      `).join('');
    }

    async function fetchPRs(repo) {
      try {
        const feedLabel = document.getElementById('pr-feed-count');
        feedLabel.innerText = "Loading PRs...";
        const res = await fetch(`/api/prs?repo=${encodeURIComponent(repo)}&limit=30`);
        const data = await res.json();
        if (!res.ok || data.error) {
          throw new Error(data.error || "PR feed request failed");
        }
        availablePRs = data.prs || [];
        feedLabel.innerText = `${availablePRs.length} PRs in graph`;

        const selectEl = document.getElementById('pr-select');
        if (availablePRs.length > 0) {
          selectEl.innerHTML = availablePRs.map(pr => `
            <option value="${pr.number}">#${pr.number}: ${pr.title.slice(0, 50)}${pr.title.length > 50 ? '...' : ''} (@${pr.author})</option>
          `).join('');
        } else {
          selectEl.innerHTML = `<option value="">No PRs found in graph</option>`;
        }
      } catch (err) {
        console.error("PRs load error", err);
        const feedLabel = document.getElementById('pr-feed-count');
        feedLabel.innerText = "PR feed unavailable";
        notify("Unable to load pull requests for this repository.", "error");
      }
    }

    function onSelectPrFromDropdown(val) {
      if (!val) return;
      document.getElementById('pr-input').value = val;
      runInvestigation();
    }

    async function onRepoChange(repo) {
      currentRepo = repo;
      document.getElementById('repo-select').value = repo;
      document.getElementById('preset-repo-tag').innerText = repo;
      renderBenchmarkButtons();
      
      await fetchStatus();
      await fetchPRs(repo);
      
      if (availablePRs.length > 0) {
        document.getElementById('pr-input').value = availablePRs[0].number;
      } else {
        const defaultPr = repo === 'fastapi' ? 16503 : 13997;
        document.getElementById('pr-input').value = defaultPr;
      }

      await fetchInsights();
      await runInvestigation();
    }

    function selectPr(num) {
      document.getElementById('pr-input').value = num;
      const selectEl = document.getElementById('pr-select');
      if ([...selectEl.options].some(o => o.value == num)) {
        selectEl.value = num;
      }
      runInvestigation();
    }

    async function runInvestigation() {
      if (runInProgress) return;
      const pr = getActivePrNumber();
      const question = "who should review this?";
      runInProgress = true;
      setRunButtonState(true, "Analyzing pull request...", "⏳");

      try {
        const res = await fetch('/api/investigate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pr_number: pr, question: question, repo: currentRepo })
        });
        currentResult = await res.json();
        if (!res.ok || currentResult.error) {
          throw new Error(currentResult.error || "Investigation request failed");
        }
        renderResult(currentResult);
        notify(`Analysis ready for PR #${pr}.`, "success");
      } catch (err) {
        console.error("Investigation error:", err);
        notify(`Couldn't analyze PR #${pr}. ${err.message || ''}`.trim(), "error");
      } finally {
        runInProgress = false;
        setRunButtonState(false);
      }
    }

    function renderResult(data) {
      const pr = data.pr_details || {};
      const metrics = data.pr_metrics || {};
      const reviewers = data.decision?.reviewers || [];
      const riskFlags = data.decision?.risk_flags || [];
      const changedFiles = pr.files || [];

      // 1. Basic PR Header
      document.getElementById('pr-badge-num').innerText = `PR #${data.pr_number}`;
      document.getElementById('pr-badge-state').innerText = pr.state ? pr.state.toUpperCase() : 'MERGED';
      document.getElementById('pr-repo-indicator').innerText = currentRepo;
      document.getElementById('pr-title').innerText = pr.title || `Pull Request #${data.pr_number}`;
      document.getElementById('pr-author').innerText = pr.author || 'contributor';
      document.getElementById('pr-files-count').innerText = `${changedFiles.length} file${changedFiles.length === 1 ? '' : 's'}`;
      
      const adds = pr.additions != null ? pr.additions : 0;
      const dels = pr.deletions != null ? pr.deletions : 0;
      document.getElementById('pr-lines-changed').innerText = `+${adds} / -${dels}`;

      // 2. Telemetry Card Updates (Stats users need to see)
      document.getElementById('stat-churn').innerText = `+${adds} / -${dels}`;
      document.getElementById('stat-files-count').innerText = `${changedFiles.length} files touched`;
      
      const peakC = metrics.criticality?.max_centrality || 0.0;
      document.getElementById('stat-blast-text').innerText = `${peakC.toFixed(3)} peak`;
      
      const blastBadge = document.getElementById('blast-badge');
      blastBadge.innerText = metrics.blast_tier || 'Architectural Impact';
      if (metrics.blast_color === 'rose') {
        blastBadge.className = "text-[10px] font-mono px-2 py-0.5 rounded bg-rose-950/80 text-rose-300 border border-rose-800";
      } else if (metrics.blast_color === 'amber') {
        blastBadge.className = "text-[10px] font-mono px-2 py-0.5 rounded bg-amber-950/80 text-amber-300 border border-amber-800";
      } else {
        blastBadge.className = "text-[10px] font-mono px-2 py-0.5 rounded bg-indigo-950/80 text-indigo-300 border border-indigo-800";
      }

      const bfFiles = metrics.bus_factor_files || [];
      document.getElementById('stat-bf-exposure').innerText = bfFiles.length > 0 ? `${bfFiles.length} file${bfFiles.length > 1 ? 's' : ''} monopolized` : 'No monopoly';
      document.getElementById('stat-pool-depth').innerText = `${reviewers.length} evaluated`;
      
      const topMatch = reviewers[0];
      document.getElementById('stat-coverage-rate').innerText = topMatch ? `${topMatch.coverage_pct}% (${topMatch.shared_files}/${changedFiles.length})` : '0%';

      // 3. Touched files breakdown with coverage indicator
      const filesList = document.getElementById('pr-files-list');
      const topCoveredSet = new Set(topMatch?.covered_files || []);
      const bfSet = new Set(bfFiles.map(b => b.path));

      filesList.innerHTML = changedFiles.map(f => {
        const isCovered = topCoveredSet.has(f);
        const hasBf = bfSet.has(f);
        return `
          <div class="font-mono text-[11px] px-2.5 py-1 rounded bg-slate-950 border ${hasBf ? 'border-rose-900/80 text-rose-300' : isCovered ? 'border-emerald-800/60 text-slate-200' : 'border-amber-800/60 text-amber-300'} flex items-center space-x-1.5">
            <span>📄</span>
            <span class="truncate max-w-xs">${f}</span>
            ${hasBf ? '<span class="text-[9px] px-1 py-0.2 bg-rose-950 text-rose-400 rounded">BUS-FACTOR</span>' : ''}
            ${isCovered ? '<span class="text-[9px] text-emerald-400">✓ Context</span>' : '<span class="text-[9px] text-amber-400">⚠ Gap</span>'}
          </div>
        `;
      }).join('') || '<span class="text-xs text-slate-500">No files recorded</span>';

      // 4. Reviewer Pairing Strategy Card (Primary + Secondary)
      const pairingContainer = document.getElementById('pairing-container');
      const primary = reviewers[0];
      const secondary = reviewers[1];

      let pairingHtml = '';
      if (primary) {
        pairingHtml += `
          <div class="bg-slate-950/80 border border-indigo-700/60 rounded-lg p-4 space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold text-indigo-400 uppercase tracking-wider">Primary Reviewer (Domain Lead)</span>
              <span class="font-mono text-xs text-indigo-300 font-bold">Score: ${primary.score.toFixed(3)}</span>
            </div>
            <div class="text-lg font-bold text-white flex items-center space-x-1.5">
              <span>@${primary.login}</span>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs pt-1 border-t border-slate-800/80">
              <div>
                <span class="text-slate-400 text-[10px] block">File Coverage</span>
                <span class="font-semibold text-emerald-400 font-mono">${primary.shared_files} of ${changedFiles.length} (${primary.coverage_pct}%)</span>
              </div>
              <div>
                <span class="text-slate-400 text-[10px] block">Review Velocity</span>
                <span class="font-semibold text-slate-200 font-mono">${primary.recent_reviews} reviews (${primary.days_ago != null ? primary.days_ago + 'd ago' : 'active'})</span>
              </div>
            </div>
          </div>
        `;
      }

      if (secondary) {
        pairingHtml += `
          <div class="bg-slate-950/80 border border-slate-800 rounded-lg p-4 space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-[10px] font-bold text-emerald-400 uppercase tracking-wider">Secondary Reviewer (Cross-Training)</span>
              <span class="font-mono text-xs text-slate-300 font-bold">Score: ${secondary.score.toFixed(3)}</span>
            </div>
            <div class="text-lg font-bold text-white flex items-center space-x-1.5">
              <span>@${secondary.login}</span>
            </div>
            <div class="grid grid-cols-2 gap-2 text-xs pt-1 border-t border-slate-800/80">
              <div>
                <span class="text-slate-400 text-[10px] block">File Coverage</span>
                <span class="font-semibold text-slate-200 font-mono">${secondary.shared_files} of ${changedFiles.length} (${secondary.coverage_pct}%)</span>
              </div>
              <div>
                <span class="text-slate-400 text-[10px] block">Capacity Status</span>
                <span class="font-semibold text-emerald-400 font-mono">${secondary.is_overloaded ? 'High Load' : 'Available'}</span>
              </div>
            </div>
          </div>
        `;
      } else {
        pairingHtml += `
          <div class="bg-slate-950/80 border border-slate-800 rounded-lg p-4 flex items-center justify-center text-slate-500 text-xs">
            Single candidate above graph relevance threshold.
          </div>
        `;
      }
      pairingContainer.innerHTML = pairingHtml;

      // 5. Narration / Rationale Text
      const summaryText = data.narration || data.decision?.rationale || "";
      document.getElementById('rationale-text').innerText = summaryText ? `"${summaryText}"` : "";

      // 6. Risk Flags Alert
      const riskContainer = document.getElementById('risk-container');
      if (riskFlags.length === 0) {
        riskContainer.innerHTML = `
          <div class="bg-emerald-950/30 border border-emerald-800/50 rounded-xl p-3 flex items-center space-x-2.5 text-xs text-emerald-300">
            <span>✅</span>
            <span>Zero knowledge coverage gaps or single-maintainer bottlenecks detected on this PR.</span>
          </div>
        `;
      } else {
        riskContainer.innerHTML = riskFlags.map(flag => `
          <div class="bg-rose-950/30 border border-rose-800/50 rounded-xl p-3 flex items-start space-x-2.5 text-xs text-rose-300">
            <span>🚩</span>
            <div>
              <div class="font-semibold uppercase tracking-wider text-[10px]">Knowledge Risk Identified</div>
              <div class="font-mono mt-0.5 text-xs">${flag}</div>
            </div>
          </div>
        `).join('');
      }

      // 7. Reviewers Table
      const revBody = document.getElementById('reviewers-body');
      if (reviewers.length === 0) {
        revBody.innerHTML = `<tr><td colspan="9" class="text-center py-6 text-slate-500">No candidate reviewer found above threshold.</td></tr>`;
      } else {
        revBody.innerHTML = reviewers.map((r, i) => `
          <tr class="hover:bg-slate-800/30 transition cursor-pointer" onclick="selectCandidateReviewer('${r.login}')">
            <td class="py-2 px-2.5">
              <span class="w-5 h-5 inline-flex items-center justify-center rounded-full ${i === 0 ? 'bg-indigo-600 text-white font-bold' : 'bg-slate-800 text-slate-400'} text-[11px]">
                ${i + 1}
              </span>
            </td>
            <td class="py-2 px-2.5 font-semibold text-white">
              <span class="text-slate-400">@</span><span>${r.login}</span>
            </td>
            <td class="py-2 px-2.5 text-right font-bold text-indigo-300">${r.score.toFixed(3)}</td>
            <td class="py-2 px-2.5 text-right text-emerald-400">${r.coverage_pct}%</td>
            <td class="py-2 px-2.5 text-right text-slate-300">${r.shared_files}</td>
            <td class="py-2 px-2.5 text-right text-slate-400 font-mono">${r.bridge_files || 0}</td>
            <td class="py-2 px-2.5 text-right text-slate-300">${r.recent_reviews}</td>
            <td class="py-2 px-2.5 text-slate-400">${r.days_ago != null ? r.days_ago + 'd ago' : (r.last_review ? r.last_review.slice(0, 10) : 'N/A')}</td>
            <td class="py-2 px-2.5 text-center">
              <button onclick="event.stopPropagation(); selectCandidateReviewer('${r.login}'); switchTab('explain');" class="text-[11px] text-indigo-400 hover:text-indigo-300 underline cursor-pointer">
                Inspect &rarr;
              </button>
            </td>
          </tr>
        `).join('');
      }

      // 8. Proposed Actions
      const actContainer = document.getElementById('actions-container');
      const actions = data.proposed_actions || [];
      if (actions.length === 0) {
        actContainer.innerHTML = `<div class="text-xs text-slate-500">No actions required for this PR.</div>`;
      } else {
        const repoLower = (currentRepo || '').toLowerCase();
        const isLiveConfig = (allowedWriteRepos || []).some(w => repoLower === w || repoLower.endsWith('/' + w) || w.endsWith('/' + repoLower));

        actContainer.innerHTML = actions.map((act, i) => {
          const target = act.who || act.label;
          const actName = act.action.replace('_', ' ').toUpperCase();
          const reason = act.reason || "Determined by graph analysis";
          const actionLive = isLiveConfig;
          const targetNote = actionLive 
            ? `🟢 Live Action &rarr; Direct write to ${currentRepo} PR #${act.on}`
            : `🛡️ Shadow Action &rarr; Logged to tracking issue on ${sandboxRepo} (logins as code)`;

          return `
            <label id="act-card-${i}" class="bg-slate-950 border border-slate-800 rounded-lg p-3.5 flex items-start justify-between cursor-pointer hover:border-slate-700 transition">
              <div class="space-y-1.5 flex-1 pr-3">
                <div class="flex items-center space-x-2 flex-wrap gap-y-1">
                  <input type="checkbox" class="plan-action mr-1 accent-indigo-500" data-action-index="${i}" checked>
                  <span class="text-xs font-semibold px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800">${actName}</span>
                  <span class="font-mono text-sm text-white font-medium">${target}</span>
                  <span class="text-xs text-slate-500">on PR #${act.on}</span>
                  <span class="text-[10px] font-mono px-2 py-0.5 rounded ${actionLive ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-purple-950 text-purple-300 border border-purple-800'}">
                    ${actionLive ? 'LIVE TARGET' : 'SHADOW MODE'}
                  </span>
                </div>
                <div class="text-xs text-slate-400 ml-6 flex items-center space-x-1.5">
                  <span class="text-indigo-400 font-semibold">Graph Evidence:</span>
                  <span>${reason}</span>
                </div>
                <div class="text-[11px] font-mono ml-6 ${actionLive ? 'text-emerald-400' : 'text-purple-300'}">
                  ${targetNote}
                </div>
              </div>
              <span id="act-status-${i}" class="text-[11px] text-amber-400 px-2 py-0.5 rounded bg-amber-950/60 border border-amber-800/60 whitespace-nowrap">Awaiting Approval</span>
            </label>
          `;
        }).join('');
      }

      currentSelectedCandidate = reviewers[0]?.login || null;
      renderCandidateSelectorSegment(reviewers);
      renderExplainabilityForCandidate(currentSelectedCandidate);
      renderInteractiveNetwork(data);
    }

    function renderCandidateSelectorSegment(reviewers) {
      const segment = document.getElementById('candidate-selector-segment');
      if (!reviewers || reviewers.length === 0) {
        segment.innerHTML = '';
        return;
      }
      segment.innerHTML = reviewers.slice(0, 3).map((r, i) => `
        <button onclick="selectCandidateReviewer('${r.login}')" class="px-2.5 py-1 rounded text-xs transition cursor-pointer ${currentSelectedCandidate === r.login ? 'bg-indigo-600 text-white font-semibold' : 'text-slate-400 hover:text-white'}">
          #${i + 1} @${r.login} (${r.coverage_pct || 0}%)
        </button>
      `).join('');
    }

    function selectCandidateReviewer(login) {
      currentSelectedCandidate = login;
      const reviewers = currentResult?.decision?.reviewers || [];
      renderCandidateSelectorSegment(reviewers);
      renderExplainabilityForCandidate(login);
    }

    function renderExplainabilityForCandidate(login) {
      if (!currentResult) return;
      const data = currentResult;
      const evidenceMap = data.reviewer_evidence || {};
      const pathData = evidenceMap[login] || data.explain_path || {};
      
      document.getElementById('explain-header').innerText = `Graph Traversal Path for @${login || 'Candidate'}:`;

      const walkBox = document.getElementById('graph-walk');
      const nodes = pathData.path_nodes || [];
      const edges = pathData.path_edges || [];

      if (nodes.length > 0) {
        walkBox.innerHTML = `
          <div class="space-y-2">
            <div class="text-xs text-slate-400 font-mono">
              Shortest Traversal Path (<strong class="text-indigo-300">${pathData.hops || nodes.length - 1} hops</strong> &middot; Evidence: <span class="text-emerald-400">${pathData.evidence || 'direct_review_history'}</span>):
            </div>
            <div class="flex items-center space-x-2 overflow-x-auto text-xs font-mono py-2">
              ${nodes.map((n, i) => `
                <div class="px-3 py-1.5 rounded-lg border font-semibold whitespace-nowrap ${n.type === 'PullRequest' ? 'bg-indigo-900/60 border-indigo-700 text-indigo-200' : n.type === 'File' ? 'bg-cyan-950 border-cyan-800 text-cyan-200' : 'bg-emerald-950 border-emerald-700 text-emerald-200'}">
                  ${n.label}
                </div>
                ${i < nodes.length - 1 ? `<div class="text-slate-500 font-bold">&mdash;[${edges[i]?.type || 'TOUCHES'}]&rarr;</div>` : ''}
              `).join('')}
            </div>
          </div>
        `;
      } else {
        walkBox.innerHTML = `<div class="text-xs text-slate-500">No multi-hop path found for candidate @${login}.</div>`;
      }

      const filesBox = document.getElementById('explain-files');
      filesBox.innerHTML = (pathData.files || []).map(f => `
        <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs font-mono flex items-center justify-between">
          <div class="flex items-center space-x-2 truncate">
            <span class="text-cyan-400">📄</span>
            <span class="text-slate-200">${f}</span>
          </div>
          <span class="text-emerald-400 text-[11px]">Direct Reviewer Context</span>
        </div>
      `).join('') || '<div class="text-xs text-slate-500">No direct file reviews recorded.</div>';

      const bridgesBox = document.getElementById('explain-bridges');
      bridgesBox.innerHTML = (pathData.bridges || []).map(b => `
        <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs font-mono flex items-center justify-between">
          <div class="flex items-center space-x-2 truncate">
            <span class="text-indigo-400">🔗</span>
            <span class="text-slate-200">${b.from} &harr; ${b.to}</span>
          </div>
          <span class="text-slate-400 text-[11px]">Co-changed ${b.weight}&times; &middot; centrality ${b.centrality}</span>
        </div>
      `).join('') || '<div class="text-xs text-slate-500">No co-change bridge files.</div>';
    }

    async function applyApprovedPlan() {
      const inputs = [...document.querySelectorAll('.plan-action:checked')];
      if (!inputs.length) {
        notify("Select at least one action before execution.", "error");
        return;
      }
      const confirmed = window.confirm(`Execute ${inputs.length} approved action${inputs.length === 1 ? '' : 's'} for PR #${currentResult?.pr_number || getActivePrNumber()}?`);
      if (!confirmed) return;
      const btn = document.getElementById('apply-plan-btn');
      btn.disabled = true;
      btn.innerText = "Executing & Logging Actions...";

      const actions = currentResult?.proposed_actions || [];

      for (const input of inputs) {
        const idx = parseInt(input.dataset.actionIndex);
        const actionObj = actions[idx];
        if (actionObj) {
          try {
            await fetch('/api/action/execute', {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify({ action: actionObj, repo: currentRepo, pr_number: currentResult.pr_number })
            });
            const statusEl = document.getElementById(`act-status-${idx}`);
            if (statusEl) {
              statusEl.className = "text-[11px] text-emerald-400 px-2 py-0.5 rounded bg-emerald-950/60 border border-emerald-800/60 whitespace-nowrap";
              statusEl.innerHTML = `✓ Executed & Logged`;
            }
          } catch (e) {
            console.error("Action exec error", e);
            notify(`Failed to execute action ${actionObj.action || ''}.`, "error");
          }
        }
      }

      await fetchLedger();

      btn.disabled = false;
      btn.innerText = "✓ Actions Executed & Logged in Graph Ledger";
      notify("Approved actions were recorded in the ledger.", "success");
    }

    async function fetchLedger() {
      try {
        const res = await fetch('/api/action/ledger');
        const data = await res.json();
        fullLedgerData = data.ledger || [];
        allowedWriteRepos = data.allowed_write_repos || allowedWriteRepos;
        sandboxRepo = data.sandbox_repo || sandboxRepo;
        
        const liveCount = data.live_count != null ? data.live_count : fullLedgerData.filter(i => i.mode === 'LIVE').length;
        const shadowCount = data.shadow_count != null ? data.shadow_count : fullLedgerData.filter(i => i.mode === 'SHADOW').length;

        document.getElementById('ledger-badge').innerText = fullLedgerData.length;
        document.getElementById('ledger-count-pill').innerText = `${fullLedgerData.length} Action${fullLedgerData.length === 1 ? '' : 's'}`;
        
        const liveEl = document.getElementById('live-actions-count');
        if (liveEl) liveEl.innerText = liveCount;
        const shadowEl = document.getElementById('shadow-actions-count');
        if (shadowEl) shadowEl.innerText = shadowCount;
        const sbLabel = document.getElementById('sandbox-repo-label');
        if (sbLabel) sbLabel.innerText = sandboxRepo;

        renderLedgerTable();
      } catch (err) {
        console.error("Ledger fetch error", err);
        notify("Unable to load the action ledger.", "error");
      }
    }

    function filterLedger(mode) {
      currentLedgerFilter = mode;
      ['all', 'live', 'shadow'].forEach(f => {
        const btn = document.getElementById(`filter-ledger-${f}`);
        if (btn) {
          if ((f === 'all' && mode === 'all') || (f.toUpperCase() === mode)) {
            btn.className = "px-2.5 py-1 rounded bg-indigo-600 text-white font-medium cursor-pointer";
          } else {
            btn.className = "px-2.5 py-1 rounded bg-slate-800 text-slate-300 hover:text-white cursor-pointer";
          }
        }
      });
      const statusLabel = document.getElementById('ledger-filter-status');
      if (statusLabel) {
        statusLabel.innerText = mode === 'all' ? 'Showing all entries' : `Showing ${mode.toLowerCase()} actions`;
      }
      renderLedgerTable();
    }

    function renderLedgerTable() {
      const tbody = document.getElementById('ledger-table-body');
      if (!tbody) return;
      const filtered = currentLedgerFilter === 'all' 
        ? fullLedgerData 
        : fullLedgerData.filter(i => i.mode === currentLedgerFilter);

      if (filtered.length === 0) {
        tbody.innerHTML = `<tr><td colspan="8" class="py-6 text-center text-slate-500 font-sans text-xs">No ${currentLedgerFilter === 'all' ? '' : currentLedgerFilter.toLowerCase() + ' '}actions recorded yet. Use the "Review Routing & Actions" tab to approve proposed actions.</td></tr>`;
        return;
      }

      tbody.innerHTML = filtered.map(item => {
        const isLive = item.mode === 'LIVE';
        return `
          <tr class="hover:bg-slate-900 transition">
            <td class="py-2.5 px-3 text-indigo-300 font-bold">${item.id}</td>
            <td class="py-2.5 px-3 text-slate-400">${item.timestamp.slice(11, 19)}</td>
            <td class="py-2.5 px-3">
              <span class="px-2 py-0.5 rounded text-[10px] font-bold ${isLive ? 'bg-emerald-950 text-emerald-300 border border-emerald-800' : 'bg-purple-950 text-purple-300 border border-purple-800'}">
                ${isLive ? '🟢 LIVE' : '🛡️ SHADOW'}
              </span>
            </td>
            <td class="py-2.5 px-3 text-slate-300">
              <span class="font-semibold text-white">${item.target}</span>
              <span class="text-slate-500 text-[11px] block">${item.repo} #${item.pr_number}</span>
            </td>
            <td class="py-2.5 px-3">
              <span class="px-2 py-0.5 rounded bg-indigo-950 text-indigo-300 border border-indigo-800 text-[11px]">${item.action}</span>
            </td>
            <td class="py-2.5 px-3 text-slate-300 text-[11px]">
              <div class="font-semibold ${isLive ? 'text-emerald-400' : 'text-purple-300'}">${item.destination || (isLive ? item.repo + ' PR' : sandboxRepo)}</div>
              <div class="text-slate-500 text-[10px] truncate max-w-xs">${item.safety_notice || (isLive ? 'Direct write' : 'Logins escaped as code')}</div>
            </td>
            <td class="py-2.5 px-3 text-slate-400 text-[11px] max-w-xs truncate">${item.reason}</td>
            <td class="py-2.5 px-3 text-right">
              <span class="text-emerald-400 font-semibold">✓ ${item.status}</span>
            </td>
          </tr>
        `;
      }).join('');
    }

    async function clearActionLedger() {
      const confirmed = window.confirm("Clear the action ledger? This removes the in-memory audit history from this session.");
      if (!confirmed) return;
      await fetch('/api/action/clear', { method: 'POST' });
      await fetchLedger();
      notify("Action ledger has been reset.", "success");
    }

    function renderInteractiveNetwork(data) {
      const container = document.getElementById('network-canvas');
      if (!container || !window.vis) return;

      const nodes = [];
      const edges = [];

      const prNum = data.pr_number;
      const targetPrNodeId = `PR_${prNum}`;
      nodes.push({
        id: targetPrNodeId,
        label: `PR #${prNum}`,
        title: `Target PR #${prNum} (${data.pr_details?.title || ''})`,
        color: { background: '#4f46e5', border: '#818cf8' },
        shape: 'box',
        font: { color: '#ffffff', face: 'JetBrains Mono', size: 14 }
      });

      const touchedFiles = (data.pr_details?.files || []).slice(0, 8);
      touchedFiles.forEach((file, idx) => {
        const fileId = `FILE_${idx}`;
        const shortName = file.split('/').pop();
        nodes.push({
          id: fileId,
          label: shortName,
          title: `File: ${file}`,
          color: { background: '#0891b2', border: '#22d3ee' },
          shape: 'ellipse',
          font: { color: '#ffffff', face: 'JetBrains Mono', size: 11 }
        });
        edges.push({
          from: targetPrNodeId,
          to: fileId,
          label: 'TOUCHES',
          color: { color: '#38bdf8' },
          arrows: 'to',
          font: { size: 9, color: '#94a3b8' }
        });
      });

      const reviewers = (data.decision?.reviewers || []).slice(0, 3);
      reviewers.forEach((rev) => {
        const revId = `REV_${rev.login}`;
        nodes.push({
          id: revId,
          label: `@${rev.login}\\n(${rev.score.toFixed(2)})`,
          title: `Reviewer @${rev.login} (Score: ${rev.score.toFixed(3)}, Coverage: ${rev.coverage_pct}%)`,
          color: { background: '#059669', border: '#34d399' },
          shape: 'circle',
          font: { color: '#ffffff', face: 'JetBrains Mono', size: 12 }
        });

        touchedFiles.slice(0, rev.shared_files || 2).forEach((_, fIdx) => {
          edges.push({
            from: `FILE_${fIdx}`,
            to: revId,
            label: 'REVIEWED',
            color: { color: '#10b981' },
            dashes: true,
            arrows: 'to',
            font: { size: 9, color: '#94a3b8' }
          });
        });
      });

      const networkData = {
        nodes: new vis.DataSet(nodes),
        edges: new vis.DataSet(edges)
      };

      const options = {
        physics: {
          solver: 'forceAtlas2Based',
          forceAtlas2Based: { gravitationalConstant: -50, centralGravity: 0.01, springLength: 100 }
        },
        interaction: { hover: true, tooltipDelay: 200 }
      };

      networkInstance = new vis.Network(container, networkData, options);

      networkInstance.on("click", function (params) {
        if (params.nodes.length > 0) {
          const nodeId = params.nodes[0];
          const nodeObj = nodes.find(n => n.id === nodeId);
          if (nodeObj) {
            const insp = document.getElementById('node-inspector');
            insp.classList.remove('hidden');
            document.getElementById('inspector-title').innerText = `${nodeObj.label.replace('\\n', ' ')}`;
            document.getElementById('inspector-desc').innerText = nodeObj.title || 'Connected graph node in active neighborhood';
          }
        }
      });
    }

    function rebuildGraphVisualization() {
      if (currentResult) {
        renderInteractiveNetwork(currentResult);
      }
    }

    function switchTab(tab) {
      const tabs = ['decision', 'explain', 'network', 'health', 'ledger', 'diagnostics'];
      tabs.forEach(t => {
        document.getElementById(`tab-${t}`).classList.add('hidden');
        const tabBtn = document.getElementById(`tab-btn-${t}`);
        tabBtn.className = `px-3.5 py-2.5 font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap cursor-pointer${t === 'ledger' ? ' flex items-center space-x-1.5' : ''}`;
        tabBtn.setAttribute('aria-selected', 'false');
      });

      document.getElementById(`tab-${tab}`).classList.remove('hidden');
      const activeBtn = document.getElementById(`tab-btn-${tab}`);
      activeBtn.className = `px-3.5 py-2.5 font-medium border-b-2 border-indigo-500 text-indigo-400 whitespace-nowrap cursor-pointer${tab === 'ledger' ? ' flex items-center space-x-1.5' : ''}`;
      activeBtn.setAttribute('aria-selected', 'true');

      if (tab === 'network' && networkInstance) {
        setTimeout(() => { networkInstance.fit(); }, 100);
      }
      if (tab === 'ledger') {
        fetchLedger();
      }
    }

    function setCypherQuery(q) {
      document.getElementById('cypher-input').value = q;
      executeCypher();
    }

    async function executeCypher() {
      const q = document.getElementById('cypher-input').value;
      const status = document.getElementById('cypher-status');
      const countEl = document.getElementById('cypher-count');
      const body = document.getElementById('cypher-table-body');

      status.innerText = "Executing query on FalkorDB...";
      body.innerHTML = `<tr><td class="py-4 text-center text-slate-500">Querying graph...</td></tr>`;

      try {
        const res = await fetch('/api/cypher', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ query: q, repo: currentRepo })
        });
        const data = await res.json();
        if (data.error) {
          status.innerText = `Error: ${data.error}`;
          body.innerHTML = `<tr><td class="text-rose-400 py-3">${data.error}</td></tr>`;
          return;
        }

        status.innerText = "Success";
        countEl.innerText = `${data.count} row(s)`;

        if (data.rows.length === 0) {
          body.innerHTML = `<tr><td class="py-4 text-center text-slate-500">(Empty result set)</td></tr>`;
          return;
        }

        body.innerHTML = data.rows.map(row => `
          <tr class="hover:bg-slate-900 transition">
            ${row.map(cell => `<td class="py-2 px-3 text-slate-300 border-b border-slate-900">${typeof cell === 'object' ? JSON.stringify(cell) : cell}</td>`).join('')}
          </tr>
        `).join('');

      } catch (err) {
        status.innerText = `Error: ${err}`;
        notify("Cypher query failed. Check syntax or connection health.", "error");
      }
    }

    async function fetchInsights() {
      try {
        const res = await fetch(`/api/insights?repo=${encodeURIComponent(currentRepo)}`);
        const data = await res.json();
        
        const bfList = document.getElementById('bus-factor-list');
        bfList.innerHTML = (data.bus_factor || []).map(b => `
          <div class="bg-slate-950 border border-rose-900/40 rounded-lg p-3 text-xs">
            <div class="font-mono text-slate-200 font-medium truncate">${b.path}</div>
            <div class="flex items-center justify-between mt-1 text-slate-400">
              <span>Sole Reviewer: <strong class="text-rose-400 font-mono">@${b.sole_reviewer}</strong></span>
              <span>${b.sole_count} / ${b.total} reviews (${Math.round(b.sole_count / b.total * 100)}%)</span>
            </div>
          </div>
        `).join('') || '<div class="text-xs text-slate-500">No coverage gaps detected.</div>';

        const cfList = document.getElementById('critical-files-list');
        cfList.innerHTML = (data.critical_files || []).map(c => `
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs flex items-center justify-between">
            <span class="font-mono text-slate-200 truncate pr-2">${c.path}</span>
            <span class="font-mono px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800 text-indigo-300 font-medium">
              ${typeof c.score === 'number' ? c.score.toFixed(3) : c.score}
            </span>
          </div>
        `).join('') || '<div class="text-xs text-slate-500">None calculated.</div>';

      } catch (err) {
        console.error("Insights error", err);
        notify("Repository insights are unavailable right now.", "error");
      }
    }

    window.onload = init;
  </script>
</body>
</html>
"""

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_index():
    return HTMLResponse(content=HTML_TEMPLATE, status_code=200)

@app.get("/api/status")
async def api_status(repo: str = DEFAULT_REPO):
    try:
        repo = validate_repo(repo)
        status = get_connection_status()
        repos = list_repos()
        try:
            provenance = graph_provenance(repo)
        except Exception:
            provenance = {"status": "unmarked", "message": "Graph data exists"}
        return JSONResponse({
            "nodes": node_count(repo),
            "edges": edge_count(repo),
            "repos": repos,
            "current_repo": repo,
            "is_live": status.get("is_live", False),
            "message": status.get("message", "FalkorDB"),
            "provenance": provenance,
            "graph": graph_stats(repo),
            "sample_pr": sample_pr(repo),
            "allowed_write_repos": ALLOWED_WRITE_REPOS,
            "sandbox_repo": SANDBOX_REPO,
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"FalkorDB unavailable: {type(e).__name__}: {e}"},
            status_code=503,
        )

@app.get("/api/prs")
async def api_prs(repo: str = DEFAULT_REPO, limit: int = 30):
    try:
        repo = validate_repo(repo)
        prs = list_recent_prs(limit=limit, repo=repo)
        return JSONResponse({"repo": repo, "prs": prs, "count": len(prs)})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/plan")
async def api_plan(req: Request):
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        question = body.get("question", "who should review this?")
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        planned = plan(pr_num, question=question, repo=repo)
        return JSONResponse({"planned_tools": planned, "question": question, "repo": repo})
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/investigate")
async def api_investigate(req: Request):
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        question = body.get("question", "who should review this?")

        result = run_keystone(pr_num, question, repo=repo)
        pr_info = get_pr(pr_num, repo=repo)
        cutoff = default_cutoff()
        crit = pr_criticality(pr_num, repo=repo)
        bf_all = bus_factor_files(cutoff, repo=repo)

        # PR-specific bus factor files
        pr_files = pr_info.get("files", [])
        pr_files_set = set(pr_files)
        pr_bf_files = [b for b in bf_all if b["path"] in pr_files_set]

        # Enriched reviewer metrics
        evidence_map = result.get("reviewer_evidence", {})
        enriched_reviewers = []
        for r in result["decision"]["reviewers"]:
            login = r["login"]
            ep = evidence_map.get(login, {})
            covered = ep.get("files", [])
            covered_set = set(covered)
            uncovered = [f for f in pr_files if f not in covered_set]
            coverage_pct = round((len(covered) / len(pr_files) * 100), 1) if pr_files else 100.0
            
            last_rev_iso = r.get("last_review")
            days_ago = None
            if last_rev_iso:
                try:
                    t = datetime.fromisoformat(last_rev_iso.replace("Z", "+00:00"))
                    days_ago = max(0, int((datetime.now(timezone.utc) - t).total_seconds() / 86400))
                except Exception:
                    pass

            enriched_reviewers.append({
                **r,
                "covered_files": covered,
                "uncovered_files": uncovered,
                "coverage_pct": coverage_pct,
                "days_ago": days_ago,
                "is_overloaded": r.get("recent_reviews", 0) > 20,
            })

        max_c = crit.get("max_centrality", 0.0)
        if max_c >= 0.25:
            blast_tier = "Critical Architecture"
            blast_color = "rose"
        elif max_c >= 0.08:
            blast_tier = "High Blast Radius"
            blast_color = "amber"
        elif max_c > 0.01:
            blast_tier = "Moderate Blast Radius"
            blast_color = "indigo"
        else:
            blast_tier = "Isolated Change"
            blast_color = "slate"

        pr_metrics = {
            "blast_tier": blast_tier,
            "blast_color": blast_color,
            "criticality": crit,
            "bus_factor_files": pr_bf_files,
            "additions": pr_info.get("additions", 0),
            "deletions": pr_info.get("deletions", 0),
            "total_files": len(pr_files),
        }

        top_rev = "davidhewitt"
        if result["decision"]["reviewers"]:
            top_rev = result["decision"]["reviewers"][0]["login"]

        path_info = explain_path(pr_num, top_rev, repo=repo)
        narration_text = narrate(result["decision"], pr_info)

        return JSONResponse({
            **result,
            "decision": {
                **result["decision"],
                "reviewers": enriched_reviewers
            },
            "pr_details": pr_info,
            "pr_metrics": pr_metrics,
            "explain_path": path_info,
            "narration": narration_text
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"Investigation failed: {e}"}, status_code=500)

@app.get("/api/insights")
async def api_insights(repo: str = DEFAULT_REPO):
    try:
        repo = validate_repo(repo)
        bf = bus_factor_files(default_cutoff(), repo=repo)
        cf = critical_files(10, repo=repo)
        return JSONResponse({
            "bus_factor": bf,
            "critical_files": cf
        })
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse(
            {"error": f"FalkorDB unavailable: {type(e).__name__}: {e}"},
            status_code=503,
        )

@app.post("/api/cypher")
async def api_cypher(req: Request):
    try:
        body = await req.json()
        query = body.get("query", "").strip()
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        if not query:
            return JSONResponse({"error": "Query cannot be empty"}, status_code=400)
        g = get_graph(repo)
        res = g.query(query)
        rows = [list(r) for r in res.result_set] if hasattr(res, "result_set") else []
        return JSONResponse({"rows": rows, "count": len(rows)})
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=400)

@app.post("/api/mcp/execute")
async def api_mcp_execute(req: Request):
    try:
        body = await req.json()
        tool_name = body.get("tool")
        params = body.get("params", {})
        repo = validate_repo(body.get("repo", DEFAULT_REPO))
        cutoff = default_cutoff()

        if tool_name == "get_pr":
            return JSONResponse(get_pr(int(params.get("number", 13997)), repo=repo))
        elif tool_name == "rank_reviewers":
            return JSONResponse(score_reviewers(int(params.get("pr_number", 13997)), cutoff, repo=repo))
        elif tool_name == "bus_factor_files":
            return JSONResponse(bus_factor_files(cutoff, int(params.get("min_reviews", 5)), repo=repo))
        elif tool_name == "critical_files":
            return JSONResponse(critical_files(int(params.get("limit", 10)), repo=repo))
        elif tool_name == "explain_path":
            return JSONResponse(explain_path(int(params.get("pr_number", 13997)), str(params.get("reviewer", "davidhewitt")), repo=repo))
        elif tool_name == "data_provenance":
            return JSONResponse(graph_provenance(repo))
        else:
            return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=400)
    except ValueError as ve:
        return JSONResponse({"error": str(ve)}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

@app.get("/api/action/ledger")
async def api_action_ledger():
    live_count = sum(1 for a in ACTION_LEDGER if a.get("mode") == "LIVE")
    shadow_count = sum(1 for a in ACTION_LEDGER if a.get("mode") == "SHADOW")
    return JSONResponse({
        "ledger": ACTION_LEDGER,
        "count": len(ACTION_LEDGER),
        "live_count": live_count,
        "shadow_count": shadow_count,
        "sandbox_repo": SANDBOX_REPO,
        "allowed_write_repos": ALLOWED_WRITE_REPOS,
    })

@app.post("/api/action/execute")
async def api_action_execute(req: Request):
    try:
        body = await req.json()
        action = body.get("action", {})
        repo = body.get("repo", DEFAULT_REPO)
        pr_number = body.get("pr_number") or action.get("on")
        action_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"
        timestamp = datetime.now(timezone.utc).isoformat()
        
        repo_lower = str(repo).lower().strip()
        is_live = (repo_lower in ALLOWED_WRITE_REPOS) or (any(repo_lower.endswith('/' + w) or w.endswith('/' + repo_lower) for w in ALLOWED_WRITE_REPOS) if ALLOWED_WRITE_REPOS else False)
        mode = "LIVE" if is_live else "SHADOW"
        destination = f"{repo} PR #{pr_number}" if is_live else f"{SANDBOX_REPO} (Tracking Issue)"
        safety_notice = "Executed directly on allowed repository" if is_live else f"Safeguarded in shadow issue on {SANDBOX_REPO}; logins formatted as code to prevent upstream notifications"

        entry = {
            "id": action_id,
            "timestamp": timestamp,
            "repo": repo,
            "pr_number": pr_number,
            "action": action.get("action", "unknown").upper(),
            "target": action.get("who") or action.get("label") or "PR",
            "reason": action.get("reason", "Graph-directed decision"),
            "status": "EXECUTED",
            "mode": mode,
            "destination": destination,
            "safety_notice": safety_notice,
        }
        ACTION_LEDGER.insert(0, entry)
        return JSONResponse({"ok": True, "action_id": action_id, "entry": entry})
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)

@app.post("/api/action/clear")
async def api_action_clear():
    ACTION_LEDGER.clear()
    return JSONResponse({"ok": True, "message": "Action ledger reset"})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
