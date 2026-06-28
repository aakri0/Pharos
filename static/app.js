const state = {
  rows: [],
  activeBrowseId: null,
  searchTimers: {},
  nextRowId: 1,
  textStore: {},
  nextTextId: 1,
  severityFilter: "all",
  lastCheckData: null,
  lastInsights: null,
  patientContexts: new Set(),
  lastPatientRisk: null,
};

const els = {
  drugCount: document.querySelector("#drugCount"),
  interactionCount: document.querySelector("#interactionCount"),
  themeToggle: document.querySelector("#themeToggle"),
  drugRows: document.querySelector("#drugRows"),
  addDrugButton: document.querySelector("#addDrugButton"),
  checkButton: document.querySelector("#checkButton"),
  exportReportButton: document.querySelector("#exportReportButton"),
  sampleAuditButton: document.querySelector("#sampleAuditButton"),
  runAuditButton: document.querySelector("#runAuditButton"),
  clearAuditButton: document.querySelector("#clearAuditButton"),
  auditText: document.querySelector("#auditText"),
  auditSuggestions: document.querySelector("#auditSuggestions"),
  auditStatus: document.querySelector("#auditStatus"),
  selectionHint: document.querySelector("#selectionHint"),
  severityFilter: document.querySelector("#severityFilter"),
  resultPanel: document.querySelector("#resultPanel"),
  aiSummary: document.querySelector("#aiSummary"),
  interactionGraph: document.querySelector("#interactionGraph"),
  foodWarnings: document.querySelector("#foodWarnings"),
  sharedSignals: document.querySelector("#sharedSignals"),
  alternativeDrugs: document.querySelector("#alternativeDrugs"),
  patientContexts: document.querySelector("#patientContexts"),
  patientRisk: document.querySelector("#patientRisk"),
  explainableAi: document.querySelector("#explainableAi"),
  detailsGrid: document.querySelector("#detailsGrid"),
  browseTabs: document.querySelector("#browseTabs"),
  browseFilter: document.querySelector("#browseFilter"),
  interactionList: document.querySelector("#interactionList"),
  ragQuery: document.querySelector("#ragQuery"),
  ragSubmit: document.querySelector("#ragSubmit"),
  ragClear: document.querySelector("#ragClear"),
  ragResult: document.querySelector("#ragResult"),
  ragSuggestions: document.querySelector("#ragSuggestions"),
};

const fmt = new Intl.NumberFormat();

function escapeHtml(value = "") {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function pillClass(severity) {
  return `severity ${severity || "informational"}`;
}

function plainPreview(text, limit) {
  const clean = String(text || "").trim();
  if (clean.length <= limit) return clean;
  const sliced = clean.slice(0, limit).replace(/\s+\S*$/, "").trim();
  return `${sliced}...`;
}

function textToBullets(text, maxItems = 5) {
  const clean = String(text || "").trim();
  if (!clean) return [];

  let parts = clean
    .replace(/\s+(\d+\))/g, "\n$1")
    .split(/\n+|(?<=[.!?])\s+(?=[A-Z0-9])/)
    .map((part) => part.replace(/^\d+\)\s*/, "").trim())
    .filter(Boolean);

  if (parts.length <= 1) {
    parts = clean
      .split(/;\s+|,\s+(?=(?:and|while|with|which|then)\b)/)
      .map((part) => part.trim())
      .filter(Boolean);
  }

  return parts.slice(0, maxItems);
}

function bulletList(items, options = {}) {
  if (!items.length) return "";
  const hasMore = Boolean(options.textId);
  const lastIndex = items.length - 1;
  return `
    <ul class="bullet-list">
      ${items
        .map((item, index) => {
          const readMore =
            hasMore && index === lastIndex
              ? ` <button class="read-more-inline" type="button" data-action="read-more">Read more</button>`
              : "";
          return `<li>${escapeHtml(item)}${readMore}</li>`;
        })
        .join("")}
    </ul>
  `;
}

function expandableText(title, text, limit = 520, maxItems = 4) {
  const clean = String(text || "").trim();
  if (!clean) return "";
  const preview = plainPreview(clean, limit);
  const previewItems = textToBullets(preview, maxItems);
  if (clean.length <= limit) return bulletList(previewItems);

  const id = `txt-${state.nextTextId++}`;
  state.textStore[id] = { title, text: clean };
  return `
    <div class="readmore-block" data-text-id="${id}">
      ${bulletList(previewItems, { textId: id })}
    </div>
  `;
}

function showReaderModal(item) {
  document.querySelector(".reader-modal")?.remove();
  const modal = document.createElement("div");
  modal.className = "reader-modal";
  modal.innerHTML = `
    <div class="reader-backdrop" data-action="close-reader"></div>
    <section class="reader-panel glass" role="dialog" aria-modal="true" aria-label="${escapeHtml(item.title)}">
      <div class="reader-head">
        <h2>${escapeHtml(item.title)}</h2>
        <button class="icon-button" type="button" data-action="close-reader" aria-label="Close reader">×</button>
      </div>
      ${bulletList(textToBullets(item.text, 80))}
    </section>
  `;
  document.body.appendChild(modal);
}

// In production the static frontend on Vercel and the backend on a separate
// host need a couple of env-style knobs. config.js (loaded before app.js
// from index.html) can set these globals; otherwise we default to
// same-origin relative paths so local dev works unchanged.
const API_BASE = (typeof window !== "undefined" && window.PHAROS_API_BASE) || "";
const API_KEY = (typeof window !== "undefined" && window.PHAROS_API_KEY) || "";

async function api(path) {
  const url = API_BASE ? `${API_BASE.replace(/\/$/, "")}${path}` : path;
  const headers = {};
  if (API_KEY) headers["X-API-Key"] = API_KEY;
  const response = await fetch(url, { headers });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return response.json();
}

async function loadStats() {
  const stats = await api("/api/stats");
  els.drugCount.textContent = fmt.format(stats.drugs);
  els.interactionCount.textContent = fmt.format(stats.interactions);
}

function selectedRows() {
  return state.rows.filter((row) => row.drug);
}

function addDrugRow(drug = null) {
  const row = { rowId: state.nextRowId++, drug, detail: null };
  state.rows.push(row);
  renderDrugRows();
  updateSelectedState();
  return row;
}

function removeDrugRow(rowId) {
  if (state.rows.length <= 2) {
    clearDrug(rowId);
    return;
  }
  state.rows = state.rows.filter((row) => row.rowId !== rowId);
  if (!selectedRows().some((row) => row.drug?.id === state.activeBrowseId)) {
    state.activeBrowseId = selectedRows()[0]?.drug?.id || null;
  }
  renderDrugRows();
  updateSelectedState();
  renderDetails();
  renderBrowseTabs();
  loadInteractionList();
  loadAlternativeSuggestions();
}

