/**
 * Keystone API Client
 * Clean async interface with pagination, cancellation, coverage metrics, and scope estimation.
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

  async getCoverage(repo, windowDays = 90) {
    const res = await fetch(`/api/repositories/${encodeURIComponent(repo)}/coverage?window_days=${windowDays}`);
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.error || `Failed to load coverage (HTTP ${res.status})`);
    }
    return res.json();
  },

  async getRepositories() {
    const res = await fetch('/api/repositories');
    if (!res.ok) throw new Error('Failed to load registered repositories');
    return res.json();
  },

  async getPRs(repoOrOpts, page = 1, pageSize = 25, q = '', filterBy = 'all', signal = null) {
    let url = '/api/prs?';
    let abortSignal = signal;

    if (typeof repoOrOpts === 'object' && repoOrOpts !== null) {
      const p = repoOrOpts;
      abortSignal = p.signal || signal;
      const params = new URLSearchParams();
      params.set('repo', p.repo || 'pydantic');
      params.set('page', p.page || 1);
      params.set('page_size', p.pageSize || p.page_size || 25);
      if (p.q) params.set('q', p.q);
      if (p.filterBy && p.filterBy !== 'all') params.set('filter_by', p.filterBy);
      if (p.state && p.state !== 'all') params.set('state', p.state);
      if (p.merged && p.merged !== 'all') params.set('merged', p.merged);
      if (p.reviewed && p.reviewed !== 'all') params.set('reviewed', p.reviewed);
      if (p.risk && p.risk !== 'all') params.set('risk', p.risk);
      if (p.author) params.set('author', p.author);
      if (p.reviewer) params.set('reviewer', p.reviewer);
      if (p.date_from) params.set('date_from', p.date_from);
      if (p.date_to) params.set('date_to', p.date_to);
      if (p.sort) params.set('sort', p.sort);
      if (p.sort_direction) params.set('sort_direction', p.sort_direction);
      if (p.view && p.view !== 'all') params.set('view', p.view);
      url += params.toString();
    } else {
      let params = `repo=${encodeURIComponent(repoOrOpts)}&page=${page}&page_size=${pageSize}&filter_by=${encodeURIComponent(filterBy)}`;
      if (q) params += `&q=${encodeURIComponent(q)}`;
      url += params;
    }

    const res = await fetch(url, { signal: abortSignal });
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

  async estimateIngestion(repoSlug, scopeType = 'recent', limit = 100, dateFrom = null, dateTo = null) {
    const res = await fetch('/api/ingest/estimate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo: repoSlug,
        scope_type: scopeType,
        limit: Number(limit),
        date_from: dateFrom,
        date_to: dateTo
      })
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || 'Failed to estimate ingestion scope');
    return data;
  },

  async startIngestion(repoSlug, limit = 100, materializeCentrality = true, scopeType = 'recent', dateFrom = null, dateTo = null) {
    const res = await fetch('/api/ingest', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        repo: repoSlug,
        limit: Number(limit),
        materialize_centrality: Boolean(materializeCentrality),
        scope_type: scopeType,
        date_from: dateFrom,
        date_to: dateTo
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
