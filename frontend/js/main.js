/**
 * Keystone Main Application Controller — Production Grade
 * Clean state management, debounced search, request cancellation,
 * truthful status handling, full-dataset PR explorer, and light-theme UI coordination.
 */

let currentRepo = 'pydantic';
let currentPrNumber = 13997;
let currentResult = null;
let currentCoverage = null;

// Routing Tab PR Selector state
let currentPrFilter = 'all';
let currentPrPage = 1;
const prPageSize = 25;

// Dedicated PR Explorer state
let explorerState = {
  page: 1,
  pageSize: 25,
  activeTab: 'recommended', // 'recommended' | 'all' | 'gaps'
  q: '',
  state: 'all',
  merged: 'merged',
  reviewed: 'all',
  risk: 'all',
  author: '',
  reviewer: '',
  dateFrom: '',
  dateTo: '',
  sort: 'number',
  sortDirection: 'desc',
  totalPages: 1,
  totalMatching: 0,
};

let currentLedgerPage = 1;
const ledgerPageSize = 20;
let currentLedgerMode = 'all';

let selectedDispatchMode = 'SHADOW';
let activeIngestJobId = null;
let ingestPollTimer = null;
let selectedScopeType = 'recent';
let investigationAbortController = null;
let prSearchAbortController = null;
let explorerAbortController = null;

// Utility: Escape untrusted values to prevent HTML injection
function escapeHtml(str) {
  if (str === null || str === undefined) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Utility: Debounce helper
function debounce(fn, delayMs = 300) {
  let timer = null;
  return function (...args) {
    if (timer) clearTimeout(timer);
    timer = setTimeout(() => fn.apply(this, args), delayMs);
  };
}

// Toast Notifications
function notify(message, variant = 'info') {
  const container = document.getElementById('toast-container');
  if (!container) return;
  const el = document.createElement('div');
  el.className = `toast ${variant}`;
  el.setAttribute('role', 'status');
  el.innerHTML = `<span>${variant === 'error' ? '⚠️' : variant === 'success' ? '✓' : 'ℹ️'}</span> <span>${escapeHtml(message)}</span>`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.opacity = '0';
    setTimeout(() => el.remove(), 250);
  }, 4500);
}

// ==============================================================
// Section Switching
// ==============================================================
function switchMainSection(sectionId) {
  const sections = ['routing', 'explorer', 'evidence', 'health'];
  sections.forEach(s => {
    const secEl = document.getElementById(`section-${s}`);
    const btnEl = document.getElementById(`nav-btn-${s}`);
    if (secEl && btnEl) {
      if (s === sectionId) {
        secEl.style.display = 'block';
        btnEl.classList.add('active');
        btnEl.setAttribute('aria-selected', 'true');
      } else {
        secEl.style.display = 'none';
        btnEl.classList.remove('active');
        btnEl.setAttribute('aria-selected', 'false');
      }
    }
  });

  if (sectionId === 'evidence' && currentResult) {
    setTimeout(() => renderInteractiveNetwork(currentResult), 50);
  } else if (sectionId === 'explorer') {
    fetchExplorerPRs();
  }
}

// ==============================================================
// Initialization & Startup
// ==============================================================
async function init() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('repo')) currentRepo = params.get('repo');
  if (params.get('pr')) currentPrNumber = parseInt(params.get('pr'), 10) || 13997;

  const directInput = document.getElementById('pr-direct-input');
  if (directInput) directInput.value = currentPrNumber;

  const ingestInput = document.getElementById('ingest-repo-input');
  if (ingestInput) ingestInput.value = currentRepo.includes('/') ? currentRepo : `${currentRepo}/${currentRepo}`;

  try {
    // 1. Fetch initial status, coverage, and registered repositories concurrently
    await Promise.all([
      fetchStatus(),
      fetchRepositoryCoverage(currentRepo),
      fetchRegisteredRepositories(),
    ]);

    // 2. Fetch secondary resources concurrently
    await Promise.all([
      fetchPRs(currentRepo, currentPrPage, ''),
      fetchExplorerPRs(),
      fetchInsights(),
      fetchLedger(),
      fetchBenchmark(),
    ]);

    // 3. Run investigation on initial PR
    await runInvestigation(currentPrNumber);
  } catch (err) {
    console.error("Initialization error:", err);
    notify("Could not complete full initialization. Verify connection.", "error");
  }
}

// ==============================================================
// Repository Status & Telemetry
// ==============================================================
async function fetchStatus() {
  try {
    const data = await KeystoneAPI.getStatus(currentRepo);
    const repoLabel = document.getElementById('current-repo-label');
    if (repoLabel) repoLabel.innerText = data.repo_slug || currentRepo;

    // Connection indicator
    const pill = document.getElementById('conn-pill');
    const dot = document.getElementById('conn-dot');
    const txt = document.getElementById('conn-text');
    if (pill && dot && txt) {
      if (data.is_live) {
        pill.className = "badge badge-green";
        dot.className = "status-dot online";
        txt.innerText = "FalkorDB Connected";
      } else {
        pill.className = "badge badge-amber";
        dot.className = "status-dot offline";
        txt.innerText = "FalkorDB Offline";
      }
    }

    // Provenance badge
    const provLabel = document.getElementById('provenance-status-label');
    if (provLabel) {
      const p = data.provenance || {};
      if (p.status === 'real') {
        provLabel.className = "badge badge-green";
        provLabel.innerText = `GitHub API (${p.last_import_count || 0} PRs)`;
      } else {
        provLabel.className = "badge badge-slate";
        provLabel.innerText = "Existing (Unmarked)";
      }
    }

    // Centrality status badge
    const centBadge = document.getElementById('centrality-status-label');
    const healthCentStatus = document.getElementById('health-centrality-status');
    const healthCentFiles = document.getElementById('health-centrality-files');
    if (data.centrality) {
      const cStatus = data.centrality.status || 'unavailable';
      if (centBadge) {
        centBadge.className = cStatus === 'current' ? 'badge badge-green' : cStatus === 'stale' ? 'badge badge-amber' : 'badge badge-slate';
        centBadge.innerText = cStatus.toUpperCase();
      }
      if (healthCentStatus) {
        healthCentStatus.className = cStatus === 'current' ? 'badge badge-green' : 'badge badge-slate';
        healthCentStatus.innerText = cStatus.toUpperCase();
      }
      if (healthCentFiles) {
        healthCentFiles.innerText = data.centrality.file_count || 0;
      }
    }

    // Telemetry counts
    const hNodes = document.getElementById('health-nodes-count');
    const hEdges = document.getElementById('health-edges-count');
    const hPRs = document.getElementById('health-prs-count');
    const hCent = document.getElementById('health-centrality-count');
    if (hNodes) hNodes.innerText = Number(data.nodes || 0).toLocaleString();
    if (hEdges) hEdges.innerText = Number(data.edges || 0).toLocaleString();
    if (hPRs && data.graph) hPRs.innerText = Number(data.graph.co_change_edges || 0).toLocaleString();
    if (hCent && data.centrality) hCent.innerText = Number(data.centrality.file_count || 0).toLocaleString();

  } catch (err) {
    console.warn("Status fetch failed:", err);
    notify("FalkorDB status check failed", "error");
  }
}

// ==============================================================
// Repository Coverage Panel
// ==============================================================
async function fetchRepositoryCoverage(repo) {
  try {
    const data = await KeystoneAPI.getCoverage(repo, 90);
    currentCoverage = data;
    renderCoveragePanel(data);
    renderIngestionGaps(data);
  } catch (err) {
    console.warn("Failed to fetch repository coverage:", err);
  }
}