function renderDrugRows() {
  els.drugRows.innerHTML = state.rows
    .map((row, index) => `
      <div class="drug-picker" data-row-id="${row.rowId}">
        <label for="drug-${row.rowId}">Drug ${index + 1}</label>
        <div class="input-wrap">
          <input id="drug-${row.rowId}" type="search" autocomplete="off" placeholder="Search or open dropdown" value="${escapeHtml(row.drug?.name || "")}">
          <button type="button" class="dropdown-button" data-action="dropdown" title="Show drug options" aria-label="Show drug ${index + 1} options"></button>
          <button type="button" class="clear-button" data-action="clear" title="Clear drug">×</button>
          <button type="button" class="remove-button" data-action="remove" title="Remove drug" aria-label="Remove drug ${index + 1}">−</button>
        </div>
        <div class="suggestions" role="listbox"></div>
      </div>
    `)
    .join("");

  els.drugRows.querySelectorAll(".drug-picker").forEach((picker) => {
    const rowId = Number(picker.dataset.rowId);
    const input = picker.querySelector("input");
    const dropdownButton = picker.querySelector('[data-action="dropdown"]');
    const clearButton = picker.querySelector('[data-action="clear"]');
    const removeButton = picker.querySelector('[data-action="remove"]');

    input.addEventListener("input", () => {
      const row = getRow(rowId);
      row.drug = null;
      row.detail = null;
      const q = input.value.trim();
      clearSuggestions(picker);
      window.clearTimeout(state.searchTimers[rowId]);
      updateSelectedState();
      if (q.length < 2) return;
      state.searchTimers[rowId] = window.setTimeout(() => searchDrugs(rowId, q), 160);
    });

    input.addEventListener("focus", () => {
      const suggestions = picker.querySelector(".suggestions");
      if (suggestions.innerHTML) suggestions.classList.add("open");
    });

    dropdownButton.addEventListener("click", () => openDrugOptions(rowId));
    clearButton.addEventListener("click", () => clearDrug(rowId));
    removeButton.addEventListener("click", () => removeDrugRow(rowId));
  });
}

function getRow(rowId) {
  return state.rows.find((row) => row.rowId === rowId);
}

function getPicker(rowId) {
  return els.drugRows.querySelector(`.drug-picker[data-row-id="${rowId}"]`);
}

function clearSuggestions(picker) {
  const suggestions = picker.querySelector(".suggestions");
  suggestions.classList.remove("open");
  suggestions.innerHTML = "";
  suggestions.dataset.mode = "";
}

async function searchDrugs(rowId, q) {
  const data = await api(`/api/search?q=${encodeURIComponent(q)}`);
  renderSuggestions(rowId, data.results, "Try another spelling or synonym.", "search");
}

async function openDrugOptions(rowId) {
  const picker = getPicker(rowId);
  const input = picker.querySelector("input");
  const suggestions = picker.querySelector(".suggestions");

  if (suggestions.classList.contains("open") && suggestions.dataset.mode === "dropdown") {
    suggestions.classList.remove("open");
    return;
  }

  suggestions.dataset.mode = "dropdown";
  suggestions.innerHTML = `<div class="suggestion static"><strong>Loading drugs</strong><small>Showing real database results...</small></div>`;
  suggestions.classList.add("open");

  const q = input.value.trim();
  const endpoint = q.length >= 2 ? `/api/options?q=${encodeURIComponent(q)}` : "/api/options";
  const data = await api(endpoint);
  renderSuggestions(
    rowId,
    data.results,
    q ? "No matches for this field." : "Type in the field to search all 19k drugs.",
    "dropdown",
  );
}

function renderSuggestions(rowId, results, emptyText, mode) {
  const picker = getPicker(rowId);
  const suggestions = picker.querySelector(".suggestions");
  suggestions.dataset.mode = mode;

  if (!results.length) {
    suggestions.innerHTML = `<div class="suggestion static"><strong>No matches</strong><small>${escapeHtml(emptyText)}</small></div>`;
    suggestions.classList.add("open");
    return;
  }

  const helper =
    mode === "dropdown"
      ? `<div class="suggestion-note">Showing ${results.length} drugs. Type to search the full database.</div>`
      : "";

  suggestions.innerHTML =
    helper +
    results
      .map((drug) => {
        const sub = drug.synonym ? `Matched synonym: ${escapeHtml(drug.synonym)}` : drug.id;
        return `
          <button class="suggestion" type="button" data-id="${escapeHtml(drug.id)}" data-name="${escapeHtml(drug.name)}">
            <strong>${escapeHtml(drug.name)}</strong>
            <small>${sub}</small>
          </button>
        `;
      })
      .join("");

  suggestions.classList.add("open");
  suggestions.querySelectorAll(".suggestion[data-id]").forEach((button) => {
    button.addEventListener("click", () => selectDrug(rowId, button.dataset.id, button.dataset.name));
  });
}

async function selectDrug(rowId, id, name) {
  const duplicate = selectedRows().find((row) => row.drug.id === id && row.rowId !== rowId);
  if (duplicate) {
    removeDrugRow(rowId);
    updateSelectedState("That drug is already in your list.");
    return;
  }

  const row = getRow(rowId);
  const picker = getPicker(rowId);
  row.drug = { id, name };
  row.detail = null;
  picker.querySelector("input").value = name;
  clearSuggestions(picker);
  state.activeBrowseId ||= id;
  await loadDrugDetail(rowId);
  updateSelectedState();
  renderDetails();
  renderBrowseTabs();
  await loadInteractionList();
  loadAlternativeSuggestions();
}

async function setDrugInRow(rowId, drug) {
  const row = getRow(rowId);
  row.drug = { id: drug.id, name: drug.name };
  row.detail = null;
  const picker = getPicker(rowId);
  if (picker) {
    picker.querySelector("input").value = drug.name;
    clearSuggestions(picker);
  }
  state.activeBrowseId ||= drug.id;
  await loadDrugDetail(rowId);
}

function clearDrug(rowId) {
  const row = getRow(rowId);
  const picker = getPicker(rowId);
  const clearedId = row.drug?.id;
  row.drug = null;
  row.detail = null;
  picker.querySelector("input").value = "";
  clearSuggestions(picker);
  if (state.activeBrowseId === clearedId) {
    state.activeBrowseId = selectedRows()[0]?.drug?.id || null;
  }
  updateSelectedState();
  renderDetails();
  renderBrowseTabs();
  loadInteractionList();
  loadAlternativeSuggestions();
}

