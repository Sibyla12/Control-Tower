const API_URL = "https://control-tower-vl22.onrender.com";
const LIVE_POLL_MS = 20000;

function humanizeMerchant(value) {
  return typeof value === "string" ? value.replace(/Merchant_(\w+)/g, "Merchant $1") : value;
}

function pipeToText(value, fallback = "All") {
  if (!value) return fallback;
  return value.split("|").map(item => humanizeMerchant(item.trim())).filter(Boolean).join(", ");
}

function formatStarted(timestamp) {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleTimeString("en-GB", {
    hour: "2-digit", minute: "2-digit", hour12: false
  });
}

function buildRootLabel(apiIncident) {
  if (apiIncident.root_cause_type === "provider") {
    return `${apiIncident.country} › ${apiIncident.provider}`;
  }
  if (apiIncident.root_cause_type === "issuing_bank") {
    return `${apiIncident.country} › ${apiIncident.merchant} › ${apiIncident.issuing_bank}`;
  }
  return `${apiIncident.country} › unresolved`;
}

function buildDiagnosticTree(apiIncident) {
  if (apiIncident.root_cause_type === "provider") {
    return { label: apiIncident.country, children: [{
      label: apiIncident.provider, state: "root", children: [{
        label: apiIncident.dominant_decline_code, state: "root"
      }]
    }] };
  }
  if (apiIncident.root_cause_type === "issuing_bank") {
    return { label: apiIncident.country, children: [{
      label: apiIncident.merchant || "Affected merchant", state: "anomaly", children: [{
        label: apiIncident.issuing_bank, state: "root", children: [{
          label: apiIncident.dominant_decline_code, state: "root"
        }]
      }]
    }] };
  }
  return null;
}

function buildEvidence(apiIncident) {
  const expected = apiIncident.expected_approval_rate * 100;
  const actual = apiIncident.observed_approval_rate * 100;
  const drop = expected - actual;
  const evidence = [
    `Approval rate fell ${drop.toFixed(1)} percentage points below its expected baseline.`,
    `${Math.round(apiIncident.estimated_lost_approvals)} approvals are estimated to have been lost.`,
    `${apiIncident.validated_windows} validated anomaly windows support this diagnosis.`,
    `${apiIncident.dominant_decline_code} is the dominant decline code in the affected flow.`
  ];
  if (apiIncident.root_cause_type === "provider") {
    evidence[1] = `The degradation spans ${pipeToText(apiIncident.affected_merchants, "multiple merchants")} and ${pipeToText(apiIncident.affected_methods, "multiple methods")}.`;
  }
  if (apiIncident.root_cause_type === "issuing_bank") {
    evidence[1] = `The failure is concentrated in ${apiIncident.issuing_bank}-issued traffic for ${apiIncident.merchant}.`;
  }
  return evidence;
}

function mapApiIncident(rawApiIncident) {
  const apiIncident = { ...rawApiIncident };
  for (const key of Object.keys(apiIncident)) {
    apiIncident[key] = humanizeMerchant(apiIncident[key]);
  }
  const durationMinutes = Math.max((new Date(apiIncident.end_time) - new Date(apiIncident.start_time)) / 60000 + 1, 1);
  const riskPerHour = apiIncident.value_at_risk_per_minute_usd * 60;
  const recoverablePerHour = (apiIncident.expected_recovered_value_usd / durationMinutes) * 60;
  const expected = apiIncident.expected_approval_rate * 100;
  const actual = apiIncident.observed_approval_rate * 100;
  const providerOrBank = apiIncident.provider || apiIncident.issuing_bank || apiIncident.root_cause_type;
  return {
    id: apiIncident.consolidated_incident_id,
    priority: apiIncident.priority,
    severity: apiIncident.priority === "P1" ? "CRITICAL" : "HIGH",
    country: apiIncident.country,
    started: formatStarted(apiIncident.start_time),
    startTime: apiIncident.start_time,
    title: apiIncident.incident_title,
    subtitle: apiIncident.root_cause_type === "provider"
      ? "Provider issue across multiple merchants"
      : `Issuer outage affecting ${apiIncident.merchant || "affected merchant"}`,
    expected,
    actual,
    confidence: Math.round(apiIncident.confidence_score * 100),
    risk: riskPerHour,
    adjustedRisk: apiIncident.net_unrecovered_value_usd,
    attempts: apiIncident.attempts_in_scope || apiIncident.attempts,
    excess: Math.round(apiIncident.estimated_lost_approvals),
    attribution: Math.round(apiIncident.recommendation_confidence * 100),
    evidence: buildEvidence(apiIncident),
    executive: `${apiIncident.incident_title} is putting approximately ${money(riskPerHour)} of payment value per hour at risk.`,
    recommendation: apiIncident.primary_action,
    root: buildRootLabel(apiIncident),
    affected: [apiIncident.country, providerOrBank, pipeToText(apiIncident.affected_methods, "All methods"), pipeToText(apiIncident.affected_merchants, "All merchants")].join(" · "),
    recovery: `${money(recoverablePerHour)} / hour`,
    method: pipeToText(apiIncident.affected_methods, apiIncident.payment_method || "All methods"),
    merchants: pipeToText(apiIncident.affected_merchants, apiIncident.merchant || "All merchants"),
    tree: buildDiagnosticTree(apiIncident),
    recommendationStatus: apiIncident.recommendation_status,
    reviewedBy: apiIncident.reviewed_by,
    priorityReason: apiIncident.priority_reason,
    paymentsOperationsAction: apiIncident.payments_operations_action,
    engineeringAction: apiIncident.engineering_action,
    financeAction: apiIncident.finance_action,
    merchantSuccessAction: apiIncident.merchant_success_action,
    executiveAction: apiIncident.executive_action,
    incidentType: apiIncident.incident_type,
    rootCauseDimensions: apiIncident.root_cause_dimensions,
    operationalOwner: apiIncident.operational_owner,
    playbookAction: apiIncident.playbook_action,
    priorityLabel: apiIncident.priority_label,
    priorityCriteria: apiIncident.priority_criteria,
    systemResponse: apiIncident.system_response,
    escalationLevel: apiIncident.escalation_level,
    expectedAttention: apiIncident.expected_attention
  };
}