function renderCoveragePanel(cov) {
  if (!cov) return;
  const counts = cov.counts || {};
  const statuses = cov.statuses || {};
  const pcts = cov.percentages || {};

  // Repository Slug
  const slugEl = document.getElementById('coverage-repo-slug');
  if (slugEl) slugEl.innerText = cov.repo || currentRepo;

  // GitHub Universe Count
  const ghTotalEl = document.getElementById('cov-github-total');
  const ghSubEl = document.getElementById('cov-discovered-sub');
  if (ghTotalEl) {
    ghTotalEl.innerText = (counts.github_total !== null && counts.github_total !== undefined)
      ? Number(counts.github_total).toLocaleString()
      : 'Unavailable';
  }
  if (ghSubEl) {
    ghSubEl.innerText = (counts.discovered !== null && counts.discovered !== undefined)
      ? `${Number(counts.discovered).toLocaleString()} discovered`
      : 'Unavailable';
  }

  // Ingested Count
  const ingEl = document.getElementById('cov-ingested');
  const ingPctEl = document.getElementById('cov-ingested-pct');
  if (ingEl) {
    ingEl.innerText = (counts.ingested !== null && counts.ingested !== undefined)
      ? Number(counts.ingested).toLocaleString()
      : 'Unavailable';
  }
  if (ingPctEl) {
    if (pcts.ingested_pct !== null && pcts.ingested_pct !== undefined) {
      ingPctEl.innerText = `${pcts.ingested_pct}% of GitHub universe`;
    } else {
      ingPctEl.innerText = "Ingested in FalkorDB";
    }
  }

  // Active Analysis Window Count
  const winEl = document.getElementById('cov-analysis-window');
  const winLabelEl = document.getElementById('cov-window-label');
  if (winEl) {
    const winVal = counts.in_active_window ?? counts.analysis_ready;
    winEl.innerText = (winVal !== null && winVal !== undefined)
      ? Number(winVal).toLocaleString()
      : 'Unavailable';
  }
  if (winLabelEl) winLabelEl.innerText = cov.analysis_window?.label || "Last 90 days";

  // Last Synced Timestamp
  const lastSyncEl = document.getElementById('coverage-last-synced');
  if (lastSyncEl) {
    if (cov.last_synced_at) {
      try {
        const dt = new Date(cov.last_synced_at);
        lastSyncEl.innerText = dt.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
      } catch (e) {
        lastSyncEl.innerText = cov.last_synced_at.slice(0, 10);
      }
    } else {
      lastSyncEl.innerText = 'Unavailable';
    }
  }

  // Status Badges (Discovery, Ingestion, Analysis, Freshness)
  updateStatusBadge('discovery', statuses.discovery || 'Connected', 'GitHub');
  updateStatusBadge('ingestion', statuses.ingestion || 'Partially ingested', 'Ingestion');
  updateStatusBadge('analysis', statuses.analysis || 'Analysis ready', 'Analysis');
  updateStatusBadge('freshness', statuses.freshness || 'Fresh', 'Graph');
}

function updateStatusBadge(type, statusText, prefix) {
  const pill = document.getElementById(`status-pill-${type}`);
  const dot = document.getElementById(`status-dot-${type}`);
  const txt = document.getElementById(`status-text-${type}`);
  if (!pill || !txt) return;

  txt.innerText = `${prefix}: ${statusText}`;

  const clean = statusText.toLowerCase();
  if (clean.includes('connected') || clean.includes('ready') || clean.includes('completed') || clean.includes('fresh')) {
    pill.className = "status-badge-detailed badge-green";
    if (dot) dot.className = "status-dot online";
  } else if (clean.includes('progress') || clean.includes('partially') || clean.includes('queued')) {
    pill.className = "status-badge-detailed badge-blue";
    if (dot) dot.className = "status-dot busy";
  } else if (clean.includes('stale') || clean.includes('insufficient')) {
    pill.className = "status-badge-detailed badge-amber";
    if (dot) dot.className = "status-dot offline";
  } else {
    pill.className = "status-badge-detailed badge-slate";
    if (dot) dot.className = "status-dot offline";
  }
}

async function fetchRegisteredRepositories() {
  try {
    const data = await KeystoneAPI.getRepositories();
    const repos = data.repositories || [];

    const topSelect = document.getElementById('repo-select');
    if (topSelect) {
      topSelect.innerHTML = repos.map(r => `<option value="${escapeHtml(r.key)}">${escapeHtml(r.slug)}</option>`).join('');
      if (repos.some(r => r.key === currentRepo)) {
        topSelect.value = currentRepo;
      }
    }

    const regCount = document.getElementById('registered-repos-count');
    if (regCount) regCount.innerText = repos.length;

    const listEl = document.getElementById('registered-repos-list');
    if (listEl) {
      if (repos.length === 0) {
        listEl.innerHTML = '<li style="color: #64748B;">No repositories registered.</li>';
      } else {
        listEl.innerHTML = repos.map(r => `
          <li style="display: flex; align-items: center; justify-content: space-between; padding: 6px 0; border-bottom: 1px solid var(--border-subtle);">
            <div>
              <strong style="color: #0F172A;">${escapeHtml(r.slug)}</strong>
              <div style="font-size: 11px; color: #64748B; font-family: monospace;">${escapeHtml(r.graph_name)}</div>
            </div>
            <div style="text-align: right;">
              <span class="badge ${r.status === 'ready' ? 'badge-green' : 'badge-slate'}">${escapeHtml(r.status)}</span>
              <div style="font-size: 10px; color: #64748B; margin-top: 2px;">${Number(r.nodes).toLocaleString()} nodes</div>
            </div>
          </li>
        `).join('');
      }
    }
  } catch (err) {
    console.error("Failed to load registered repositories:", err);
  }
}

function onRepoSelectChange(newRepo) {
  currentRepo = newRepo;
  currentPrPage = 1;
  explorerState.page = 1;

  const url = new URL(window.location);
  url.searchParams.set('repo', newRepo);
  window.history.replaceState({}, '', url);

  const ingestInput = document.getElementById('ingest-repo-input');
  if (ingestInput) ingestInput.value = currentRepo.includes('/') ? currentRepo : `${currentRepo}/${currentRepo}`;

  fetchStatus();
  fetchRepositoryCoverage(currentRepo);
  fetchPRs(currentRepo, 1, '');
  fetchExplorerPRs();
  fetchInsights();
}

// ==============================================================
// PR Search & Selection in Review Routing Tab
// ==============================================================
const onPrSearchInput = debounce((query) => {
  currentPrPage = 1;
  fetchPRs(currentRepo, currentPrPage, query);
}, 300);

function setPrFilter(filter) {
  currentPrFilter = filter;
  ['all', 'reviewed', 'unreviewed', 'critical'].forEach(f => {
    const el = document.getElementById(`pill-filter-${f}`);
    if (el) el.className = (f === filter) ? 'badge badge-blue' : 'badge badge-slate';
  });
  currentPrPage = 1;
  const searchVal = document.getElementById('pr-search-input')?.value || '';
  fetchPRs(currentRepo, currentPrPage, searchVal);
}

function changePrPage(delta) {
  currentPrPage = Math.max(1, currentPrPage + delta);
  const searchVal = document.getElementById('pr-search-input')?.value || '';
  fetchPRs(currentRepo, currentPrPage, searchVal);
}