function updateSelectedState(message = "") {
  const count = selectedRows().length;
  const possiblePairs = count > 1 ? (count * (count - 1)) / 2 : 0;
  if (message) {
    els.selectionHint.textContent = message;
  } else if (count >= 2) {
    els.selectionHint.textContent = `${count} drugs selected. ${possiblePairs} pairs will be checked.`;
  } else if (count === 1) {
    els.selectionHint.textContent = "Select one more drug.";
  } else {
    els.selectionHint.textContent = "Select at least two drugs.";
  }
  if (count < 2) {
    state.lastCheckData = null;
    resetInsights();
  }
}

async function loadDrugDetail(rowId) {
  const row = getRow(rowId);
  if (!row?.drug) return;
  const data = await api(`/api/drugs/${encodeURIComponent(row.drug.id)}`);
  row.detail = data.error ? null : data;
}

async function checkInteractions() {
  const selected = selectedRows();
  if (selected.length < 2) {
    els.resultPanel.innerHTML = `<p class="error">Select at least two drugs first.</p>`;
    return;
  }

  els.resultPanel.innerHTML = `<div class="empty-state"><span class="status-dot"></span><p>Checking ${selected.length} drugs...</p></div>`;
  const ids = selected.map((row) => row.drug.id).join(",");
  const data = await api(`/api/check-many?ids=${encodeURIComponent(ids)}`);
  if (data.error) {
    els.resultPanel.innerHTML = `<p class="error">${escapeHtml(data.error)}</p>`;
    return;
  }
  state.lastCheckData = data;
  renderMultiResults(data);
  await loadAiInsights(ids);
}

function parseAuditLines(text) {
  return [...new Set(String(text || "")
    .split(/\n|,|;/)
    .map((item) => item.replace(/\s+\d+(\.\d+)?\s*(mg|mcg|g|ml|tablet|tab|capsule|cap).*$/i, "").trim())
    .filter((item) => item.length >= 2))].slice(0, 12);
}

async function matchAuditDrug(name) {
  const data = await api(`/api/search?q=${encodeURIComponent(name)}`);
  return data.results?.[0] || null;
}

function currentAuditLine() {
  const value = els.auditText.value;
  const cursor = els.auditText.selectionStart || 0;
  const start = value.lastIndexOf("\n", cursor - 1) + 1;
  const nextBreak = value.indexOf("\n", cursor);
  const end = nextBreak === -1 ? value.length : nextBreak;
  return {
    start,
    end,
    text: value.slice(start, end).trim(),
  };
}

function replaceCurrentAuditLine(drug) {
  const line = currentAuditLine();
  const value = els.auditText.value;
  const replacement = drug.name;
  els.auditText.value = `${value.slice(0, line.start)}${replacement}${value.slice(line.end)}`;
  const cursor = line.start + replacement.length;
  els.auditText.focus();
  els.auditText.setSelectionRange(cursor, cursor);
  closeAuditSuggestions();
}

function closeAuditSuggestions() {
  els.auditSuggestions.classList.remove("open");
  els.auditSuggestions.innerHTML = "";
}

async function updateAuditSuggestions() {
  const line = currentAuditLine();
  if (line.text.length < 2) {
    closeAuditSuggestions();
    return;
  }

  const data = await api(`/api/search?q=${encodeURIComponent(line.text)}`);
  const results = (data.results || []).slice(0, 5);
  if (!results.length) {
    closeAuditSuggestions();
    return;
  }

  els.auditSuggestions.innerHTML = `
    <div class="audit-suggestion-label">Suggested matches</div>
    ${results
    .map((drug) => `
      <button class="audit-suggestion" type="button" data-id="${escapeHtml(drug.id)}" data-name="${escapeHtml(drug.name)}">
        <strong>${escapeHtml(drug.name)}</strong>
        <span>${escapeHtml(drug.synonym ? `Synonym: ${drug.synonym}` : drug.id)}</span>
      </button>
    `)
    .join("")}
  `;
  els.auditSuggestions.classList.add("open");
  els.auditSuggestions.querySelectorAll(".audit-suggestion").forEach((button) => {
    button.addEventListener("click", () => replaceCurrentAuditLine({ id: button.dataset.id, name: button.dataset.name }));
  });
}

function renderAuditMatches(matches, missing = []) {
  const matchedRows = matches
    .map((match) => `
      <div class="audit-match ok">
        <strong>${escapeHtml(match.input)}</strong>
        <span>${escapeHtml(match.drug.name)} · ${escapeHtml(match.drug.id)}</span>
      </div>
    `)
    .join("");
  const missingRows = missing
    .map((name) => `
      <div class="audit-match missing">
        <strong>${escapeHtml(name)}</strong>
        <span>No confident DrugBank match</span>
      </div>
    `)
    .join("");

  els.auditStatus.innerHTML = `
    <div class="audit-summary">
      <span><strong>${matches.length}</strong> matched</span>
      <span><strong>${missing.length}</strong> unmatched</span>
    </div>
    <div class="audit-matches">${matchedRows}${missingRows}</div>
  `;
}

async function runPrescriptionAudit() {
  const names = parseAuditLines(els.auditText.value);
  if (names.length < 2) {
    els.auditStatus.innerHTML = `<p class="error">Paste at least two medicines to audit.</p>`;
    return;
  }

  els.auditStatus.innerHTML = `<p class="muted">Matching ${names.length} medicines against DrugBank...</p>`;
  const results = await Promise.all(names.map(async (name) => ({ input: name, drug: await matchAuditDrug(name) })));
  const matches = [];
  const missing = [];
  for (const item of results) {
    if (item.drug && !matches.some((match) => match.drug.id === item.drug.id)) {
      matches.push(item);
    } else {
      missing.push(item.input);
    }
  }

  renderAuditMatches(matches, missing);
  if (matches.length < 2) {
    els.selectionHint.textContent = "Audit needs at least two matched medicines.";
    return;
  }

  state.rows = [];
  state.activeBrowseId = null;
  matches.forEach((match) => addDrugRow(match.drug));
  while (state.rows.length < 2) addDrugRow();
  renderDrugRows();
  for (let index = 0; index < matches.length; index += 1) {
    await setDrugInRow(state.rows[index].rowId, matches[index].drug);
  }
  state.activeBrowseId = matches[0].drug.id;
  updateSelectedState(`Audit loaded ${matches.length} matched medicines.`);
  renderDrugRows();
  renderDetails();
  renderBrowseTabs();
  await loadInteractionList();
  await loadAlternativeSuggestions();
  await checkInteractions();
}

