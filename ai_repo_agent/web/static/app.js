const state = {
  repositories: [],
  currentRepository: null,
  currentSnapshot: null,
  currentPayload: null,
  currentFinding: null,
  currentPatchFinding: null,
  currentTreePath: null,
  activeScanJobId: null,
  activeScanPath: null,
  scanPollTimer: null,
  scanActivity: [],
  lastScanActivityKey: null,
};

const elements = {};

document.addEventListener("DOMContentLoaded", async () => {
  bindElements();
  bindEvents();
  await loadBootstrap();
});

function bindElements() {
  const ids = [
    "repo-list", "scan-form", "scan-path", "browse-folder-button", "rescan-button", "hero-title", "hero-meta",
    "stat-findings", "stat-risk", "stat-changes", "stat-memory",
    "overview-repo", "overview-summary", "overview-runs", "overview-health",
    "overview-languages", "overview-top-findings", "overview-memory", "overview-diff", "overview-critical-paths", "overview-scan-posture", "overview-risk-board", "tree-view", "tree-filter",
    "tree-summary", "file-detail", "file-preview", "findings-table", "finding-detail",
    "compare-new", "compare-fixed", "compare-unchanged", "compare-deps", "compare-deltas",
    "compare-summary", "compare-files", "compare-dependency-list", "memory-timeline",
    "memory-detail", "memory-symbols", "memory-chunks", "chat-output", "chat-question",
    "chat-send", "patch-generate", "patch-output", "patch-selection", "refresh-logs", "log-output",
    "settings-form", "settings-provider", "settings-api-key", "settings-model", "settings-base-url", "settings-analyzer-backend",
    "settings-lsp-enabled", "settings-timeout", "settings-retries", "settings-max-findings", "settings-chunk-lines", "settings-watch",
    "settings-log-level", "install-hook", "report-json", "report-md", "report-html",
    "filter-severity", "filter-category", "filter-source", "repo-graph", "graph-summary",
    "signal-bands", "tree-breadcrumb", "finding-kpis", "compare-insights",
    "memory-constellation", "memory-constellation-summary", "scan-stage", "scan-badge",
    "scan-progress-bar", "scan-status-text", "scan-percent", "scan-activity"
  ];
  for (const id of ids) {
    elements[id] = document.getElementById(id);
  }
}

function bindEvents() {
  document.querySelectorAll(".nav-item").forEach((button) => {
    button.addEventListener("click", () => switchPage(button.dataset.page, button));
  });

  elements["scan-form"].addEventListener("submit", async (event) => {
    event.preventDefault();
    const path = elements["scan-path"].value.trim();
    if (!path) return;
    await runScan(path);
  });

  elements["rescan-button"].addEventListener("click", async () => {
    if (!state.currentRepository) return;
    await runScan(state.currentRepository.path);
  });

  elements["browse-folder-button"].addEventListener("click", browseFolder);

  elements["tree-filter"].addEventListener("input", () => renderTree());
  elements["chat-send"].addEventListener("click", sendChat);
  elements["patch-generate"].addEventListener("click", generatePatch);
  elements["refresh-logs"].addEventListener("click", loadLogs);
  elements["settings-form"].addEventListener("submit", saveSettings);
  elements["settings-provider"].addEventListener("change", handleProviderChange);
  elements["install-hook"].addEventListener("click", installHook);
  elements["report-json"].addEventListener("click", () => downloadReport("json"));
  elements["report-md"].addEventListener("click", () => downloadReport("md"));
  elements["report-html"].addEventListener("click", () => downloadReport("html"));
  elements["filter-severity"].addEventListener("change", renderFindings);
  elements["filter-category"].addEventListener("change", renderFindings);
  elements["filter-source"].addEventListener("change", renderFindings);
}

async function loadBootstrap() {
  const response = await fetch("/api/bootstrap");
  const payload = await response.json();
  state.repositories = payload.repositories;
  renderRepositories();
  applySettings(payload.settings);
  renderLogs(payload.logs);
  if (state.repositories.length) {
    await loadRepository(state.repositories[0].id);
  }
}

async function runScan(path) {
  setScanState({
    status: "running",
    stage: "Submitting scan job",
    progress: 2,
    path,
    append: `Queued scan for ${path}`,
  });
  toggleScanControls(true);
  const response = await fetch("/api/scan", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({path}),
  });
  if (!response.ok) {
    const message = await response.text();
    setScanState({
      status: "failed",
      stage: "Scan submission failed",
      progress: 100,
      append: `Failed to start scan: ${message}`,
    });
    toggleScanControls(false);
    alert(`Scan failed: ${message}`);
    return;
  }
  const payload = await response.json();
  state.activeScanJobId = payload.job_id;
  state.activeScanPath = path;
  setScanState({
    status: payload.status,
    stage: payload.stage,
    progress: payload.progress,
    append: `Background job ${payload.job_id} started`,
  });
  startScanPolling();
}

async function browseFolder() {
  const response = await fetch("/api/pick-folder");
  if (!response.ok) {
    alert(`Folder picker failed: ${await response.text()}`);
    return;
  }
  const payload = await response.json();
  if (!payload.path) return;
  elements["scan-path"].value = payload.path;
  await runScan(payload.path);
}

function startScanPolling() {
  stopScanPolling();
  state.scanPollTimer = window.setInterval(async () => {
    if (!state.activeScanJobId) {
      stopScanPolling();
      return;
    }
    await pollScanJob(state.activeScanJobId);
  }, 1200);
  pollScanJob(state.activeScanJobId);
}

function stopScanPolling() {
  if (state.scanPollTimer) {
    window.clearInterval(state.scanPollTimer);
    state.scanPollTimer = null;
  }
}