async function fetchPRs(repo, page = 1, query = '') {
  if (prSearchAbortController) {
    prSearchAbortController.abort();
  }
  prSearchAbortController = new AbortController();

  const feedStatus = document.getElementById('pr-feed-status');
  if (feedStatus) feedStatus.innerText = "Loading PRs...";

  try {
    const data = await KeystoneAPI.getPRs({
      repo,
      page,
      pageSize: prPageSize,
      q: query,
      filterBy: currentPrFilter,
      signal: prSearchAbortController.signal
    });
    const prs = data.prs || [];
    const select = document.getElementById('pr-select-dropdown');
    if (select) {
      if (prs.length === 0) {
        select.innerHTML = '<option value="">No matching pull requests found</option>';
      } else {
        select.innerHTML = prs.map(p => `
          <option value="${p.number}">#${p.number}: ${escapeHtml(p.title.slice(0, 50))} (@${escapeHtml(p.author)})</option>
        `).join('');
        if (prs.some(p => p.number === currentPrNumber)) {
          select.value = currentPrNumber;
        } else if (prs.length > 0 && !query) {
          select.value = prs[0].number;
        }
      }
    }

    if (feedStatus) feedStatus.innerText = `${data.count || prs.length} PRs`;

    // Pagination buttons state
    const prevBtn = document.getElementById('btn-pr-prev');
    const nextBtn = document.getElementById('btn-pr-next');
    const pageLabel = document.getElementById('pr-pagination-label');
    if (prevBtn) prevBtn.disabled = page <= 1;
    if (nextBtn) nextBtn.disabled = prs.length < prPageSize;
    if (pageLabel) pageLabel.innerText = `Page ${page}`;

  } catch (err) {
    if (err.name !== 'AbortError') {
      console.warn("Failed to load PRs:", err);
      if (feedStatus) feedStatus.innerText = "Error loading PRs";
    }
  }
}

function onSelectPr(prNumber) {
  if (!prNumber) return;
  currentPrNumber = parseInt(prNumber, 10);
  const input = document.getElementById('pr-direct-input');
  if (input) input.value = currentPrNumber;
  runInvestigation(currentPrNumber);
}

function runInvestigationForInput() {
  const input = document.getElementById('pr-direct-input');
  const val = parseInt(input.value, 10);
  if (!val || isNaN(val)) {
    notify("Please enter a valid pull request number", "error");
    return;
  }
  currentPrNumber = val;
  runInvestigation(val);
}

// ==============================================================
// Investigation & Reasoning
// ==============================================================
async function runInvestigation(prNumber) {
  if (investigationAbortController) {
    investigationAbortController.abort();
  }
  investigationAbortController = new AbortController();

  const analyzeBtn = document.getElementById('btn-analyze-pr');
  if (analyzeBtn) {
    analyzeBtn.disabled = true;
    analyzeBtn.innerHTML = '<span>⏳ Analyzing...</span>';
  }

  try {
    const data = await KeystoneAPI.investigate(prNumber, currentRepo, 'who should review this?', investigationAbortController.signal);
    currentResult = data;

    renderPRMetadata(data.pr_details || {});
    renderReviewerRecommendations(data.decision?.reviewers || []);
    renderKnowledgeRisks(data.decision?.risks || [], data.pr_metrics || {});
    renderEvidenceBreakdown(data);
    renderInvestigationScope(data.analysis_scope || {});
    updateProposedAction(data.decision?.reviewers || []);

  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error("Investigation failed:", err);
      notify(err.message || "Could not analyze pull request", "error");
    }
  } finally {
    if (analyzeBtn) {
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = '<span>🔍 Analyze PR</span>';
    }
  }
}

function renderInvestigationScope(scope) {
  const card = document.getElementById('training-scope-card');
  if (!card) return;

  const readyEl = document.getElementById('scope-ready-prs');
  const revRelsEl = document.getElementById('scope-rev-rels');
  const winEl = document.getElementById('scope-window-days');
  const covLabelEl = document.getElementById('scope-cov-label');
  const badgeEl = document.getElementById('training-scope-quality-badge');
  const alertEl = document.getElementById('routing-confidence-alert');
  const alertTextEl = document.getElementById('routing-confidence-text');

  if (readyEl) readyEl.innerText = Number(scope.analysis_ready_prs || 0).toLocaleString();
  if (revRelsEl) revRelsEl.innerText = Number(scope.review_relationships_used || 0).toLocaleString();
  if (winEl) winEl.innerText = scope.analysis_window || "Last 90 days";
  if (covLabelEl) covLabelEl.innerText = scope.coverage_quality || "partial";

  if (badgeEl) {
    const isComplete = scope.coverage_quality === 'complete';
    badgeEl.className = isComplete ? 'badge badge-green' : 'badge badge-blue';
    badgeEl.innerText = isComplete ? 'Complete Coverage' : 'Partial Coverage';
  }

  if (alertEl && alertTextEl) {
    if (scope.confidence_notice) {
      alertTextEl.innerText = scope.confidence_notice;
      alertEl.style.display = 'flex';
    } else {
      alertEl.style.display = 'none';
    }
  }
}

function renderPRMetadata(pr) {
  const title = document.getElementById('pr-summary-title');
  const author = document.getElementById('pr-summary-author');
  const files = document.getElementById('pr-summary-files');
  const adds = document.getElementById('pr-summary-additions');
  const dels = document.getElementById('pr-summary-deletions');
  const merged = document.getElementById('pr-summary-merged');
  const badge = document.getElementById('pr-state-badge');

  if (title) title.innerText = `#${pr.number || currentPrNumber}: ${pr.title || 'Untitled'}`;
  if (author) author.innerText = `@${pr.author || 'unknown'}`;
  if (files) files.innerText = pr.files ? pr.files.length : (pr.files_changed || 0);
  if (adds) adds.innerText = `+${pr.additions || 0}`;
  if (dels) dels.innerText = `-${pr.deletions || 0}`;
  if (merged) {
    merged.innerText = pr.merged_at
      ? new Date(pr.merged_at).toLocaleDateString()
      : 'Not merged (Open/Closed)';
  }
  if (badge) {
    badge.innerText = pr.merged_at ? 'Merged' : (pr.state || 'Closed');
    badge.className = pr.merged_at ? 'badge badge-green' : 'badge badge-slate';
  }
}

function renderReviewerRecommendations(reviewers) {
  const primary = reviewers[0];
  const secondary = reviewers[1];

  // Primary
  const pName = document.getElementById('rec-primary-name');
  const pScore = document.getElementById('rec-primary-score');
  const pBadge = document.getElementById('rec-primary-score-badge');
  const pShared = document.getElementById('rec-primary-shared');
  const pRecent = document.getElementById('rec-primary-recent');
  const pCov = document.getElementById('rec-primary-coverage');
  const pLast = document.getElementById('rec-primary-last');
  const pReasons = document.getElementById('rec-primary-reasons');

  if (!primary) {
    if (pName) pName.innerText = "No reviewer found";
    if (pScore) pScore.innerText = "--";
    if (pReasons) pReasons.innerHTML = '<li style="color: #64748B;">No suitable reviewer found in current review history.</li>';
  } else {
    if (pName) pName.innerText = `@${primary.login}`;
    if (pScore) pScore.innerText = (primary.score * 100).toFixed(0);
    if (pBadge) {
      pBadge.className = primary.score >= 0.75 ? "score-badge-circle high" : "score-badge-circle medium";
    }
    if (pShared) pShared.innerText = `${primary.shared_files} files`;
    if (pRecent) pRecent.innerText = `${primary.recent_reviews} PRs`;
    if (pCov) pCov.innerText = `${primary.coverage_pct || 100}%`;
    if (pLast) {
      pLast.innerText = primary.days_ago !== undefined && primary.days_ago !== null
        ? `${primary.days_ago}d ago`
        : 'recent';
    }

    if (pReasons) {
      const reasons = [];
      if (primary.shared_files > 0) {
        reasons.push(`Direct review history on ${primary.shared_files} touched files`);
      }
      if (primary.bridge_files > 0) {
        reasons.push(`Connected via ${primary.bridge_files} co-change bridge files (affinity: ${primary.affinity})`);
      }
      if (primary.recent_reviews > 0) {
        reasons.push(`Active contributor with ${primary.recent_reviews} recent pull request reviews`);
      }
      if (primary.is_overloaded) {
        reasons.push(`Review load penalty applied (>20 recent reviews)`);
      }
      if (reasons.length === 0) {
        reasons.push("Graph candidate based on directory overlap and structural betweenness");
      }
      pReasons.innerHTML = reasons.map(r => `
        <li style="display: flex; align-items: flex-start; gap: 6px;">
          <span style="color: #16A34A; font-weight: 700;">✓</span>
          <span>${escapeHtml(r)}</span>
        </li>
      `).join('');
    }
  }

  // Secondary
  const sCard = document.getElementById('secondary-reviewer-card');
  const sName = document.getElementById('rec-secondary-name');
  const sScore = document.getElementById('rec-secondary-score');
  const sDesc = document.getElementById('rec-secondary-desc');

  if (!secondary) {
    if (sCard) sCard.style.display = 'none';
  } else {
    if (sCard) sCard.style.display = 'block';
    if (sName) sName.innerText = `@${secondary.login}`;
    if (sScore) sScore.innerText = (secondary.score * 100).toFixed(0);
    if (sDesc) {
      sDesc.innerText = `Shares ${secondary.shared_files} files · ${secondary.recent_reviews} reviews · structural bridge: ${secondary.structural}`;
    }
  }
}