function renderMultiResults(data) {
  const currentFilter = state.severityFilter;
  const visiblePairs = data.pairs.filter((pair) => {
    if (currentFilter === "all") return true;
    if (currentFilter === "none") return !pair.found;
    return pair.found && pair.interaction?.severity === currentFilter;
  });
  const found = visiblePairs.filter((pair) => pair.found);
  const notFound = visiblePairs.filter((pair) => !pair.found);
  const filterLabel = currentFilter === "all" ? "All results" : els.severityFilter.querySelector(`[data-severity="${currentFilter}"]`)?.textContent || "Filtered";

  els.resultPanel.innerHTML = `
    <div class="summary-strip">
      <span><strong>${data.summary.selected}</strong> drugs</span>
      <span><strong>${data.summary.checked}</strong> pairs checked</span>
      <span><strong>${data.summary.found}</strong> interactions found</span>
      <span><strong>${visiblePairs.length}</strong> shown · ${escapeHtml(filterLabel)}</span>
    </div>
    <div class="result-stack">
      ${
        found.length
          ? found.map(renderPairResult).join("")
          : ""
      }
      ${
        notFound.length
          ? `<details class="quiet-details"><summary>${notFound.length} pairs without a listed interaction</summary>${notFound
              .map((pair) => `<p>${escapeHtml(pair.drug1.name)} with ${escapeHtml(pair.drug2.name)}</p>`)
              .join("")}</details>`
          : ""
      }
      ${
        !visiblePairs.length || (!found.length && !notFound.length)
          ? `<article class="result-card"><h3>No matching rows for this filter</h3><p class="muted">Try another severity filter or select a different drug set.</p></article>`
          : ""
      }
    </div>
  `;
}

function renderPairResult(pair) {
  const interaction = pair.interaction;
  return `
    <article class="result-card">
      <div class="result-head">
        <div>
          <h3>${escapeHtml(pair.drug1.name)} + ${escapeHtml(pair.drug2.name)}</h3>
          <p>${escapeHtml(interaction.description)}</p>
        </div>
        <span class="${pillClass(interaction.severity)}">${escapeHtml(interaction.label)}</span>
      </div>
    </article>
  `;
}

function resetInsights() {
  state.lastInsights = null;
  state.lastPatientRisk = null;
  els.aiSummary.innerHTML = "No analysis yet.";
  els.interactionGraph.innerHTML = "No graph yet.";
  els.foodWarnings.innerHTML = "No selected-drug food warnings yet.";
  els.sharedSignals.innerHTML = "No shared target, enzyme, or category signals yet.";
  els.patientRisk.innerHTML = state.patientContexts.size
    ? "Run an interaction check to score the selected contexts."
    : "Select context chips, then run an interaction check.";
  els.explainableAi.innerHTML = "Evidence trace will appear here after scoring.";
}

async function loadAiInsights(ids) {
  els.aiSummary.innerHTML = `<p class="muted">Analyzing selected DrugBank records...</p>`;
  els.interactionGraph.innerHTML = `<p class="muted">Building graph...</p>`;
  els.foodWarnings.innerHTML = `<p class="muted">Checking food interactions...</p>`;
  els.sharedSignals.innerHTML = `<p class="muted">Scanning mechanisms...</p>`;
  loadPatientRisk(ids);

  const data = await api(`/api/ai-insights?ids=${encodeURIComponent(ids)}`);
  if (data.error) {
    els.aiSummary.innerHTML = `<p class="error">${escapeHtml(data.error)}</p>`;
    return;
  }
  state.lastInsights = data;
  renderAiSummary(data);
  renderInteractionGraph(data);
  renderFoodWarnings(data.foodWarnings);
  renderSharedSignals(data.shared);
}

async function loadPatientRisk(ids) {
  if (!state.patientContexts.size) {
    state.lastPatientRisk = null;
    els.patientRisk.innerHTML = `<p class="muted">No patient context selected. Choose one or more chips above to personalize the score.</p>`;
    els.explainableAi.innerHTML = `<p class="muted">The evidence trace appears when patient context scoring is active.</p>`;
    return;
  }

  const contexts = [...state.patientContexts].join(",");
  els.patientRisk.innerHTML = `<p class="muted">Scoring patient context...</p>`;
  els.explainableAi.innerHTML = `<p class="muted">Tracing matched DrugBank evidence...</p>`;
  const data = await api(`/api/patient-risk?ids=${encodeURIComponent(ids)}&contexts=${encodeURIComponent(contexts)}`);
  if (data.error) {
    els.patientRisk.innerHTML = `<p class="error">${escapeHtml(data.error)}</p>`;
    return;
  }
  state.lastPatientRisk = data;
  renderPatientRisk(data);
  renderExplainableAi(data);
}

function renderPatientRisk(data) {
  const topContexts = (data.contexts || []).slice(0, 4);
  const level = data.overall.level || "none";
  els.patientRisk.innerHTML = `
    <div class="risk-score ${level}">
      <div>
        <span>${escapeHtml(data.overall.label)}</span>
        <strong>${data.overall.score}</strong>
      </div>
      <p>${escapeHtml(data.mode)}</p>
    </div>
    <div class="context-score-list">
      ${topContexts
        .map((context) => `
          <article class="context-score-row ${context.level}">
            <div>
              <strong>${escapeHtml(context.label)}</strong>
              <span>${escapeHtml(context.signalCount)} evidence signal${context.signalCount === 1 ? "" : "s"}</span>
            </div>
            <b>${context.score}</b>
          </article>
        `)
        .join("")}
    </div>
    ${
      topContexts.length
        ? `<div class="monitor-note">${bulletList(topContexts.map((context) => `${context.label}: ${context.monitor}`))}</div>`
        : `<p class="muted">No matching patient-context signals were detected in the selected records.</p>`
    }
  `;
}

function renderExplainableAi(data) {
  const topSignals = (data.contexts || []).flatMap((context) =>
    (context.signals || []).slice(0, 3).map((signal) => ({ ...signal, context: context.label })),
  ).slice(0, 8);
  const method = data.method || {};

  els.explainableAi.innerHTML = `
    <div class="explain-method">
      <span>${escapeHtml(data.mode)}</span>
      <span>${escapeHtml(method.scoreRange || "0-100")}</span>
    </div>
    <div class="explain-summary">
      ${bulletList(data.explanation || [])}
    </div>
    <div class="evidence-list">
      ${topSignals
        .map((signal) => `
          <article class="evidence-row">
            <div class="evidence-head">
              <div>
                <strong>${escapeHtml(signal.context)}</strong>
                <span>${escapeHtml(signal.drugName)}</span>
              </div>
              <b>${escapeHtml(signal.source)} · +${escapeHtml(signal.points)} pts</b>
            </div>
            <p>${escapeHtml(signal.excerpt)}</p>
            <div class="match-tags" aria-label="Matched evidence terms">
              ${(signal.matched || []).map((term) => `<span>${escapeHtml(term)}</span>`).join("")}
            </div>
          </article>
        `)
        .join("") || `<p class="muted">No evidence snippets matched the selected contexts.</p>`}
    </div>
  `;
}