async function pollScanJob(jobId) {
  const response = await fetch(`/api/scan-jobs/${encodeURIComponent(jobId)}`);
  if (!response.ok) {
    stopScanPolling();
    toggleScanControls(false);
    return;
  }
  const payload = await response.json();
  setScanState({
    status: payload.status,
    stage: payload.stage,
    progress: payload.progress,
    path: payload.path,
    append: payload.stage,
  });
  await loadLogs();
  if (payload.status === "completed" && payload.result) {
    stopScanPolling();
    toggleScanControls(false);
    state.activeScanJobId = null;
    state.currentRepository = payload.result.repository;
    state.currentSnapshot = payload.result.snapshot;
    state.currentPayload = payload.result;
    state.repositories = await fetchRepositories();
    renderRepositories();
    renderCurrentPayload();
    setScanState({
      status: "completed",
      stage: "Scan complete",
      progress: 100,
      path: payload.path,
      append: `Completed scan for ${payload.path}`,
    });
    return;
  }
  if (payload.status === "failed") {
    stopScanPolling();
    toggleScanControls(false);
    state.activeScanJobId = null;
    setScanState({
      status: "failed",
      stage: "Scan failed",
      progress: 100,
      path: payload.path,
      append: payload.error || "Scan failed.",
    });
    alert(`Scan failed: ${payload.error || "Unknown error"}`);
  }
}

async function fetchRepositories() {
  const response = await fetch("/api/repositories");
  const payload = await response.json();
  return payload.repositories;
}

async function loadRepository(repoId) {
  const response = await fetch(`/api/repositories/${repoId}/latest`);
  if (!response.ok) return;
  const payload = await response.json();
  state.currentRepository = payload.repository;
  state.currentSnapshot = payload.snapshot;
  state.currentPayload = payload;
  state.currentFinding = null;
  state.currentPatchFinding = null;
  state.currentTreePath = null;
  renderCurrentPayload();
  await loadLogs();
}

function renderRepositories() {
  elements["repo-list"].innerHTML = "";
  for (const repo of state.repositories) {
    const card = document.createElement("button");
    card.className = `repo-card ${state.currentRepository?.id === repo.id ? "active" : ""}`;
    card.innerHTML = `<strong>${escapeHtml(repo.name)}</strong><br><span class="subtle">${escapeHtml(repo.path)}</span>`;
    card.addEventListener("click", async () => loadRepository(repo.id));
    elements["repo-list"].appendChild(card);
  }
}

function setScanState({status, stage, progress, path, append}) {
  if (stage) elements["scan-stage"].textContent = stage;
  elements["scan-status-text"].textContent = path || state.activeScanPath || "No scan in progress.";
  if (typeof progress === "number") {
    const safeProgress = Math.max(0, Math.min(100, progress));
    elements["scan-progress-bar"].style.width = `${safeProgress}%`;
    elements["scan-percent"].textContent = `${safeProgress}%`;
  }
  if (status) {
    elements["scan-badge"].className = `scan-badge ${status}`;
    elements["scan-badge"].textContent = status[0].toUpperCase() + status.slice(1);
  }
  if (append) {
    const activityKey = `${status || ""}|${stage || ""}|${progress ?? ""}|${append}`;
    if (state.lastScanActivityKey !== activityKey) {
      state.lastScanActivityKey = activityKey;
      state.scanActivity.unshift({
        message: append,
        time: new Date().toLocaleTimeString([], {hour: "2-digit", minute: "2-digit", second: "2-digit"}),
      });
    }
    state.scanActivity = state.scanActivity.slice(0, 7);
  }
  renderScanActivity();
}

function renderScanActivity() {
  const items = state.scanActivity.length ? state.scanActivity : [{message: "Waiting for the next repository scan.", time: "Idle"}];
  elements["scan-activity"].innerHTML = items.map((item) => `
    <div class="activity-item">
      <span class="activity-dot"></span>
      <span class="activity-copy">${escapeHtml(item.message)}</span>
      <span class="activity-time">${escapeHtml(item.time)}</span>
    </div>
  `).join("");
}

function toggleScanControls(disabled) {
  document.querySelector('#scan-form button[type="submit"]').disabled = disabled;
  elements["rescan-button"].disabled = disabled;
  elements["browse-folder-button"].disabled = disabled;
}

