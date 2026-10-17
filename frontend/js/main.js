/**
 * Keystone Main Application Controller
 */

let currentRepo = 'pydantic';
let availablePRs = [];
let currentResult = null;
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
  setTimeout(() => el.remove(), 4500);
}

function createScoreRing(score, size = 72) {
  const r = (size - 10) / 2;
  const circumference = 2 * Math.PI * r;
  const offset = circumference * (1 - Math.min(score, 1));
  const color = score >= 0.7 ? '#34d399' : score >= 0.4 ? '#818cf8' : '#fbbf24';
  return `
    <div class="score-ring" style="width:${size}px;height:${size}px;">
      <svg width="${size}" height="${size}" viewBox="0 0 ${size} ${size}">
        <circle class="bg-ring" cx="${size/2}" cy="${size/2}" r="${r}"/>
        <circle class="fg-ring" cx="${size/2}" cy="${size/2}" r="${r}"
                style="stroke: ${color}; stroke-dasharray: ${circumference}; stroke-dashoffset: ${offset};"/>
      </svg>
      <div class="score-value">${score.toFixed(2)}</div>
    </div>
  `;
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
    notify("Keystone couldn't finish loading. Check FalkorDB connection.", "error");
  }
}

async function fetchStatus() {
  try {
    const data = await KeystoneAPI.getStatus(currentRepo);
    const repos = data.repos || ['pydantic', 'fastapi'];
    const topSelect = document.getElementById('repo-select');
    if (topSelect) {
      topSelect.innerHTML = repos.map(r => `<option value="${r}">${r}</option>`).join('');
      if (repos.includes(currentRepo)) topSelect.value = currentRepo;
      else { currentRepo = repos[0]; topSelect.value = currentRepo; }
    }

    // Hero live stats
    const heroNodes = document.getElementById('hero-nodes-count');
    const heroEdges = document.getElementById('hero-edges-count');
    const heroRepos = document.getElementById('hero-repos-count');
    if (heroNodes) heroNodes.innerText = Number(data.nodes || 0).toLocaleString();
    if (heroEdges) heroEdges.innerText = Number(data.edges || 0).toLocaleString();
    if (heroRepos) heroRepos.innerText = `${repos.length} Repos`;

    allowedWriteRepos = data.allowed_write_repos || allowedWriteRepos;
    sandboxRepo = data.sandbox_repo || sandboxRepo;
    const sbLabel = document.getElementById('sandbox-repo-label');
    if (sbLabel) sbLabel.innerText = sandboxRepo;
    const preTag = document.getElementById('preset-repo-tag');
    if (preTag) preTag.innerText = currentRepo;

    const pill = document.getElementById('conn-pill');
    const txt = document.getElementById('conn-text');
    if (pill && txt) {
      if (data.is_live) {
        pill.style.background = 'rgba(5, 46, 31, 0.4)';
        pill.style.borderColor = 'rgba(52, 211, 153, 0.2)';
        txt.innerText = "FalkorDB Connected";
        txt.className = "text-emerald-300 font-medium";
      } else {
        pill.style.background = 'rgba(78, 50, 0, 0.4)';
        pill.style.borderColor = 'rgba(251, 191, 36, 0.2)';
        txt.innerText = "FalkorDB Offline";
        txt.className = "text-amber-300 font-medium";
      }
    }
    renderBenchmarkButtons();
  } catch (err) {
    console.error("Status error", err);
    notify("Unable to load repository status.", "error");
  }
}

function renderBenchmarkButtons() {
  const container = document.getElementById('benchmark-buttons-container');
  if (!container) return;
  const list = BENCHMARKS[currentRepo] || BENCHMARKS['pydantic'];
  container.innerHTML = list.map(b => `
    <button onclick="selectPr(${b.num})" class="text-left p-2.5 rounded-xl transition cursor-pointer group"
            style="background: rgba(6, 7, 14, 0.5); border: 1px solid var(--line);"
            onmouseover="this.style.borderColor='rgba(99, 102, 241, 0.25)'"
            onmouseout="this.style.borderColor='var(--line)'">
      <span class="font-mono text-violet-400 font-semibold block text-xs">${b.label}</span>
      <span class="text-slate-400 truncate block text-[10px] mt-0.5">${b.desc}</span>
    </button>
  `).join('');
}

let currentPrFilterTab = 'all';
let prSearchQuery = '';
let prStats = { total: 0, reviewed: 0, unreviewed: 0 };

async function fetchPRs(repo) {
  try {
    const feedLabel = document.getElementById('pr-feed-count');
    if (feedLabel) feedLabel.innerText = "Loading 500 PRs...";
    const data = await KeystoneAPI.getPRs(repo, 500);
    availablePRs = data.prs || [];
    prStats = data.stats || { total: availablePRs.length, reviewed: 0, unreviewed: 0 };
    if (feedLabel) feedLabel.innerText = `${availablePRs.length} PRs in Graph`;

    updatePrFilterCounts();
    renderPrDropdown();
  } catch (err) {
    console.error("PRs load error", err);
    const feedLabel = document.getElementById('pr-feed-count');
    if (feedLabel) feedLabel.innerText = "Unavailable";
    notify("Unable to load pull requests.", "error");
  }
}