async function loadLiveIncidents() {
  const response = await fetch(`${API_URL}/incidents`);
  if (!response.ok) throw new Error(`Control Tower API returned ${response.status}`);
  const payload = await response.json();
  return payload.incidents.map(mapApiIncident);
}

async function loadDashboard() {
  const response = await fetch(`${API_URL}/dashboard`);
  if (!response.ok) throw new Error(`Control Tower API returned ${response.status}`);
  return response.json();
}

function pickTimeLabels(history) {
  if (!history.length) return [];
  const lastIndex = history.length - 1;
  const indices = [...new Set([0, Math.round(lastIndex / 3), Math.round((lastIndex * 2) / 3), lastIndex])];
  return indices.map((index, position) => position === indices.length - 1 ? "Now" : formatStarted(history[index].timestamp));
}

function findMarkerIndex(history, liveIncidents) {
  if (!history.length || !liveIncidents.length) return undefined;
  const startTimes = liveIncidents
    .map(incident => new Date(incident.startTime).getTime())
    .filter(ms => !Number.isNaN(ms));
  if (!startTimes.length) return undefined;
  const earliestMs = Math.min(...startTimes);
  let bestIndex = 0, bestDiff = Infinity;
  history.forEach((point, index) => {
    const diff = Math.abs(new Date(point.timestamp).getTime() - earliestMs);
    if (diff < bestDiff) { bestDiff = diff; bestIndex = index; }
  });
  return bestIndex;
}

function buildLiveScenario(dashboard, liveIncidents) {
  const globalMetrics = dashboard.global_metrics;
  const countries = {};
  Object.entries(dashboard.countries).forEach(([code, country]) => {
    countries[code] = [country.status, country.approval_rate !== null ? country.approval_rate * 100 : 0];
  });
  const history = dashboard.conversion_history || [];
  const chart = history.map(point => point.observed_rate !== null ? point.observed_rate * 100 : null);
  const expectedChart = history.map(point => point.expected_rate !== null ? point.expected_rate * 100 : null);
  const isHealthy = dashboard.system_status === "healthy";
  return {
    tone: dashboard.system_status,
    pill: isHealthy ? "SYSTEM HEALTHY" : `${liveIncidents.length} ACTIVE INCIDENT${liveIncidents.length === 1 ? "" : "S"}`,
    title: isHealthy
      ? "Payment network operating within expected range"
      : liveIncidents.length > 1
        ? "Multiple live incidents detected and prioritized"
        : "Live incident detected and prioritized",
    description: isHealthy
      ? "No meaningful deterioration detected across monitored payment flows."
      : "Control Tower separated the active failures, estimated their financial impact, and generated operator recommendations.",
    conversion: globalMetrics.approval_rate !== null ? globalMetrics.approval_rate * 100 : 0,
    expected: globalMetrics.expected_approval_rate !== null ? globalMetrics.expected_approval_rate * 100 : 0,
    chart, expectedChart,
    timeLabels: pickTimeLabels(history),
    incidents: liveIncidents,
    countries,
    monitoredTraffic: dashboard.monitored_traffic,
    lastUpdated: dashboard.last_updated,
    marker: findMarkerIndex(history, liveIncidents)
  };
}

function connectingScenario() {
  return {
    tone: "healthy", pill: "CONNECTING…", title: "Connecting to the live payment network",
    description: "Fetching current incidents and conversion data from Control Tower.",
    conversion: 0, expected: 0, chart: [], expectedChart: [], timeLabels: [],
    incidents: [], countries: { MX: ["healthy", 0], CO: ["healthy", 0], BR: ["healthy", 0] },
    monitoredTraffic: { attempts_total: 0, merchants: 0, providers: 0 }, marker: undefined
  };
}

