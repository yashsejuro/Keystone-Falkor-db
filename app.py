"""Keystone — Knowledge-risk and reviewer-routing agent for codebases built on FalkorDB."""
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from graph_client import node_count, edge_count, get_connection_status, get_graph
from agent import run_keystone
from tools import get_pr, explain_path, bus_factor_files, critical_files, default_cutoff

try:
    from narration import narrate
except Exception:
    def narrate(decision, pr):
        return decision.get("rationale", "")

app = FastAPI(title="Keystone", description="Graph-based PR Reviewer Routing & Knowledge Risk Agent")

HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Keystone — Reviewer Routing & Knowledge Risk</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    code, pre, .font-mono { font-family: 'JetBrains Mono', monospace; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">

  <!-- Navigation / Topbar -->
  <header class="border-b border-slate-800 bg-slate-900/80 backdrop-blur sticky top-0 z-30 px-6 py-3.5">
    <div class="max-w-7xl mx-auto flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-9 h-9 rounded-lg bg-indigo-600/30 border border-indigo-500/40 flex items-center justify-center text-indigo-400 font-bold text-lg shadow-sm">
          🧭
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <span class="font-bold text-lg text-white tracking-tight">Keystone</span>
            <span class="text-xs px-2 py-0.5 rounded-full bg-slate-800 text-slate-300 border border-slate-700">FalkorDB Graph Agent</span>
          </div>
          <p class="text-xs text-slate-400">Knowledge-risk analysis & reviewer routing for connected codebases</p>
        </div>
      </div>

      <div class="flex items-center space-x-4">
        <div class="flex items-center space-x-2 text-xs bg-slate-800/80 border border-slate-700 px-3 py-1.5 rounded-lg">
          <span class="text-slate-400">Target Repo:</span>
          <span class="font-mono font-medium text-indigo-300">pydantic/pydantic</span>
        </div>
        <div id="conn-pill" class="flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-700/60 text-emerald-300">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span id="conn-text">Checking graph...</span>
        </div>
      </div>
    </div>
  </header>

  <!-- Main Content Layout -->
  <main class="max-w-7xl mx-auto px-6 py-6 flex-1 w-full grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- Left Column: Controls & Graph Metrics (4 cols) -->
    <div class="lg:col-span-4 space-y-6">

      <!-- Investigation Controls Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
            <span>🎯</span>
            <span>Investigate PR</span>
          </h2>
          <span class="text-xs text-slate-500">Deterministic Agent</span>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Pull Request Number</label>
          <div class="relative">
            <input type="number" id="pr-input" value="13997" min="1"
                   class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 font-mono">
          </div>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Agent Question / Intent</label>
          <input type="text" id="question-input" value="who should review this?"
                 class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>

        <div>
          <button id="run-btn" onclick="runInvestigation()"
                  class="w-full bg-indigo-600 hover:bg-indigo-500 text-white font-medium py-2.5 px-4 rounded-lg text-sm shadow-md transition flex items-center justify-center space-x-2 cursor-pointer">
            <span id="btn-icon">🚀</span>
            <span id="btn-label">Run Keystone Agent</span>
          </button>
        </div>

        <!-- Sample PR Quick Chips -->
        <div class="pt-2 border-t border-slate-800/80">
          <label class="block text-xs font-medium text-slate-400 mb-2">Benchmark Ground Truths:</label>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <button onclick="selectPr(13997)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#13997</span>
              <span class="text-slate-400 truncate block text-[11px]">JSON Schema (Cross-module)</span>
            </button>
            <button onclick="selectPr(14000)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#14000</span>
              <span class="text-slate-400 truncate block text-[11px]">BaseModel Validator</span>
            </button>
            <button onclick="selectPr(13950)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#13950</span>
              <span class="text-slate-400 truncate block text-[11px]">Dataclass Type Adapter</span>
            </button>
            <button onclick="selectPr(13800)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#13800</span>
              <span class="text-slate-400 truncate block text-[11px]">Plugin Loader Refactor</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Graph Database Stats Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
          <span>📊</span>
          <span>Knowledge Graph</span>
        </h2>
        
        <div class="grid grid-cols-2 gap-3">
          <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3">
            <div class="text-xs text-slate-400">Total Nodes</div>
            <div id="stat-nodes" class="text-xl font-bold font-mono text-white mt-0.5">1,420</div>
            <div class="text-[11px] text-slate-500 mt-1">PRs, Files, People</div>
          </div>
          <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3">
            <div class="text-xs text-slate-400">Total Edges</div>
            <div id="stat-edges" class="text-xl font-bold font-mono text-white mt-0.5">4,860</div>
            <div class="text-[11px] text-slate-500 mt-1">Touches, Reviews, Co-chg</div>
          </div>
        </div>

        <div class="pt-3 border-t border-slate-800">
          <button onclick="toggleConfig()" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center justify-between w-full">
            <span>⚙️ FalkorDB Credentials & Connection</span>
            <span id="config-toggle-arrow">▼</span>
          </button>
          
          <div id="config-drawer" class="hidden mt-3 space-y-3 bg-slate-950 p-3 rounded-lg border border-slate-800">
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_HOST</label>
              <input type="text" id="cfg-host" placeholder="e.g. falkordb.cloud" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_PORT</label>
              <input type="text" id="cfg-port" value="6379" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_USER</label>
              <input type="text" id="cfg-user" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_PASS</label>
              <input type="password" id="cfg-pass" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5">
            </div>
            <button onclick="saveConfig()" class="w-full bg-slate-800 hover:bg-slate-700 text-xs text-white py-1.5 rounded font-medium transition">
              Connect & Verify
            </button>
          </div>
        </div>
      </div>

    </div>

    <!-- Right Column: Results & Tabs (8 cols) -->
    <div class="lg:col-span-8 space-y-6">

      <!-- Navigation Tabs -->
      <div class="flex border-b border-slate-800 space-x-1">
        <button onclick="switchTab('decision')" id="tab-btn-decision" class="px-4 py-2.5 text-sm font-medium border-b-2 border-indigo-500 text-indigo-400">
          🎯 Decision & Actions
        </button>
        <button onclick="switchTab('explain')" id="tab-btn-explain" class="px-4 py-2.5 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200">
          🗺️ Graph Explainability
        </button>
        <button onclick="switchTab('health')" id="tab-btn-health" class="px-4 py-2.5 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200">
          📈 Repository Health & Bus-Factor
        </button>
      </div>

      <!-- Tab 1: Decision & Actions -->
      <div id="tab-decision" class="space-y-6">

        <!-- PR Details Header -->
        <div id="pr-card" class="bg-slate-900 border border-slate-800 rounded-xl p-5">
          <div class="flex items-start justify-between">
            <div>
              <div class="flex items-center space-x-2">
                <span id="pr-badge-num" class="font-mono text-xs px-2.5 py-1 rounded-md bg-indigo-900/60 border border-indigo-700/60 text-indigo-300 font-semibold">PR #13997</span>
                <span id="pr-badge-state" class="text-xs px-2 py-0.5 rounded-md bg-emerald-900/60 border border-emerald-700/60 text-emerald-300">MERGED</span>
              </div>
              <h3 id="pr-title" class="text-base font-semibold text-white mt-2">Fix JSON Schema generation for nested generic models and union types</h3>
              <p class="text-xs text-slate-400 mt-1">
                Author: <span id="pr-author" class="font-mono text-slate-300 font-medium">adriangb</span> &middot;
                Files Changed: <span id="pr-files-count" class="font-mono text-slate-300">4</span>
              </p>
            </div>
          </div>
          
          <div id="pr-files-list" class="mt-3 flex flex-wrap gap-1.5 pt-3 border-t border-slate-800/80">
            <!-- Touched files will be inserted here -->
          </div>
        </div>

        <!-- Plan Trace -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-200 flex items-center space-x-2">
              <span>📋</span>
              <span>Agent Plan Execution Trace</span>
            </h3>
            <span class="text-xs text-slate-500 font-mono">no-llm &middot; deterministic</span>
          </div>
          <div id="plan-trace" class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 space-y-1.5 text-xs font-mono text-slate-300 overflow-x-auto">
            <!-- Trace lines -->
          </div>
        </div>

        <!-- Risk Flags Alert -->
        <div id="risk-container" class="space-y-2">
          <!-- Dynamic risk cards -->
        </div>

        <!-- Reviewer Recommendations Table -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>👥</span>
                <span>Recommended Reviewers</span>
              </h3>
              <p id="rationale-text" class="text-xs text-indigo-300 mt-0.5 italic"></p>
            </div>
            <span class="text-xs text-slate-400">Score based on multi-hop overlap & recency</span>
          </div>

          <div class="overflow-x-auto">
            <table class="w-full text-left text-xs">
              <thead class="text-slate-400 border-b border-slate-800 uppercase font-semibold">
                <tr>
                  <th class="py-2.5 px-3">Rank</th>
                  <th class="py-2.5 px-3">Reviewer</th>
                  <th class="py-2.5 px-3 text-right">Graph Score</th>
                  <th class="py-2.5 px-3 text-right">Shared Files</th>
                  <th class="py-2.5 px-3 text-right">Recent Reviews</th>
                  <th class="py-2.5 px-3">Last Active</th>
                </tr>
              </thead>
              <tbody id="reviewers-body" class="divide-y divide-slate-800/60 font-mono">
                <!-- Reviewer rows -->
              </tbody>
            </table>
          </div>
        </div>

        <!-- Proposed Actions & Approval Gate -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>⚡</span>
                <span>Proposed Actions (Approval Gate)</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Automated actions proposed by Keystone awaiting human verification</p>
            </div>
            <span class="text-xs px-2.5 py-1 rounded bg-amber-950/60 border border-amber-800/60 text-amber-300 font-medium">Pending Decisions</span>
          </div>

          <div id="actions-container" class="space-y-3">
            <!-- Action cards -->
          </div>
        </div>

      </div>

      <!-- Tab 2: Graph Explainability -->
      <div id="tab-explain" class="hidden space-y-6">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div>
            <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
              <span>🔍</span>
              <span>Multi-Hop Subgraph Traversal Path</span>
            </h3>
            <p id="explain-header" class="text-xs text-slate-400 mt-1">Explaining connection between target PR and top reviewer candidate</p>
          </div>

          <!-- Visual Graph Diagram -->
          <div id="graph-walk" class="bg-slate-950 border border-slate-800 rounded-lg p-5 space-y-4">
            <!-- Graph walk nodes -->
          </div>

          <div class="mt-4 pt-4 border-t border-slate-800">
            <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Connecting Files in Repo:</h4>
            <div id="explain-files" class="space-y-2">
              <!-- Files listed here -->
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 3: Repository Knowledge Health -->
      <div id="tab-health" class="hidden space-y-6">
        <div class="grid grid-cols-1 md:grid-cols-2 gap-6">

          <!-- Bus Factor -->
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-rose-300 flex items-center space-x-2">
                <span>⚠️</span>
                <span>Bus-Factor Risk Files</span>
              </h3>
              <span class="text-[11px] text-slate-500">>60% reviews by 1 engineer</span>
            </div>
            <p class="text-xs text-slate-400">Critical files with high knowledge concentration risk in the last 90 days:</p>
            <div id="bus-factor-list" class="space-y-2 max-h-96 overflow-y-auto pr-1">
              <!-- Bus factor items -->
            </div>
          </div>

          <!-- Betweenness Centrality -->
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-indigo-300 flex items-center space-x-2">
                <span>🌐</span>
                <span>Critical Files (Centrality)</span>
              </h3>
              <span class="text-[11px] text-slate-500">Betweenness on CO_CHANGES</span>
            </div>
            <p class="text-xs text-slate-400">Core architectural bridging files that co-change most frequently:</p>
            <div id="critical-files-list" class="space-y-2 max-h-96 overflow-y-auto pr-1">
              <!-- Critical files -->
            </div>
          </div>

        </div>
      </div>

    </div>

  </main>

  <script>
    let currentResult = null;

    async function init() {
      await fetchStatus();
      await fetchInsights();
      await runInvestigation();
    }

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        const data = await res.json();
        document.getElementById('stat-nodes').innerText = data.nodes.toLocaleString();
        document.getElementById('stat-edges').innerText = data.edges.toLocaleString();
        
        const pill = document.getElementById('conn-pill');
        const txt = document.getElementById('conn-text');
        if (data.is_live) {
          pill.className = "flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-700/60 text-emerald-300";
          txt.innerText = data.message;
        } else {
          pill.className = "flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-amber-950/60 border border-amber-700/60 text-amber-300";
          txt.innerText = "Sandbox Graph (pydantic benchmark)";
        }
      } catch (err) {
        console.error("Status error", err);
      }
    }

    async function fetchInsights() {
      try {
        const res = await fetch('/api/insights');
        const data = await res.json();
        
        // Render Bus Factor
        const bfList = document.getElementById('bus-factor-list');
        bfList.innerHTML = data.bus_factor.map(b => `
          <div class="bg-slate-950 border border-rose-900/40 rounded-lg p-3 text-xs">
            <div class="font-mono text-slate-200 font-medium truncate">${b.path}</div>
            <div class="flex items-center justify-between mt-1 text-slate-400">
              <span>Sole Reviewer: <strong class="text-rose-400 font-mono">${b.sole_reviewer}</strong></span>
              <span>${b.sole_count} / ${b.total} reviews (${Math.round(b.sole_count / b.total * 100)}%)</span>
            </div>
          </div>
        `).join('');

        // Render Critical Files
        const cfList = document.getElementById('critical-files-list');
        cfList.innerHTML = data.critical_files.map(c => `
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs flex items-center justify-between">
            <span class="font-mono text-slate-200 truncate pr-2">${c.path}</span>
            <span class="font-mono px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800 text-indigo-300 font-medium">
              ${c.score.toFixed(3)}
            </span>
          </div>
        `).join('');

      } catch (err) {
        console.error("Insights error", err);
      }
    }

    function selectPr(num) {
      document.getElementById('pr-input').value = num;
      runInvestigation();
    }

    async function runInvestigation() {
      const pr = parseInt(document.getElementById('pr-input').value) || 13997;
      const question = document.getElementById('question-input').value || "who should review this?";

      const btn = document.getElementById('run-btn');
      const icon = document.getElementById('btn-icon');
      const label = document.getElementById('btn-label');
      icon.innerText = "⏳";
      label.innerText = "Running Graph Tools...";
      btn.disabled = true;

      try {
        const res = await fetch('/api/investigate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pr_number: pr, question: question })
        });
        currentResult = await res.json();
        renderResult(currentResult);
      } catch (err) {
        alert("Failed to run Keystone: " + err);
      } finally {
        icon.innerText = "🚀";
        label.innerText = "Run Keystone Agent";
        btn.disabled = false;
      }
    }

    function renderResult(data) {
      const pr = data.pr_details || {};
      document.getElementById('pr-badge-num').innerText = `PR #${data.pr_number}`;
      document.getElementById('pr-badge-state').innerText = pr.state || 'MERGED';
      document.getElementById('pr-title').innerText = pr.title || `Pull Request #${data.pr_number}`;
      document.getElementById('pr-author').innerText = pr.author || 'contributor';
      document.getElementById('pr-files-count').innerText = (pr.files || []).length;

      const filesList = document.getElementById('pr-files-list');
      filesList.innerHTML = (pr.files || []).map(f => `
        <span class="font-mono text-[11px] px-2 py-1 rounded bg-slate-950 border border-slate-800 text-slate-300">
          📄 ${f}
        </span>
      `).join('');

      // Plan Trace
      const traceBox = document.getElementById('plan-trace');
      traceBox.innerHTML = (data.trace || []).map(line => `
        <div class="hover:text-white transition">
          <span class="text-indigo-400 font-bold">&gt;</span> ${line}
        </div>
      `).join('');

      // Rationale / Narration
      const summaryText = data.narration || data.decision?.rationale || "";
      document.getElementById('rationale-text').innerText = summaryText ? `"${summaryText}"` : "";

      // Risk Flags
      const riskContainer = document.getElementById('risk-container');
      const flags = data.decision?.risk_flags || [];
      if (flags.length === 0) {
        riskContainer.innerHTML = `
          <div class="bg-emerald-950/40 border border-emerald-800/60 rounded-xl p-3.5 flex items-center space-x-3 text-xs text-emerald-300">
            <span class="text-base">✅</span>
            <span>No knowledge coverage gaps or stale reviewer risks detected on this PR's files.</span>
          </div>
        `;
      } else {
        riskContainer.innerHTML = flags.map(flag => `
          <div class="bg-rose-950/40 border border-rose-800/60 rounded-xl p-3.5 flex items-start space-x-3 text-xs text-rose-300">
            <span class="text-base">🚩</span>
            <div>
              <div class="font-semibold uppercase tracking-wider text-[11px]">Knowledge Risk Detected</div>
              <div class="font-mono mt-0.5">${flag}</div>
            </div>
          </div>
        `).join('');
      }

      // Reviewers Table
      const revBody = document.getElementById('reviewers-body');
      const reviewers = data.decision?.reviewers || [];
      if (reviewers.length === 0) {
        revBody.innerHTML = `<tr><td colspan="6" class="text-center py-6 text-slate-500">No candidate reviewer above threshold.</td></tr>`;
      } else {
        revBody.innerHTML = reviewers.map((r, i) => `
          <tr class="hover:bg-slate-800/40 transition">
            <td class="py-2.5 px-3">
              <span class="w-5 h-5 inline-flex items-center justify-center rounded-full ${i === 0 ? 'bg-indigo-600 text-white font-bold' : 'bg-slate-800 text-slate-400'} text-[11px]">
                ${i + 1}
              </span>
            </td>
            <td class="py-2.5 px-3 font-semibold text-white flex items-center space-x-2">
              <span class="text-slate-400">@</span><span>${r.login}</span>
            </td>
            <td class="py-2.5 px-3 text-right">
              <span class="px-2 py-0.5 rounded bg-indigo-950 border border-indigo-700/60 text-indigo-300 font-semibold">
                ${r.score.toFixed(3)}
              </span>
            </td>
            <td class="py-2.5 px-3 text-right text-slate-300">${r.shared_files}</td>
            <td class="py-2.5 px-3 text-right text-slate-300">${r.recent_reviews}</td>
            <td class="py-2.5 px-3 text-slate-400">${r.last_review ? r.last_review.slice(0, 10) : 'N/A'}</td>
          </tr>
        `).join('');
      }

      // Proposed Actions
      const actContainer = document.getElementById('actions-container');
      const actions = data.proposed_actions || [];
      if (actions.length === 0) {
        actContainer.innerHTML = `<div class="text-xs text-slate-500">No actions required.</div>`;
      } else {
        actContainer.innerHTML = actions.map((act, i) => {
          const target = act.who || act.label;
          const actName = act.action.replace('_', ' ').toUpperCase();
          return `
            <div id="act-card-${i}" class="bg-slate-950 border border-slate-800 rounded-lg p-3.5 flex items-center justify-between">
              <div>
                <span class="text-xs font-semibold px-2 py-0.5 rounded bg-slate-800 text-slate-300 mr-2">${actName}</span>
                <span class="font-mono text-sm text-indigo-300 font-medium">${target}</span>
                <span class="text-xs text-slate-500 ml-2">on PR #${act.on}</span>
              </div>
              <div id="act-actions-${i}" class="flex items-center space-x-2">
                <button onclick="approveAction(${i}, '${act.action}', '${target}')" class="bg-emerald-600/80 hover:bg-emerald-600 text-white text-xs px-3 py-1.5 rounded transition">
                  ✓ Approve
                </button>
                <button onclick="rejectAction(${i}, '${act.action}', '${target}')" class="bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs px-3 py-1.5 rounded transition">
                  ✕ Reject
                </button>
              </div>
            </div>
          `;
        }).join('');
      }

      // Explainability Tab
      renderExplainability(data);
    }

    function approveAction(idx, action, target) {
      const container = document.getElementById(`act-actions-${idx}`);
      container.innerHTML = `<span class="text-xs font-semibold text-emerald-400 bg-emerald-950/60 border border-emerald-800 px-2.5 py-1 rounded">✓ Approved (${action})</span>`;
    }

    function rejectAction(idx, action, target) {
      const container = document.getElementById(`act-actions-${idx}`);
      container.innerHTML = `<span class="text-xs font-semibold text-slate-400 bg-slate-800 px-2.5 py-1 rounded">✕ Rejected</span>`;
    }

    function renderExplainability(data) {
      const pathData = data.explain_path || {};
      const topRev = (data.decision?.reviewers || [])[0]?.login || "davidhewitt";
      document.getElementById('explain-header').innerText = `Why ${topRev} was selected via shared graph paths:`;

      const walkBox = document.getElementById('graph-walk');
      const files = pathData.files || [];
      
      walkBox.innerHTML = `
        <div class="flex items-center space-x-3 text-xs font-mono">
          <div class="px-3 py-2 bg-indigo-900/60 border border-indigo-700 rounded-lg text-indigo-200 font-semibold">
            Target PR #${data.pr_number}
          </div>
          <div class="text-slate-500">──[touches]──▶</div>
          <div class="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 font-semibold">
            ${files.length} Shared File(s)
          </div>
          <div class="text-slate-500">◀──[touches]──</div>
          <div class="px-3 py-2 bg-slate-800 border border-slate-700 rounded-lg text-slate-200 font-semibold">
            Past Merged PRs
          </div>
          <div class="text-slate-500">◀──[reviewed]──</div>
          <div class="px-3 py-2 bg-emerald-900/60 border border-emerald-700 rounded-lg text-emerald-200 font-semibold">
            @${topRev}
          </div>
        </div>
      `;

      const filesBox = document.getElementById('explain-files');
      filesBox.innerHTML = files.map(f => `
        <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs font-mono flex items-center justify-between">
          <div class="flex items-center space-x-2 truncate">
            <span class="text-indigo-400">📄</span>
            <span class="text-slate-200">${f}</span>
          </div>
          <span class="text-slate-500 text-[11px]">Verified Past Reviews in Graph</span>
        </div>
      `).join('');
    }

    function switchTab(tab) {
      document.getElementById('tab-decision').classList.add('hidden');
      document.getElementById('tab-explain').classList.add('hidden');
      document.getElementById('tab-health').classList.add('hidden');

      document.getElementById('tab-btn-decision').className = "px-4 py-2.5 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200";
      document.getElementById('tab-btn-explain').className = "px-4 py-2.5 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200";
      document.getElementById('tab-btn-health').className = "px-4 py-2.5 text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200";

      document.getElementById(`tab-${tab}`).classList.remove('hidden');
      document.getElementById(`tab-btn-${tab}`).className = "px-4 py-2.5 text-sm font-medium border-b-2 border-indigo-500 text-indigo-400";
    }

    function toggleConfig() {
      const drawer = document.getElementById('config-drawer');
      const arrow = document.getElementById('config-toggle-arrow');
      drawer.classList.toggle('hidden');
      arrow.innerText = drawer.classList.contains('hidden') ? '▼' : '▲';
    }

    async function saveConfig() {
      const host = document.getElementById('cfg-host').value;
      const port = document.getElementById('cfg-port').value;
      const user = document.getElementById('cfg-user').value;
      const pass = document.getElementById('cfg-pass').value;

      try {
        const res = await fetch('/api/config', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ host, port, user, pass })
        });
        const data = await res.json();
        alert(data.message);
        await fetchStatus();
      } catch (err) {
        alert("Failed to update config: " + err);
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
async def api_status():
    status = get_connection_status()
    return JSONResponse({
        "nodes": node_count(),
        "edges": edge_count(),
        "is_live": status.get("is_live", False),
        "message": status.get("message", "FalkorDB")
    })

@app.post("/api/investigate")
async def api_investigate(req: Request):
    body = await req.json()
    pr_num = int(body.get("pr_number", 13997))
    question = body.get("question", "who should review this?")

    result = run_keystone(pr_num, question)
    pr_info = get_pr(pr_num)

    top_rev = "davidhewitt"
    if result["decision"]["reviewers"]:
        top_rev = result["decision"]["reviewers"][0]["login"]

    path_info = explain_path(pr_num, top_rev)
    narration_text = narrate(result["decision"], pr_info)

    return JSONResponse({
        **result,
        "pr_details": pr_info,
        "explain_path": path_info,
        "narration": narration_text
    })

@app.get("/api/insights")
async def api_insights():
    bf = bus_factor_files(default_cutoff())
    cf = critical_files(10)
    return JSONResponse({
        "bus_factor": bf,
        "critical_files": cf
    })

@app.post("/api/config")
async def api_config(req: Request):
    body = await req.json()
    os.environ["FALKOR_HOST"] = body.get("host", "")
    os.environ["FALKOR_PORT"] = body.get("port", "6379")
    os.environ["FALKOR_USER"] = body.get("user", "")
    os.environ["FALKOR_PASS"] = body.get("pass", "")

    get_graph.cache_clear()
    status = get_connection_status()
    return JSONResponse({"success": True, "message": status.get("message", "Updated")})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")