function renderAiSummary(data) {
  const top = data.topInteractions?.length
    ? `
      <div class="mini-stack">
        ${data.topInteractions
          .slice(0, 3)
          .map((edge) => `
            <div class="mini-risk ${edge.severity}">
              <strong>${escapeHtml(edge.sourceName)} + ${escapeHtml(edge.targetName)}</strong>
              <span>${escapeHtml(edge.label)}</span>
            </div>
          `)
          .join("")}
      </div>
    `
    : "";

  els.aiSummary.innerHTML = `
    <p class="ai-mode">${escapeHtml(data.mode)}</p>
    ${bulletList(data.summary)}
    ${top}
  `;
}

function renderInteractionGraph(data) {
  const nodes = data.nodes || [];
  const edges = data.edges || [];
  if (!nodes.length) {
    els.interactionGraph.innerHTML = `<p class="muted">No graph available.</p>`;
    return;
  }

  const width = 520;
  const height = 300;
  const centerX = width / 2;
  const centerY = height / 2;
  const radius = nodes.length <= 2 ? 95 : 110;
  const positions = {};
  nodes.forEach((node, index) => {
    const angle = nodes.length === 1 ? 0 : (Math.PI * 2 * index) / nodes.length - Math.PI / 2;
    positions[node.id] = {
      x: centerX + Math.cos(angle) * radius,
      y: centerY + Math.sin(angle) * radius,
    };
  });

  const edgeMarkup = edges
    .map((edge) => {
      const source = positions[edge.source];
      const target = positions[edge.target];
      const cls = edge.found ? edge.severity : "none";
      return `<line class="graph-edge ${cls}" x1="${source.x}" y1="${source.y}" x2="${target.x}" y2="${target.y}"><title>${escapeHtml(edge.sourceName)} + ${escapeHtml(edge.targetName)}: ${escapeHtml(edge.label)}</title></line>`;
    })
    .join("");

  const nodeMarkup = nodes
    .map((node) => {
      const position = positions[node.id];
      return `
        <g class="graph-node">
          <circle cx="${position.x}" cy="${position.y}" r="30"></circle>
          <text x="${position.x}" y="${position.y + 5}" text-anchor="middle">${escapeHtml(node.name.slice(0, 3))}</text>
          <title>${escapeHtml(node.name)}</title>
        </g>
      `;
    })
    .join("");

  const legend = `
    <div class="graph-legend">
      <span><i class="legend high"></i>High</span>
      <span><i class="legend moderate"></i>Monitor</span>
      <span><i class="legend none"></i>No listed row</span>
    </div>
  `;

  els.interactionGraph.innerHTML = `
    <svg class="interaction-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Drug interaction graph">
      ${edgeMarkup}
      ${nodeMarkup}
    </svg>
    ${legend}
  `;
}

function renderFoodWarnings(warnings) {
  if (!warnings?.length) {
    els.foodWarnings.innerHTML = `<p class="muted">No food interaction warnings were listed for these selections.</p>`;
    return;
  }
  els.foodWarnings.innerHTML = warnings
    .map((item) => `
      <div class="warning-group">
        <h4>${escapeHtml(item.drugName)}</h4>
        ${bulletList(item.warnings.slice(0, 4))}
      </div>
    `)
    .join("");
}

function renderSharedSignals(shared) {
  const groups = [
    ["Shared categories", shared?.categories || []],
    ["Shared targets", shared?.targets || []],
    ["Shared enzymes", shared?.enzymes || []],
  ];
  const html = groups
    .filter(([, items]) => items.length)
    .map(([title, items]) => `
      <div class="signal-group">
        <h4>${escapeHtml(title)}</h4>
        ${items
          .slice(0, 5)
          .map((item) => `
            <div class="signal-row">
              <strong>${escapeHtml(item.name)}</strong>
              <span>${escapeHtml(item.drugs.join(", "))}</span>
            </div>
          `)
          .join("")}
      </div>
    `)
    .join("");

  els.sharedSignals.innerHTML = html || `<p class="muted">No shared structured signals were detected.</p>`;
}

function setRagResultEmpty(isEmpty) {
  els.ragResult.classList.toggle("insight-empty", Boolean(isEmpty));
}

function resetRagResult(message) {
  setRagResultEmpty(true);
  els.ragResult.innerHTML = escapeHtml(message);
}

