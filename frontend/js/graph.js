/**
 * Keystone Knowledge Graph Visualizer (Vis.js Network)
 */
let networkInstance = null;

function renderInteractiveNetwork(data) {
  const container = document.getElementById('network-canvas');
  if (!container || typeof vis === 'undefined') return;

  const prNum = data.pr_number;
  const pr = data.pr_details || {};
  const changedFiles = pr.files || [];
  const reviewers = data.decision?.reviewers || [];
  const evidenceMap = data.reviewer_evidence || {};

  const nodes = [];
  const edges = [];

  // 1. Central PR node
  nodes.push({
    id: `pr_${prNum}`,
    label: `PR #${prNum}`,
    color: { background: '#6366f1', border: '#818cf8', highlight: { background: '#818cf8', border: '#fff' } },
    shape: 'box',
    font: { color: '#ffffff', face: 'JetBrains Mono', size: 14, bold: true },
    margin: 10,
    title: `Pull Request #${prNum}: ${pr.title || ''}`
  });

  // 2. Touched File nodes
  changedFiles.forEach((file, idx) => {
    const fileId = `file_${idx}`;
    const shortName = file.split('/').pop();
    nodes.push({
      id: fileId,
      label: shortName,
      color: { background: '#0891b2', border: '#06b6d4', highlight: { background: '#06b6d4', border: '#fff' } },
      shape: 'ellipse',
      font: { color: '#ffffff', face: 'JetBrains Mono', size: 11 },
      title: `File: ${file}`
    });
    edges.push({
      from: `pr_${prNum}`,
      to: fileId,
      label: 'TOUCHES',
      font: { size: 9, color: '#94a3b8', strokeWidth: 0 },
      color: { color: 'rgba(99, 102, 241, 0.45)', highlight: '#818cf8' },
      arrows: 'to',
      length: 140
    });
  });

  // 3. Top Candidate Reviewer nodes & connections
  reviewers.slice(0, 4).forEach((rev, idx) => {
    const revId = `rev_${rev.login}`;
    const ep = evidenceMap[rev.login] || {};
    const isTop = idx === 0;

    nodes.push({
      id: revId,
      label: `@${rev.login}\n${rev.score.toFixed(2)}`,
      color: {
        background: isTop ? '#059669' : '#10b981',
        border: isTop ? '#34d399' : '#6ee7b7',
        highlight: { background: '#34d399', border: '#fff' }
      },
      shape: 'circle',
      font: { color: '#ffffff', face: 'JetBrains Mono', size: isTop ? 13 : 11, bold: isTop },
      title: `Candidate Reviewer @${rev.login} (Composite Score: ${rev.score.toFixed(2)})`
    });

    const coveredSet = new Set(ep.files || []);
    changedFiles.forEach((file, fIdx) => {
      if (coveredSet.has(file)) {
        edges.push({
          from: revId,
          to: `file_${fIdx}`,
          label: 'REVIEWED',
          font: { size: 8, color: '#6ee7b7', strokeWidth: 0 },
          color: { color: 'rgba(52, 211, 153, 0.45)', highlight: '#34d399' },
          arrows: 'to',
          dashes: false,
          length: 160
        });
      }
    });

    // Co-change bridge edges
    (ep.bridges || []).slice(0, 3).forEach((b) => {
      const bridgeId = `bridge_${b.co_file}`;
      if (!nodes.some(n => n.id === bridgeId)) {
        nodes.push({
          id: bridgeId,
          label: b.co_file.split('/').pop(),
          color: { background: '#8b5cf6', border: '#a78bfa' },
          shape: 'box',
          font: { color: '#ffffff', face: 'JetBrains Mono', size: 9 },
          title: `Co-Changed Bridge File: ${b.co_file}`
        });
      }
      edges.push({
        from: revId,
        to: bridgeId,
        label: `affinity (${b.weight || 1})`,
        font: { size: 8, color: '#c4b5fd', strokeWidth: 0 },
        color: { color: 'rgba(167, 139, 250, 0.35)' },
        dashes: true,
        length: 170
      });
    });
  });

  const networkData = { nodes: new vis.DataSet(nodes), edges: new vis.DataSet(edges) };
  const options = {
    physics: {
      solver: 'forceAtlas2Based',
      forceAtlas2Based: { gravitationalConstant: -45, centralGravity: 0.008, springLength: 130, springConstant: 0.08, damping: 0.4 }
    },
    interaction: { hover: true, tooltipDelay: 100, zoomView: true, dragView: true }
  };

  networkInstance = new vis.Network(container, networkData, options);

  networkInstance.on("click", function (params) {
    if (params.nodes.length > 0) {
      const nodeId = params.nodes[0];
      const nodeObj = nodes.find(n => n.id === nodeId);
      if (nodeObj) {
        const insp = document.getElementById('node-inspector');
        if (insp) {
          insp.classList.remove('hidden');
          document.getElementById('inspector-title').innerText = nodeObj.label.replace('\n', ' ');
          document.getElementById('inspector-desc').innerText = nodeObj.title || 'Knowledge Graph Node';
        }
      }
    }
  });
}

function rebuildGraphVisualization(currentResult) {
  if (currentResult) renderInteractiveNetwork(currentResult);
}
