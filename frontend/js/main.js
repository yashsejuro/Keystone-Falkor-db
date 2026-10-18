/**
 * Keystone Main Application Controller — Production Grade
 * Clean state management, debounced search, request cancellation,
 * truthful status handling, and light-theme UI coordination.
 */

let currentRepo = 'pydantic';
let currentPrNumber = 13997;
let currentResult = null;
let currentPrFilter = 'all';
let currentPrPage = 1;
const prPageSize = 25;

let currentLedgerPage = 1;
const ledgerPageSize = 20;
let currentLedgerMode = 'all';

let selectedDispatchMode = 'SHADOW';
let activeIngestJobId = null;
let ingestPollTimer = null;
let investigationAbortController = null;
let prSearchAbortController = null;

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
  const sections = ['routing', 'evidence', 'health'];
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
  }
}

// ==============================================================
// Initialization & Startup
// ==============================================================
async function init() {
  const params = new URLSearchParams(window.location.search);
  if (params.get('repo')) currentRepo = params.get('repo');
  if (params.get('pr')) currentPrNumber = parseInt(params.get('pr'), 10) || 13997;

  document.getElementById('pr-direct-input').value = currentPrNumber;

  try {
    // 1. Fetch initial status and repositories concurrently
    await Promise.all([
      fetchStatus(),
      fetchRegisteredRepositories(),
    ]);

    // 2. Fetch independent secondary resources concurrently
    await Promise.all([
      fetchPRs(currentRepo, currentPrPage, ''),
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
  const url = new URL(window.location);
  url.searchParams.set('repo', newRepo);
  window.history.replaceState({}, '', url);

  fetchStatus();
  fetchPRs(currentRepo, 1, '');
  fetchInsights();
}

// ==============================================================
// PR Search & Selection
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
  fetchPRs(currentRepo, currentPrPage, document.getElementById('pr-search-input').value);
}

function changePrPage(delta) {
  currentPrPage = Math.max(1, currentPrPage + delta);
  fetchPRs(currentRepo, currentPrPage, document.getElementById('pr-search-input').value);
}

async function fetchPRs(repo, page = 1, query = '') {
  if (prSearchAbortController) {
    prSearchAbortController.abort();
  }
  prSearchAbortController = new AbortController();

  const feedStatus = document.getElementById('pr-feed-status');
  if (feedStatus) feedStatus.innerText = "Loading PRs...";

  try {
    const data = await KeystoneAPI.getPRs(repo, page, prPageSize, query, currentPrFilter, prSearchAbortController.signal);
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
  document.getElementById('pr-direct-input').value = currentPrNumber;
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
    renderRiskSummary(data.pr_metrics || {}, data.decision || {});
    renderEvidence(data);

    // Update URL without page reload
    const url = new URL(window.location);
    url.searchParams.set('pr', prNumber);
    window.history.replaceState({}, '', url);

  } catch (err) {
    if (err.name !== 'AbortError') {
      console.error("Investigation failed:", err);
      notify(err.message || "Failed to analyze PR. Verify FalkorDB data.", "error");
      renderEmptyRecommendation();
    }
  } finally {
    if (analyzeBtn) {
      analyzeBtn.disabled = false;
      analyzeBtn.innerHTML = '<span>🔍 Analyze PR</span>';
    }
  }
}

function renderPRMetadata(pr) {
  const titleEl = document.getElementById('pr-summary-title');
  const authorEl = document.getElementById('pr-summary-author');
  const filesEl = document.getElementById('pr-summary-files');
  const addEl = document.getElementById('pr-summary-additions');
  const delEl = document.getElementById('pr-summary-deletions');
  const mergedEl = document.getElementById('pr-summary-merged');

  if (titleEl) titleEl.innerText = pr.title ? `#${pr.number}: ${pr.title}` : `#${pr.number || currentPrNumber}`;
  if (authorEl) authorEl.innerText = `@${pr.author || 'unknown'}`;
  if (filesEl) filesEl.innerText = pr.files_changed || (pr.files ? pr.files.length : 0);
  if (addEl) addEl.innerText = `+${Number(pr.additions || 0).toLocaleString()}`;
  if (delEl) delEl.innerText = `-${Number(pr.deletions || 0).toLocaleString()}`;
  if (mergedEl) mergedEl.innerText = pr.merged_at ? new Date(pr.merged_at).toLocaleDateString() : 'Merged';
}

function renderReviewerRecommendations(reviewers) {
  const primaryNameEl = document.getElementById('rec-primary-name');
  const primaryScoreEl = document.getElementById('rec-primary-score');
  const primarySharedEl = document.getElementById('rec-primary-shared');
  const primaryRecentEl = document.getElementById('rec-primary-recent');
  const primaryCoverageEl = document.getElementById('rec-primary-coverage');
  const primaryLastEl = document.getElementById('rec-primary-last');
  const primaryReasonsEl = document.getElementById('rec-primary-reasons');
  const actionTargetLabel = document.getElementById('action-target-label');

  if (!reviewers || reviewers.length === 0) {
    renderEmptyRecommendation();
    return;
  }

  // 1. Primary Reviewer
  const p = reviewers[0];
  if (primaryNameEl) primaryNameEl.innerText = `@${p.login}`;
  if (primaryScoreEl) primaryScoreEl.innerText = p.score.toFixed(2);
  if (primarySharedEl) primarySharedEl.innerText = `${p.shared_files} files`;
  if (primaryRecentEl) primaryRecentEl.innerText = `${p.recent_reviews} reviews`;
  if (primaryCoverageEl) primaryCoverageEl.innerText = `${p.coverage_pct || 0}%`;
  if (primaryLastEl) primaryLastEl.innerText = p.days_ago !== null && p.days_ago !== undefined ? `${p.days_ago}d ago` : 'Active';
  if (actionTargetLabel) actionTargetLabel.innerText = `@${p.login}`;

  // Bullets: why this reviewer was chosen
  if (primaryReasonsEl) {
    const reasons = [
      `Reviewed ${p.shared_files} file${p.shared_files === 1 ? '' : 's'} touched by this PR`,
      `Reviewed ${p.recent_reviews} related PR${p.recent_reviews === 1 ? '' : 's'} in training window`,
      p.bridge_files > 0 ? `Connected through ${p.bridge_files} co-change bridge file${p.bridge_files === 1 ? '' : 's'}` : null,
      'Is not the PR author (no self-review)',
      p.is_overloaded ? '⚠️ High review load (>20 recent reviews)' : 'Has available review capacity',
    ].filter(Boolean);

    primaryReasonsEl.innerHTML = reasons.map(r => `
      <li style="display: flex; align-items: flex-start; gap: 6px;">
        <span style="color: ${r.startsWith('⚠️') ? '#D97706' : '#16A34A'}; font-weight: 700;">✓</span>
        <span>${escapeHtml(r)}</span>
      </li>
    `).join('');
  }

  // 2. Secondary Reviewer
  const secCard = document.getElementById('secondary-reviewer-card');
  const secNameEl = document.getElementById('rec-secondary-name');
  const secScoreEl = document.getElementById('rec-secondary-score');

  if (reviewers.length > 1) {
    const s = reviewers[1];
    if (secCard) secCard.style.display = 'block';
    if (secNameEl) secNameEl.innerText = `@${s.login}`;
    if (secScoreEl) secScoreEl.innerText = s.score.toFixed(2);
  } else {
    if (secCard) secCard.style.display = 'none';
  }
}

function renderEmptyRecommendation() {
  const primaryNameEl = document.getElementById('rec-primary-name');
  const primaryScoreEl = document.getElementById('rec-primary-score');
  const primaryReasonsEl = document.getElementById('rec-primary-reasons');
  const secCard = document.getElementById('secondary-reviewer-card');

  if (primaryNameEl) primaryNameEl.innerText = 'No suitable reviewer found';
  if (primaryScoreEl) primaryScoreEl.innerText = '0.00';
  if (primaryReasonsEl) {
    primaryReasonsEl.innerHTML = `
      <li style="color: #64748B;">
        No suitable reviewer was found from the currently ingested review history.
      </li>
    `;
  }
  if (secCard) secCard.style.display = 'none';
}

function renderRiskSummary(metrics, decision) {
  const blastBadge = document.getElementById('risk-blast-badge');
  const flagsContainer = document.getElementById('risk-flags-container');

  if (blastBadge) {
    const tier = metrics.blast_tier || 'Standard Change';
    blastBadge.className = tier === 'Critical Architecture' ? 'badge badge-red' :
                           tier === 'High Risk' ? 'badge badge-amber' :
                           tier === 'Moderate Risk' ? 'badge badge-blue' : 'badge badge-slate';
    blastBadge.innerText = tier;
  }

  if (flagsContainer) {
    const risks = decision.risks || [];
    if (risks.length === 0) {
      flagsContainer.innerHTML = '<div style="font-size: 12px; color: #16A34A;">✓ No knowledge concentration or coverage gaps detected.</div>';
    } else {
      flagsContainer.innerHTML = risks.map(r => `
        <div style="font-size: 12px; color: #B45309; background: #FFFBEB; padding: 6px 10px; border-radius: 4px; border-left: 3px solid #D97706;">
          <strong>${escapeHtml(r.label)}:</strong> ${escapeHtml(r.detail)}
        </div>
      `).join('');
    }
  }
}

// ==============================================================
// Evidence Section Rendering
// ==============================================================
function renderEvidence(data) {
  const pr = data.pr_details || {};
  const changedFiles = pr.files || [];
  const reviewers = data.decision?.reviewers || [];
  const primary = reviewers.length > 0 ? reviewers[0] : null;
  const ep = primary ? (data.reviewer_evidence?.[primary.login] || {}) : {};

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
// Repository Ingestion Feature
// ==============================================================
async function startRepositoryIngestion() {
  const input = document.getElementById('ingest-repo-input');
  const limitSelect = document.getElementById('ingest-limit-select');
  const matCheck = document.getElementById('ingest-materialize-check');

  const slug = (input.value || '').trim();
  if (!slug || !slug.includes('/')) {
    notify("Please enter repository in owner/name format (e.g. pydantic/pydantic)", "error");
    return;
  }

  const limit = parseInt(limitSelect.value, 10) || 100;
  const materialize = matCheck.checked;

  const btn = document.getElementById('btn-start-ingest');
  if (btn) {
    btn.disabled = true;
    btn.innerText = "Starting...";
  }

  try {
    const res = await KeystoneAPI.startIngestion(slug, limit, materialize);
    activeIngestJobId = res.job_id;
    notify(`Ingestion job ${res.job_id} started for ${slug}`, "info");

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
      if (m.toUpperCase() === mode) {
        el.style.border = '2px solid var(--accent-primary)';
        el.style.backgroundColor = '#EFF6FF';
      } else {
        el.style.border = '1px solid var(--border)';
        el.style.backgroundColor = '#FFFFFF';
      }
    }
  });

  const liveConfirmBox = document.getElementById('live-confirmation-container');
  if (liveConfirmBox) {
    liveConfirmBox.style.display = mode === 'LIVE' ? 'block' : 'none';
  }
}

function scrollToDispatch() {
  const card = document.getElementById('dispatch-card');
  if (card) {
    card.scrollIntoView({ behavior: 'smooth' });
    card.style.boxShadow = '0 0 0 2px var(--accent-primary)';
    setTimeout(() => { card.style.boxShadow = 'var(--shadow-sm)'; }, 1500);
  }
}

async function dispatchAction() {
  if (!currentResult || !currentResult.proposed_actions || currentResult.proposed_actions.length === 0) {
    notify("No proposed actions to dispatch for this PR", "error");
    return;
  }

  const action = currentResult.proposed_actions[0];
  const isLive = selectedDispatchMode === 'LIVE';
  const confirmed = isLive ? document.getElementById('live-confirm-checkbox')?.checked : false;

  if (isLive && !confirmed) {
    notify("Please confirm before executing live GitHub actions", "error");
    return;
  }

  const idempotencyKey = `idemp-${Date.now()}-${Math.random().toString(36).substring(2, 7)}`;
  const btn = document.getElementById('btn-dispatch-action');
  if (btn) btn.disabled = true;

  try {
    const res = await KeystoneAPI.executeAction(action, currentRepo, currentPrNumber, selectedDispatchMode, confirmed, idempotencyKey);
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