function renderRagResult(data) {
  if (!data) {
    resetRagResult("No RAG result yet.");
    return;
  }
  if (data.error) {
    setRagResultEmpty(false);
    els.ragResult.innerHTML = `<p class="error">${escapeHtml(data.error)}</p>`;
    return;
  }
  setRagResultEmpty(false);

  const answerLines = String(data.answer || "").split("\n").filter(Boolean);
  const answerHtml = answerLines
    .map((line) => `<p>${escapeHtml(line)}</p>`)
    .join("");

  const citations = data.citations || [];
  const citationsHtml = citations.length
    ? `
      <ol class="rag-citations">
        ${citations
          .map(
            (citation, index) => `
              <li>
                <div class="rag-citation-head">
                  <span class="rag-citation-tag">[${index + 1}]</span>
                  <strong>${escapeHtml(citation.drugName)}</strong>
                  <span class="rag-field">${escapeHtml(citation.field)}</span>
                  <span class="rag-score" title="BM25 relevance">relevance ${Math.round((citation.relevance || 0) * 100)}%</span>
                </div>
                <p class="rag-evidence">${escapeHtml(citation.evidence || citation.excerpt || "")}</p>
              </li>
            `,
          )
          .join("")}
      </ol>
    `
    : `<p class="muted">No passages exceeded the retrieval threshold.</p>`;

  const queryTerms = data.queryTerms || [];
  const expandedTerms = data.expandedTerms || [];
  const fieldBoosts = data.fieldBoosts || {};
  const usedFallback = Boolean(data.fallback);

  const termChips = (items, className) =>
    items.map((term) => `<code class="${className}">${escapeHtml(term)}</code>`).join(" ");

  const queryTermsHtml = queryTerms.length
    ? `<div class="rag-trace-row">
         <span class="rag-trace-label">Your terms</span>
         <div class="rag-trace-chips">${termChips(queryTerms, "rag-chip-original")}</div>
       </div>`
    : "";

  const expandedTermsHtml = expandedTerms.length
    ? `<div class="rag-trace-row">
         <span class="rag-trace-label" title="Added by the NLP layer via Porter stemming, lexicon synonyms, or intent detection">NLP added</span>
         <div class="rag-trace-chips">${termChips(expandedTerms, "rag-chip-expanded")}</div>
       </div>`
    : "";

  const boostEntries = Object.entries(fieldBoosts);
  const boostsHtml = boostEntries.length
    ? `<div class="rag-trace-row">
         <span class="rag-trace-label" title="Fields whose BM25 scores were multiplied because the query signalled this intent">Boosted fields</span>
         <div class="rag-trace-chips">${boostEntries
           .sort((a, b) => b[1] - a[1])
           .map(([field, mult]) => `<span class="rag-boost-chip">${escapeHtml(field)} <em>×${Number(mult).toFixed(1)}</em></span>`)
           .join(" ")}</div>
       </div>`
    : "";

  const traceHtml = (queryTermsHtml || expandedTermsHtml || boostsHtml)
    ? `<details class="rag-trace" ${usedFallback ? "open" : ""}>
         <summary>How the assistant interpreted your question</summary>
         ${queryTermsHtml}${expandedTermsHtml}${boostsHtml}
       </details>`
    : "";

  const fallbackBanner = usedFallback
    ? `<div class="rag-fallback-banner" role="note">
         <strong>Fallback used.</strong> No DrugBank passage strongly matched your question for the selected drugs, so the top description chunk for each drug is shown instead.
       </div>`
    : "";

  els.ragResult.innerHTML = `
    <div class="rag-meta">
      <span>${escapeHtml(data.mode || "Local RAG")}</span>
      <span>Retrieved ${fmt.format(data.retrieved || 0)} of ${fmt.format(data.corpusSize || 0)} chunks</span>
      ${usedFallback ? `<span class="rag-meta-warn">fallback</span>` : ""}
    </div>
    ${fallbackBanner}
    <div class="rag-answer">${answerHtml || `<p class="muted">No answer produced.</p>`}</div>
    <h4 class="rag-subhead">Citations</h4>
    ${citationsHtml}
    ${traceHtml}
  `;
}

async function runRagQuery() {
  const query = (els.ragQuery.value || "").trim();
  if (!query) {
    resetRagResult("Type a question first.");
    els.ragQuery.focus();
    return;
  }
  const selected = selectedRows();
  if (!selected.length) {
    setRagResultEmpty(false);
    els.ragResult.innerHTML = `<p class="error">Select at least one drug above so RAG has a corpus to retrieve from.</p>`;
    return;
  }
  const ids = selected.map((row) => row.drug.id).join(",");
  setRagResultEmpty(false);
  els.ragResult.innerHTML = `<div class="empty-state"><span class="status-dot"></span><p>Indexing selected DrugBank text and retrieving evidence...</p></div>`;
  els.ragSubmit.disabled = true;
  try {
    const data = await api(
      `/api/rag-query?q=${encodeURIComponent(query)}&ids=${encodeURIComponent(ids)}`,
    );
    renderRagResult(data);
  } catch (error) {
    setRagResultEmpty(false);
    els.ragResult.innerHTML = `<p class="error">RAG request failed: ${escapeHtml(error.message || String(error))}</p>`;
  } finally {
    els.ragSubmit.disabled = false;
  }
}

async function loadAlternativeSuggestions() {
  const selected = selectedRows();
  if (!selected.length) {
    els.alternativeDrugs.innerHTML = "Select a drug to see related alternatives.";
    return;
  }

  const source = selected.find((row) => row.drug.id === state.activeBrowseId) || selected[0];
  els.alternativeDrugs.innerHTML = `<p class="muted">Finding related drugs for ${escapeHtml(source.drug.name)}...</p>`;
  const data = await api(`/api/similar?drug=${encodeURIComponent(source.drug.id)}`);
  if (data.error) {
    els.alternativeDrugs.innerHTML = `<p class="error">${escapeHtml(data.error)}</p>`;
    return;
  }
  if (!data.results.length) {
    els.alternativeDrugs.innerHTML = `<p class="muted">No close structured alternatives were found for ${escapeHtml(data.source.name)}.</p>`;
    return;
  }

  els.alternativeDrugs.innerHTML = `
    <p class="muted">Similar structured profile to ${escapeHtml(data.source.name)}. Review clinically before substitution.</p>
    <div class="alternative-list">
      ${data.results
        .map((drug) => `
          <article class="alternative-row">
            <div>
              <strong>${escapeHtml(drug.name)}</strong>
              <span>${escapeHtml(drug.signals.slice(0, 2).join(" · ") || "Shared database signals")}</span>
            </div>
            <button class="mini-button" type="button" data-action="profile" data-drug-id="${escapeHtml(drug.id)}">Profile</button>
          </article>
        `)
        .join("")}
    </div>
  `;
}

function renderDetails() {
  const selected = selectedRows();
  state.textStore = {};
  state.nextTextId = 1;
  if (!selected.length) {
    els.detailsGrid.innerHTML = "";
    return;
  }
  els.detailsGrid.innerHTML = selected
    .map((row) => {
      if (!row.detail) {
        return `<article class="panel glass"><p class="muted">${escapeHtml(row.drug.name)} details loading...</p></article>`;
      }
      return `<article class="panel glass">${renderDrugDetail(row.detail)}</article>`;
    })
    .join("");
}

function renderDrugDetail(data) {
  const drug = data.drug;
  const categoryTags = data.categories
    .slice(0, 6)
    .map((category) => `<span class="pill">${escapeHtml(category)}</span>`)
    .join("");

  return `
    <div class="detail-header">
      <div>
        <h3>${escapeHtml(drug.name)}</h3>
        <p class="muted">${escapeHtml(drug.id)}</p>
      </div>
      <div class="detail-actions">
        <span class="pill">${fmt.format(data.interactionCount)} interactions</span>
        <button class="mini-button" type="button" data-action="profile" data-drug-id="${escapeHtml(drug.id)}">Profile</button>
      </div>
    </div>
    <div class="meta-grid">
      <div class="meta-item"><span>Half-life</span>${expandableText(`${drug.name} half-life`, drug.half_life || "Not listed", 210, 3)}</div>
      <div class="meta-item"><span>Metabolism</span>${expandableText(`${drug.name} metabolism`, drug.metabolism || "Not listed", 210, 2)}</div>
    </div>
    ${drug.indication ? `<div class="text-block"><h3>Indication</h3>${expandableText(`${drug.name} indication`, drug.indication, 300, 3)}</div>` : ""}
    ${drug.mechanism ? `<div class="text-block"><h3>Mechanism</h3>${expandableText(`${drug.name} mechanism`, drug.mechanism, 300, 3)}</div>` : ""}
    ${categoryTags ? `<div class="tags">${categoryTags}</div>` : ""}
  `;
}