function liveErrorScenario(message) {
  return {
    tone: "warning", pill: "LIVE DATA UNAVAILABLE", title: "Could not reach the Control Tower API",
    description: message,
    conversion: 0, expected: 0, chart: [], expectedChart: [], timeLabels: [],
    incidents: [], countries: { MX: ["healthy", 0], CO: ["healthy", 0], BR: ["healthy", 0] },
    monitoredTraffic: { attempts_total: 0, merchants: 0, providers: 0 }, marker: undefined
  };
}

const state = { selectedIncident: null, liveData: null, liveError: null, liveTimer: null, reviewUi: { modifying: false } };

function money(value) { return value >= 1000 ? `$${(value/1000).toFixed(1)}K` : `$${Math.round(value)}`; }
function formatCount(value) { return value >= 1000 ? `${(value/1000).toFixed(1)}K` : `${Math.round(value)}`; }

function currentView() {
  if (state.liveData) return state.liveData;
  if (state.liveError) return liveErrorScenario(state.liveError);
  return connectingScenario();
}

async function fetchLive() {
  try {
    const [dashboard, liveIncidents] = await Promise.all([loadDashboard(), loadLiveIncidents()]);
    const hadError = Boolean(state.liveError);
    state.liveData = buildLiveScenario(dashboard, liveIncidents);
    state.liveError = null;
    render();
    if (hadError) showToast("Live connection restored");
  } catch (error) {
    console.error("Could not load live data:", error);
    state.liveError = (error && error.message) || "Control Tower API unavailable";
    render();
    showToast("Live data unavailable — check the Control Tower API");
  }
}

function startLivePolling() {
  fetchLive();
  clearInterval(state.liveTimer);
  state.liveTimer = setInterval(fetchLive, LIVE_POLL_MS);
}

function render() {
  const s = currentView();
  const risk = s.incidents.reduce((sum, i) => sum + i.risk, 0);
  const adjusted = s.incidents.reduce((sum, i) => sum + i.adjustedRisk, 0);
  const strip = document.getElementById("statusStrip");
  strip.className = `status-strip ${s.tone === "healthy" ? "" : s.tone}`;
  document.getElementById("statusPill").textContent = s.pill;
  document.getElementById("statusTitle").textContent = s.title;
  document.getElementById("statusDescription").textContent = s.description;
  document.getElementById("conversionValue").textContent = `${s.conversion.toFixed(1)}%`;
  document.getElementById("conversionExpected").textContent = `${s.expected.toFixed(1)}%`;
  const delta = +(s.conversion - s.expected).toFixed(1);
  const deltaEl = document.getElementById("conversionDelta");
  deltaEl.textContent = `${delta > 0 ? "+" : "−"}${Math.abs(delta).toFixed(1)} pp`;
  deltaEl.className = `delta ${delta < -5 ? "critical" : delta < -1 ? "warning" : "neutral"}`;
  document.getElementById("incidentCount").textContent = s.incidents.length;
  const incDelta = document.getElementById("incidentDelta");
  incDelta.textContent = s.incidents.length ? (s.incidents.length > 1 ? "Separated" : "Detected") : "Quiet";
  incDelta.className = `delta ${s.incidents.length ? (s.tone === "critical" ? "critical" : "warning") : "healthy"}`;
  document.getElementById("highestPriority").textContent = s.incidents.length ? s.incidents[0].priority : "—";
  document.getElementById("riskValue").textContent = money(risk);
  document.getElementById("riskConfidence").textContent = money(adjusted);
  document.getElementById("monitoredAttempts").textContent = formatCount(s.monitoredTraffic.attempts_total);
  document.getElementById("monitoredEntities").textContent = `${s.monitoredTraffic.merchants} / ${s.monitoredTraffic.providers}`;
  document.getElementById("timeLabels").innerHTML = s.timeLabels.map(t => `<span>${t}</span>`).join("");
  document.getElementById("statusTimestamp").textContent = s.lastUpdated
    ? `Updated ${formatStarted(s.lastUpdated)}`
    : "Updated just now";
  renderCountries(s.countries);
  renderMarketRoster(s.countries, s.incidents);
  renderIncidents(s.incidents);
  renderChart(s.chart, s.expectedChart, s.marker);
  renderAnnunciators(s.incidents);
}

function renderAnnunciators(incidentList) {
  const warningCount = incidentList.filter(i => i.severity === "CRITICAL").length;
  const cautionCount = incidentList.filter(i => i.severity !== "CRITICAL").length;
  const warningEl = document.getElementById("beaconWarning");
  const cautionEl = document.getElementById("beaconCaution");
  warningEl.classList.toggle("is-lit", warningCount > 0);
  cautionEl.classList.toggle("is-lit", cautionCount > 0);
  warningEl.setAttribute("aria-pressed", String(warningCount > 0));
  cautionEl.setAttribute("aria-pressed", String(cautionCount > 0));
  document.getElementById("warningCount").textContent = warningCount;
  document.getElementById("cautionCount").textContent = cautionCount;
}