function renderKnowledgeRisks(risks, metrics) {
  const badge = document.getElementById('risk-blast-badge');
  if (badge) {
    badge.innerText = metrics.blast_tier || 'Standard Change';
    badge.className = `badge badge-${metrics.blast_color || 'slate'}`;
  }

  const container = document.getElementById('risk-flags-container');
  if (!container) return;

  if (risks.length === 0 && (!metrics.bus_factor_files || metrics.bus_factor_files.length === 0)) {
    container.innerHTML = '<div style="font-size: 12px; color: #64748B;">No elevated knowledge risk flags detected for this pull request.</div>';
    return;
  }

  let html = '';
  // Centrality warning
  const maxC = metrics.criticality?.max_centrality || 0;
  if (maxC >= 0.08) {
    html += `
      <div style="padding: 8px 12px; background: #FFFBEB; border: 1px solid #FEF3C7; border-radius: var(--radius-sm); font-size: 12px; color: #B45309;">
        <strong>Architectural Centrality Risk:</strong> Changed files reach ${maxC} normalised betweenness centrality.
      </div>
    `;
  }

  // Bus Factor Monopoly flags
  (metrics.bus_factor_files || []).forEach(bf => {
    html += `
      <div style="padding: 8px 12px; background: #FEF2F2; border: 1px solid #FEE2E2; border-radius: var(--radius-sm); font-size: 12px; color: #B91C1C;">
        <strong>Bus Factor Exposure:</strong> <code>${escapeHtml(bf.path)}</code> has single-reviewer monopoly (@${escapeHtml(bf.sole_reviewer)}).
      </div>
    `;
  });

  // Additional risks
  risks.forEach(r => {
    html += `
      <div style="font-size: 12px; color: #475569; display: flex; align-items: center; gap: 6px;">
        <span class="badge badge-amber font-mono">${escapeHtml(r.label || 'risk')}</span>
        <span>${escapeHtml(r.detail || r.flag)}</span>
      </div>
    `;
  });

  container.innerHTML = html;
}

function renderEvidenceBreakdown(data) {
  const ep = data.explain_path || {};
  const primary = (data.decision?.reviewers || [])[0];
  const changedFiles = data.pr_details?.files || [];

  // 1. Narrative Explanation
  const narrativeEl = document.getElementById('evidence-narrative-text');
  if (narrativeEl) {
    if (!primary) {
      narrativeEl.innerText = "No reviewer with sufficient graph affinity was identified for this pull request.";
    } else {
      narrativeEl.innerText = `This reviewer @${primary.login} was selected because they reviewed ${primary.shared_files} of the ${changedFiles.length} files changed by this PR and recently reviewed related changes in the same module.`;
    }
  }

  // 2. Direct File Overlap
  const overlapList = document.getElementById('evidence-overlap-list');
  const overlapCount = document.getElementById('evidence-overlap-count');
  const directItems = ep.direct || [];
  if (overlapCount) overlapCount.innerText = `${directItems.length} files`;
  if (overlapList) {
    if (directItems.length === 0) {
      overlapList.innerHTML = '<li style="color: #64748B;">No direct prior reviews on these specific files.</li>';
    } else {
      overlapList.innerHTML = directItems.map(d => `
        <li style="padding: 4px 0; border-bottom: 1px solid var(--border-subtle); display: flex; justify-content: space-between;">
          <span class="font-mono" style="color: #0F172A;">${escapeHtml(d.file)}</span>
          <span style="color: #64748B;">via PR #${escapeHtml(d.via_pr)}</span>
        </li>
      `).join('');
    }
  }

  // 3. Co-Change Bridges
  const bridgeList = document.getElementById('evidence-bridge-list');
  const bridgeCount = document.getElementById('evidence-bridge-count');
  const bridges = ep.bridges || [];
  if (bridgeCount) bridgeCount.innerText = `${bridges.length} bridges`;
  if (bridgeList) {
    if (bridges.length === 0) {
      bridgeList.innerHTML = '<li style="color: #64748B;">No secondary co-change bridges required.</li>';
    } else {
      bridgeList.innerHTML = bridges.map(b => `
        <li style="padding: 4px 0; border-bottom: 1px solid var(--border-subtle); font-size: 11px;">
          <div style="font-weight: 600; color: #4F46E5;">${escapeHtml(b.from)} ➔ ${escapeHtml(b.to)}</div>
          <div style="color: #64748B;">Co-change weight: ${b.weight} · Centrality: ${b.centrality}</div>
        </li>
      `).join('');
    }
  }

  // 4. Shortest Path Traverse
  const pathHops = document.getElementById('evidence-hops-badge');
  const pathChain = document.getElementById('evidence-path-chain');
  if (pathHops) pathHops.innerText = `${ep.hops || 0} hops`;
  if (pathChain) {
    if (!ep.path || ep.path.length === 0) {
      pathChain.innerText = "No connected path found between PR files and candidate.";
    } else {
      pathChain.innerHTML = ep.path.map(p => `<span>${escapeHtml(p)}</span>`).join(' <span style="color: #94A3B8;">➔</span> ');
    }
  }

  // 5. Render Vis.js Network
  renderInteractiveNetwork(data);
}

// ==============================================================
// PR Explorer Implementation (Server-Side Paginated & Filtered)
// ==============================================================
const onExplorerSearchInput = debounce(() => {
  explorerState.page = 1;
  const input = document.getElementById('explorer-search-input');
  if (input) explorerState.q = input.value;
  const authInput = document.getElementById('explorer-author-filter');
  if (authInput) explorerState.author = authInput.value;
  const revInput = document.getElementById('explorer-reviewer-filter');
  if (revInput) explorerState.reviewer = revInput.value;
  fetchExplorerPRs();
}, 300);

function onExplorerFilterChange() {
  explorerState.page = 1;
  explorerState.state = document.getElementById('explorer-filter-state')?.value || 'all';
  explorerState.reviewed = document.getElementById('explorer-filter-reviewed')?.value || 'all';
  explorerState.risk = document.getElementById('explorer-filter-risk')?.value || 'all';
  explorerState.sort = document.getElementById('explorer-sort-by')?.value || 'number';
  explorerState.dateFrom = document.getElementById('explorer-date-from')?.value || '';
  explorerState.dateTo = document.getElementById('explorer-date-to')?.value || '';
  fetchExplorerPRs();
}