function renderCurrentPayload() {
  const payload = state.currentPayload;
  if (!payload) return;
  const {repository, snapshot, findings, compare, symbols, chunks, patches, reviews, scan_runs, scan_metadata, files} = payload;
  elements["hero-title"].textContent = repository.name;
  elements["hero-meta"].textContent = `${repository.path} | Branch: ${snapshot.branch || "n/a"} | Commit: ${snapshot.commit_hash || "n/a"} | Dirty: ${snapshot.dirty_flag}`;
  elements["stat-findings"].textContent = String(findings.length);
  elements["stat-risk"].textContent = extractRisk(snapshot.summary);
  elements["stat-changes"].textContent = String(compare?.deltas?.length || 0);
  elements["stat-memory"].textContent = String(symbols.length + chunks.length);
  elements["overview-repo"].textContent = [
    `Repository: ${repository.name}`,
    `Path: ${repository.path}`,
    `Git Repo: ${repository.is_git_repo}`,
    `Snapshot ID: ${snapshot.id}`,
    `Fingerprint: ${repository.fingerprint}`,
    ``,
    `Files: ${files.length}`,
    `Findings: ${findings.length}`,
    `Symbols: ${symbols.length}`,
    `Chunks: ${chunks.length}`,
    `Patches: ${patches.length}`,
  ].join("\n");
  elements["overview-summary"].textContent = [
    snapshot.summary || "No summary.",
    "",
    `Repository: ${repository.name}`,
    `Snapshot: ${snapshot.id}`,
    `Current Findings: ${findings.length}`,
    `Risk Score: ${extractRisk(snapshot.summary)}`,
    `Changed Files: ${compare?.changed_files?.length || 0}`,
  ].join("\n");
  elements["overview-runs"].textContent = scan_runs.length
    ? scan_runs.map((run) => `[${run.scanner_name}] ${run.status}\n${run.message}\nFinished: ${run.finished_at || "n/a"}`).join("\n\n")
    : "No scan execution history.";
  elements["overview-health"].textContent = [
    `LLM Reviews: ${reviews.length}`,
    `Changed Files: ${snapshot.changed_files_count}`,
    `Dependency Count: ${payload.scan_metadata ? Object.keys(scan_metadata.languages || {}).length : 0}`,
    `Recent Patch Suggestions: ${patches.length}`,
    ``,
    `Diff Summary:`,
    snapshot.diff_summary || "No diff summary available.",
  ].join("\n");
  elements["overview-languages"].textContent = [
    "Languages",
    ...Object.entries(scan_metadata.languages || {}).map(([key, value]) => `${key}: ${value}`),
    "",
    "Frameworks",
    ...(scan_metadata.frameworks || []),
  ].join("\n");
  elements["overview-memory"].textContent = [
    `Symbols Indexed: ${symbols.length}`,
    `Chunks Stored: ${chunks.length}`,
    `Reviews Stored: ${reviews.length}`,
    `Patch Suggestions: ${patches.length}`,
    "",
    "Coverage Notes:",
    "Symbols and chunks are the memory substrate for compare, chat, and patch context.",
  ].join("\n");
  elements["overview-diff"].textContent = compare
    ? [
        `Previous Snapshot: ${compare.previous_snapshot_id || "n/a"}`,
        `Current Snapshot: ${compare.current_snapshot_id || "n/a"}`,
        `Changed Files: ${(compare.changed_files || []).length}`,
        `Changed Dependencies: ${(compare.changed_dependencies || []).length}`,
        `Risk Delta: ${compare.risk_delta ?? 0}`,
        "",
        compare.summary,
      ].join("\n")
    : "No prior snapshot available for diff analysis.";
  elements["overview-top-findings"].textContent = findings.length
    ? findings.slice(0, 10).map((finding) => `[${finding.severity}] ${finding.title}\n${finding.file_path || "n/a"}`).join("\n\n")
    : "No findings stored.";
  elements["overview-critical-paths"].textContent = buildCriticalPathsSummary(payload);
  elements["overview-scan-posture"].textContent = buildScanPostureSummary(payload);

  renderRepositoryGraph(payload);
  renderSignalBands(payload);
  renderRiskBoard(payload);
  populateFilters(findings);
  renderFindings();
  renderCompare(compare);
  renderMemory(payload);
  renderTree();
  elements["patch-output"].textContent = patches.length
    ? patches.slice(0, 6).map((patch) => `${patch.summary}\n${patch.suggested_diff}`).join("\n\n")
    : "No patch suggestions yet.";
  elements["patch-selection"].textContent = state.currentPatchFinding
    ? formatPatchSelection(state.currentPatchFinding)
    : "Select a new or regressed finding from the Compare page to enable Patch Lab.";
  elements["finding-detail"].textContent = "Select a finding to inspect its structured LLM judgment.";
  elements["file-detail"].textContent = "Select a file or folder.";
  elements["file-preview"].textContent = "Select a text file to preview its contents.";
  elements["chat-output"].innerHTML = "";
}

function populateFilters(findings) {
  fillSelect(elements["filter-severity"], ["all", ...new Set(findings.map((finding) => finding.severity))]);
  fillSelect(elements["filter-category"], ["all", ...new Set(findings.map((finding) => finding.category))]);
  fillSelect(elements["filter-source"], ["all", ...new Set(findings.map((finding) => finding.scanner_name))]);
}