function renderCountries(countries) {
  const names = {MX:"mx",CO:"co",BR:"br"};
  Object.entries(countries).forEach(([code,[status,value]]) => {
    const node = document.querySelector(`[data-country="${code}"]`);
    node.className = `country-node ${code === "MX" ? "mexico" : code === "CO" ? "colombia" : "brazil"} ${status === "healthy" ? "" : status}`;
    document.getElementById(`${names[code]}Status`).textContent = status === "healthy" ? "HEALTHY" : status === "critical" ? "CRITICAL" : "INVESTIGATING";
    document.getElementById(`${names[code]}Metric`).textContent = `Country conversion ${value.toFixed(1)}%`;
  });
}

const COUNTRY_NAMES = { MX: "Mexico", CO: "Colombia", BR: "Brazil" };

function renderMarketRoster(countries, incidentList) {
  document.getElementById("marketDetail").hidden = true;
  document.getElementById("marketRoster").hidden = false;
  const el = document.getElementById("marketRoster");
  el.innerHTML = Object.entries(countries).map(([code, [status, value]]) => {
    const hit = incidentList.find(x => x.country === code);
    const cls = status === "critical" ? "is-critical" : status === "warning" ? "is-caution" : "";
    const statusText = hit ? `${hit.priority} · ${hit.severity}` : "Healthy";
    const riskText = hit ? `${money(hit.risk)}/h` : `${value.toFixed(1)}%`;
    return `<button class="market-row ${cls}" data-country="${code}">
      <span class="market-row-id"><span class="market-row-dot"></span><span class="market-row-name">${COUNTRY_NAMES[code]}</span><span class="market-row-status">${statusText}</span></span>
      <span class="market-row-risk">${riskText}</span><span class="market-row-arrow">→</span>
    </button>`;
  }).join("");
}

function showCountry(code) {
  const s = currentView();
  const hit = s.incidents.find(i => i.country === code);
  const value = s.countries[code][1];
  const roster = document.getElementById("marketRoster");
  const detail = document.getElementById("marketDetail");
  roster.hidden = true;
  detail.hidden = false;
  const body = hit
    ? `<div class="market-incident ${hit.priority === "P1" ? "" : "is-caution"}">
        <h5>${hit.title}</h5>
        <p class="market-segment-note">Affected segment</p>
        <div class="market-fields">
          <div><span>Method</span><strong>${hit.method}</strong></div>
          <div><span>Merchants</span><strong>${hit.merchants}</strong></div>
          <div><span>Expected</span><strong>${hit.expected.toFixed(1)}%</strong></div>
          <div><span>Actual</span><strong>${hit.actual.toFixed(1)}%</strong></div>
          <div><span>Drop</span><strong>−${(hit.expected - hit.actual).toFixed(1)}pp</strong></div>
          <div><span>Started</span><strong>${hit.started}</strong></div>
          <div><span>Confidence</span><strong>${hit.confidence}%</strong></div>
          <div><span>GMV at risk</span><strong>${money(hit.risk)}/h</strong></div>
        </div>
        <button class="market-view-btn" id="marketViewIncident">View investigation →</button>
      </div>`
    : `<div class="market-empty">Healthy — no significant incidents. Country conversion ${value.toFixed(1)}%, within its own historical baseline.</div>`;
  detail.innerHTML = `<div class="market-detail-head"><h4>${COUNTRY_NAMES[code]}</h4><button class="market-back" id="marketBack" aria-label="Back to network overview">←</button></div>${body}`;
  document.getElementById("marketBack").addEventListener("click", () => { detail.hidden = true; roster.hidden = false; });
  const viewBtn = document.getElementById("marketViewIncident");
  if (viewBtn) viewBtn.addEventListener("click", () => openDrawer(hit));
}

function renderIncidents(list) {
  const el = document.getElementById("incidentList");
  if (!list.length) {
    el.innerHTML = `<div class="empty-state"><div><div class="empty-icon">✓</div><h3>No incidents require attention</h3><p>PRSM is monitoring 50,000 payment attempts without firing on normal statistical noise.</p></div></div>`;
    return;
  }
  el.innerHTML = list.map(i => `<button class="incident-card" data-incident="${i.id}">
    <div class="incident-top"><span class="priority-tag ${i.priority === "P1" ? "" : "warning"}">${i.priority} · ${i.severity}</span><span class="incident-time">Since ${i.started}</span></div>
    <h3>${i.title}</h3><p>${i.subtitle}</p>
    <div class="incident-metrics"><span>Drop<strong>−${(i.expected-i.actual).toFixed(1)} pp</strong></span><span>Confidence<strong>${i.confidence}%</strong></span><span>GMV risk<strong>${money(i.risk)}/h</strong></span><span class="incident-arrow">→</span></div>
  </button>`).join("");
  el.querySelectorAll("[data-incident]").forEach(button => button.addEventListener("click", () => {
    const item = list.find(i => i.id === button.dataset.incident); openDrawer(item);
  }));
}

function fillGaps(arr, fallback) {
  let last = arr.find(v => v !== null && v !== undefined);
  if (last === undefined) last = fallback;
  return arr.map(v => { if (v === null || v === undefined) return last; last = v; return v; });
}