function renderBrowseTabs() {
  const selected = selectedRows();
  if (!selected.length) {
    els.browseTabs.innerHTML = "";
    return;
  }

  if (!selected.some((row) => row.drug.id === state.activeBrowseId)) {
    state.activeBrowseId = selected[0].drug.id;
  }

  els.browseTabs.innerHTML = selected
    .map((row) => `
      <button class="tab ${row.drug.id === state.activeBrowseId ? "active" : ""}" data-drug-id="${escapeHtml(row.drug.id)}" type="button">
        ${escapeHtml(row.drug.name)}
      </button>
    `)
    .join("");

  els.browseTabs.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      state.activeBrowseId = button.dataset.drugId;
      renderBrowseTabs();
      loadInteractionList();
      loadAlternativeSuggestions();
    });
  });
}

async function loadInteractionList() {
  if (!state.activeBrowseId) {
    els.interactionList.innerHTML = `<p class="muted">No drug selected yet.</p>`;
    return;
  }
  const selected = selectedRows().find((row) => row.drug.id === state.activeBrowseId);
  if (!selected) return;

  const filter = els.browseFilter.value.trim();
  els.interactionList.innerHTML = `<p class="muted">Loading interactions for ${escapeHtml(selected.drug.name)}...</p>`;
  const data = await api(`/api/drugs/${encodeURIComponent(selected.drug.id)}/interactions?q=${encodeURIComponent(filter)}`);
  if (!data.results.length) {
    els.interactionList.innerHTML = `<p class="muted">No matching interactions found.</p>`;
    return;
  }
  els.interactionList.innerHTML = data.results
    .map((row) => `
      <article class="interaction-row glass">
        <div class="row-top">
          <h3>${escapeHtml(row.name)}</h3>
          <span class="${pillClass(row.severity)}">${escapeHtml(row.label)}</span>
        </div>
        <p>${escapeHtml(row.description)}</p>
      </article>
    `)
    .join("");
}

function valueList(items, mapper = (item) => item) {
  const clean = items.map(mapper).filter(Boolean);
  return clean.length ? bulletList(clean.slice(0, 10)) : `<p class="muted">Not listed.</p>`;
}

function profileSection(title, content) {
  if (!content) return "";
  return `
    <article class="profile-section">
      <h3>${escapeHtml(title)}</h3>
      ${content}
    </article>
  `;
}

function hasItems(items) {
  return Array.isArray(items) && items.length > 0;
}

async function openDrugProfile(drugId) {
  const data = await api(`/api/drugs/${encodeURIComponent(drugId)}`);
  if (data.error) return;
  document.querySelector(".profile-modal")?.remove();
  const drug = data.drug;
  const transportItems = [...(data.carriers || []), ...(data.transporters || [])];
  const optionalSections = [
    profileSection("Food warnings", hasItems(data.foodInteractions) ? valueList(data.foodInteractions) : ""),
    profileSection("Targets", hasItems(data.targets) ? valueList(data.targets, (item) => [item.name, item.action, item.organism].filter(Boolean).join(" · ")) : ""),
    profileSection("Enzymes", hasItems(data.enzymes) ? valueList(data.enzymes, (item) => [item.name, item.organism].filter(Boolean).join(" · ")) : ""),
    profileSection("Dosages", hasItems(data.dosages) ? valueList(data.dosages, (item) => [item.strength, item.form, item.route].filter(Boolean).join(" · ")) : ""),
    profileSection("Products", hasItems(data.products) ? valueList(data.products, (item) => [item.name, item.form, item.route].filter(Boolean).join(" · ")) : ""),
    profileSection("Transport", hasItems(transportItems) ? valueList(transportItems) : ""),
    profileSection(
      "Categories",
      hasItems(data.categories)
        ? `<div class="tags">${data.categories.slice(0, 12).map((category) => `<span class="pill">${escapeHtml(category)}</span>`).join("")}</div>`
        : "",
    ),
  ].join("");
  const modal = document.createElement("div");
  modal.className = "profile-modal";
  modal.innerHTML = `
    <div class="reader-backdrop" data-action="close-profile"></div>
    <section class="profile-panel glass" role="dialog" aria-modal="true" aria-label="${escapeHtml(drug.name)} profile">
      <div class="reader-head">
        <div>
          <p class="eyebrow">Drug profile</p>
          <h2>${escapeHtml(drug.name)}</h2>
          <p class="muted">${escapeHtml(drug.id)} · ${fmt.format(data.interactionCount)} interactions</p>
        </div>
        <button class="icon-button" type="button" data-action="close-profile" aria-label="Close profile">×</button>
      </div>
      <div class="profile-grid">
        <article class="profile-section wide">
          <h3>Description</h3>
          ${expandableText(`${drug.name} description`, drug.description || "Not listed.", 520, 4)}
        </article>
        ${optionalSections || `<article class="profile-section"><h3>Structured fields</h3><p class="muted">No additional structured profile rows were imported for this drug.</p></article>`}
      </div>
    </section>
  `;
  document.body.appendChild(modal);
}

