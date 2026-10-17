/**
 * Keystone API Client
 * Wraps backend endpoints with clean async functions
 */
const KeystoneAPI = {
  async getStatus(repo) {
    const res = await fetch(`/api/status?repo=${encodeURIComponent(repo)}`);
    if (!res.ok) throw new Error((await res.json()).error || 'Status failed');
    return res.json();
  },

  async getPRs(repo, limit = 500, q = '', filterBy = 'all') {
    let url = `/api/prs?repo=${encodeURIComponent(repo)}&limit=${limit}&filter_by=${encodeURIComponent(filterBy)}`;
    if (q) url += `&q=${encodeURIComponent(q)}`;
    const res = await fetch(url);
    if (!res.ok) throw new Error((await res.json()).error || 'PRs failed');
    return res.json();
  },

  async investigate(prNumber, repo, question = 'who should review this?') {
    const res = await fetch('/api/investigate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pr_number: prNumber, repo, question })
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Investigation failed');
    return data;
  },

  async getInsights(repo) {
    const res = await fetch(`/api/insights?repo=${encodeURIComponent(repo)}`);
    if (!res.ok) throw new Error((await res.json()).error || 'Insights failed');
    return res.json();
  },

  async executeCypher(query, repo) {
    const res = await fetch('/api/cypher', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, repo })
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Cypher query failed');
    return data;
  },

  async getMCPTools() {
    const res = await fetch('/api/mcp/tools');
    if (!res.ok) throw new Error('Failed to load MCP tools');
    return res.json();
  },

  async executeMCPTool(tool, params, repo) {
    const res = await fetch('/api/mcp/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ tool, params, repo })
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'MCP tool execution failed');
    return data;
  },

  async getLedger() {
    const res = await fetch('/api/action/ledger');
    if (!res.ok) throw new Error('Failed to fetch action ledger');
    return res.json();
  },

  async executeAction(action, repo, prNumber) {
    const res = await fetch('/api/action/execute', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ action, repo, pr_number: prNumber })
    });
    const data = await res.json();
    if (!res.ok || data.error) throw new Error(data.error || 'Action execution failed');
    return data;
  },

  async clearLedger() {
    const res = await fetch('/api/action/clear', { method: 'POST' });
    return res.json();
  }
};