function renderAxisLabels(max, min) {
  const steps = [0, .25, .5, .75, 1];
  document.getElementById("axisLabels").innerHTML = steps
    .map(step => `<span>${Math.round(max - step * (max - min))}%</span>`)
    .join("");
}

function renderChart(rawActual, rawExpected, marker) {
  const svg = document.getElementById("conversionChart");
  if (!rawActual || rawActual.length < 2) { svg.innerHTML = ""; renderAxisLabels(95, 55); return; }
  const width=1200, height=250;
  const actual = fillGaps(rawActual, 75);
  const expected = rawExpected && rawExpected.length === actual.length ? fillGaps(rawExpected, 75) : actual;
  const dataMin = Math.min(...actual, ...expected);
  const dataMax = Math.max(...actual, ...expected);
  const padding = Math.max((dataMax - dataMin) * 0.3, 2);
  const min = Math.max(0, Math.floor(dataMin - padding));
  const max = Math.min(100, Math.ceil(dataMax + padding));
  renderAxisLabels(max, min);
  const x = i => i*(width/(actual.length-1)); const y = v => height-((v-min)/(max-min))*height;
  const points = arr => arr.map((v,i)=>`${x(i)},${y(v)}`).join(" ");
  const area = `0,${height} ${points(actual)} ${width},${height}`;
  const grids = [0,.25,.5,.75,1].map(p=>`<line class="chart-grid" x1="0" y1="${p*height}" x2="${width}" y2="${p*height}"/>`).join("");
  const markerSvg = marker !== undefined ? `<line class="incident-line" x1="${x(marker)}" y1="0" x2="${x(marker)}" y2="${height}"/><text class="chart-label" x="${x(marker)+8}" y="15">INCIDENT DETECTED</text>` : "";
  svg.innerHTML = `<defs><linearGradient id="areaGradient" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#ffffff" stop-opacity="0"/></linearGradient></defs>${grids}<polygon class="area-path" points="${area}"/><polyline class="expected-path" points="${points(expected)}"/><polyline class="actual-path" points="${points(actual)}"/>${markerSvg}<circle class="chart-point" cx="${x(actual.length-1)}" cy="${y(actual[actual.length-1])}" r="5"/>`;
}

function renderTreeNode(node) {
  const stateClass = node.state ? `state-${node.state}` : "";
  const tag = node.state === "root" ? "ROOT CAUSE" : node.state === "anomaly" ? "ANOMALY" : node.state === "hypothesis" ? `HYPOTHESIS · ${node.pct}%` : "";
  const label = `<span class="tree-label ${stateClass}">${node.label}</span>${tag ? `<span class="tree-tag">${tag}</span>` : ""}`;
  if (!node.children || !node.children.length) return `<li>${label}</li>`;
  return `<li>${label}<ul>${node.children.map(renderTreeNode).join("")}</ul></li>`;
}
function renderTree(root) {
  if (!root || !root.children) return "";
  return `<div class="tree-root">${root.label}</div><ul class="tree">${root.children.map(renderTreeNode).join("")}</ul>`;
}

const REVIEW_STATUS_LABELS = { proposed: "Proposed", modified: "Modified", approved: "Approved", rejected: "Rejected", executed: "Executed" };
const REVIEW_ACTIONS_BY_STATUS = {
  proposed: [["approve", "Approve"], ["modify", "Modify"], ["reject", "Reject"]],
  modified: [["approve", "Approve"], ["modify", "Modify"], ["reject", "Reject"]],
  approved: [["execute", "Execute"], ["modify", "Modify"], ["reject", "Reject"]]
};

function getSavedReviewer() {
  try { return localStorage.getItem("controlTowerReviewer") || ""; } catch (error) { return ""; }
}

function buildHumanDecisionHtml(i) {
  const status = i.recommendationStatus || "proposed";
  const statusLine = `<div class="review-status">Status: <strong>${REVIEW_STATUS_LABELS[status] || status}</strong>${i.reviewedBy ? ` · last reviewed by ${i.reviewedBy}` : ""}</div>`;
  const actions = REVIEW_ACTIONS_BY_STATUS[status] || [];
  if (!actions.length) return `<h3>HUMAN DECISION</h3>${statusLine}`;

  const modifying = state.reviewUi.modifying;
  const fields = `
    <label class="review-field"><span>Your name</span><input type="text" id="reviewerInput" placeholder="e.g. Ana Ruiz" value="${getSavedReviewer()}"></label>
    <label class="review-field"><span>Comment (optional)</span><input type="text" id="reviewerComment" placeholder="Add context for the audit log"></label>
    ${modifying ? `<label class="review-field"><span>Modified action</span><textarea id="modifiedActionInput" rows="3">${i.playbookAction || i.recommendation || ""}</textarea></label>` : ""}`;
  const buttonRow = modifying
    ? `<div class="drawer-actions"><button class="drawer-action" data-review-cancel="1">Cancel</button><button class="drawer-action primary" data-review-action="modify">Save modification</button></div>`
    : `<div class="drawer-actions">${actions.map(([action, label]) => `<button class="drawer-action ${action === "reject" ? "" : "primary"}" data-review-action="${action}">${label}</button>`).join("")}</div>`;
  return `<h3>HUMAN DECISION</h3>${statusLine}${fields}${buttonRow}`;
}