function fillSelect(select, values) {
  const current = select.value || "all";
  select.innerHTML = values.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`).join("");
  if (values.includes(current)) select.value = current;
}

function renderFindings() {
  const payload = state.currentPayload;
  if (!payload) return;
  const severity = elements["filter-severity"].value || "all";
  const category = elements["filter-category"].value || "all";
  const source = elements["filter-source"].value || "all";
  const filtered = payload.findings.filter((finding) =>
    (severity === "all" || finding.severity === severity) &&
    (category === "all" || finding.category === category) &&
    (source === "all" || finding.scanner_name === source)
  );
  renderFindingKpis(filtered, payload.findings);
  const tbody = elements["findings-table"].querySelector("tbody");
  tbody.innerHTML = "";
  for (const finding of filtered) {
    const row = document.createElement("tr");
    if (state.currentFinding?.id === finding.id) row.classList.add("active");
    row.innerHTML = `
      <td><span class="severity-pill severity-${escapeHtml(normalizeSeverity(finding.severity))}">${escapeHtml(finding.severity)}</span></td>
      <td>${escapeHtml(finding.scanner_name)}</td>
      <td>${escapeHtml(finding.category)}</td>
      <td>${escapeHtml(finding.title)}</td>
      <td>${escapeHtml(finding.file_path || "")}</td>
      <td><span class="status-pill">${escapeHtml(finding.status)}</span></td>
    `;
    row.addEventListener("click", () => selectFinding(finding.id));
    tbody.appendChild(row);
  }
}

function selectFinding(findingId) {
  const payload = state.currentPayload;
  if (!payload) return;
  state.currentFinding = payload.findings.find((finding) => finding.id === findingId) || null;
  renderFindings();
  if (!state.currentFinding) return;
  const review = payload.reviews.find((item) => item.finding_id === state.currentFinding.id);
  let rawPayload = state.currentFinding.raw_payload;
  try {
    rawPayload = JSON.stringify(JSON.parse(rawPayload), null, 2);
  } catch (error) {}
  elements["finding-detail"].textContent = [
    `Title: ${state.currentFinding.title}`,
    `Description: ${state.currentFinding.description}`,
    `File: ${state.currentFinding.file_path || "n/a"}`,
    `Lines: ${state.currentFinding.line_start}-${state.currentFinding.line_end}`,
    `Category: ${state.currentFinding.category}`,
    `Source: ${state.currentFinding.scanner_name}`,
    `Fingerprint: ${state.currentFinding.fingerprint}`,
    "",
    "Structured Judgment",
    review
      ? `Verdict: ${review.verdict}\nConfidence: ${review.confidence}\nSeverity Override: ${review.severity_override}\nReasoning: ${review.reasoning_summary}\nRemediation: ${review.remediation_summary}`
      : "No LLM review stored.",
    "",
    "Raw Payload",
    rawPayload,
  ].join("\n");
}

function renderCompare(compare) {
  elements["compare-new"].textContent = "0";
  elements["compare-fixed"].textContent = "0";
  elements["compare-unchanged"].textContent = "0";
  elements["compare-deps"].textContent = "0";
  elements["compare-summary"].textContent = "No prior snapshot available.";
  elements["compare-deltas"].innerHTML = "";
  elements["compare-files"].innerHTML = "";
  elements["compare-dependency-list"].innerHTML = "";
  renderCompareInsights(compare);
  if (!compare) return;
  const deltas = compare.deltas || [];
  elements["compare-new"].textContent = String(deltas.filter((delta) => delta.delta_type === "new").length);
  elements["compare-fixed"].textContent = String(deltas.filter((delta) => delta.delta_type === "fixed").length);
  elements["compare-unchanged"].textContent = String(deltas.filter((delta) => delta.delta_type === "unchanged").length);
  elements["compare-deps"].textContent = String((compare.changed_dependencies || []).length);
  elements["compare-summary"].textContent = `${compare.summary}\n\nRisk Delta: ${compare.risk_delta}\nPrevious Snapshot: ${compare.previous_snapshot_id}\nCurrent Snapshot: ${compare.current_snapshot_id}`;
  renderCompareDeltas(compare);
  renderChipList(elements["compare-files"], compare.changed_files || [], "No changed files detected.");
  renderChipList(elements["compare-dependency-list"], compare.changed_dependencies || [], "No changed dependencies detected.");
  renderCompareInsights(compare);
}

function renderCompareDeltas(compare) {
  const container = elements["compare-deltas"];
  container.innerHTML = "";
  const payload = state.currentPayload;
  if (!compare || !payload) {
    container.innerHTML = `<div class="list-chip">No delta data available.</div>`;
    return;
  }
  const actionable = (compare.deltas || []).filter((delta) => ["new", "regressed"].includes(delta.delta_type));
  if (!actionable.length) {
    container.innerHTML = `<div class="list-chip">No new or regressed findings available for patch generation.</div>`;
    return;
  }
  for (const delta of actionable.slice(0, 20)) {
    const finding = payload.findings.find((item) => item.id === delta.current_finding_id);
    if (!finding) continue;
    const button = document.createElement("button");
    button.className = `delta-card ${state.currentPatchFinding?.id === finding.id ? "active" : ""}`;
    button.innerHTML = `
      <span class="delta-topline">
        <span class="severity-pill severity-${escapeHtml(normalizeSeverity(finding.severity))}">${escapeHtml(finding.severity)}</span>
        <span class="status-pill ${escapeHtml(delta.delta_type)}">${escapeHtml(delta.delta_type)}</span>
      </span>
      <strong>${escapeHtml(finding.title)}</strong>
      <span class="subtle">${escapeHtml(finding.file_path || "n/a")} ${finding.line_start ? `• line ${finding.line_start}` : ""}</span>
    `;
    button.addEventListener("click", () => selectCompareFinding(finding.id));
    container.appendChild(button);
  }
}

function selectCompareFinding(findingId) {
  const payload = state.currentPayload;
  if (!payload) return;
  state.currentPatchFinding = payload.findings.find((finding) => finding.id === findingId) || null;
  elements["patch-selection"].textContent = state.currentPatchFinding
    ? formatPatchSelection(state.currentPatchFinding)
    : "Select a new or regressed finding from the Compare page to enable Patch Lab.";
  renderCompare(payload.compare);
}

function formatPatchSelection(finding) {
  return [
    `Title: ${finding.title}`,
    `Severity: ${finding.severity}`,
    `Category: ${finding.category}`,
    `File: ${finding.file_path || "n/a"}`,
    `Lines: ${finding.line_start || "n/a"}-${finding.line_end || "n/a"}`,
    `Source: selected from Compare`,
  ].join("\n");
}

function renderChipList(container, values, emptyText) {
  container.innerHTML = "";
  if (!values.length) {
    const chip = document.createElement("div");
    chip.className = "list-chip";
    chip.textContent = emptyText;
    container.appendChild(chip);
    return;
  }
  for (const value of values.slice(0, 200)) {
    const chip = document.createElement("div");
    chip.className = "list-chip";
    chip.textContent = value;
    container.appendChild(chip);
  }
}

function renderMemory(payload) {
  const timeline = elements["memory-timeline"];
  timeline.innerHTML = "";
  for (const snapshot of [payload.snapshot]) {
    const card = document.createElement("button");
    card.className = "timeline-card active";
    card.innerHTML = `<strong>Snapshot ${snapshot.id}</strong><br><span class="subtle">${snapshot.created_at}</span><br><span class="subtle">${snapshot.branch || "n/a"}</span>`;
    timeline.appendChild(card);
  }
  elements["memory-detail"].textContent = [
    `Snapshot: ${payload.snapshot.id}`,
    `Created: ${payload.snapshot.created_at}`,
    `Branch: ${payload.snapshot.branch || "n/a"}`,
    `Commit: ${payload.snapshot.commit_hash || "n/a"}`,
    `Dirty: ${payload.snapshot.dirty_flag}`,
    "",
    "Summary:",
    payload.snapshot.summary,
    "",
    `Stored reviews: ${payload.reviews.length}`,
    `Stored patches: ${payload.patches.length}`,
  ].join("\n");
  elements["memory-symbols"].textContent = payload.symbols.slice(0, 250).map((symbol) => `${symbol.symbol_kind}: ${symbol.symbol_name} [${symbol.file_path}]`).join("\n");
  elements["memory-chunks"].textContent = payload.chunks.slice(0, 16).map((chunk) => `${chunk.file_path}\n${chunk.chunk_text.slice(0, 450)}`).join("\n\n");
  renderMemoryConstellation(payload);
}

function renderTree() {
  const payload = state.currentPayload;
  if (!payload) return;
  const query = elements["tree-filter"].value.trim().toLowerCase();
  elements["tree-summary"].textContent = `${payload.files.length} tracked files | ${(payload.compare?.changed_files || []).length} changed since prior snapshot`;
  elements["tree-breadcrumb"].textContent = state.currentTreePath ? `Focused node: ${state.currentTreePath}` : "No node selected.";
  elements["tree-view"].innerHTML = "";
  const tree = buildTreeFromFiles(payload.files, new Set(payload.compare?.changed_files || []));
  for (const node of tree.filter((item) => treeMatches(item, query))) {
    elements["tree-view"].appendChild(renderTreeNode(node, query));
  }
}

function buildTreeFromFiles(files, changedPaths) {
  const root = {};
  for (const file of files) {
    let cursor = root;
    let currentPath = "";
    const parts = file.path.split("/");
    for (let index = 0; index < parts.length; index += 1) {
      const part = parts[index];
      currentPath = currentPath ? `${currentPath}/${part}` : part;
      if (!cursor[part]) {
        cursor[part] = {
          name: part,
          path: currentPath,
          children: {},
          leaf: index === parts.length - 1,
          language: index === parts.length - 1 ? file.language : "",
          size: index === parts.length - 1 ? file.size : 0,
          changed: false,
        };
      }
      cursor[part].changed = cursor[part].changed || changedPaths.has(currentPath) || [...changedPaths].some((value) => value.startsWith(`${currentPath}/`));
      cursor = cursor[part].children;
    }
  }
  return normalizeTree(root);
}

function normalizeTree(tree) {
  return Object.keys(tree).sort().map((key) => ({
    ...tree[key],
    children: normalizeTree(tree[key].children),
  }));
}

function treeMatches(node, query) {
  if (!query) return true;
  if (node.path.toLowerCase().includes(query)) return true;
  return node.children.some((child) => treeMatches(child, query));
}

function renderTreeNode(node, query) {
  const wrapper = document.createElement("div");
  wrapper.className = "tree-node";
  const label = document.createElement("div");
  label.className = `tree-label ${node.changed ? "changed" : ""} ${state.currentTreePath === node.path ? "active" : ""}`;
  label.innerHTML = `
    <span class="tree-name-wrap">
      <span class="tree-icon">${node.leaf ? "▣" : "▾"}</span>
      <span>${escapeHtml(node.name)}${node.changed ? " *" : ""}</span>
    </span>
    <span class="tree-meta">${escapeHtml(node.language || (node.leaf ? "" : "folder"))}${node.size ? ` • ${node.size} bytes` : ""}</span>
  `;
  label.addEventListener("click", () => openTreeNode(node.path, node.leaf, node.language, node.size, node.changed));
  wrapper.appendChild(label);
  if (node.children.length) {
    const children = document.createElement("div");
    children.className = "tree-children";
    for (const child of node.children.filter((item) => treeMatches(item, query))) {
      children.appendChild(renderTreeNode(child, query));
    }
    wrapper.appendChild(children);
  }
  return wrapper;
}

async function openTreeNode(path, leaf, language, size, changed) {
  state.currentTreePath = path;
  elements["tree-breadcrumb"].textContent = `Focused node: ${path}`;
  elements["file-detail"].textContent = [
    `Path: ${path}`,
    `Type: ${leaf ? "file" : "directory"}`,
    `Language: ${language || "n/a"}`,
    `Size: ${size || "n/a"} bytes`,
    `Changed In Compare: ${changed ? "yes" : "no"}`,
  ].join("\n");
  if (!leaf || !state.currentRepository) {
    elements["file-preview"].textContent = "Directory selected. Expand the tree to inspect files.";
    renderTree();
    return;
  }
  const response = await fetch(`/api/repositories/${state.currentRepository.id}/file?path=${encodeURIComponent(path)}`);
  const payload = await response.json();
  elements["file-preview"].textContent = payload.content || "[empty file]";
  renderTree();
}

async function sendChat() {
  if (!state.currentRepository || !state.currentSnapshot) return;
  const question = elements["chat-question"].value.trim();
  if (!question) return;
  appendChat("User", question);
  elements["chat-question"].value = "";
  const response = await fetch("/api/chat", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      repo_id: state.currentRepository.id,
      snapshot_id: state.currentSnapshot.id,
      question,
    }),
  });
  const payload = await response.json();
  appendChat("Assistant", payload.answer || "No response.");
  await loadLogs();
}

function appendChat(role, message) {
  const entry = document.createElement("div");
  entry.className = "chat-entry";
  entry.innerHTML = `<div class="chat-role">${escapeHtml(role)}</div><div>${escapeHtml(message)}</div>`;
  elements["chat-output"].appendChild(entry);
  elements["chat-output"].scrollTop = elements["chat-output"].scrollHeight;
}

async function generatePatch() {
  if (!state.currentRepository || !state.currentSnapshot || !state.currentPatchFinding) {
    alert("Select a new or regressed finding from the Compare page first.");
    return;
  }
  const response = await fetch("/api/patch", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({
      repo_path: state.currentRepository.path,
      snapshot_id: state.currentSnapshot.id,
      finding_id: state.currentPatchFinding.id,
    }),
  });
  const payload = await response.json();
  elements["patch-output"].textContent = payload.patch || "No patch returned.";
  await loadLogs();
}

async function loadLogs() {
  const response = await fetch("/api/logs");
  const payload = await response.json();
  renderLogs(payload.logs || []);
}

function renderLogs(logs) {
  elements["log-output"].textContent = logs.join("\n");
}

function applySettings(settings) {
  elements["settings-provider"].value = settings.llm_provider || "gemini";
  elements["settings-api-key"].value = settings.llm_api_key || "";
  elements["settings-model"].value = settings.llm_model || "";
  elements["settings-base-url"].value = settings.llm_base_url || "";
  elements["settings-analyzer-backend"].value = settings.analyzer_backend || "hybrid";
  elements["settings-lsp-enabled"].value = String(settings.lsp_enabled !== false);
  elements["settings-timeout"].value = settings.llm_timeout_seconds || 60;
  elements["settings-retries"].value = settings.llm_retry_count || 2;
  elements["settings-max-findings"].value = settings.llm_max_findings_per_scan || 25;
  elements["settings-chunk-lines"].value = settings.embedding_chunk_lines || 80;
  elements["settings-watch"].value = String(Boolean(settings.watch_mode_enabled));
  elements["settings-log-level"].value = settings.logging_level || "INFO";
  handleProviderChange();
}

function handleProviderChange() {
  const provider = elements["settings-provider"].value;
  const modelInput = elements["settings-model"];
  const baseUrlInput = elements["settings-base-url"];

  if (provider === "openrouter") {
    if (!baseUrlInput.value.trim()) {
      baseUrlInput.value = "https://openrouter.ai/api/v1";
    }
    baseUrlInput.placeholder = "https://openrouter.ai/api/v1";
    modelInput.placeholder = "openai/gpt-4o-mini or anthropic/claude-3.5-sonnet";
    return;
  }

  if (provider === "openai_compatible") {
    baseUrlInput.placeholder = "https://api.example.com/v1";
    modelInput.placeholder = "your-model-name";
    return;
  }

  if (provider === "gemini") {
    modelInput.placeholder = "gemini-2.5-flash";
    if (baseUrlInput.value === "https://openrouter.ai/api/v1") {
      baseUrlInput.value = "";
    }
    baseUrlInput.placeholder = "";
    return;
  }

  modelInput.placeholder = "";
  baseUrlInput.placeholder = "";
}

async function saveSettings(event) {
  event.preventDefault();
  const payload = {
    llm_provider: elements["settings-provider"].value,
    llm_api_key: elements["settings-api-key"].value,
    llm_model: elements["settings-model"].value,
    llm_base_url: elements["settings-base-url"].value,
    analyzer_backend: elements["settings-analyzer-backend"].value,
    lsp_enabled: elements["settings-lsp-enabled"].value === "true",
    llm_timeout_seconds: Number(elements["settings-timeout"].value || 60),
    llm_retry_count: Number(elements["settings-retries"].value || 2),
    llm_max_findings_per_scan: Number(elements["settings-max-findings"].value || 25),
    embedding_chunk_lines: Number(elements["settings-chunk-lines"].value || 80),
    watch_mode_enabled: elements["settings-watch"].value === "true",
    logging_level: elements["settings-log-level"].value,
  };
  const response = await fetch("/api/settings", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    alert(`Failed to save settings: ${await response.text()}`);
    return;
  }
  await loadLogs();
  alert("Settings saved.");
}

async function installHook() {
  if (!state.currentRepository) {
    alert("Load a git repository first.");
    return;
  }
  const response = await fetch("/api/precommit", {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify({repo_path: state.currentRepository.path}),
  });
  const payload = await response.json();
  alert(`Installed hook at ${payload.hook_path}`);
}

function downloadReport(format) {
  if (!state.currentSnapshot) {
    alert("No snapshot loaded.");
    return;
  }
  window.open(`/api/report/${state.currentSnapshot.id}?format=${encodeURIComponent(format)}`, "_blank");
}

function switchPage(page, button) {
  document.querySelectorAll(".page").forEach((node) => node.classList.remove("active"));
  document.querySelectorAll(".nav-item").forEach((node) => node.classList.remove("active"));
  document.getElementById(`page-${page}`).classList.add("active");
  button.classList.add("active");
}

function renderRepositoryGraph(payload) {
  const graph = elements["repo-graph"];
  if (!graph) return;
  const files = payload.files || [];
  const findings = payload.findings || [];
  const changedFiles = new Set(payload.compare?.changed_files || []);
  const topDirs = aggregateTopDirectories(files, changedFiles);
  const frameworks = (payload.scan_metadata?.frameworks || []).slice(0, 4);
  const languages = Object.entries(payload.scan_metadata?.languages || {})
    .sort((left, right) => right[1] - left[1])
    .slice(0, 4);
  const highRisk = findings.filter((finding) => ["critical", "high"].includes(normalizeSeverity(finding.severity)));
  const riskyFiles = aggregateRiskFiles(highRisk);
  const riskCount = highRisk.length;
  const changeCount = changedFiles.size;
  const nodes = [
    {label: payload.repository.name, x: 450, y: 150, radius: 44, hub: true, changed: false, tone: "hub"},
    {label: `Risk ${riskCount}`, x: 720, y: 150, radius: 28, changed: false, tone: "risk"},
    {label: `Changes ${changeCount}`, x: 170, y: 150, radius: 24, changed: changeCount > 0, tone: "change"},
    ...topDirs.slice(0, 5).map((item, index) => ({
      label: `${item.name} (${item.count})`,
      x: 160 + index * 120,
      y: index % 2 === 0 ? 70 : 238,
      radius: 18 + Math.min(item.count, 12),
      changed: item.changedCount > 0,
      tone: "zone",
    })),
    ...languages.map(([name, count], index) => ({
      label: `${name} ${count}`,
      x: 250 + index * 120,
      y: 34,
      radius: 12 + Math.min(Number(count), 12),
      changed: false,
      tone: "lang",
    })),
    ...frameworks.map((name, index) => ({
      label: name,
      x: 760,
      y: 58 + index * 48,
      radius: 15,
      changed: false,
      tone: "framework",
    })),
    ...riskyFiles.slice(0, 3).map((item, index) => ({
      label: `${item.name} (${item.count})`,
      x: 640 + index * 95,
      y: 242,
      radius: 14 + Math.min(item.count, 10),
      changed: changedFiles.has(item.path),
      tone: "risk-file",
    })),
  ];
  const edges = nodes.slice(1).map((node) => `
    <line class="link ${node.tone || ""}" x1="450" y1="150" x2="${node.x}" y2="${node.y}"></line>
  `).join("");
  const circles = nodes.map((node) => `
    <g>
      <circle class="node ${node.hub ? "hub" : ""} ${node.changed ? "changed" : ""} ${node.tone || ""}" cx="${node.x}" cy="${node.y}" r="${node.radius}"></circle>
      <text class="graph-label ${node.tone || ""}" x="${node.x}" y="${node.y + node.radius + 18}" text-anchor="middle">${escapeHtml(node.label)}</text>
    </g>
  `).join("");
  const halos = `
    <circle class="graph-ring" cx="450" cy="150" r="84"></circle>
    <circle class="graph-ring faint" cx="450" cy="150" r="126"></circle>
  `;
  graph.innerHTML = `${halos}${edges}${circles}`;
  elements["graph-summary"].textContent = `${topDirs.length} major zones | ${languages.length} language signals | ${frameworks.length} framework markers | ${riskyFiles.length} risky hotspots`;
}

function aggregateTopDirectories(files, changedFiles) {
  const groups = new Map();
  for (const file of files) {
    const parts = file.path.split("/");
    const name = parts.length > 1 ? parts[0] : "root";
    const entry = groups.get(name) || {name, count: 0, changedCount: 0};
    entry.count += 1;
    if (changedFiles.has(file.path)) entry.changedCount += 1;
    groups.set(name, entry);
  }
  return [...groups.values()].sort((left, right) => right.count - left.count);
}

function renderSignalBands(payload) {
  const container = elements["signal-bands"];
  if (!container) return;
  const findings = payload.findings || [];
  const compare = payload.compare;
  const bands = [
    {
      label: "Exposure",
      value: findings.filter((finding) => ["critical", "high"].includes(normalizeSeverity(finding.severity))).length,
      note: "Critical and high-severity findings currently open.",
    },
    {
      label: "Drift",
      value: compare?.changed_files?.length || 0,
      note: "Files changed versus the most recent prior snapshot.",
    },
    {
      label: "Memory",
      value: (payload.symbols?.length || 0) + (payload.chunks?.length || 0),
      note: "Stored symbols and chunk records available for retrieval.",
    },
    {
      label: "Reviews",
      value: payload.reviews?.length || 0,
      note: "Structured LLM review decisions attached to this snapshot.",
    },
  ];
  container.innerHTML = bands.map((band) => `
    <article class="signal-card">
      <span class="stat-label">${escapeHtml(band.label)}</span>
      <strong>${escapeHtml(band.value)}</strong>
      <div class="subtle">${escapeHtml(band.note)}</div>
    </article>
  `).join("");
}

function renderRiskBoard(payload) {
  const container = elements["overview-risk-board"];
  if (!container) return;
  const findings = payload.findings || [];
  const compare = payload.compare || {};
  const highRisk = findings.filter((finding) => ["critical", "high"].includes(normalizeSeverity(finding.severity)));
  const cards = [
    {
      label: "Change Pressure",
      value: (compare.changed_files || []).length,
      note: "Changed files in the current compare window.",
    },
    {
      label: "High-Risk Density",
      value: filesafeRatio(highRisk.length, Math.max((payload.files || []).length, 1)),
      note: "High-risk findings per tracked file.",
    },
    {
      label: "Review Coverage",
      value: filesafeRatio((payload.reviews || []).length, Math.max(findings.length, 1)),
      note: "Structured reviews relative to stored findings.",
    },
    {
      label: "Patch Readiness",
      value: payload.patches?.length || 0,
      note: "Generated patch suggestions available for inspection.",
    },
  ];
  container.innerHTML = cards.map((card) => `
    <article class="signal-card emphasis-card">
      <span class="stat-label">${escapeHtml(card.label)}</span>
      <strong>${escapeHtml(card.value)}</strong>
      <div class="subtle">${escapeHtml(card.note)}</div>
    </article>
  `).join("");
}

function buildCriticalPathsSummary(payload) {
  const files = payload.files || [];
  const changedFiles = new Set(payload.compare?.changed_files || []);
  const findings = payload.findings || [];
  const groups = aggregateTopDirectories(files, changedFiles).slice(0, 5);
  const lines = groups.map((group) => {
    const groupFindings = findings.filter((finding) => (finding.file_path || "").startsWith(`${group.name}/`) || finding.file_path === group.name);
    const severe = groupFindings.filter((finding) => ["critical", "high"].includes(normalizeSeverity(finding.severity))).length;
    return `${group.name}: ${group.count} files | ${group.changedCount} changed | ${severe} high-risk findings`;
  });
  return lines.length ? lines.join("\n") : "No critical path summary available yet.";
}

function buildScanPostureSummary(payload) {
  const scanRuns = payload.scan_runs || [];
  const reviews = payload.reviews || [];
  const findings = payload.findings || [];
  const completed = scanRuns.filter((run) => run.status === "completed").length;
  const failed = scanRuns.filter((run) => run.status === "failed").length;
  return [
    `Completed runs: ${completed}`,
    `Failed runs: ${failed}`,
    `Stored reviews: ${reviews.length}`,
    `Findings with review ratio: ${filesafeRatio(reviews.length, Math.max(findings.length, 1))}`,
    "",
    completed
      ? "Latest scan pipeline completed and persisted."
      : "No completed scan runs recorded for this snapshot.",
  ].join("\n");
}

function aggregateRiskFiles(findings) {
  const groups = new Map();
  for (const finding of findings) {
    const path = finding.file_path || "unknown";
    const name = path.split("/").slice(-2).join("/") || path;
    const entry = groups.get(path) || {path, name, count: 0};
    entry.count += 1;
    groups.set(path, entry);
  }
  return [...groups.values()].sort((left, right) => right.count - left.count);
}

function filesafeRatio(numerator, denominator) {
  const value = denominator ? numerator / denominator : 0;
  return `${value.toFixed(2)}x`;
}

function renderFindingKpis(filteredFindings, allFindings) {
  const container = elements["finding-kpis"];
  if (!container) return;
  const grouped = {
    critical: 0,
    high: 0,
    medium: 0,
    low: 0,
  };
  for (const finding of filteredFindings) {
    const key = normalizeSeverity(finding.severity);
    if (grouped[key] !== undefined) grouped[key] += 1;
  }
  container.innerHTML = [
    {label: "Visible Findings", value: filteredFindings.length, detail: `${allFindings.length} total in snapshot`},
    {label: "High Risk", value: grouped.critical + grouped.high, detail: "Critical + high severities in current filter"},
    {label: "Medium", value: grouped.medium, detail: "Needs remediation planning"},
    {label: "Low / Info", value: grouped.low + filteredFindings.filter((item) => ["info", "unknown"].includes(normalizeSeverity(item.severity))).length, detail: "Track but usually not release blockers"},
  ].map((item) => `
    <article class="kpi-card">
      <span class="stat-label">${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <div class="subtle">${escapeHtml(item.detail)}</div>
    </article>
  `).join("");
}

function renderCompareInsights(compare) {
  const container = elements["compare-insights"];
  if (!container) return;
  if (!compare) {
    container.innerHTML = `
      <article class="insight-card">
        <span class="stat-label">No Compare Baseline</span>
        <strong>Awaiting</strong>
        <div class="subtle">Run another scan later to visualize drift, regressions, and fixed findings.</div>
      </article>
    `;
    return;
  }
  const deltas = compare.deltas || [];
  const cards = [
    {
      label: "Risk Delta",
      value: compare.risk_delta ?? 0,
      detail: "Overall risk score change versus previous snapshot.",
    },
    {
      label: "New Issues",
      value: deltas.filter((delta) => delta.delta_type === "new").length,
      detail: "Findings introduced since the previous snapshot.",
    },
    {
      label: "Fixed Issues",
      value: deltas.filter((delta) => delta.delta_type === "fixed").length,
      detail: "Findings that disappeared in the current snapshot.",
    },
    {
      label: "Dependency Drift",
      value: (compare.changed_dependencies || []).length,
      detail: "Dependencies added, removed, or version-changed.",
    },
  ];
  container.innerHTML = cards.map((item) => `
    <article class="insight-card">
      <span class="stat-label">${escapeHtml(item.label)}</span>
      <strong>${escapeHtml(item.value)}</strong>
      <div class="subtle">${escapeHtml(item.detail)}</div>
    </article>
  `).join("");
}

function renderMemoryConstellation(payload) {
  const graph = elements["memory-constellation"];
  if (!graph) return;
  const nodes = [
    {label: "Snapshot", x: 120, y: 120, radius: 34, hub: true},
    {label: `Symbols ${payload.symbols.length}`, x: 310, y: 70, radius: 24},
    {label: `Chunks ${payload.chunks.length}`, x: 310, y: 175, radius: 24},
    {label: `Reviews ${payload.reviews.length}`, x: 540, y: 58, radius: 20},
    {label: `Patches ${payload.patches.length}`, x: 540, y: 182, radius: 20},
    {label: `Findings ${payload.findings.length}`, x: 760, y: 120, radius: 28},
  ];
  graph.innerHTML = nodes.slice(1).map((node) => `
    <line class="link" x1="120" y1="120" x2="${node.x}" y2="${node.y}"></line>
  `).join("") + nodes.map((node) => `
    <g>
      <circle class="node ${node.hub ? "hub" : ""}" cx="${node.x}" cy="${node.y}" r="${node.radius}"></circle>
      <text x="${node.x}" y="${node.y + node.radius + 18}" text-anchor="middle">${escapeHtml(node.label)}</text>
    </g>
  `).join("");
  elements["memory-constellation-summary"].textContent =
    `${payload.symbols.length} symbols, ${payload.chunks.length} chunks, ${payload.reviews.length} reviews, ${payload.patches.length} patches`;
}

function normalizeSeverity(value) {
  const normalized = String(value || "").toLowerCase();
  if (["critical", "high", "medium", "low", "info"].includes(normalized)) return normalized;
  return "unknown";
}

function extractRisk(summary) {
  const marker = "risk score:";
  if (!summary || !summary.includes(marker)) return "n/a";
  return summary.split(marker)[1].split(".")[0].trim();
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}
