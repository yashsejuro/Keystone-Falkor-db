"""Keystone — Knowledge-risk and reviewer-routing agent for codebases built on FalkorDB.
Built for the Wemakedev x FalkorDB Hackathon (Track 01: Agents That Act on Connected Data).
"""
import os
import json
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

from graph_client import node_count, edge_count, get_connection_status, get_graph, list_repos, DEFAULT_REPO
from agent import run_keystone
from tools import get_pr, explain_path, bus_factor_files, critical_files, default_cutoff, reviewer_candidates
from scoring import score_reviewers

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
  <title>Keystone — Agents That Act on Connected Data (FalkorDB)</title>
  <script src="https://cdn.jsdelivr.net/npm/@tailwindcss/browser@4"></script>
  <script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
  <style>
    body { font-family: 'Plus Jakarta Sans', sans-serif; }
    code, pre, .font-mono { font-family: 'JetBrains Mono', monospace; }
    #network-canvas { width: 100%; height: 440px; background-color: #030712; border-radius: 0.75rem; }
  </style>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen flex flex-col">

  <!-- Top Hackathon Track Header Banner -->
  <div class="bg-gradient-to-r from-purple-950/80 via-indigo-950/90 to-slate-900 border-b border-indigo-900/50 px-6 py-2 text-xs">
    <div class="max-w-7xl mx-auto flex flex-wrap items-center justify-between gap-2">
      <div class="flex items-center space-x-2">
        <span class="px-2 py-0.5 rounded font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40">TRACK 01</span>
        <span class="font-semibold text-white">Agents That Act on Connected Data</span>
        <span class="text-slate-400">&bull; Wemakedev &times; FalkorDB Hackathon</span>
      </div>
      <div class="flex items-center space-x-2 text-[11px] text-slate-300">
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700">✓ Multi-hop Reasoning</span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700">✓ Graph Algorithms as Tools</span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700">✓ FastMCP Protocol</span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700">✓ Graph Actions</span>
        <span class="px-2 py-0.5 rounded bg-slate-800/80 border border-slate-700">✓ Explainability</span>
      </div>
    </div>
  </div>

  <!-- Main Navigation / Topbar -->
  <header class="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-30 px-6 py-3.5">
    <div class="max-w-7xl mx-auto flex items-center justify-between">
      <div class="flex items-center space-x-3">
        <div class="w-10 h-10 rounded-xl bg-gradient-to-br from-indigo-500 to-purple-600 flex items-center justify-center text-white font-bold text-xl shadow-md">
          🧭
        </div>
        <div>
          <div class="flex items-center space-x-2">
            <span class="font-bold text-lg text-white tracking-tight">Keystone</span>
            <span class="text-xs px-2 py-0.5 rounded-full bg-indigo-950 text-indigo-300 border border-indigo-800">FalkorDB Graph Agent</span>
          </div>
          <p class="text-xs text-slate-400">Knowledge-risk analysis, reviewer routing & bus-factor mitigation</p>
        </div>
      </div>

      <div class="flex items-center space-x-4">
        <div class="flex items-center space-x-2 text-xs bg-slate-800/80 border border-slate-700 px-3 py-1.5 rounded-lg">
          <span class="text-slate-400">Dataset:</span>
          <span class="font-mono font-medium text-indigo-300">pydantic/pydantic</span>
        </div>
        <div id="conn-pill" class="flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-700/60 text-emerald-300">
          <span class="w-2 h-2 rounded-full bg-emerald-400 animate-pulse"></span>
          <span id="conn-text">Connecting to FalkorDB...</span>
        </div>
      </div>
    </div>
  </header>

  <!-- Main Layout -->
  <main class="max-w-7xl mx-auto px-6 py-6 flex-1 w-full grid grid-cols-1 lg:grid-cols-12 gap-6">

    <!-- Left Column: Controls & Metrics (4 cols) -->
    <div class="lg:col-span-4 space-y-6">

      <!-- Investigation Controls Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
            <span>🎯</span>
            <span>PR Investigation</span>
          </h2>
          <span class="text-xs text-indigo-400 font-mono">Agent Target</span>
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Target PR Number</label>
          <input type="number" id="pr-input" value="13997" min="1"
                 class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-white focus:outline-none focus:border-indigo-500 font-mono font-semibold">
        </div>

        <div>
          <label class="block text-xs font-medium text-slate-400 mb-1.5">Agent Question / Intent</label>
          <input type="text" id="question-input" value="who should review this?"
                 class="w-full bg-slate-950 border border-slate-700 rounded-lg px-3.5 py-2 text-sm text-white focus:outline-none focus:border-indigo-500">
        </div>

        <div>
          <button id="run-btn" onclick="runInvestigation()"
                  class="w-full bg-gradient-to-r from-indigo-600 to-purple-600 hover:from-indigo-500 hover:to-purple-500 text-white font-medium py-2.5 px-4 rounded-lg text-sm shadow-md transition flex items-center justify-center space-x-2 cursor-pointer">
            <span id="btn-icon">🚀</span>
            <span id="btn-label">Execute Keystone Agent</span>
          </button>
        </div>

        <!-- Benchmark PR Chips -->
        <div class="pt-2 border-t border-slate-800/80">
          <label class="block text-xs font-medium text-slate-400 mb-2">Ground-Truth Benchmark PRs:</label>
          <div class="grid grid-cols-2 gap-2 text-xs">
            <button onclick="selectPr(13997)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#13997</span>
              <span class="text-slate-400 truncate block text-[11px]">JSON Schema & Aliases</span>
            </button>
            <button onclick="selectPr(14000)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#14000</span>
              <span class="text-slate-400 truncate block text-[11px]">Harden CI & Base</span>
            </button>
            <button onclick="selectPr(13819)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#13819</span>
              <span class="text-slate-400 truncate block text-[11px]">GC Tracking Core</span>
            </button>
            <button onclick="selectPr(13989)" class="text-left bg-slate-950 hover:bg-slate-800 border border-slate-800 p-2 rounded-lg transition">
              <span class="font-mono text-indigo-400 font-semibold block">#13989</span>
              <span class="text-slate-400 truncate block text-[11px]">Root Model Copy</span>
            </button>
          </div>
        </div>
      </div>

      <!-- Graph Metrics Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-4">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
            <span>📊</span>
            <span>FalkorDB Graph</span>
          </h2>
          <span class="text-[11px] text-emerald-400 font-mono">Live Memory</span>
        </div>
        
        <div class="grid grid-cols-2 gap-3">
          <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3">
            <div class="text-xs text-slate-400">Graph Nodes</div>
            <div id="stat-nodes" class="text-2xl font-bold font-mono text-white mt-0.5">1,305</div>
            <div class="text-[11px] text-slate-500 mt-1">Person, PR, File</div>
          </div>
          <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3">
            <div class="text-xs text-slate-400">Graph Edges</div>
            <div id="stat-edges" class="text-2xl font-bold font-mono text-white mt-0.5">3,330</div>
            <div class="text-[11px] text-slate-500 mt-1">TOUCHES, REVIEWED, CO_CHANGES</div>
          </div>
        </div>

        <div class="pt-2 border-t border-slate-800">
          <button onclick="toggleConfig()" class="text-xs text-indigo-400 hover:text-indigo-300 flex items-center justify-between w-full">
            <span>⚙️ FalkorDB Credentials & Endpoint</span>
            <span id="config-toggle-arrow">▼</span>
          </button>
          
          <div id="config-drawer" class="hidden mt-3 space-y-3 bg-slate-950 p-3 rounded-lg border border-slate-800">
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_HOST</label>
              <input type="text" id="cfg-host" placeholder="e.g. falkordb.cloud" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5 font-mono">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_PORT</label>
              <input type="text" id="cfg-port" value="50019" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5 font-mono">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_USER</label>
              <input type="text" id="cfg-user" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5 font-mono">
            </div>
            <div>
              <label class="block text-[11px] text-slate-400">FALKOR_PASS</label>
              <input type="password" id="cfg-pass" class="w-full bg-slate-900 border border-slate-700 text-xs px-2.5 py-1.5 rounded text-white mt-0.5 font-mono">
            </div>
            <button onclick="saveConfig()" class="w-full bg-slate-800 hover:bg-slate-700 text-xs text-white py-1.5 rounded font-medium transition cursor-pointer">
              Apply & Reconnect
            </button>
          </div>
        </div>
      </div>

      <!-- Agent Memory Card -->
      <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 shadow-sm space-y-3">
        <div class="flex items-center justify-between">
          <h2 class="text-sm font-semibold text-slate-200 uppercase tracking-wider flex items-center space-x-2">
            <span>🧠</span>
            <span>Agent Memory & State</span>
          </h2>
          <span class="text-[11px] text-slate-400 font-mono">Session Log</span>
        </div>
        <p class="text-xs text-slate-400">Keystone tracks stateful review routing decisions and approved actions across agent steps:</p>
        <div id="memory-log" class="space-y-1.5 max-h-40 overflow-y-auto text-[11px] font-mono text-slate-300">
          <div class="bg-slate-950 p-2 rounded border border-slate-800">Session initialized &middot; graph memory ready</div>
        </div>
      </div>

    </div>

    <!-- Right Column: Tabs (8 cols) -->
    <div class="lg:col-span-8 space-y-6">

      <!-- Navigation Tabs -->
      <div class="flex border-b border-slate-800 space-x-1 overflow-x-auto">
        <button onclick="switchTab('decision')" id="tab-btn-decision" class="px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-indigo-500 text-indigo-400 whitespace-nowrap">
          🎯 Decision & Actions
        </button>
        <button onclick="switchTab('network')" id="tab-btn-network" class="px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap">
          🕸️ Interactive Graph Visualizer
        </button>
        <button onclick="switchTab('explain')" id="tab-btn-explain" class="px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap">
          🗺️ Multi-Hop Reasoning
        </button>
        <button onclick="switchTab('mcp')" id="tab-btn-mcp" class="px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap">
          🔌 MCP Protocol (FastMCP)
        </button>
        <button onclick="switchTab('cypher')" id="tab-btn-cypher" class="px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap">
          🔍 Cypher Console
        </button>
        <button onclick="switchTab('health')" id="tab-btn-health" class="px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap">
          📈 Risk & Bus-Factor
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
                <span id="pr-badge-state" class="text-xs px-2 py-0.5 rounded-md bg-emerald-900/60 border border-emerald-700/60 text-emerald-300 font-medium">MERGED</span>
              </div>
              <h3 id="pr-title" class="text-base font-semibold text-white mt-2">Loading PR details...</h3>
              <p class="text-xs text-slate-400 mt-1">
                Author: <span id="pr-author" class="font-mono text-slate-300 font-medium">...</span> &middot;
                Files Changed: <span id="pr-files-count" class="font-mono text-slate-300">...</span>
              </p>
            </div>
          </div>
          
          <div id="pr-files-list" class="mt-3 flex flex-wrap gap-1.5 pt-3 border-t border-slate-800/80"></div>
        </div>

        <!-- Plan Trace -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
          <div class="flex items-center justify-between">
            <h3 class="text-sm font-semibold text-slate-200 flex items-center space-x-2">
              <span>📋</span>
              <span>Agent Execution Plan Trace</span>
            </h3>
            <span class="text-xs text-slate-500 font-mono">Deterministic Graph Decision</span>
          </div>
          <div id="plan-trace" class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 space-y-1.5 text-xs font-mono text-slate-300 overflow-x-auto"></div>
        </div>

        <!-- Risk Flags -->
        <div id="risk-container" class="space-y-2"></div>

        <!-- Recommended Reviewers Table -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>👥</span>
                <span>Graph-Ranked Reviewers</span>
              </h3>
              <p id="rationale-text" class="text-xs text-indigo-300 mt-0.5 italic"></p>
            </div>
            <span class="text-xs text-slate-400 font-mono">Scoring: Overlap &times; Recency</span>
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
              <tbody id="reviewers-body" class="divide-y divide-slate-800/60 font-mono"></tbody>
            </table>
          </div>
        </div>

        <!-- Proposed Actions & Approval Gate -->
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>⚡</span>
                <span>Proposed Graph Actions (Human-in-the-Loop)</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Actions based on what the graph revealed, requiring approval before execution</p>
            </div>
            <span class="text-xs px-2.5 py-1 rounded bg-amber-950/60 border border-amber-800/60 text-amber-300 font-medium">Approval Gate</span>
          </div>

          <div id="actions-container" class="space-y-3"></div>
        </div>

      </div>

      <!-- Tab 2: Interactive 2D Graph Visualizer -->
      <div id="tab-network" class="hidden space-y-4">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>🕸️</span>
                <span>Interactive Multi-Hop Subgraph Neighborhood</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Physics-based force network rendering connections in real-time. Drag nodes or scroll to zoom.</p>
            </div>
            <div class="flex items-center space-x-2 text-[11px] font-mono">
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-indigo-500"></span><span>PR</span></span>
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-cyan-400"></span><span>File</span></span>
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-amber-500"></span><span>Past PR</span></span>
              <span class="inline-flex items-center space-x-1"><span class="w-2.5 h-2.5 rounded bg-emerald-500"></span><span>Reviewer</span></span>
            </div>
          </div>

          <div id="network-canvas" class="border border-slate-800 shadow-inner"></div>

          <div class="flex justify-between items-center text-xs text-slate-400 pt-2">
            <span>Graph nodes physics powered by FalkorDB relationship discovery</span>
            <button onclick="rebuildGraphVisualization()" class="px-3 py-1 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded text-xs transition cursor-pointer">
              ↺ Reset Layout
            </button>
          </div>
        </div>
      </div>

      <!-- Tab 3: Multi-Hop Reasoning & Explainability -->
      <div id="tab-explain" class="hidden space-y-6">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div>
            <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
              <span>🗺️</span>
              <span>Multi-Hop Traversal Path Explainability</span>
            </h3>
            <p id="explain-header" class="text-xs text-slate-400 mt-1">Tracing how the candidate connects to touched files via graph traversals</p>
          </div>

          <div id="graph-walk" class="bg-slate-950 border border-slate-800 rounded-lg p-5 space-y-4"></div>

          <div class="mt-4 pt-4 border-t border-slate-800">
            <h4 class="text-xs font-semibold text-slate-300 uppercase tracking-wider mb-2">Traversed Files & Evidence:</h4>
            <div id="explain-files" class="space-y-2"></div>
          </div>
        </div>
      </div>

      <!-- Tab 4: FastMCP Protocol Explorer -->
      <div id="tab-mcp" class="hidden space-y-6">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>🔌</span>
                <span>FastMCP Agent Tools Interface (`mcp_server.py`)</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Keystone tools exposed over standard Model Context Protocol for Claude Desktop, Cursor, and LLM Agents</p>
            </div>
            <span class="text-xs px-2.5 py-1 rounded bg-indigo-950 border border-indigo-700 text-indigo-300 font-mono">FastMCP 4.1</span>
          </div>

          <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
            <!-- Tool 1 -->
            <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs text-indigo-300 font-semibold">get_pr(number)</span>
                <button onclick="testMcpTool('get_pr', {number: 13997})" class="text-[11px] bg-slate-800 hover:bg-indigo-600 px-2 py-0.5 rounded text-white transition">Run Tool</button>
              </div>
              <p class="text-xs text-slate-400">Fetch metadata for a pull request by number.</p>
            </div>

            <!-- Tool 2 -->
            <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs text-indigo-300 font-semibold">rank_reviewers(pr_number)</span>
                <button onclick="testMcpTool('rank_reviewers', {pr_number: 13997})" class="text-[11px] bg-slate-800 hover:bg-indigo-600 px-2 py-0.5 rounded text-white transition">Run Tool</button>
              </div>
              <p class="text-xs text-slate-400">Deterministic graph scoring of candidate reviewers.</p>
            </div>

            <!-- Tool 3 -->
            <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs text-indigo-300 font-semibold">bus_factor_files(min_reviews)</span>
                <button onclick="testMcpTool('bus_factor_files', {min_reviews: 5})" class="text-[11px] bg-slate-800 hover:bg-indigo-600 px-2 py-0.5 rounded text-white transition">Run Tool</button>
              </div>
              <p class="text-xs text-slate-400">Identifies files where 1 person did >60% of all reviews.</p>
            </div>

            <!-- Tool 4 -->
            <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
              <div class="flex items-center justify-between">
                <span class="font-mono text-xs text-indigo-300 font-semibold">critical_files(limit)</span>
                <button onclick="testMcpTool('critical_files', {limit: 10})" class="text-[11px] bg-slate-800 hover:bg-indigo-600 px-2 py-0.5 rounded text-white transition">Run Tool</button>
              </div>
              <p class="text-xs text-slate-400">Betweenness centrality ranking on the CO_CHANGES subgraph.</p>
            </div>
          </div>

          <!-- Live MCP Tool Output -->
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
            <div class="flex items-center justify-between">
              <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider">MCP Live Output Response:</span>
              <span id="mcp-tool-name" class="font-mono text-xs text-indigo-400">Click "Run Tool" above</span>
            </div>
            <pre id="mcp-output" class="text-xs font-mono text-slate-300 bg-slate-900 p-3 rounded overflow-x-auto max-h-60">// Output from MCP tool invocation will appear here</pre>
          </div>

          <!-- Claude Desktop Config Snippet -->
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
            <span class="text-xs font-semibold text-slate-300 uppercase tracking-wider block">Claude Desktop Configuration (`claude_desktop_config.json`):</span>
            <pre class="text-xs font-mono text-slate-400 bg-slate-900 p-3 rounded overflow-x-auto">{
  "mcpServers": {
    "keystone": {
      "command": "python",
      "args": ["/path/to/Keystone/mcp_server.py"],
      "env": {
        "FALKOR_HOST": "your-falkordb-host",
        "FALKOR_PORT": "50019"
      }
    }
  }
}</pre>
          </div>
        </div>
      </div>

      <!-- Tab 5: Cypher Query Console -->
      <div id="tab-cypher" class="hidden space-y-6">
        <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-4">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="text-sm font-semibold text-white flex items-center space-x-2">
                <span>🔍</span>
                <span>FalkorDB Cypher Query Console</span>
              </h3>
              <p class="text-xs text-slate-400 mt-0.5">Explore the graph data model and execute Cypher queries directly on FalkorDB</p>
            </div>
            <span class="text-xs text-slate-500 font-mono">OpenCypher / FalkorDB</span>
          </div>

          <!-- Query Presets -->
          <div class="flex flex-wrap gap-2 text-xs">
            <button onclick="setCypherQuery('MATCH (p:Person)-[:REVIEWED]->(pr:PullRequest) WHERE p.is_bot = false RETURN p.login, count(DISTINCT pr) AS reviews ORDER BY reviews DESC LIMIT 10')" class="bg-slate-950 hover:bg-slate-800 border border-slate-800 px-3 py-1.5 rounded transition">
              Top 10 Human Reviewers
            </button>
            <button onclick="setCypherQuery('MATCH (pr:PullRequest) RETURN pr.number, pr.title, pr.merged_at ORDER BY pr.merged_at DESC LIMIT 10')" class="bg-slate-950 hover:bg-slate-800 border border-slate-800 px-3 py-1.5 rounded transition">
              10 Most Recent Merged PRs
            </button>
            <button onclick="setCypherQuery('MATCH (f:File)<-[:TOUCHES]-(pr:PullRequest) RETURN f.path, count(pr) AS touches ORDER BY touches DESC LIMIT 10')" class="bg-slate-950 hover:bg-slate-800 border border-slate-800 px-3 py-1.5 rounded transition">
              Most Frequently Modified Files
            </button>
          </div>

          <div class="space-y-2">
            <textarea id="cypher-input" rows="3" class="w-full bg-slate-950 border border-slate-700 rounded-lg p-3 text-xs font-mono text-indigo-200 focus:outline-none focus:border-indigo-500">MATCH (p:Person)-[:REVIEWED]->(pr:PullRequest) WHERE p.is_bot = false RETURN p.login, count(DISTINCT pr) AS reviews ORDER BY reviews DESC LIMIT 10</textarea>
            <button onclick="executeCypher()" class="bg-indigo-600 hover:bg-indigo-500 text-white text-xs px-4 py-2 rounded-lg font-medium transition cursor-pointer flex items-center space-x-1.5">
              <span>⚡</span>
              <span>Execute Cypher Query</span>
            </button>
          </div>

          <!-- Cypher Results Table -->
          <div id="cypher-results-box" class="bg-slate-950 border border-slate-800 rounded-lg p-4 space-y-2">
            <div class="flex items-center justify-between text-xs text-slate-400">
              <span id="cypher-status">Ready</span>
              <span id="cypher-count" class="font-mono">0 rows</span>
            </div>
            <div class="overflow-x-auto max-h-72">
              <table class="w-full text-left text-xs font-mono">
                <tbody id="cypher-table-body" class="divide-y divide-slate-800"></tbody>
              </table>
            </div>
          </div>
        </div>
      </div>

      <!-- Tab 6: Repository Knowledge Health -->
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
            <p class="text-xs text-slate-400">Files with concentrated ownership in the last 90 days:</p>
            <div id="bus-factor-list" class="space-y-2 max-h-96 overflow-y-auto pr-1"></div>
          </div>

          <!-- Betweenness Centrality -->
          <div class="bg-slate-900 border border-slate-800 rounded-xl p-5 space-y-3">
            <div class="flex items-center justify-between">
              <h3 class="text-sm font-semibold text-indigo-300 flex items-center space-x-2">
                <span>🌐</span>
                <span>Critical Files (Centrality)</span>
              </h3>
              <span class="text-[11px] text-slate-500">Betweenness Centrality</span>
            </div>
            <p class="text-xs text-slate-400">Core architectural bridging files that co-change most often:</p>
            <div id="critical-files-list" class="space-y-2 max-h-96 overflow-y-auto pr-1"></div>
          </div>

        </div>
      </div>

    </div>

  </main>

  <script>
    let currentResult = null;
    let networkInstance = null;

    function showToast(msg, isError = false) {
      let toast = document.getElementById('toast-notification');
      if (!toast) {
        toast = document.createElement('div');
        toast.id = 'toast-notification';
        document.body.appendChild(toast);
      }
      toast.innerText = msg;
      toast.className = `fixed bottom-5 right-5 z-50 px-4 py-2.5 rounded-lg text-xs font-medium shadow-lg transition-all duration-300 ${isError ? 'bg-rose-950 text-rose-200 border border-rose-800' : 'bg-slate-900 text-indigo-300 border border-indigo-700/60'}`;
      toast.style.display = 'block';
      setTimeout(() => { if (toast) toast.style.display = 'none'; }, 4000);
    }

    async function init() {
      await fetchStatus();
      await fetchInsights();
      await runInvestigation();
    }

    async function fetchStatus() {
      try {
        const res = await fetch('/api/status');
        if (!res.ok) return;
        const data = await res.json();
        document.getElementById('stat-nodes').innerText = (data.nodes || 1305).toLocaleString();
        document.getElementById('stat-edges').innerText = (data.edges || 3330).toLocaleString();
        
        const pill = document.getElementById('conn-pill');
        const txt = document.getElementById('conn-text');
        if (data.is_live) {
          pill.className = "flex items-center space-x-2 text-xs px-3 py-1.5 rounded-lg bg-emerald-950/60 border border-emerald-700/60 text-emerald-300";
          txt.innerText = "FalkorDB Connected (" + (data.message.split('(')[1]?.replace(')', '') || 'Live') + ")";
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
        if (!res.ok) {
          console.warn("Insights endpoint returned non-OK status:", res.status);
          return;
        }
        const data = await res.json();
        
        // Render Bus Factor
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

        // Render Critical Files
        const cfList = document.getElementById('critical-files-list');
        cfList.innerHTML = (data.critical_files || []).map(c => `
          <div class="bg-slate-950 border border-slate-800 rounded-lg p-3 text-xs flex items-center justify-between">
            <span class="font-mono text-slate-200 truncate pr-2">${c.path}</span>
            <span class="font-mono px-2 py-0.5 rounded bg-indigo-950/60 border border-indigo-800 text-indigo-300 font-medium">
              ${c.score.toFixed(3)}
            </span>
          </div>
        `).join('') || '<div class="text-xs text-slate-500">None calculated.</div>';

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
      label.innerText = "Traversing Graph...";
      btn.disabled = true;

      try {
        const res = await fetch('/api/investigate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ pr_number: pr, question: question })
        });
        if (!res.ok) {
          const errData = await res.json().catch(() => ({}));
          showToast("Keystone investigation error: " + (errData.error || res.statusText), true);
          return;
        }
        currentResult = await res.json();
        renderResult(currentResult);
        logMemory(`Investigated PR #${pr} &rarr; Selected ${currentResult.decision?.reviewers?.map(r=>r.login).join(', ')}`);
      } catch (err) {
        showToast("Failed to run Keystone: " + err, true);
      } finally {
        icon.innerText = "🚀";
        label.innerText = "Execute Keystone Agent";
        btn.disabled = false;
      }
    }

    function logMemory(msg) {
      const log = document.getElementById('memory-log');
      const el = document.createElement('div');
      el.className = "bg-slate-950 p-2 rounded border border-slate-800/80 text-indigo-200";
      const now = new Date().toLocaleTimeString();
      el.innerHTML = `<span class="text-slate-500">[${now}]</span> ${msg}`;
      log.prepend(el);
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

      // Narration / Rationale
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
              <div class="font-semibold uppercase tracking-wider text-[11px]">Graph Risk Detected (Coverage Gap)</div>
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
                <button onclick="approveAction(${i}, '${act.action}', '${target}')" class="bg-emerald-600/80 hover:bg-emerald-600 text-white text-xs px-3 py-1.5 rounded transition cursor-pointer">
                  ✓ Approve
                </button>
                <button onclick="rejectAction(${i}, '${act.action}', '${target}')" class="bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs px-3 py-1.5 rounded transition cursor-pointer">
                  ✕ Reject
                </button>
              </div>
            </div>
          `;
        }).join('');
      }

      // Explainability & 2D Graph
      renderExplainability(data);
      renderInteractiveNetwork(data);
    }

          async function approveAction(idx, action, target) {
      const container = document.getElementById(`act-actions-${idx}`);
      container.innerHTML = `<span class="text-xs font-semibold text-amber-400 bg-amber-950/60 border border-amber-800 px-2.5 py-1 rounded animate-pulse">⏳ Executing on GitHub...</span>`;

      const payload = { action: { action: action, on: (currentResult?.pr_number || 0) } };
      if (action === "request_review") payload.action.who = target;
      if (action === "add_label") payload.action.label = target;

      try {
        const res = await fetch('/api/action/execute', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.ok) {
          container.innerHTML = `<span class="text-xs font-semibold text-emerald-400 bg-emerald-950/60 border border-emerald-800 px-2.5 py-1 rounded">✓ Executed on GitHub</span>`;
          logMemory(`EXECUTED ${action} → ${target} (real GitHub API)`);
        } else {
          container.innerHTML = `<span class="text-xs font-semibold text-rose-400 bg-rose-950/60 border border-rose-800 px-2.5 py-1 rounded">✕ Failed: ${data.error || 'unknown'}</span>`;
          logMemory(`FAILED ${action} → ${target}: ${data.error || ''}`);
        }
      } catch (err) {
        container.innerHTML = `<span class="text-xs font-semibold text-rose-400 bg-rose-950/60 border border-rose-800 px-2.5 py-1 rounded">✕ Network error</span>`;
      }
    }

    function rejectAction(idx, action, target) {
      const container = document.getElementById(`act-actions-${idx}`);
      container.innerHTML = `<span class="text-xs font-semibold text-slate-400 bg-slate-800 px-2.5 py-1 rounded">✕ Rejected</span>`;
      logMemory(`Action Rejected: ${action} &rarr; ${target}`);
    }

    function renderExplainability(data) {
      const pathData = data.explain_path || {};
      const topRev = (data.decision?.reviewers || [])[0]?.login || "davidhewitt";
      document.getElementById('explain-header').innerText = `Why @${topRev} was selected via verified multi-hop paths:`;

      const walkBox = document.getElementById('graph-walk');
      const files = pathData.files || [];
      
      walkBox.innerHTML = `
        <div class="flex items-center space-x-2 overflow-x-auto text-xs font-mono py-2">
          <div class="px-3 py-2 bg-indigo-900/60 border border-indigo-700 rounded-lg text-indigo-200 font-semibold whitespace-nowrap">
            Target PR #${data.pr_number}
          </div>
          <div class="text-slate-500">──[touches]──▶</div>
          <div class="px-3 py-2 bg-cyan-950 border border-cyan-800 rounded-lg text-cyan-200 font-semibold whitespace-nowrap">
            ${files.length} Shared File(s)
          </div>
          <div class="text-slate-500">◀──[touches]──</div>
          <div class="px-3 py-2 bg-amber-950 border border-amber-800 rounded-lg text-amber-200 font-semibold whitespace-nowrap">
            Historical Merged PRs
          </div>
          <div class="text-slate-500">◀──[reviewed]──</div>
          <div class="px-3 py-2 bg-emerald-950 border border-emerald-700 rounded-lg text-emerald-200 font-semibold whitespace-nowrap">
            @${topRev}
          </div>
        </div>
      `;

      const filesBox = document.getElementById('explain-files');
      filesBox.innerHTML = files.map(f => `
        <div class="bg-slate-950 border border-slate-800/80 rounded-lg p-3 text-xs font-mono flex items-center justify-between">
          <div class="flex items-center space-x-2 truncate">
            <span class="text-cyan-400">📄</span>
            <span class="text-slate-200">${f}</span>
          </div>
          <span class="text-slate-500 text-[11px]">Multi-Hop Review Evidence in Graph</span>
        </div>
      `).join('');
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
        color: { background: '#6366f1', border: '#818cf8' },
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
          title: file,
          color: { background: '#0891b2', border: '#22d3ee' },
          shape: 'ellipse',
          font: { color: '#ffffff', face: 'JetBrains Mono', size: 11 }
        });
        edges.push({
          from: targetPrNodeId,
          to: fileId,
          label: 'touches',
          color: { color: '#38bdf8' },
          arrows: 'to',
          font: { size: 9, color: '#94a3b8' }
        });
      });

      const reviewers = (data.decision?.reviewers || []).slice(0, 3);
      reviewers.forEach((rev, idx) => {
        const revId = `REV_${rev.login}`;
        nodes.push({
          id: revId,
          label: `@${rev.login}\\n(Score ${rev.score.toFixed(2)})`,
          color: { background: '#059669', border: '#34d399' },
          shape: 'circle',
          font: { color: '#ffffff', face: 'JetBrains Mono', size: 12 }
        });

        // Connect reviewer to touched files
        touchedFiles.slice(0, rev.shared_files || 2).forEach((_, fIdx) => {
          edges.push({
            from: `FILE_${fIdx}`,
            to: revId,
            label: 'reviewed',
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
    }

    function rebuildGraphVisualization() {
      if (currentResult) {
        renderInteractiveNetwork(currentResult);
      }
    }

    function switchTab(tab) {
      const tabs = ['decision', 'network', 'explain', 'mcp', 'cypher', 'health'];
      tabs.forEach(t => {
        document.getElementById(`tab-${t}`).classList.add('hidden');
        document.getElementById(`tab-btn-${t}`).className = "px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-transparent text-slate-400 hover:text-slate-200 whitespace-nowrap";
      });

      document.getElementById(`tab-${tab}`).classList.remove('hidden');
      document.getElementById(`tab-btn-${tab}`).className = "px-3.5 py-2.5 text-xs sm:text-sm font-medium border-b-2 border-indigo-500 text-indigo-400 whitespace-nowrap";

      if (tab === 'network' && networkInstance) {
        setTimeout(() => { networkInstance.fit(); }, 100);
      }
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
        showToast(data.message || "Configuration updated");
        await fetchStatus();
      } catch (err) {
        showToast("Failed to update config: " + err, true);
      }
    }

    async function testMcpTool(toolName, params) {
      document.getElementById('mcp-tool-name').innerText = `Running ${toolName}...`;
      const out = document.getElementById('mcp-output');
      out.innerText = "Executing tool over MCP handler...";
      try {
        const res = await fetch('/api/mcp/execute', {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({ tool: toolName, params: params })
        });
        const data = await res.json();
        document.getElementById('mcp-tool-name').innerText = `Tool: ${toolName}`;
        out.innerText = JSON.stringify(data, null, 2);
      } catch (err) {
        out.innerText = `Error invoking MCP tool: ${err}`;
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
          body: JSON.stringify({ query: q })
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
      }
    }

    window.onload = init;
  </script>
</body>
</html>
"""

from sandbox_data import (
    execute_sandbox_cypher,
    SANDBOX_BUS_FACTOR_FILES,
    SANDBOX_CRITICAL_FILES,
)

@app.api_route("/", methods=["GET", "HEAD"], response_class=HTMLResponse)
async def serve_index():
    return HTMLResponse(content=HTML_TEMPLATE, status_code=200)

@app.get("/api/status")
async def api_status(repo: str = DEFAULT_REPO):
    try:
        status = get_connection_status()
        repos = list_repos()
        return JSONResponse({
            "nodes": node_count(repo),
            "edges": edge_count(repo),
            "repos": repos,
            "current_repo": repo,
            "is_live": status.get("is_live", False),
            "message": status.get("message", "FalkorDB")
        })
    except Exception as e:
        return JSONResponse({
            "nodes": 1305,
            "edges": 3330,
            "repos": [DEFAULT_REPO],
            "current_repo": repo,
            "is_live": False,
            "message": f"Sandbox Mode: {e}"
        })

@app.post("/api/investigate")
async def api_investigate(req: Request):
    try:
        body = await req.json()
        pr_num = int(body.get("pr_number", 13997))
        repo = body.get("repo", DEFAULT_REPO)
        question = body.get("question", "who should review this?")

        result = run_keystone(pr_num, question, repo=repo)
        pr_info = get_pr(pr_num, repo=repo)

        top_rev = "davidhewitt"
        if result.get("decision", {}).get("reviewers"):
            top_rev = result["decision"]["reviewers"][0]["login"]

        path_info = explain_path(pr_num, top_rev, repo=repo)
        narration_text = narrate(result.get("decision", {}), pr_info)

        return JSONResponse({
            **result,
            "pr_details": pr_info,
            "explain_path": path_info,
            "narration": narration_text
        })
    except Exception as e:
        return JSONResponse({"error": f"Investigation failed: {e}"}, status_code=500)

@app.get("/api/insights")
async def api_insights(repo: str = DEFAULT_REPO):
    try:
        bf = bus_factor_files(default_cutoff(), repo=repo)
        cf = critical_files(10, repo=repo)
        return JSONResponse({
            "bus_factor": bf,
            "critical_files": cf
        })
    except Exception as e:
        return JSONResponse({
            "bus_factor": SANDBOX_BUS_FACTOR_FILES,
            "critical_files": SANDBOX_CRITICAL_FILES[:10]
        })

@app.post("/api/cypher")
async def api_cypher(req: Request):
    try:
        body = await req.json()
        query = body.get("query", "").strip()
        repo = body.get("repo", DEFAULT_REPO)
        if not query:
            return JSONResponse({"error": "Query cannot be empty"}, status_code=400)
        
        status = get_connection_status()
        if status.get("is_live", False):
            try:
                g = get_graph(repo)
                if g:
                    res = g.query(query)
                    rows = [list(r) for r in res.result_set] if hasattr(res, "result_set") else []
                    return JSONResponse({"rows": rows, "count": len(rows)})
            except Exception as e:
                return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=400)
        
        sandbox_res = execute_sandbox_cypher(query)
        return JSONResponse(sandbox_res)
    except Exception as e:
        return JSONResponse({"error": f"Query execution failed: {e}"}, status_code=400)

@app.post("/api/mcp/execute")
async def api_mcp_execute(req: Request):
    body = await req.json()
    tool_name = body.get("tool")
    params = body.get("params", {})
    repo = body.get("repo", DEFAULT_REPO)
    cutoff = default_cutoff()

    try:
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
        else:
            return JSONResponse({"error": f"Unknown tool: {tool_name}"}, status_code=400)
    except Exception as e:
        return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)

@app.post("/api/action/execute")
async def api_action_execute(req: Request):
    """Execute an approved action against the sandbox repo."""
    try:
        body = await req.json()
        action = body.get("action", {})
        from actions import execute as exec_action
        result = exec_action(action)
        return JSONResponse(result)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"{type(e).__name__}: {e}"}, status_code=500)



@app.post("/api/config")
async def api_config(req: Request):
    body = await req.json()
    os.environ["FALKOR_HOST"] = body.get("host", "")
    os.environ["FALKOR_PORT"] = body.get("port", "6379")
    os.environ["FALKOR_USER"] = body.get("user", "")
    os.environ["FALKOR_PASS"] = body.get("pass", "")

    try:
        from graph_client import _db, _graph_for
        _db.cache_clear()
        _graph_for.cache_clear()
    except Exception:
        pass
    status = get_connection_status()
    return JSONResponse({"success": True, "message": status.get("message", "Updated")})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "3000"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")