function renderHumanDecision(i) {
  const section = document.getElementById("humanDecisionSection");
  if (!section) return;
  section.innerHTML = buildHumanDecisionHtml(i);
  section.querySelectorAll("[data-review-action]").forEach(button => {
    button.addEventListener("click", () => {
      const action = button.dataset.reviewAction;
      if (action === "modify" && !state.reviewUi.modifying) {
        state.reviewUi.modifying = true;
        renderHumanDecision(i);
        return;
      }
      submitReview(i, action);
    });
  });
  const cancelButton = section.querySelector("[data-review-cancel]");
  if (cancelButton) cancelButton.addEventListener("click", () => { state.reviewUi.modifying = false; renderHumanDecision(i); });
}

async function submitReview(i, action) {
  const reviewerInput = document.getElementById("reviewerInput");
  const commentInput = document.getElementById("reviewerComment");
  const modifiedInput = document.getElementById("modifiedActionInput");
  const reviewer = reviewerInput ? reviewerInput.value.trim() : "";
  if (reviewer.length < 2) {
    showToast("Enter your name to record this decision");
    if (reviewerInput) reviewerInput.focus();
    return;
  }
  if (action === "modify" && (!modifiedInput || !modifiedInput.value.trim())) {
    showToast("Enter the modified action text");
    if (modifiedInput) modifiedInput.focus();
    return;
  }
  try { localStorage.setItem("controlTowerReviewer", reviewer); } catch (error) { /* private browsing or storage disabled */ }

  const body = { action, reviewer };
  if (commentInput && commentInput.value.trim()) body.comment = commentInput.value.trim();
  if (action === "modify") body.modified_primary_action = modifiedInput.value.trim();

  const submitButton = document.querySelector(`[data-review-action="${action}"]`);
  const originalLabel = submitButton ? submitButton.textContent : "";
  if (submitButton) { submitButton.disabled = true; submitButton.textContent = "Submitting…"; }

  try {
    const response = await fetch(`${API_URL}/incidents/${i.id}/review`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    state.reviewUi.modifying = false;
    showToast(`Decision recorded: ${action}`);
    await fetchLive();
    const updated = state.liveData && state.liveData.incidents.find(inc => inc.id === i.id);
    if (updated) openDrawer(updated); else closeDrawer();
  } catch (error) {
    showToast(error.message || "Could not record the decision");
    if (submitButton) { submitButton.disabled = false; submitButton.textContent = originalLabel; }
  }
}

function openDrawer(i) {
  if (!i) return;
  state.selectedIncident = i;
  document.getElementById("drawerId").textContent = `${i.id} · Started ${i.started}`;
  const rootCauseHeading = i.incidentType ? `ROOT CAUSE · ${i.incidentType}` : "ROOT CAUSE";
  const rootCauseBody = i.tree ? renderTree(i.tree) : `<div class="tree-root">${i.root}</div>`;
  document.getElementById("drawerContent").innerHTML = `
    <div class="drawer-title-row"><span class="severity-label ${i.priority === "P1" ? "" : "warning"}">${i.priority} · ${i.severity}</span><h2>${i.title}</h2><p>${i.affected}</p></div>
    <div class="executive-summary"><span class="eyebrow">EXECUTIVE SUMMARY</span><br>${i.executive}</div>
    <div class="drawer-section"><h3>${rootCauseHeading}</h3>${rootCauseBody}</div>
    <div class="drawer-section"><h3>EVIDENCE</h3><div class="evidence-list">${i.evidence.map(e=>`<div class="evidence-item"><span class="evidence-check">✓</span><span>${e}</span></div>`).join("")}</div></div>
    <div class="drawer-section"><h3>PRIORITY</h3><span class="severity-label ${i.priority === "P1" ? "" : "warning"}">${i.priorityLabel || `${i.priority} · ${i.severity}`}</span><p class="priority-summary">${money(i.risk)}/h at risk · ${i.confidence}% confidence${i.priorityCriteria ? ` — ${i.priorityCriteria}` : ""}</p></div>
    <div class="drawer-section"><h3>OPERATIONAL PLAYBOOK</h3><div class="metric-grid"><div class="metric-pair"><span>Owner</span><strong>${i.operationalOwner || "—"}</strong></div><div class="metric-pair"><span>Escalation</span><strong>${i.escalationLevel || "—"}</strong></div></div><div class="recommendation"><strong>Recommended action</strong><br>${i.playbookAction || i.recommendation}</div></div>
    <div class="drawer-section"><h3>OBSERVED VS EXPECTED · AFFECTED SEGMENT</h3><div class="conversion-compare"><div><span>Expected</span><strong>${i.expected.toFixed(1)}%</strong></div><span class="compare-arrow">→</span><div class="drop-value"><span>Observed</span><strong>${i.actual.toFixed(1)}%</strong></div></div></div>
    <div class="drawer-section"><h3>ECONOMIC IMPACT</h3><div class="metric-grid"><div class="metric-pair"><span>GMV at risk</span><strong>${money(i.risk)}/h</strong></div><div class="metric-pair"><span>Recoverable</span><strong>${i.recovery}</strong></div><div class="metric-pair"><span>Affected attempts</span><strong>${i.attempts.toLocaleString()}</strong></div><div class="metric-pair"><span>Excess declines</span><strong>${i.excess.toLocaleString()}</strong></div></div></div>
    <div class="drawer-section"><h3>DIAGNOSIS CONFIDENCE</h3><div class="confidence-head"><span>${i.root}</span><strong>${i.confidence}%</strong></div><div class="confidence-track"><div class="confidence-fill ${i.confidence < 60 ? "warning" : ""}" style="width:${i.confidence}%"></div></div><div class="attribution"><div class="attribution-label"><span>Conversion loss explained</span><strong>${i.attribution}%</strong></div><div class="confidence-track"><div class="confidence-fill ${i.attribution < 60 ? "warning" : ""}" style="width:${i.attribution}%"></div></div></div></div>
    <div class="drawer-section" id="humanDecisionSection"></div>`;
  state.reviewUi = { modifying: false };
  renderHumanDecision(i);
  document.getElementById("drawerBackdrop").hidden = false;
  document.getElementById("detailDrawer").classList.add("is-open");
  document.getElementById("detailDrawer").setAttribute("aria-hidden","false");
}

function closeDrawer() {
  document.getElementById("detailDrawer").classList.remove("is-open");
  document.getElementById("detailDrawer").setAttribute("aria-hidden","true");
  setTimeout(()=>{ document.getElementById("drawerBackdrop").hidden = true; }, 240);
}

let toastTimer;
function showToast(message) { const t=document.getElementById("toast"); t.textContent=message; t.classList.add("show"); clearTimeout(toastTimer); toastTimer=setTimeout(()=>t.classList.remove("show"),2200); }
function updateClock() { document.getElementById("clock").textContent = new Date().toLocaleTimeString("en-GB", {hour12:false}); }

/* ============ GLOBE — orthographic 3D projection, no dependencies ============ */
const Globe = (() => {
  const canvas = document.getElementById("globeCanvas");
  const stage = document.getElementById("mapStage");
  const ctx = canvas.getContext("2d");
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const nodeEls = { MX: document.querySelector('[data-country="MX"]'), CO: document.querySelector('[data-country="CO"]'), BR: document.querySelector('[data-country="BR"]') };
  const NODES = { MX: { lat: 23, lng: -102 }, CO: { lat: 4, lng: -72 }, BR: { lat: -18, lng: -47 } };
  const BASE_LNG = 78; // rotates the sphere so the LATAM band faces the camera at rest
  const SWING = 26;    // gentle turntable swing, in degrees, keeps all three nodes always in view

  const css = getComputedStyle(document.documentElement);
  function hexToRgba(hex, a) {
    const h = hex.trim().replace("#", "");
    const r = parseInt(h.substring(0, 2), 16), g = parseInt(h.substring(2, 4), 16), b = parseInt(h.substring(4, 6), 16);
    return `rgba(${r},${g},${b},${a})`;
  }
  const STATUS_COLOR = {
    nominal: css.getPropertyValue("--nominal").trim() || "#c7c7c7",
    caution: css.getPropertyValue("--caution").trim() || "#ffb224",
    warning: css.getPropertyValue("--warning").trim() || "#ff3b3b"
  };
  function countryStatus(code) {
    const el = nodeEls[code];
    if (el && el.classList.contains("critical")) return "warning";
    if (el && el.classList.contains("warning")) return "caution";
    return "nominal";
  }

  let radius = 0, cx = 0, cy = 0;

  function project(lat, lng, rotation) {
    const phi = lat * Math.PI / 180;
    const lambda = (lng + rotation) * Math.PI / 180;
    const x = Math.cos(phi) * Math.sin(lambda);
    const y = Math.sin(phi);
    const z = Math.cos(phi) * Math.cos(lambda);
    return { x: cx + x * radius, y: cy - y * radius, z, front: z > 0.02 };
  }

  function resize() {
    const rect = stage.getBoundingClientRect();
    const size = Math.floor(Math.min(rect.width, rect.height) * 0.86);
    const dpr = window.devicePixelRatio || 1;
    canvas.style.width = size + "px";
    canvas.style.height = size + "px";
    canvas.width = Math.round(size * dpr);
    canvas.height = Math.round(size * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    radius = size / 2 - 2;
    cx = size / 2; cy = size / 2;
  }

  function drawArc(latFixed, lngFixed, rotation, mode) {
    ctx.beginPath();
    let started = false;
    const step = 4;
    const range = mode === "meridian" ? [-90, 90] : [0, 360];
    for (let v = range[0]; v <= range[1]; v += step) {
      const p = mode === "meridian" ? project(v, lngFixed, rotation) : project(latFixed, v, rotation);
      if (p.front) { if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y); }
      else started = false;
    }
    ctx.stroke();
  }

  // ring = [[lng,lat], ...]; draws only the front-facing arcs of the outline
  function drawRing(ring, rotation) {
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < ring.length; i++) {
      const p = project(ring[i][1], ring[i][0], rotation);
      if (p.front) { if (!started) { ctx.moveTo(p.x, p.y); started = true; } else ctx.lineTo(p.x, p.y); }
      else started = false;
    }
    ctx.stroke();
  }

  function ringAllFront(ring, rotation) {
    for (let i = 0; i < ring.length; i++) if (!project(ring[i][1], ring[i][0], rotation).front) return false;
    return true;
  }

  function fillRing(ring, rotation, fillStyle) {
    ctx.beginPath();
    for (let i = 0; i < ring.length; i++) {
      const p = project(ring[i][1], ring[i][0], rotation);
      if (i === 0) ctx.moveTo(p.x, p.y); else ctx.lineTo(p.x, p.y);
    }
    ctx.closePath();
    ctx.fillStyle = fillStyle;
    ctx.fill();
  }

  function draw(rotation) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    const shade = ctx.createRadialGradient(cx - radius * 0.35, cy - radius * 0.35, radius * 0.08, cx, cy, radius);
    shade.addColorStop(0, "#1e1e1e");
    shade.addColorStop(1, "#050505");
    ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.fillStyle = shade; ctx.fill();

    ctx.lineWidth = 1;
    ctx.strokeStyle = "rgba(255,255,255,.08)";
    for (let lng = 0; lng < 360; lng += 30) drawArc(0, lng, rotation, "meridian");
    for (let lat = -60; lat <= 60; lat += 30) drawArc(lat, 0, rotation, "parallel");
    ctx.strokeStyle = "rgba(255,255,255,.15)";
    drawArc(0, 0, rotation, "parallel");

    ctx.lineWidth = 0.75;
    ctx.strokeStyle = "rgba(236,236,236,.4)";
    WORLD.land.forEach(ring => drawRing(ring, rotation));

    Object.entries(WORLD.countries).forEach(([code, rings]) => {
      const status = countryStatus(code);
      const color = STATUS_COLOR[status];
      rings.forEach(ring => {
        if (status !== "nominal" && ringAllFront(ring, rotation)) fillRing(ring, rotation, hexToRgba(color, 0.14));
        ctx.lineWidth = status === "nominal" ? 1.1 : 1.6;
        ctx.strokeStyle = status === "nominal" ? "rgba(236,236,236,.75)" : color;
        drawRing(ring, rotation);
      });
    });

    ctx.strokeStyle = "rgba(255,255,255,.16)";
    ctx.beginPath(); ctx.arc(cx, cy, radius, 0, Math.PI * 2); ctx.stroke();

    const canvasRect = canvas.getBoundingClientRect();
    const stageRect = stage.getBoundingClientRect();
    const offX = canvasRect.left - stageRect.left, offY = canvasRect.top - stageRect.top;
    Object.entries(NODES).forEach(([code, n]) => {
      const p = project(n.lat, n.lng, rotation);
      const el = nodeEls[code];
      if (!el) return;
      el.style.transform = `translate(${(offX + p.x).toFixed(1)}px, ${(offY + p.y).toFixed(1)}px)`;
      el.style.opacity = p.front ? "1" : "0";
      el.style.pointerEvents = p.front ? "auto" : "none";
      el.classList.toggle("flip-label", p.x > radius * 0.15);
    });
  }

  function frame(now) {
    const rotation = BASE_LNG + (reduceMotion ? 0 : Math.sin(now * 0.00022) * SWING);
    draw(rotation);
    if (!reduceMotion) requestAnimationFrame(frame);
  }

  function start() {
    resize();
    requestAnimationFrame(frame);
    let resizeTimer;
    window.addEventListener("resize", () => { clearTimeout(resizeTimer); resizeTimer = setTimeout(() => { resize(); draw(BASE_LNG); }, 120); });
  }

  return { start };
})();
Globe.start();

document.querySelectorAll(".country-node[data-country]").forEach(b=>b.addEventListener("click",()=>showCountry(b.dataset.country)));
document.getElementById("marketRoster").addEventListener("click", e => { const b = e.target.closest("[data-country]"); if (b) showCountry(b.dataset.country); });
document.getElementById("beaconWarning").addEventListener("click", () => { if (document.getElementById("beaconWarning").classList.contains("is-lit")) showToast("Critical signal acknowledged"); });
document.getElementById("beaconCaution").addEventListener("click", () => { if (document.getElementById("beaconCaution").classList.contains("is-lit")) showToast("Caution signal acknowledged"); });
document.getElementById("closeDrawer").addEventListener("click",closeDrawer);
document.getElementById("drawerBackdrop").addEventListener("click",closeDrawer);
document.addEventListener("keydown",e=>{ if(e.key==="Escape") closeDrawer(); });
setInterval(updateClock, 1000);
updateClock();
render();
startLivePolling();