function updatePrFilterCounts() {
  const pillAll = document.getElementById('pr-count-all');
  const pillRev = document.getElementById('pr-count-reviewed');
  const pillUnrev = document.getElementById('pr-count-unreviewed');
  if (pillAll) pillAll.innerText = prStats.total || availablePRs.length;
  if (pillRev) pillRev.innerText = prStats.reviewed || availablePRs.filter(p => p.is_reviewed).length;
  if (pillUnrev) pillUnrev.innerText = prStats.unreviewed || availablePRs.filter(p => !p.is_reviewed).length;
}

function setPrFilterTab(tab) {
  currentPrFilterTab = tab;
  ['all', 'reviewed', 'unreviewed'].forEach(t => {
    const el = document.getElementById(`pr-filter-tab-${t}`);
    if (el) {
      if (t === tab) {
        el.className = "badge badge-brand cursor-pointer";
      } else {
        el.className = "badge cursor-pointer";
        el.style.background = "rgba(255,255,255,0.04)";
        el.style.color = "var(--text-muted)";
      }
    }
  });
  renderPrDropdown();
  renderTriageTable();
}

function filterPrDropdown(q) {
  prSearchQuery = (q || '').toLowerCase().trim();
  renderPrDropdown();
  renderTriageTable();
}

function getFilteredPRs() {
  return availablePRs.filter(p => {
    if (currentPrFilterTab === 'reviewed' && !p.is_reviewed) return false;
    if (currentPrFilterTab === 'unreviewed' && p.is_reviewed) return false;
    if (prSearchQuery) {
      const matchNum = String(p.number).includes(prSearchQuery);
      const matchTitle = (p.title || '').toLowerCase().includes(prSearchQuery);
      const matchAuthor = (p.author || '').toLowerCase().includes(prSearchQuery);
      return matchNum || matchTitle || matchAuthor;
    }
    return true;
  });
}

function renderPrDropdown() {
  const selectEl = document.getElementById('pr-select');
  if (!selectEl) return;
  const filtered = getFilteredPRs();
  if (filtered.length === 0) {
    selectEl.innerHTML = `<option value="">No PRs matching query</option>`;
    return;
  }
  selectEl.innerHTML = filtered.slice(0, 100).map(pr => `
    <option value="${pr.number}">
      #${pr.number}: ${pr.title.slice(0, 48)}${pr.title.length > 48 ? '…' : ''} (@${pr.author} · ${pr.file_count}f · ${pr.is_reviewed ? '✓' + pr.reviewer_count + ' rev' : 'unreviewed'})
    </option>
  `).join('');

  const currentVal = parseInt(document.getElementById('pr-input')?.value);
  if (currentVal && filtered.some(p => p.number === currentVal)) {
    selectEl.value = currentVal;
  }
}

function openPrTriageModal() {
  const modal = document.getElementById('pr-triage-modal');
  if (modal) {
    modal.classList.remove('hidden');
    renderTriageTable();
    document.body.style.overflow = 'hidden';
  }
}

function closePrTriageModal() {
  const modal = document.getElementById('pr-triage-modal');
  if (modal) {
    modal.classList.add('hidden');
    document.body.style.overflow = '';
  }
}

function renderTriageTable() {
  const tbody = document.getElementById('triage-table-body');
  const countBadge = document.getElementById('triage-count-badge');
  if (!tbody) return;
  const filtered = getFilteredPRs();
  if (countBadge) countBadge.innerText = `${filtered.length} of ${availablePRs.length} PRs`;

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="6" class="py-12 text-center text-slate-500 text-xs">No pull requests match the current search or filter.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.slice(0, 200).map(pr => `
    <tr class="reviewer-row" style="border-bottom: 1px solid var(--line);">
      <td class="py-2.5 px-3 font-mono font-bold text-indigo-400">#${pr.number}</td>
      <td class="py-2.5 px-3 text-white font-medium max-w-[340px] truncate" title="${pr.title}">${pr.title}</td>
      <td class="py-2.5 px-3 text-slate-300 font-mono text-[11px]">@${pr.author}</td>
      <td class="py-2.5 px-3 text-slate-400 font-mono text-[11px]">${pr.file_count} files</td>
      <td class="py-2.5 px-3">
        ${pr.is_reviewed
          ? `<span class="badge badge-ok text-[9px] font-mono">✓ ${pr.reviewer_count} reviewer${pr.reviewer_count > 1 ? 's' : ''}</span>`
          : `<span class="badge badge-warn text-[9px] font-mono">Unreviewed</span>`}
      </td>
      <td class="py-2.5 px-3 text-right">
        <button onclick="selectAndAnalyzePr(${pr.number})" class="btn-primary text-xs px-3 py-1">
          ⚡ Analyze
        </button>
      </td>
    </tr>
  `).join('');
}

function selectAndAnalyzePr(num) {
  closePrTriageModal();
  selectPr(num);
}

function onSelectPrFromDropdown(val) {
  if (!val) return;
  document.getElementById('pr-input').value = val;
  runInvestigation();
}

async function onRepoChange(repo) {
  currentRepo = repo;
  const topSelect = document.getElementById('repo-select');
  if (topSelect) topSelect.value = repo;
  const preTag = document.getElementById('preset-repo-tag');
  if (preTag) preTag.innerText = repo;
  renderBenchmarkButtons();
  await fetchStatus();
  await fetchPRs(repo);
  if (availablePRs.length > 0) {
    document.getElementById('pr-input').value = availablePRs[0].number;
  } else {
    document.getElementById('pr-input').value = repo === 'fastapi' ? 16503 : 13997;
  }
  await fetchInsights();
  await runInvestigation();
}

