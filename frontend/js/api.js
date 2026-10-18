/**
 * Keystone API Client
 * Clean async interface with pagination, cancellation, and error handling.
 */
const KeystoneAPI = {
  async getHealth() {
    const res = await fetch('/api/health');
    return res.json();
  },

  async getStatus(repo) {
    const res = await fetch(`/api/status?repo=${encodeURIComponent(repo)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Failed to fetch status (HTTP ${res.status})`);
    }
    return res.json();
  },

  async getRepositories() {
    const res = await fetch('/api/repositories');
    if (!res.ok) throw new Error('Failed to load registered repositories');
    return res.json();
  },

  async getPRs(repo, page = 1, pageSize = 25, q = '', filterBy = 'all', signal = null) {
    let url = `/api/prs?repo=${encodeURIComponent(repo)}&page=${page}&page_size=${pageSize}&filter_by=${encodeURIComponent(filterBy)}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    const res = await fetch(url, { signal });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Failed to load PRs (HTTP ${res.status})`);
    }
    return res.json();
  },

  async investigate(prNumber, repo, question = 'who should review this?', signal = null) {
    const res = await fetch('/api/investigate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pr_number: Number(prNumber), repo, question }),
      signal
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) {
      throw new Error(data.error || `Investigation failed (HTTP ${res.status})`);
    }
    return data;
  },

  async getInsights(repo) {
    const res = await fetch(`/api/insights?repo=${encodeURIComponent(repo)}`);
    if (!res.ok) throw new Error('Failed to fetch insights');
    return res.json();
  },

  async startIngestion(repoSlug, limit = 100, materializeCentrality = true) {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo: repoSlug,
        limit: Number(limit),
        materialize_centrality: Boolean(materializeCentrality)
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `Failed to start ingestion (HTTP ${res.status})`);
    return data;
  },

  async getIngestionStatus(jobId) {
    const res = await fetch(`/api/ingest/${encodeURIComponent(jobId)}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || 'Job not found');
    }
    return res.json();
  },

  async cancelIngestion(jobId) {
    const res = await fetch(`/api/ingest/${encodeURIComponent(jobId)}/cancel`, { method: 'POST' });
    if (!res.ok) throw new Error('Failed to cancel ingestion job');
    return res.json();
  },

  async refreshCentrality(repo) {
    const res = await fetch('/api/centrality/refresh', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ repo })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Centrality refresh failed');
    return data;
  },

  async getLedger(page = 1, pageSize = 20, repo = null, mode = null) {
    let url = `/api/action/ledger?page=${page}&page_size=${pageSize}`;
    if (repo && repo !== 'all') url += `&repo=${encodeURIComponent(repo)}`;
    if (mode && mode !== 'all') url += `&mode=${encodeURIComponent(mode)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error('Failed to fetch action ledger');
    return res.json();
  },

  async executeAction(action, repo, prNumber, mode = 'SHADOW', confirmed = false, idempotencyKey = null) {
    const res = await fetch('/api/action/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        action,
        repo,
        pr_number: Number(prNumber),
        mode,
        confirmed: Boolean(confirmed),
        idempotency_key: idempotencyKey
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || 'Action dispatch failed');
    return data;
  },

  async clearLedger() {
    const res = await fetch('/api/action/clear', { method: 'POST' });
    return res.json();
  },

  async getBenchmark() {
    const res = await fetch('/api/benchmark');
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.message || 'Benchmark results unavailable');
    }
    return res.json();
  },

  async executeCypher(query, repo) {
    const res = await fetch('/api/cypher', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, repo })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || 'Cypher query execution failed');
    return data;
  },

  async getMCPTools() {
    const res = await fetch('/api/mcp/tools');
    if (!res.ok) throw new Error('Failed to load FastMCP tools');
    return res.json();
  },

  async executeMCPTool(tool, params, repo) {
    const res = await fetch('/api/mcp/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, params, repo })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.error) throw new Error(data.error || 'MCP tool execution failed');
    return data;
  }
};