function exportReport() {
  if (!state.lastCheckData) {
    els.selectionHint.textContent = "Run an interaction check before exporting.";
    return;
  }

  const checkedAt = new Date().toLocaleString();
  const drugs = state.lastCheckData.drugs || [];
  const found = state.lastCheckData.pairs.filter((pair) => pair.found);
  const missing = state.lastCheckData.pairs.filter((pair) => !pair.found);
  const insightItems = state.lastInsights?.summary || [];
  const patientItems = state.lastPatientRisk
    ? [
        `Patient context score: ${state.lastPatientRisk.overall.score}/100 (${state.lastPatientRisk.overall.label}).`,
        ...(state.lastPatientRisk.contexts || []).slice(0, 3).map((context) => `${context.label}: ${context.score}/100 from ${context.signalCount} evidence signal(s).`),
      ]
    : [];
  const reportHtml = `
    <!doctype html>
    <html>
      <head>
        <meta charset="utf-8">
        <title>NeuroPharmDB Interaction Report</title>
        <style>
          body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 40px; color: #111; line-height: 1.45; }
          h1 { margin-bottom: 4px; }
          h2 { margin-top: 28px; border-bottom: 1px solid #ddd; padding-bottom: 8px; }
          .pill { display: inline-block; border: 1px solid #ccc; border-radius: 999px; padding: 4px 9px; margin: 3px; color: #444; }
          .card { border: 1px solid #ddd; border-radius: 12px; padding: 14px; margin: 10px 0; break-inside: avoid; }
          .high { color: #b00020; } .moderate { color: #9a5a00; } .informational { color: #187a3b; }
          @media print { body { margin: 22mm; } button { display: none; } }
        </style>
      </head>
      <body>
        <button onclick="window.print()">Print or save PDF</button>
        <h1>NeuroPharmDB Interaction Report</h1>
        <p>Generated ${escapeHtml(checkedAt)} from the local DrugBank database.</p>
        <h2>Selected Drugs</h2>
        <p>${drugs.map((drug) => `<span class="pill">${escapeHtml(drug.name)} (${escapeHtml(drug.id)})</span>`).join("")}</p>
        <h2>Summary</h2>
        ${bulletList([
          `${state.lastCheckData.summary.checked} pairs checked.`,
          `${state.lastCheckData.summary.found} listed interactions found.`,
          `${missing.length} pairs had no listed interaction row.`,
          ...patientItems,
          ...insightItems,
        ])}
        <h2>Listed Interactions</h2>
        ${
          found.length
            ? found.map((pair) => `
              <div class="card">
                <strong>${escapeHtml(pair.drug1.name)} + ${escapeHtml(pair.drug2.name)}</strong>
                <p class="${escapeHtml(pair.interaction.severity)}">${escapeHtml(pair.interaction.label)}</p>
                <p>${escapeHtml(pair.interaction.description)}</p>
              </div>
            `).join("")
            : "<p>No listed interactions found.</p>"
        }
      </body>
    </html>
  `;

  const report = window.open("", "_blank");
  if (!report) {
    els.selectionHint.textContent = "Allow pop-ups to open the report.";
    return;
  }
  report.document.open();
  report.document.write(reportHtml);
  report.document.close();
}

function applyTheme(theme) {
  document.documentElement.dataset.theme = theme;
  localStorage.setItem("neuropharm-theme", theme);
  els.themeToggle.querySelector(".theme-icon").textContent = theme === "dark" ? "☀" : "☾";
}

document.addEventListener("click", (event) => {
  if (!event.target.closest(".drug-picker")) {
    els.drugRows.querySelectorAll(".suggestions").forEach((suggestions) => suggestions.classList.remove("open"));
  }
  if (!event.target.closest(".audit-input")) {
    closeAuditSuggestions();
  }

  const readMoreButton = event.target.closest('[data-action="read-more"]');
  if (readMoreButton) {
    const block = readMoreButton.closest(".readmore-block");
    const item = state.textStore[block.dataset.textId];
    showReaderModal(item);
  }

  const profileButton = event.target.closest('[data-action="profile"]');
  if (profileButton) {
    openDrugProfile(profileButton.dataset.drugId);
  }

  if (event.target.closest('[data-action="close-reader"]')) {
    document.querySelector(".reader-modal")?.remove();
  }

  if (event.target.closest('[data-action="close-profile"]')) {
    document.querySelector(".profile-modal")?.remove();
  }
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    document.querySelector(".reader-modal")?.remove();
    document.querySelector(".profile-modal")?.remove();
  }
});

els.addDrugButton.addEventListener("click", () => {
  const row = addDrugRow();
  getPicker(row.rowId).querySelector("input").focus();
});

els.checkButton.addEventListener("click", checkInteractions);
els.exportReportButton.addEventListener("click", exportReport);
els.runAuditButton.addEventListener("click", runPrescriptionAudit);
els.sampleAuditButton.addEventListener("click", () => {
  els.auditText.value = "Warfarin\nIbuprofen\nApixaban";
  closeAuditSuggestions();
});
els.clearAuditButton.addEventListener("click", () => {
  els.auditText.value = "";
  els.auditStatus.innerHTML = `<p class="muted">No audit run yet.</p>`;
  closeAuditSuggestions();
});
els.auditText.addEventListener("input", () => {
  window.clearTimeout(state.searchTimers.audit);
  state.searchTimers.audit = window.setTimeout(updateAuditSuggestions, 160);
});
els.auditText.addEventListener("click", updateAuditSuggestions);
els.auditText.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeAuditSuggestions();
});

els.severityFilter.querySelectorAll(".filter-chip").forEach((button) => {
  button.addEventListener("click", () => {
    state.severityFilter = button.dataset.severity;
    els.severityFilter.querySelectorAll(".filter-chip").forEach((item) => item.classList.toggle("active", item === button));
    if (state.lastCheckData) renderMultiResults(state.lastCheckData);
  });
});

els.patientContexts.querySelectorAll(".context-chip").forEach((button) => {
  button.addEventListener("click", () => {
    const context = button.dataset.context;
    if (state.patientContexts.has(context)) {
      state.patientContexts.delete(context);
      button.classList.remove("active");
    } else {
      state.patientContexts.add(context);
      button.classList.add("active");
    }

    if (state.lastCheckData) {
      const ids = selectedRows().map((row) => row.drug.id).join(",");
      loadPatientRisk(ids);
    } else {
      els.patientRisk.innerHTML = state.patientContexts.size
        ? "Run an interaction check to score the selected contexts."
        : "Select context chips, then run an interaction check.";
      els.explainableAi.innerHTML = "Evidence trace will appear here after scoring.";
    }
  });
});

els.browseFilter.addEventListener("input", () => {
  window.clearTimeout(state.searchTimers.browse);
  state.searchTimers.browse = window.setTimeout(loadInteractionList, 200);
});

if (els.ragSubmit) {
  els.ragSubmit.addEventListener("click", runRagQuery);
}
if (els.ragClear) {
  els.ragClear.addEventListener("click", () => {
    els.ragQuery.value = "";
    resetRagResult("Cleared. Ask another question.");
    els.ragQuery.focus();
  });
}
if (els.ragQuery) {
  els.ragQuery.addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter") {
      event.preventDefault();
      runRagQuery();
    }
  });
}
if (els.ragSuggestions) {
  els.ragSuggestions.querySelectorAll("[data-question]").forEach((button) => {
    button.addEventListener("click", () => {
      els.ragQuery.value = button.dataset.question || button.textContent.trim();
      runRagQuery();
    });
  });
}

els.themeToggle.addEventListener("click", () => {
  const current = document.documentElement.dataset.theme === "dark" ? "dark" : "light";
  applyTheme(current === "dark" ? "light" : "dark");
});

const savedTheme = localStorage.getItem("neuropharm-theme");
const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
applyTheme(savedTheme || (prefersDark ? "dark" : "light"));

addDrugRow();
addDrugRow();
loadStats().catch(() => {
  els.drugCount.textContent = "N/A";
  els.interactionCount.textContent = "N/A";
});