function selectPr(num) {
  document.getElementById('pr-input').value = num;
  const selectEl = document.getElementById('pr-select');
  if (selectEl && [...selectEl.options].some(o => o.value == num)) selectEl.value = num;
  runInvestigation();
}

async function runInvestigation() {
  if (runInProgress) return;
  const prInput = document.getElementById('pr-input');
  const pr = parseInt(prInput ? prInput.value : 13997) || 13997;
  runInProgress = true;
  setRunButtonState(true, "Analyzing PR...", "⏳");

  try {
    currentResult = await KeystoneAPI.investigate(pr, currentRepo);
    renderResult(currentResult);
    notify(`Analysis ready for PR #${pr}`, "success");
  } catch (err) {
    console.error("Investigation error:", err);
    notify(`Couldn't analyze PR #${pr}. ${err.message || ''}`.trim(), "error");
  } finally {
    runInProgress = false;
    setRunButtonState(false);
  }
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

let simulatedExcludedReviewer = null;

function onWhatIfChange(val) {
  simulatedExcludedReviewer = val || null;
  if (currentResult) {
    renderResult(currentResult);
    if (simulatedExcludedReviewer) {
      notify(`Simulating absence of @${simulatedExcludedReviewer}. Re-routing active!`, "default");
    } else {
      notify("Simulation reset. Normal routing restored.", "default");
    }
  }
}

function copyGitHubDossier() {
  if (!currentResult) return;
  const pr = currentResult.pr_details || {};
  const metrics = currentResult.pr_metrics || {};
  const reviewers = currentResult.decision?.reviewers || [];
  const primary = reviewers[0] || { login: 'unassigned', score: 0, shared_files: 0 };
  const secondary = reviewers[1] || { login: 'unassigned', score: 0 };
  const bfFiles = metrics.bus_factor_files || [];
  const peakC = metrics.criticality?.max_centrality || 0.0;
  const rationale = currentResult.narration || currentResult.decision?.rationale || "Graph-directed decision";

  const md = `### 🛡️ Keystone Graph PR Review Routing Report
> **FalkorDB Multi-Hop Knowledge Risk Agent**

| Reviewer Role | Candidate | Graph Score | Historical Affinity |
| :--- | :--- | :--- | :--- |
| **Primary Reviewer** | **@${primary.login}** | \`${primary.score.toFixed(2)}\` | ${primary.shared_files} files touched, ${primary.recent_reviews} recent reviews |
| **Cross-Training** | **@${secondary.login}** | \`${secondary.score.toFixed(2)}\` | Secondary pairing to distribute codebase knowledge |

#### 📊 Risk & Impact Telemetry
- **Blast Radius Tier:** \`${metrics.blast_tier}\` (${peakC.toFixed(3)} peak betweenness centrality)
- **Monopolized Files:** ${bfFiles.length > 0 ? bfFiles.map(b => '\`' + b.path + '\` (@' + b.sole_reviewer + ')').join(', ') : 'None detected (No single point of failure)'}
- **Knowledge Rationale:** ${rationale}

*Generated autonomously via FalkorDB Knowledge Graph (Track 01: Agents That Act on Connected Data)*`;

  navigator.clipboard.writeText(md).then(() => {
    notify("📋 GitHub Markdown comment copied to clipboard!", "success");
  }).catch(() => {
    notify("Couldn't copy to clipboard", "error");
  });
}

function copyCurrentHopCypher() {
  const el = document.getElementById('explain-cypher-code');
  if (el) {
    navigator.clipboard.writeText(el.innerText).then(() => {
      notify("OpenCypher query copied!", "success");
    });
  }
}

function renderResult(data) {
  const pr = data.pr_details || {};
  const metrics = data.pr_metrics || {};
  let reviewers = data.decision?.reviewers || [];
  const riskFlags = data.decision?.risk_flags || [];
  const changedFiles = pr.files || [];

  // Populate What-If Select
  const whatIfSelect = document.getElementById('what-if-select');
  if (whatIfSelect && !simulatedExcludedReviewer) {
    whatIfSelect.innerHTML = `<option value="">(None — Normal Routing)</option>` +
      reviewers.map(r => `<option value="${r.login}">@${r.login} (Simulate Leave)</option>`).join('');
  }

  // Filter if simulation active
  if (simulatedExcludedReviewer) {
    reviewers = reviewers.filter(r => r.login !== simulatedExcludedReviewer);
    const statusEl = document.getElementById('what-if-status');
    if (statusEl) {
      statusEl.innerHTML = `<span class="text-amber-400 font-bold">⚠️ Rerouted: @${simulatedExcludedReviewer} on leave.</span>`;
    }
  } else {
    const statusEl = document.getElementById('what-if-status');
    if (statusEl) {
      statusEl.innerHTML = `<span class="text-emerald-400">✓ All reviewers available</span>`;
    }
  }

  document.getElementById('pr-badge-num').innerText = `PR #${data.pr_number}`;
  document.getElementById('pr-badge-state').innerText = pr.state ? pr.state.toUpperCase() : 'MERGED';
  document.getElementById('pr-repo-indicator').innerText = currentRepo;
  document.getElementById('pr-title').innerText = pr.title || `Pull Request #${data.pr_number}`;
  document.getElementById('pr-author').innerText = pr.author || 'contributor';
  document.getElementById('pr-files-count').innerText = `${changedFiles.length} file${changedFiles.length === 1 ? '' : 's'}`;
  const adds = pr.additions != null ? pr.additions : 0;
  const dels = pr.deletions != null ? pr.deletions : 0;
  document.getElementById('pr-lines-changed').innerText = `+${adds} / -${dels}`;

  document.getElementById('stat-churn').innerText = `+${adds} / -${dels}`;
  document.getElementById('stat-files-count').innerText = `${changedFiles.length} files touched`;
  const peakC = metrics.criticality?.max_centrality || 0.0;
  document.getElementById('stat-blast-text').innerText = `${peakC.toFixed(3)} peak`;

  const blastBadge = document.getElementById('blast-badge');
  blastBadge.innerText = metrics.blast_tier || 'Impact';
  if (metrics.blast_color === 'rose') {
    blastBadge.className = "badge badge-danger text-[10px]";
  } else if (metrics.blast_color === 'amber') {
    blastBadge.className = "badge badge-warn text-[10px]";
  } else {
    blastBadge.className = "badge badge-brand text-[10px]";
  }

  const bfFiles = metrics.bus_factor_files || [];
  document.getElementById('stat-bf-exposure').innerText = bfFiles.length > 0 ? `${bfFiles.length} file${bfFiles.length > 1 ? 's' : ''} monopolized` : 'No monopoly';
  document.getElementById('stat-pool-depth').innerText = `${reviewers.length} evaluated`;
  const topMatch = reviewers[0];
  document.getElementById('stat-coverage-rate').innerText = topMatch ? `${topMatch.coverage_pct}% (${topMatch.shared_files}/${changedFiles.length})` : '0%';

  const filesList = document.getElementById('pr-files-list');
  const topCoveredSet = new Set(topMatch?.covered_files || []);
  const bfSet = new Set(bfFiles.map(b => b.path));
  filesList.innerHTML = changedFiles.map(f => {
    const isCovered = topCoveredSet.has(f);
    const hasBf = bfSet.has(f);
    const borderColor = hasBf ? 'rgba(251,113,133,0.3)' : isCovered ? 'rgba(52,211,153,0.2)' : 'rgba(251,191,36,0.2)';
    const textColor = hasBf ? '#fda4af' : isCovered ? '#e2e8f0' : '#fcd34d';
    return `
      <div class="font-mono text-[11px] px-2.5 py-1.5 rounded-lg flex items-center gap-1.5"
           style="background: rgba(6,7,14,0.5); border: 1px solid ${borderColor}; color: ${textColor};">
        <span>📄</span>
        <span class="truncate max-w-[200px]">${f}</span>
        ${hasBf ? '<span class="text-[9px] px-1.5 py-0.5 rounded" style="background: rgba(251,113,133,0.1); color: #fb7185;">BUS-FACTOR</span>' : ''}
        ${isCovered ? '<span class="text-[9px] text-emerald-400">✓</span>' : '<span class="text-[9px] text-amber-400">⚠</span>'}
      </div>
    `;
  }).join('') || '<span class="text-xs text-slate-500">No files recorded</span>';

  // Reviewer Pairing
  const pairingContainer = document.getElementById('pairing-container');
  const primary = reviewers[0];
  const secondary = reviewers[1];
  let pairingHtml = '';

  if (primary) {
    pairingHtml += `
      <div class="p-4 rounded-xl space-y-3" style="background: rgba(6,7,14,0.5); border: 1px solid rgba(99,102,241,0.2);">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-extrabold text-violet-400 uppercase tracking-wider">Primary Reviewer</span>
        </div>
        <div class="flex items-center gap-3">
          ${createScoreRing(primary.score)}
          <div>
            <div class="text-lg font-bold text-white">@${primary.login}</div>
            <div class="text-[11px] text-slate-400 mt-0.5">
              ${primary.shared_files} of ${changedFiles.length} files · ${primary.recent_reviews} reviews
              ${primary.days_ago != null ? ' · ' + primary.days_ago + 'd ago' : ''}
            </div>
          </div>
        </div>
      </div>
    `;
  }
  if (secondary) {
    pairingHtml += `
      <div class="p-4 rounded-xl space-y-3" style="background: rgba(6,7,14,0.5); border: 1px solid var(--line);">
        <div class="flex items-center justify-between">
          <span class="text-[10px] font-extrabold text-emerald-400 uppercase tracking-wider">Secondary (Cross-Training)</span>
        </div>
        <div class="flex items-center gap-3">
          ${createScoreRing(secondary.score)}
          <div>
            <div class="text-lg font-bold text-white">@${secondary.login}</div>
            <div class="text-[11px] text-slate-400 mt-0.5">
              ${secondary.shared_files} of ${changedFiles.length} files ·
              ${secondary.is_overloaded ? 'High Load' : 'Available'}
            </div>
          </div>
        </div>
      </div>
    `;
  } else {
    pairingHtml += `
      <div class="p-4 rounded-xl flex items-center justify-center text-slate-500 text-xs" style="background: rgba(6,7,14,0.4); border: 1px solid var(--line);">
        Single candidate above threshold.
      </div>
    `;
  }
  pairingContainer.innerHTML = pairingHtml;

  const summaryText = data.narration || data.decision?.rationale || "";
  document.getElementById('rationale-text').innerText = summaryText ? `"${summaryText}"` : "";

  // Risk Flags
  const riskContainer = document.getElementById('risk-container');
  if (riskFlags.length === 0) {
    riskContainer.innerHTML = `
      <div class="flex items-center gap-2.5 text-xs p-3 rounded-xl" style="background: rgba(5,46,31,0.3); border: 1px solid rgba(52,211,153,0.15); color: #6ee7b7;">
        <span>✅</span>
        <span>No knowledge coverage gaps or single-maintainer bottlenecks on this PR.</span>
      </div>
    `;
  } else {
    riskContainer.innerHTML = riskFlags.map(rf => `
      <div class="flex items-start gap-2.5 text-xs p-3 rounded-xl" style="background: rgba(78,50,0,0.3); border: 1px solid rgba(251,191,36,0.2); color: #fde68a;">
        <span>⚠️</span>
        <div>
          <span class="font-semibold text-amber-300">${rf.type || 'Risk'}:</span>
          <span class="text-amber-100">${rf.file || rf.detail || ''}</span>
          ${rf.sole_reviewer ? `<span class="block text-[11px] text-amber-300/80 mt-0.5">Review monopoly held by <strong>@${rf.sole_reviewer}</strong> (${rf.sole_reviews}/${rf.total_reviews} reviews)</span>` : ''}
        </div>
      </div>
    `).join('');
  }

  // All Candidate Reviewers Table
  const tbody = document.getElementById('reviewers-body');
  tbody.innerHTML = reviewers.map((r, i) => `
    <tr class="reviewer-row" style="border-bottom: 1px solid var(--line);" onclick="selectCandidateReviewer('${r.login}')">
      <td class="py-2.5 px-2 text-slate-500">${i + 1}</td>
      <td class="py-2.5 px-2 font-bold text-white flex items-center gap-1.5">
        <span>@${r.login}</span>
        ${r.is_overloaded ? '<span class="badge badge-warn text-[9px]">Fatigued</span>' : ''}
      </td>
      <td class="py-2.5 px-2 text-right font-bold" style="color: ${r.score >= 0.7 ? '#34d399' : r.score >= 0.4 ? '#818cf8' : '#fbbf24'};">${r.score.toFixed(2)}</td>
      <td class="py-2.5 px-2 text-right text-slate-300">${r.coverage_pct}%</td>
      <td class="py-2.5 px-2 text-right text-slate-400">${r.shared_files}</td>
      <td class="py-2.5 px-2 text-right text-slate-400">${(data.reviewer_evidence[r.login]?.bridges || []).length}</td>
      <td class="py-2.5 px-2 text-right text-slate-400">${r.recent_reviews}</td>
      <td class="py-2.5 px-2 text-slate-400">${r.days_ago != null ? r.days_ago + 'd ago' : '—'}</td>
      <td class="py-2.5 px-2 text-center">
        <button onclick="event.stopPropagation(); selectCandidateReviewer('${r.login}'); switchTab('explain');"
                class="text-[10px] text-violet-400 hover:text-violet-300 font-sans cursor-pointer underline">Path ▸</button>
      </td>
    </tr>
  `).join('');

  // Proposed Action Plans
  const actionContainer = document.getElementById('actions-container');
  const actions = data.decision?.actions || [];
  actionContainer.innerHTML = actions.map((act, i) => `
    <div class="action-card flex items-center justify-between">
      <div class="flex items-center gap-3">
        <input type="checkbox" id="action-cb-${i}" checked class="rounded border-slate-600 cursor-pointer">
        <div>
          <div class="text-xs font-semibold text-white">
            ${act.action === 'assign_reviewer' ? `Assign @${act.who}` : act.action === 'request_cross_training' ? `Cross-train @${act.who}` : `Add label "${act.label}"`}
          </div>
          <div class="text-[11px] text-slate-400 mt-0.5">${act.reason}</div>
        </div>
      </div>
      <span class="badge ${act.action === 'assign_reviewer' ? 'badge-ok' : 'badge-brand'} text-[10px] uppercase font-mono">${act.action.replace('_', ' ')}</span>
    </div>
  `).join('') || '<div class="text-xs text-slate-500">No actions suggested.</div>';

  if (reviewers.length > 0) {
    selectCandidateReviewer(reviewers[0].login);
  }

  renderInteractiveNetwork(data);
}

function selectCandidateReviewer(login) {
  if (!currentResult) return;
  const ep = currentResult.reviewer_evidence?.[login] || {};
  const changedFiles = currentResult.pr_details?.files || [];

  const segmentContainer = document.getElementById('candidate-selector-segment');
  if (segmentContainer) {
    segmentContainer.innerHTML = (currentResult.decision?.reviewers || []).slice(0, 4).map(r => `
      <button onclick="selectCandidateReviewer('${r.login}')"
              class="px-2.5 py-1 rounded-lg text-xs font-mono font-medium transition cursor-pointer ${r.login === login ? 'bg-indigo-600 text-white font-bold' : 'text-slate-400 hover:text-slate-200'}">
        @${r.login}
      </button>
    `).join('');
  }

  const gw = document.getElementById('graph-walk');
  const directFiles = ep.files || [];
  const bridges = ep.bridges || [];
  gw.innerHTML = `
    <div class="text-xs font-medium text-slate-400 mb-2">Traversal Path to <strong class="text-white">@${login}</strong>:</div>
    <div class="flex items-center gap-2 overflow-x-auto py-2 text-xs font-mono">
      <div class="px-3 py-2 rounded-xl text-white font-bold" style="background: rgba(99,102,241,0.25); border: 1px solid rgba(99,102,241,0.5);">
        PR #${currentResult.pr_number}
      </div>
      <div class="text-violet-400 font-bold">──TOUCHES──▶</div>
      <div class="px-3 py-2 rounded-xl text-cyan-300 font-medium" style="background: rgba(6,182,212,0.15); border: 1px solid rgba(6,182,212,0.3);">
        ${directFiles.length} Direct Files
      </div>
      ${bridges.length > 0 ? `
        <div class="text-purple-400 font-bold">──CO_CHANGES──▶</div>
        <div class="px-3 py-2 rounded-xl text-purple-300 font-medium" style="background: rgba(168,85,247,0.15); border: 1px solid rgba(168,85,247,0.3);">
          ${bridges.length} Bridge Files
        </div>
      ` : ''}
      <div class="text-emerald-400 font-bold">──REVIEWED_BY──▶</div>
      <div class="px-3 py-2 rounded-xl text-emerald-300 font-bold" style="background: rgba(52,211,153,0.15); border: 1px solid rgba(52,211,153,0.3);">
        @${login}
      </div>
    </div>
  `;

  document.getElementById('explain-files').innerHTML = directFiles.map(f => `
    <div class="stat-card text-xs flex items-center justify-between">
      <span class="font-mono text-slate-200 truncate">${f}</span>
      <span class="badge badge-ok text-[10px]">DIRECT OVERLAP</span>
    </div>
  `).join('') || '<div class="text-xs text-slate-500">No direct files shared. Connected via co-change bridges.</div>';

  document.getElementById('explain-bridges').innerHTML = bridges.map(b => `
    <div class="stat-card text-xs flex items-center justify-between">
      <div>
        <span class="font-mono text-slate-300 text-[11px]">${b.pr_file || ''}</span>
        <span class="text-slate-500 mx-1">⟷</span>
        <span class="font-mono text-purple-300 text-[11px] font-medium">${b.co_file}</span>
      </div>
      <span class="badge badge-brand text-[10px] font-mono">Weight ${b.weight}</span>
    </div>
  `).join('') || '<div class="text-xs text-slate-500">No co-change bridge traversals used.</div>';
}

function switchTab(tab) {
  const tabs = ['routing', 'explain', 'graph', 'health'];
  tabs.forEach(t => {
    document.getElementById(`tab-${t}`).classList.remove('active');
    document.getElementById(`tab-btn-${t}`).classList.remove('active');
    document.getElementById(`tab-btn-${t}`).setAttribute('aria-selected', 'false');
  });
  document.getElementById(`tab-${tab}`).classList.add('active');
  document.getElementById(`tab-btn-${tab}`).classList.add('active');
  document.getElementById(`tab-btn-${tab}`).setAttribute('aria-selected', 'true');

  if (tab === 'graph' && networkInstance) setTimeout(() => networkInstance.fit(), 150);
  if (tab === 'health') fetchLedger();
}

async function applyApprovedPlan() {
  if (!currentResult) return;
  const actions = currentResult.decision?.actions || [];
  const btn = document.getElementById('apply-plan-btn');
  btn.disabled = true;
  btn.innerText = "Executing Actions...";

  let executed = 0;
  for (let i = 0; i < actions.length; i++) {
    const cb = document.getElementById(`action-cb-${i}`);
    if (cb && cb.checked) {
      try {
        await KeystoneAPI.executeAction(actions[i], currentRepo, currentResult.pr_number);
        executed++;
      } catch (err) {
        console.error("Action error", err);
      }
    }
  }

  btn.disabled = false;
  btn.innerText = "✓ Approve & Execute Selected";
  notify(`Dispatched ${executed} action${executed === 1 ? '' : 's'} to audit ledger!`, "success");
  await fetchLedger();
  switchTab('health');
}

async function fetchLedger() {
  try {
    const data = await KeystoneAPI.getLedger();
    fullLedgerData = data.ledger || [];
    renderLedger();
    const lPill = document.getElementById('ledger-badge');
    if (lPill) lPill.innerText = data.count || 0;
    const lCountPill = document.getElementById('ledger-count-pill');
    if (lCountPill) lCountPill.innerText = `${data.count} Actions`;
    const liveEl = document.getElementById('live-actions-count');
    if (liveEl) liveEl.innerText = data.live_count || 0;
    const shadowEl = document.getElementById('shadow-actions-count');
    if (shadowEl) shadowEl.innerText = data.shadow_count || 0;
  } catch (err) {
    console.error("Ledger error", err);
  }
}

function filterLedger(mode) {
  currentLedgerFilter = mode;
  ['all', 'live', 'shadow'].forEach(m => {
    const btn = document.getElementById(`filter-ledger-${m}`);
    if (!btn) return;
    if ((m === 'all' && mode === 'all') || (m.toUpperCase() === mode)) {
      btn.className = "badge badge-brand cursor-pointer";
    } else {
      btn.className = "badge cursor-pointer";
      btn.style.background = "rgba(255,255,255,0.04)";
      btn.style.color = "var(--text-muted)";
    }
  });
  renderLedger();
}

function renderLedger() {
  const tbody = document.getElementById('ledger-table-body');
  if (!tbody) return;
  const filtered = currentLedgerFilter === 'all'
    ? fullLedgerData
    : fullLedgerData.filter(e => e.mode === currentLedgerFilter);

  if (filtered.length === 0) {
    tbody.innerHTML = `<tr><td colspan="8" class="py-8 text-center text-slate-500 text-xs">No ${currentLedgerFilter === 'all' ? '' : currentLedgerFilter} actions logged yet. Approve actions from the Routing tab.</td></tr>`;
    return;
  }

  tbody.innerHTML = filtered.map(e => `
    <tr class="reviewer-row" style="border-bottom: 1px solid var(--line);">
      <td class="py-2.5 px-3 text-slate-400">${e.id}</td>
      <td class="py-2.5 px-3 text-slate-500">${e.timestamp.slice(11, 19)}</td>
      <td class="py-2.5 px-3">
        <span class="badge ${e.mode === 'LIVE' ? 'badge-ok' : 'badge-brand'} text-[9px]">${e.mode}</span>
      </td>
      <td class="py-2.5 px-3 text-white font-semibold">${e.target} (#${e.pr_number})</td>
      <td class="py-2.5 px-3 text-violet-300">${e.action}</td>
      <td class="py-2.5 px-3 text-slate-400 truncate max-w-[180px]">${e.destination}</td>
      <td class="py-2.5 px-3 text-slate-400 truncate max-w-[200px]">${e.reason}</td>
      <td class="py-2.5 px-3 text-right text-emerald-400 font-bold">EXECUTED</td>
    </tr>
  `).join('');
}

async function clearActionLedger() {
  await KeystoneAPI.clearLedger();
  notify("Action audit ledger cleared.", "default");
  await fetchLedger();
}

function setCypherQuery(q) {
  const input = document.getElementById('cypher-input');
  if (input) input.value = q;
  executeCypher();
}

async function executeCypher() {
  const input = document.getElementById('cypher-input');
  const q = input ? input.value : '';
  const status = document.getElementById('cypher-status');
  const countEl = document.getElementById('cypher-count');
  const body = document.getElementById('cypher-table-body');
  status.innerText = "Executing...";
  body.innerHTML = `<tr><td class="py-4 text-center text-slate-500">Querying graph...</td></tr>`;
  try {
    const data = await KeystoneAPI.executeCypher(q, currentRepo);
    status.innerText = "Success";
    countEl.innerText = `${data.count} row(s)`;
    if (data.rows.length === 0) {
      body.innerHTML = `<tr><td class="py-4 text-center text-slate-500">(Empty result)</td></tr>`;
      return;
    }
    body.innerHTML = data.rows.map(row => `
      <tr class="reviewer-row" style="border-bottom: 1px solid var(--line);">
        ${row.map(cell => `<td class="py-2 px-3 text-slate-300">${typeof cell === 'object' ? JSON.stringify(cell) : cell}</td>`).join('')}
      </tr>
    `).join('');
  } catch (err) {
    status.innerText = `Error: ${err.message}`;
    body.innerHTML = `<tr><td class="py-3" style="color: var(--danger);">${err.message}</td></tr>`;
    notify("Cypher query failed.", "error");
  }
}

async function fetchInsights() {
  try {
    const data = await KeystoneAPI.getInsights(currentRepo);
    const bfList = document.getElementById('bus-factor-list');
    bfList.innerHTML = (data.bus_factor || []).map(b => `
      <div class="stat-card text-xs">
        <div class="font-mono text-slate-200 font-medium truncate">${b.path}</div>
        <div class="flex items-center justify-between mt-1.5 text-slate-400">
          <span>Sole: <strong class="font-mono" style="color: var(--danger);">@${b.sole_reviewer}</strong></span>
          <span>${b.sole_count}/${b.total} (${Math.round(b.sole_count / b.total * 100)}%)</span>
        </div>
      </div>
    `).join('') || '<div class="text-xs text-slate-500">No coverage gaps detected.</div>';

    const cfList = document.getElementById('critical-files-list');
    cfList.innerHTML = (data.critical_files || []).map(c => `
      <div class="stat-card text-xs flex items-center justify-between">
        <span class="font-mono text-slate-200 truncate pr-2">${c.path}</span>
        <span class="badge badge-brand text-[10px] font-mono">${typeof c.score === 'number' ? c.score.toFixed(3) : c.score}</span>
      </div>
    `).join('') || '<div class="text-xs text-slate-500">None calculated.</div>';
  } catch (err) {
    console.error("Insights error", err);
    notify("Repository insights unavailable.", "error");
  }
}

/* === Interactive 1-Minute Guided Demo Tour === */
let tourCurrentStep = 0;
const TOUR_STEPS = [
  {
    title: "1. Select Any Pull Request (500 Ingested)",
    desc: "Keystone continuously ingests repository commits, PRs, and review histories into FalkorDB. Select benchmark PR #13997 (JSON Schema & Aliases) or search among 500 PRs using Ctrl+K.",
    tab: "routing",
    action: () => {
      document.getElementById('workspace')?.scrollIntoView({ behavior: 'smooth' });
      selectPr(13997);
    }
  },
  {
    title: "2. Reviewer Pairing & Knowledge Bottlenecks",
    desc: "Notice how Keystone recommends @davidhewitt as Primary domain expert (highest composite score) paired with a Secondary Reviewer for cross-training. This prevents knowledge monopolies and maintains review velocity.",
    tab: "routing",
    action: () => {
      switchTab('routing');
    }
  },
  {
    title: "3. Multi-Hop Reasoning & Explainability",
    desc: "Zero LLM hallucinations. Keystone traverses PR -> Files -> Co-Change Bridges -> Historical Reviewers. Inspect the exact graph walk and mathematical formula breakdown (30% overlap, 30% structural, 20% activity, 20% recency).",
    tab: "explain",
    action: () => {
      switchTab('explain');
    }
  },
  {
    title: "4. Interactive Force-Directed Subgraph",
    desc: "Explore the live force-directed graph. Purple represents the PR, cyan shows touched files, green highlights candidate reviewers, and violet indicates co-change bridges. Click any node to inspect FalkorDB properties.",
    tab: "graph",
    action: () => {
      switchTab('graph');
    }
  },
  {
    title: "5. Safe Human Approval & Audit Ledger",
    desc: "Keystone adheres to safe action dispatch. Maintainers review proposed actions before execution, safely logged to the shadow tracking ledger to prevent upstream spam.",
    tab: "health",
    action: () => {
      switchTab('health');
    }
  }
];

function startInteractiveDemoTour() {
  tourCurrentStep = 0;
  openTourModal();
  renderTourStep();
}

function openTourModal() {
  let modal = document.getElementById('tour-guide-modal');
  if (!modal) {
    modal = document.createElement('div');
    modal.id = 'tour-guide-modal';
    modal.className = 'fixed bottom-6 right-6 z-50 glass-strong p-6 rounded-2xl border border-indigo-500/40 shadow-2xl max-w-md space-y-4';
    document.body.appendChild(modal);
  }
  modal.classList.remove('hidden');
}

function closeTourModal() {
  const modal = document.getElementById('tour-guide-modal');
  if (modal) modal.classList.add('hidden');
}

function renderTourStep() {
  const modal = document.getElementById('tour-guide-modal');
  if (!modal) return;
  const step = TOUR_STEPS[tourCurrentStep];
  step.action();

  modal.innerHTML = `
    <div class="flex items-center justify-between pb-2 border-b border-indigo-500/20">
      <div class="flex items-center gap-2">
        <span class="badge badge-brand text-[10px]">Step ${tourCurrentStep + 1} of ${TOUR_STEPS.length}</span>
        <span class="text-xs font-bold text-white tracking-tight">Interactive Guide</span>
      </div>
      <button onclick="closeTourModal()" class="text-slate-400 hover:text-white text-sm cursor-pointer">✕</button>
    </div>
    <div class="space-y-1.5">
      <h4 class="text-sm font-bold text-indigo-300">${step.title}</h4>
      <p class="text-xs text-slate-300 leading-relaxed">${step.desc}</p>
    </div>
    <div class="flex items-center justify-between pt-2">
      <button onclick="prevTourStep()" class="btn-secondary text-xs px-3 py-1 cursor-pointer" ${tourCurrentStep === 0 ? 'disabled style="opacity:0.4;cursor:not-allowed;"' : ''}>
        ← Prev
      </button>
      <div class="flex gap-1">
        ${TOUR_STEPS.map((_, i) => `<span class="w-2 h-2 rounded-full ${i === tourCurrentStep ? 'bg-indigo-400' : 'bg-slate-700'}"></span>`).join('')}
      </div>
      <button onclick="nextTourStep()" class="btn-primary text-xs px-4 py-1 cursor-pointer">
        ${tourCurrentStep === TOUR_STEPS.length - 1 ? 'Finish 🏁' : 'Next →'}
      </button>
    </div>
  `;
}

function nextTourStep() {
  if (tourCurrentStep < TOUR_STEPS.length - 1) {
    tourCurrentStep++;
    renderTourStep();
  } else {
    closeTourModal();
    notify("Tour complete! You're ready to explore Keystone.", "success");
  }
}

function prevTourStep() {
  if (tourCurrentStep > 0) {
    tourCurrentStep--;
    renderTourStep();
  }
}

/* === Global Keyboard Shortcuts === */
document.addEventListener('keydown', (e) => {
  const tag = (e.target.tagName || '').toLowerCase();
  const isInput = tag === 'input' || tag === 'textarea' || tag === 'select';

  // Ctrl + K or / to open PR Triage Browser
  if ((e.ctrlKey && e.key === 'k') || (!isInput && e.key === '/')) {
    e.preventDefault();
    openPrTriageModal();
    return;
  }

  // Escape closes modals
  if (e.key === 'Escape') {
    closePrTriageModal();
    closeTourModal();
    return;
  }

  // 1-4 switches tabs when not typing
  if (!isInput && !e.ctrlKey && !e.altKey && !e.metaKey) {
    if (e.key === '1') switchTab('routing');
    else if (e.key === '2') switchTab('explain');
    else if (e.key === '3') switchTab('graph');
    else if (e.key === '4') switchTab('health');
  }
});

window.onload = init;