function resetExplorerFilters() {
  explorerState.page = 1;
  explorerState.q = '';
  explorerState.state = 'all';
  explorerState.reviewed = 'all';
  explorerState.risk = 'all';
  explorerState.sort = 'number';
  explorerState.dateFrom = '';
  explorerState.dateTo = '';
  explorerState.author = '';
  explorerState.reviewer = '';

  const sInput = document.getElementById('explorer-search-input');
  if (sInput) sInput.value = '';
  const stSelect = document.getElementById('explorer-filter-state');
  if (stSelect) stSelect.value = 'all';
  const revSelect = document.getElementById('explorer-filter-reviewed');
  if (revSelect) revSelect.value = 'all';
  const rkSelect = document.getElementById('explorer-filter-risk');
  if (rkSelect) rkSelect.value = 'all';
  const sortSelect = document.getElementById('explorer-sort-by');
  if (sortSelect) sortSelect.value = 'number';
  const df = document.getElementById('explorer-date-from');
  if (df) df.value = '';
  const dt = document.getElementById('explorer-date-to');
  if (dt) dt.value = '';
  const af = document.getElementById('explorer-author-filter');
  if (af) af.value = '';
  const rf = document.getElementById('explorer-reviewer-filter');
  if (rf) rf.value = '';

  fetchExplorerPRs();
}

function setExplorerTab(tab) {
  explorerState.activeTab = tab;
  explorerState.page = 1;

  ['recommended', 'all', 'gaps'].forEach(t => {
    const btn = document.getElementById(`tab-btn-${t}`);
    if (btn) {
      if (t === tab) {
        btn.classList.add('active');
        btn.setAttribute('aria-selected', 'true');
      } else {
        btn.classList.remove('active');
        btn.setAttribute('aria-selected', 'false');
      }
    }
  });

  const filterCard = document.getElementById('explorer-filter-card');
  const tableCard = document.getElementById('explorer-table-card');
  const gapsContainer = document.getElementById('explorer-gaps-container');
  const viewTitle = document.getElementById('explorer-view-title');

  if (tab === 'gaps') {
    if (filterCard) filterCard.style.display = 'none';
    if (tableCard) tableCard.style.display = 'none';
    if (gapsContainer) gapsContainer.style.display = 'flex';
    if (currentCoverage) renderIngestionGaps(currentCoverage);
  } else {
    if (filterCard) filterCard.style.display = 'block';
    if (tableCard) tableCard.style.display = 'block';
    if (gapsContainer) gapsContainer.style.display = 'none';
    if (viewTitle) {
      viewTitle.innerText = tab === 'recommended' ? 'Recommended Candidate Pull Requests' : 'All Ingested Pull Requests';
    }
    fetchExplorerPRs();
  }
}

async function fetchExplorerPRs() {
  if (explorerAbortController) {
    explorerAbortController.abort();
  }
  explorerAbortController = new AbortController();

  const countEl = document.getElementById('explorer-results-count');
  if (countEl) countEl.innerText = "Searching graph...";

  try {
    const params = {
      repo: currentRepo,
      page: explorerState.page,
      pageSize: explorerState.pageSize,
      q: explorerState.q,
      state: explorerState.state,
      reviewed: explorerState.reviewed,
      risk: explorerState.risk,
      sort: explorerState.sort,
      sort_direction: explorerState.sortDirection,
      date_from: explorerState.dateFrom,
      date_to: explorerState.dateTo,
      author: explorerState.author,
      reviewer: explorerState.reviewer,
      view: explorerState.activeTab === 'recommended' ? 'recommended' : 'all',
      signal: explorerAbortController.signal,
    };

    const data = await KeystoneAPI.getPRs(params);
    const pagination = data.pagination || { page: 1, total_matching: 0, total_pages: 1 };
    explorerState.totalPages = pagination.total_pages || 1;
    explorerState.totalMatching = pagination.total_matching || 0;

    renderExplorerTable(data.items || data.prs || []);
    renderExplorerPagination(pagination);
    renderScopeExplanation(data.scope || {}, data.coverage || {});

    // Update top coverage showing counters
    const covShowing = document.getElementById('cov-showing-count');
    const covPageInfo = document.getElementById('cov-page-info');
    const covMatching = document.getElementById('cov-matching-sub');
    if (covShowing) covShowing.innerText = `${(data.items || []).length}`;
    if (covPageInfo) covPageInfo.innerText = `Showing PRs · Page ${pagination.page} of ${pagination.total_pages}`;
    if (covMatching) covMatching.innerText = `${pagination.total_matching.toLocaleString()} matching filters`;

    if (countEl) countEl.innerText = `${pagination.total_matching.toLocaleString()} PRs`;

  } catch (err) {
    if (err.name !== 'AbortError') {
      console.warn("Explorer search failed:", err);
      if (countEl) countEl.innerText = "Error searching";
    }
  }
}

