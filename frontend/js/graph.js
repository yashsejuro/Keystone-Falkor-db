/**
 * Keystone Knowledge Graph Visualizer (Light Theme Vis.js Network)
 * Provides clean, readable graph visualization supporting the explanation.
 */
let networkInstance = null;

function renderInteractiveNetwork(data) {
  const container = document.getElementById('vis-network-container');
  if (!container || typeof vis === 'undefined') return;

  if (!data || !data.pr_number) {
    container.innerHTML = '<div style="display:flex;height:100%;align-items:center;justify-content:center;color:#64748B;font-size:13px;">Select a PR and run analysis to view the evidence graph.</div>';
    return;
  }

  const prNum = data.pr_number;
  const pr = data.pr_details || {};
  const changedFiles = pr.files || [];
  const reviewers = data.decision?.reviewers || [];
  const evidenceMap = data.reviewer_evidence || {};

  const nodes = [];
  const edges = [];

  // 1. Central PR node (Primary Blue)
  nodes.push({
    id: `pr_${prNum}`,
    label: `PR #${prNum}`,
    color: {
      background: '#2563EB',
      border: '#1D4ED8',
      highlight: { background: '#1D4ED8', border: '#0F172A' }
    },
    shape: 'box',
    font: { color: '#FFFFFF', face: 'JetBrains Mono', size: 13, bold: true },
    margin: 10,
    title: `Pull Request #${prNum}: ${pr.title || ''}`
  });

  // 2. Touched File nodes (Amber)
  changedFiles.forEach((file, idx) => {
    const fileId = `file_${idx}`;
    const shortName = file.split('/').pop();
    nodes.push({
      id: fileId,
      label: shortName,
      color: {
        background: '#FFFBEB',
        border: '#D97706',
        highlight: { background: '#FEF3C7', border: '#B45309' }
      },
      shape: 'box',
      font: { color: '#92400E', face: 'JetBrains Mono', size: 10, bold: true },
      margin: 6,
      title: `File: ${file}`
    });
    edges.push({
      from: `pr_${prNum}`,
      to: fileId,
      label: 'TOUCHES',
      font: { size: 9, color: '#64748B', strokeWidth: 0 },
      color: { color: '#CBD5E1', highlight: '#2563EB' },
      arrows: 'to',
      length: 130
    });
  });

  // 3. Recommended Reviewer nodes (Green)
  reviewers.slice(0, 3).forEach((rev, idx) => {
    const revId = `rev_${rev.login}`;
    const ep = evidenceMap[rev.login] || {};
    const isPrimary = idx === 0;

    nodes.push({
      id: revId,
      label: `@${rev.login}\nScore: ${rev.score.toFixed(2)}`,
      color: {
        background: isPrimary ? '#16A34A' : '#4F46E5',
        border: isPrimary ? '#15803D' : '#4338CA',
        highlight: { background: isPrimary ? '#15803D' : '#4338CA', border: '#0F172A' }
      },
      shape: 'box',
      font: { color: '#FFFFFF', face: 'JetBrains Mono', size: 11, bold: true },
      margin: 8,
      title: `${isPrimary ? 'Primary' : 'Secondary'} Candidate Reviewer @${rev.login}`
    });

    const coveredSet = new Set(ep.files || []);
    changedFiles.forEach((file, fIdx) => {
      if (coveredSet.has(file)) {
        edges.push({
          from: revId,
          to: `file_${fIdx}`,
          label: 'REVIEWED',
          font: { size: 8, color: '#15803D', strokeWidth: 0 },
          color: { color: '#86EFAC', highlight: '#16A34A' },
          arrows: 'to',
          length: 150
        });
      }
    });

    // Bridge files
    (ep.bridges || []).slice(0, 2).forEach((b) => {
      const coPath = b.to || b.from;
      if (!coPath) return;
      const bridgeId = `bridge_${coPath}`;
      if (!nodes.some(n => n.id === bridgeId)) {
        nodes.push({
          id: bridgeId,
          label: coPath.split('/').pop(),
          color: { background: '#F5F3FF', border: '#7C3AED' },
          shape: 'ellipse',
          font: { color: '#5B21B6', face: 'JetBrains Mono', size: 9 },
          title: `Co-Change Bridge File: ${coPath}`
        });
      }
      edges.push({
        from: revId,
        to: bridgeId,
        label: `affinity (${b.weight || 1})`,
        font: { size: 8, color: '#7C3AED', strokeWidth: 0 },
        color: { color: '#DDD6FE', highlight: '#7C3AED' },
        dashes: true,
        length: 160
      });
    });
  });

  const networkData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: {
        gravitationalConstant: -40,
        centralGravity: 0.006,
        springLength: 120,
        springConstant: 0.08,
        damping: 0.4
      }
    },
    interaction: {
      hover: true,
      tooltipDelay: 100,
      zoomView: true,
      dragView: true
    }
  };

  networkInstance = new vis.Network(container, networkData, options);
}

function zoomInGraph() {
  if (networkInstance) {
    const scale = networkInstance.getScale();
    networkInstance.moveTo({ scale: scale * 1.25 });
  }
}

function zoomOutGraph() {
  if (networkInstance) {
    const scale = networkInstance.getScale();
    networkInstance.moveTo({ scale: scale * 0.8 });
  }
}

function fitGraph() {
  if (networkInstance) {
    networkInstance.fit({ animation: { duration: 300, easingFunction: 'easeInOutQuad' } });
  }
}

function resetGraph() {
  if (networkInstance) {
    fitGraph();
  }
}