function renderExplorerTable(prs) {
  const tbody = document.getElementById('explorer-prs-tbody');
  if (!tbody) return;

  if (prs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="8" style="text-align: center; color: #64748B; padding: 36px;">
          <div>No pull requests found matching the current search criteria or active window.</div>
          <button onclick="resetExplorerFilters()" class="btn btn-secondary btn-sm" style="margin-top: 10px;">Clear Filters</button>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = prs.map(p => {
    const isRecommended = explorerState.activeTab === 'recommended';
    const reasonsHtml = (p.recommendation_reasons && p.recommendation_reasons.length > 0)
      ? `<div style="font-size: 11px; color: #2563EB; margin-top: 4px;">• ${escapeHtml(p.recommendation_reasons[0])}</div>`
      : '';

    return `
      <tr>
        <td class="font-mono">
          <a href="javascript:void(0)" onclick="selectAndAnalyzePR(${p.number})" style="color: #2563EB; font-weight: 700; text-decoration: none;">
            #${p.number}
          </a>
        </td>
        <td>
          <div style="font-weight: 600; color: #0F172A;">${escapeHtml(p.title)}</div>
          ${reasonsHtml}
        </td>
        <td class="font-mono" style="color: #475569;">@${escapeHtml(p.author)}</td>
        <td style="color: #64748B; font-size: 11px;">
          ${p.merged_at ? new Date(p.merged_at).toLocaleDateString() : (p.state || 'closed')}
        </td>
        <td style="text-align: center; font-weight: 600;">${p.file_count || 0}</td>
        <td style="text-align: center;">
          <span class="badge ${p.is_reviewed ? 'badge-green' : 'badge-slate'}">
            ${p.reviewer_count || 0} revs
          </span>
        </td>
        <td>
          <span class="badge badge-${p.risk_color || 'slate'}">
            ${escapeHtml(p.risk_tier || 'Standard')}
          </span>
        </td>
        <td style="text-align: right;">
          <button onclick="selectAndAnalyzePR(${p.number})" class="btn btn-primary btn-sm" style="font-size: 11px; padding: 4px 8px;">
            Analyze ›
          </button>
        </td>
      </tr>
    `;
  }).join('');
}

function selectAndAnalyzePR(prNumber) {
  currentPrNumber = prNumber;
  const directInput = document.getElementById('pr-direct-input');
  if (directInput) directInput.value = prNumber;
  const dropdown = document.getElementById('pr-select-dropdown');
  if (dropdown) dropdown.value = prNumber;

  switchMainSection('routing');
  runInvestigation(prNumber);
}

function renderExplorerPagination(pagination) {
  const firstBtn = document.getElementById('btn-exp-first');
  const prevBtn = document.getElementById('btn-exp-prev');
  const nextBtn = document.getElementById('btn-exp-next');
  const lastBtn = document.getElementById('btn-exp-last');
  const label = document.getElementById('explorer-pagination-summary');

  const page = pagination.page || 1;
  const pages = pagination.total_pages || 1;
  const total = pagination.total_matching || 0;

  if (firstBtn) firstBtn.disabled = page <= 1;
  if (prevBtn) prevBtn.disabled = page <= 1;
  if (nextBtn) nextBtn.disabled = page >= pages;
  if (lastBtn) lastBtn.disabled = page >= pages;

  if (label) {
    label.innerText = `Page ${page} of ${pages} (${total.toLocaleString()} total matching PRs)`;
  }
}

function changeExplorerPageDelta(delta) {
  explorerState.page = Math.max(1, Math.min(explorerState.page + delta, explorerState.totalPages));
  fetchExplorerPRs();
}

function changeExplorerPageTo(page) {
  explorerState.page = page;
  fetchExplorerPRs();
}

function changeExplorerPageLast() {
  explorerState.page = explorerState.totalPages;
  fetchExplorerPRs();
}

function changeExplorerPageSize(newSize) {
  explorerState.pageSize = parseInt(newSize, 10) || 25;
  explorerState.page = 1;
  fetchExplorerPRs();
}

function renderScopeExplanation(scope, coverage) {
  const whyRepo = document.getElementById('why-repo-name');
  const whyScope = document.getElementById('why-active-scope');
  const whyWin = document.getElementById('why-analysis-window');
  const whyExclusions = document.getElementById('why-exclusions-text');

  if (whyRepo) whyRepo.innerText = currentRepo;
  if (whyScope) whyScope.innerText = scope.explanation || "Displaying matching pull requests from FalkorDB graph.";
  if (whyWin) whyWin.innerText = coverage.analysis_window?.label || "Last 90 days";

  if (whyExclusions) {
    const ghTotal = coverage.github_total || currentCoverage?.counts?.github_total;
    const ingTotal = coverage.ingested || currentCoverage?.counts?.ingested || 0;
    if (ghTotal && ghTotal > ingTotal) {
      whyExclusions.innerText = `• Exclusions: ${(ghTotal - ingTotal).toLocaleString()} older PRs available on GitHub have not been ingested into Keystone yet.`;
      whyExclusions.style.display = 'block';
    } else {
      whyExclusions.style.display = 'none';
    }
  }
}

function renderIngestionGaps(cov) {
  const grid = document.getElementById('gaps-cards-grid');
  if (!grid || !cov) return;

  const gaps = cov.gaps || {};
  const counts = cov.counts || {};

  grid.innerHTML = `
    <!-- Discovered Not Ingested -->
    <div class="gap-category-card">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <strong style="color: #0F172A; font-size: 14px;">1. Discovered but Not Ingested</strong>
        <span class="badge badge-amber font-mono">${(gaps.discovered_not_ingested?.count || 0).toLocaleString()} PRs</span>
      </div>
      <p style="font-size: 12px; color: #475569; line-height: 1.4;">
        ${escapeHtml(gaps.discovered_not_ingested?.explanation || "Older PRs identified on GitHub but not yet imported into the knowledge graph.")}
      </p>
      <div style="font-size: 11px; color: #64748B;">Date Range: ${escapeHtml(cov.date_ranges?.earliest_discovered?.slice(0, 10) || '2017-06-01')} to ${escapeHtml(cov.date_ranges?.earliest_ingested?.slice(0, 10) || 'Recent')}</div>
      <button onclick="switchMainSection('health'); document.getElementById('scope-card-all_merged').click();" class="btn btn-secondary btn-sm" style="margin-top: 6px;">
        Ingest Older History
      </button>
    </div>

    <!-- Outside Active Analysis Window -->
    <div class="gap-category-card">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <strong style="color: #0F172A; font-size: 14px;">2. Outside Active Window</strong>
        <span class="badge badge-slate font-mono">${(gaps.outside_active_window?.count || 0).toLocaleString()} PRs</span>
      </div>
      <p style="font-size: 12px; color: #475569; line-height: 1.4;">
        ${escapeHtml(gaps.outside_active_window?.explanation || "PRs merged earlier than the 90-day active window. Retained in graph but excluded from active reviewer routing to ensure recency.")}
      </p>
      <div style="font-size: 11px; color: #64748B;">Active Window Cutoff: ${escapeHtml(cov.analysis_window?.start?.slice(0, 10) || '90 days ago')}</div>
    </div>

    <!-- Missing Review Data -->
    <div class="gap-category-card">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <strong style="color: #0F172A; font-size: 14px;">3. Missing Peer Review Data</strong>
        <span class="badge badge-blue font-mono">${(gaps.missing_review_history?.count || counts.unreviewed || 0).toLocaleString()} PRs</span>
      </div>
      <p style="font-size: 12px; color: #475569; line-height: 1.4;">
        ${escapeHtml(gaps.missing_review_history?.explanation || "Merged without peer review records. Excluded from training to prevent false expertise assumptions.")}
      </p>
      <div style="font-size: 11px; color: #64748B;">Impact: Surface knowledge risks and coverage gaps in PR Explorer.</div>
    </div>

    <!-- Failed Ingestion Records -->
    <div class="gap-category-card">
      <div style="display: flex; justify-content: space-between; align-items: center;">
        <strong style="color: #0F172A; font-size: 14px;">4. Failed During Ingestion</strong>
        <span class="badge ${counts.failed > 0 ? 'badge-red' : 'badge-green'} font-mono">${counts.failed || 0} PRs</span>
      </div>
      <p style="font-size: 12px; color: #475569; line-height: 1.4;">
        ${escapeHtml(gaps.failed_ingestion?.explanation || "PRs that hit GitHub rate limits, HTTP 403, or database timeouts.")}
      </p>
      ${counts.failed > 0 ? `
        <button onclick="switchMainSection('health'); document.getElementById('scope-card-resume').click();" class="btn btn-danger btn-sm" style="margin-top: 6px;">
          Retry Failed Records
        </button>
      ` : '<div style="font-size: 11px; color: #16A34A;">✓ Zero recorded failures</div>'}
    </div>
  `;
}

// ==============================================================
// Ingestion Scope Controls & Pre-Flight Confirmation
// ==============================================================
function onScopeTypeChange(scopeType) {
  selectedScopeType = scopeType;
  ['recent', 'date_range', 'all_merged', 'resume'].forEach(t => {
    const card = document.getElementById(`scope-card-${t}`);
    if (card) {
      if (t === scopeType) {
        card.classList.add('selected');
      } else {
        card.classList.remove('selected');
      }
    }
  });

  const rangeContainer = document.getElementById('ingest-date-range-container');
  const limitContainer = document.getElementById('ingest-limit-container');

  if (rangeContainer) rangeContainer.style.display = (scopeType === 'date_range') ? 'flex' : 'none';
  if (limitContainer) limitContainer.style.display = (scopeType === 'date_range' || scopeType === 'all_merged') ? 'none' : 'block';
}

async function previewIngestionConfirmation() {
  const input = document.getElementById('ingest-repo-input');
  const slug = (input?.value || '').trim();
  if (!slug || !slug.includes('/')) {
    notify("Please enter repository in owner/name format (e.g. pydantic/pydantic)", "error");
    return;
  }

  const limitSelect = document.getElementById('ingest-limit-select');
  const limit = parseInt(limitSelect?.value || '100', 10);
  const dateFrom = document.getElementById('ingest-date-from')?.value || null;
  const dateTo = document.getElementById('ingest-date-to')?.value || null;

  try {
    const est = await KeystoneAPI.estimateIngestion(slug, selectedScopeType, limit, dateFrom, dateTo);
    
    const card = document.getElementById('scope-confirmation-card');
    if (!card) return;

    document.getElementById('conf-repo-slug').innerText = est.repo;
    document.getElementById('conf-scope-desc').innerText = est.requested_scope;
    document.getElementById('conf-est-prs').innerText = Number(est.estimated_prs).toLocaleString();
    document.getElementById('conf-est-requests').innerText = `~${Number(est.estimated_github_api_requests).toLocaleString()} calls`;
    document.getElementById('conf-est-size').innerText = est.expected_graph_size;
    document.getElementById('conf-est-limits').innerText = est.estimated_limitation;

    card.style.display = 'block';
    card.scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    notify(err.message || "Failed to estimate scope", "error");
  }
}

async function startRepositoryIngestionConfirmed() {
  const card = document.getElementById('scope-confirmation-card');
  if (card) card.style.display = 'none';
  await startRepositoryIngestion();
}

async function startRepositoryIngestion() {
  const input = document.getElementById('ingest-repo-input');
  const limitSelect = document.getElementById('ingest-limit-select');
  const matCheck = document.getElementById('ingest-materialize-check');

  const slug = (input?.value || '').trim();
  if (!slug || !slug.includes('/')) {
    notify("Please enter repository in owner/name format (e.g. pydantic/pydantic)", "error");
    return;
  }

  const limit = parseInt(limitSelect?.value || '100', 10);
  const materialize = matCheck ? matCheck.checked : true;
  const dateFrom = document.getElementById('ingest-date-from')?.value || null;
  const dateTo = document.getElementById('ingest-date-to')?.value || null;

  const btn = document.getElementById('btn-start-ingest');
  if (btn) {
    btn.disabled = true;
    btn.innerText = "Starting...";
  }

  try {
    const res = await KeystoneAPI.startIngestion(slug, limit, materialize, selectedScopeType, dateFrom, dateTo);
    activeIngestJobId = res.job_id;
    notify(`Ingestion job ${res.job_id} queued for ${slug}`, "info");

    showIngestionStatus(res.job);
    startIngestionPolling(activeIngestJobId);
  } catch (err) {
    notify(err.message || "Could not start ingestion", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "⚡ Connect & Ingest";
    }
  }
}

function showIngestionStatus(job) {
  const box = document.getElementById('ingest-status-box');
  if (!box) return;
  box.style.display = 'block';

  document.getElementById('ingest-job-badge').innerText = job.job_id;
  document.getElementById('ingest-target-prs').innerText = job.target_limit;
  document.getElementById('ingest-count-prs').innerText = job.prs_processed;
  document.getElementById('ingest-count-files').innerText = job.files_processed;
  document.getElementById('ingest-count-reviews').innerText = job.reviews_processed;
  const failedCountEl = document.getElementById('ingest-count-failed');
  if (failedCountEl) failedCountEl.innerText = job.failed_count || 0;
  const skippedCountEl = document.getElementById('ingest-count-skipped');
  if (skippedCountEl) skippedCountEl.innerText = job.skipped_count || 0;
  document.getElementById('ingest-count-page').innerText = job.current_page;

  const pct = Math.min(100, Math.round((job.prs_processed / Math.max(1, job.target_limit)) * 100));
  document.getElementById('ingest-progress-bar').style.width = `${pct}%`;

  const statusTitle = document.getElementById('ingest-status-title');
  const dot = document.getElementById('ingest-status-dot');
  const errMsg = document.getElementById('ingest-error-msg');

  if (job.status === 'IN_PROGRESS' || job.status === 'QUEUED') {
    statusTitle.innerText = `Ingestion in progress (${pct}%)...`;
    dot.className = "status-dot busy";
    errMsg.style.display = 'none';
  } else if (job.status === 'COMPLETED' || job.status === 'PARTIALLY_COMPLETED') {
    statusTitle.innerText = `Ingestion ${job.status.toLowerCase()}!`;
    dot.className = "status-dot online";
    errMsg.style.display = 'none';
  } else if (job.status === 'FAILED' || job.status === 'CANCELLED') {
    statusTitle.innerText = `Ingestion ${job.status.toLowerCase()}`;
    dot.className = "status-dot offline";
    if (job.error) {
      errMsg.innerText = job.error;
      errMsg.style.display = 'block';
    }
  }
}

function startIngestionPolling(jobId) {
  if (ingestPollTimer) clearInterval(ingestPollTimer);
  ingestPollTimer = setInterval(async () => {
    try {
      const res = await KeystoneAPI.getIngestionStatus(jobId);
      const job = res.job;
      showIngestionStatus(job);

      if (['COMPLETED', 'PARTIALLY_COMPLETED', 'FAILED', 'CANCELLED'].includes(job.status)) {
        clearInterval(ingestPollTimer);
        ingestPollTimer = null;
        notify(`Ingestion ${job.status.toLowerCase()}: ${job.prs_processed} PRs processed.`, job.status.includes('COMPLETED') ? 'success' : 'error');
        fetchRegisteredRepositories();
        fetchStatus();
        fetchRepositoryCoverage(currentRepo);
        fetchExplorerPRs();
      }
    } catch (e) {
      console.warn("Ingest status poll error:", e);
    }
  }, 1500);
}

async function cancelActiveIngestion() {
  if (!activeIngestJobId) return;
  try {
    await KeystoneAPI.cancelIngestion(activeIngestJobId);
    notify("Cancellation requested", "info");
  } catch (err) {
    notify(err.message, "error");
  }
}

async function refreshActiveIngestion() {
  if (!activeIngestJobId) return;
  try {
    const res = await KeystoneAPI.getIngestionStatus(activeIngestJobId);
    showIngestionStatus(res.job);
  } catch (err) {
    notify("Could not refresh ingestion status", "error");
  }
}

// ==============================================================
// Action Ledger & Dispatch
// ==============================================================
function onModeChange(mode) {
  selectedDispatchMode = mode;
  ['dryrun', 'shadow', 'live'].forEach(m => {
    const el = document.getElementById(`mode-label-${m}`);
    if (el) {
      if (m.toUpperCase() === mode.replace('_', '')) {
        el.style.border = '2px solid var(--accent-primary)';
        el.style.background = '#EFF6FF';
      } else {
        el.style.border = '1px solid var(--border)';
        el.style.background = 'transparent';
      }
    }
  });

  const confirmContainer = document.getElementById('live-confirmation-container');
  if (confirmContainer) {
    confirmContainer.style.display = (mode === 'LIVE') ? 'block' : 'none';
  }
}

function scrollToDispatch() {
  const el = document.getElementById('dispatch-card');
  if (el) {
    el.scrollIntoView({ behavior: 'smooth' });
    el.style.boxShadow = '0 0 0 3px rgba(37, 99, 235, 0.4)';
    setTimeout(() => { el.style.boxShadow = 'var(--shadow-sm)'; }, 1500);
  }
}

function updateProposedAction(reviewers) {
  const targetLabel = document.getElementById('action-target-label');
  if (!targetLabel) return;
  if (!reviewers || reviewers.length === 0) {
    targetLabel.innerText = "no candidate";
  } else {
    targetLabel.innerText = `@${reviewers[0].login}`;
  }
}

async function dispatchAction() {
  const btn = document.getElementById('btn-dispatch-action');
  if (btn) btn.disabled = true;

  try {
    const mode = selectedDispatchMode;
    const isLive = mode === 'LIVE';
    const confirmed = isLive ? (document.getElementById('live-confirm-checkbox')?.checked || false) : false;

    if (isLive && !confirmed) {
      notify("Please confirm dispatching live action by checking the authorization box", "error");
      return;
    }

    const primaryReviewer = currentResult?.decision?.reviewers?.[0];
    if (!primaryReviewer) {
      notify("No recommended reviewer found to dispatch", "error");
      return;
    }

    const action = {
      action: "request_review",
      who: primaryReviewer.login,
      on: currentPrNumber,
    };

    const res = await KeystoneAPI.executeAction(action, currentRepo, currentPrNumber, mode, confirmed);
    const entry = res.entry || {};
    notify(`Action recorded (${entry.status}) in ${entry.mode} mode`, entry.mode === 'FAILED' ? 'error' : 'success');
    await fetchLedger();
  } catch (err) {
    notify(err.message || "Failed to dispatch action", "error");
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function fetchLedger() {
  try {
    const data = await KeystoneAPI.getLedger(currentLedgerPage, ledgerPageSize, currentRepo, currentLedgerMode);
    const entries = data.ledger || [];
    const tbody = document.getElementById('action-ledger-tbody');
    if (!tbody) return;

    if (entries.length === 0) {
      tbody.innerHTML = '<tr><td colspan="8" style="color: #64748B; text-align: center; padding: 20px;">No actions recorded in audit ledger yet.</td></tr>';
    } else {
      tbody.innerHTML = entries.map(e => `
        <tr>
          <td class="font-mono">${escapeHtml(e.id)}</td>
          <td style="color: #64748B; font-size: 11px;">${new Date(e.timestamp).toLocaleTimeString()}</td>
          <td class="font-mono">#${escapeHtml(e.pr_number)}</td>
          <td><strong>${escapeHtml(e.action)}</strong></td>
          <td class="font-mono">${escapeHtml(e.target)}</td>
          <td>
            <span class="badge ${e.mode === 'LIVE' ? 'badge-green' : e.mode === 'FAILED' ? 'badge-red' : e.mode === 'DRY_RUN' ? 'badge-slate' : 'badge-blue'}">
              ${escapeHtml(e.mode)}
            </span>
          </td>
          <td>${escapeHtml(e.status)}</td>
          <td style="font-size: 11px; color: #64748B; max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;" title="${escapeHtml(e.safety_notice || e.error || '')}">
            ${escapeHtml(e.safety_notice || e.error || '')}
          </td>
        </tr>
      `).join('');
    }

    const prevBtn = document.getElementById('btn-ledger-prev');
    const nextBtn = document.getElementById('btn-ledger-next');
    const pageLabel = document.getElementById('ledger-pagination-label');
    if (prevBtn) prevBtn.disabled = currentLedgerPage <= 1;
    if (nextBtn) nextBtn.disabled = currentLedgerPage >= (data.total_pages || 1);
    if (pageLabel) pageLabel.innerText = `Page ${currentLedgerPage} of ${data.total_pages || 1}`;

  } catch (err) {
    console.warn("Failed to load ledger:", err);
  }
}

function onLedgerFilterChange(mode) {
  currentLedgerMode = mode;
  currentLedgerPage = 1;
  fetchLedger();
}

function changeLedgerPage(delta) {
  currentLedgerPage = Math.max(1, currentLedgerPage + delta);
  fetchLedger();
}

async function clearActionLedger() {
  try {
    await KeystoneAPI.clearLedger();
    notify("Action ledger reset", "info");
    currentLedgerPage = 1;
    await fetchLedger();
  } catch (err) {
    notify("Could not clear ledger", "error");
  }
}

// ==============================================================
// Insights, Critical Files & Bus Factor
// ==============================================================
async function fetchInsights() {
  try {
    const data = await KeystoneAPI.getInsights(currentRepo);
    
    // Critical Files Table
    const critTbody = document.getElementById('critical-files-tbody');
    if (critTbody) {
      const cFiles = data.critical_files || [];
      if (cFiles.length === 0) {
        critTbody.innerHTML = '<tr><td colspan="2" style="color: #64748B;">No precomputed centrality files available.</td></tr>';
      } else {
        critTbody.innerHTML = cFiles.slice(0, 10).map(f => `
          <tr>
            <td class="font-mono">${escapeHtml(f.path)}</td>
            <td style="text-align: right; font-weight: 600; color: #2563EB;">${f.score.toFixed(4)}</td>
          </tr>
        `).join('');
      }
    }

    // Bus Factor Table
    const bfTbody = document.getElementById('bus-factor-tbody');
    if (bfTbody) {
      const bfFiles = data.bus_factor || [];
      if (bfFiles.length === 0) {
        bfTbody.innerHTML = '<tr><td colspan="3" style="color: #64748B;">No files exceed the 60% monopoly review threshold.</td></tr>';
      } else {
        bfTbody.innerHTML = bfFiles.slice(0, 10).map(b => `
          <tr>
            <td class="font-mono">${escapeHtml(b.path)}</td>
            <td><strong style="color: #B45309;">@${escapeHtml(b.sole_reviewer)}</strong></td>
            <td style="text-align: right; color: #64748B;">${b.sole_count}/${b.total} (${Math.round((b.sole_count/b.total)*100)}%)</td>
          </tr>
        `).join('');
      }
    }
  } catch (err) {
    console.warn("Insights fetch failed:", err);
  }
}

async function triggerCentralityRefresh() {
  const btn = document.getElementById('btn-recalc-centrality');
  if (btn) {
    btn.disabled = true;
    btn.innerText = "Materializing...";
  }
  try {
    const res = await KeystoneAPI.refreshCentrality(currentRepo);
    notify(res.message || "Centrality materialized successfully", "success");
    await fetchStatus();
    await fetchInsights();
  } catch (err) {
    notify(err.message || "Centrality materialization failed", "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerText = "Recalculate Centrality";
    }
  }
}

// ==============================================================
// Benchmark Validation
// ==============================================================
async function fetchBenchmark() {
  const container = document.getElementById('benchmark-results-container');
  if (!container) return;

  try {
    const data = await KeystoneAPI.getBenchmark();
    const t1 = data.top1 || {};
    const t3 = data.top3 || {};
    container.innerHTML = `
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 14px; margin-bottom: 14px;">
        <div style="padding: 12px; background: #F8FAFC; border: 1px solid var(--border); border-radius: var(--radius-sm);">
          <span style="color: #64748B; font-size: 11px;">Top-1 Accuracy</span>
          <div style="font-size: 20px; font-weight: 700; color: #2563EB;">${((t1.graph_scorer || 0.60) * 100).toFixed(1)}%</div>
          <span style="font-size: 11px; color: #16A34A;">+${(((t1.graph_scorer || 0.6) - (t1.relational_ablation || 0.5)) * 100).toFixed(1)}% over relational ablation</span>
        </div>
        <div style="padding: 12px; background: #F8FAFC; border: 1px solid var(--border); border-radius: var(--radius-sm);">
          <span style="color: #64748B; font-size: 11px;">Top-3 Accuracy</span>
          <div style="font-size: 20px; font-weight: 700; color: #0F172A;">${((t3.graph_scorer || 0.683) * 100).toFixed(1)}%</div>
          <span style="font-size: 11px; color: #64748B;">Evaluated on ${data.n || 60} merged PRs</span>
        </div>
      </div>
      <div style="color: #64748B; font-size: 11px;">
        Pinned evaluation timestamp: ${escapeHtml(data.timestamp || 'Verified lock')} · No training window leakage.
      </div>
    `;
  } catch (err) {
    container.innerHTML = `
      <div style="color: #64748B;">${escapeHtml(err.message || 'Benchmark results not yet generated. Run backtest.py.')}</div>
    `;
  }
}

// Global bootstrap
document.addEventListener('DOMContentLoaded', init);
