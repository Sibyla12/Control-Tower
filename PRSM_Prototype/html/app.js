// When the dashboard is served from localhost/127.0.0.1 (e.g. by run_demo.sh),
// talk to the locally running backend instead of the deployed one — this keeps
// the local "trial by fire" demo fast and working offline, while a publicly
// hosted copy of this page still defaults to the deployed API.
const API_URL = ["localhost", "127.0.0.1"].includes(window.location.hostname)
  ? "http://localhost:8000"
  : "https://control-tower-vl22.onrender.com";
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
  if (apiIncident.root_cause_type === "decline_code") {
    return `${apiIncident.country} › ${apiIncident.dominant_decline_code}`;
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
  if (apiIncident.root_cause_type === "decline_code") {
    return { label: apiIncident.country, children: [{
      label: apiIncident.dominant_decline_code, state: "root", children: [
        { label: `Banks: ${pipeToText(apiIncident.affected_banks, "multiple")}`, state: "anomaly" },
        { label: `Merchants: ${pipeToText(apiIncident.affected_merchants, "multiple")}`, state: "anomaly" }
      ]
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
  if (apiIncident.root_cause_type === "decline_code") {
    evidence[1] = `${apiIncident.dominant_decline_code} spans ${pipeToText(apiIncident.affected_banks, "multiple banks")} and ${pipeToText(apiIncident.affected_merchants, "multiple merchants")} — no single provider or bank explains it alone.`;
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
      : apiIncident.root_cause_type === "decline_code"
        ? `${apiIncident.dominant_decline_code} spike, root cause not yet isolated`
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
    expectedAttention: apiIncident.expected_attention,
    mttrHours: apiIncident.mttr_assumption_hours,
    projections: apiIncident.projections || [],
    dataQuality: apiIncident.data_quality,
    baselineSource: apiIncident.baseline_source,
    baselineReliableShare: apiIncident.baseline_reliable_share,
    baselineHistoricalAttempts: apiIncident.baseline_historical_attempts,
    rank: null,
    cumulativePct: null,
    isRepeatIncident: apiIncident.is_repeat_incident,
    repeatOccurrenceCount: apiIncident.repeat_occurrence_count,
    repeatFirstSeenAt: apiIncident.repeat_first_seen_at,
    repeatLastSeenAt: apiIncident.repeat_last_seen_at
  };
}

function withAsOf(path, asOf) {
  return asOf ? `${API_URL}${path}?as_of=${encodeURIComponent(asOf)}` : `${API_URL}${path}`;
}

async function loadLiveIncidents(asOf) {
  const response = await fetch(withAsOf("/incidents", asOf));
  if (!response.ok) throw new Error(`Control Tower API returned ${response.status}`);
  const payload = await response.json();
  return payload.incidents.map(mapApiIncident);
}

async function loadDashboard(asOf) {
  const response = await fetch(withAsOf("/dashboard", asOf));
  if (!response.ok) throw new Error(`Control Tower API returned ${response.status}`);
  return response.json();
}

function mapUnresolvedCandidate(raw) {
  const candidate = { ...raw };
  for (const key of Object.keys(candidate)) candidate[key] = humanizeMerchant(candidate[key]);
  const suspects = [candidate.provider, candidate.issuing_bank, candidate.merchant, candidate.payment_method]
    .filter(Boolean)
    .map(value => pipeToText(value, value));
  return {
    id: candidate.incident_id,
    country: candidate.country,
    incidentType: candidate.incident_type,
    declineCode: candidate.dominant_decline_code,
    confidence: Math.round(candidate.confidence_score * 100),
    confidenceLevel: candidate.confidence_level,
    started: formatStarted(candidate.start_time),
    dropPoints: candidate.approval_rate_drop * 100,
    suspects: suspects.length ? suspects.join(" · ") : "not isolated to one dimension"
  };
}

async function loadUnresolvedCandidates(asOf) {
  const response = await fetch(withAsOf("/unresolved-candidates", asOf));
  if (!response.ok) throw new Error(`Control Tower API returned ${response.status}`);
  const payload = await response.json();
  return payload.candidates.map(mapUnresolvedCandidate);
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

function applyRiskRanking(liveIncidents, riskRanking) {
  const rankById = {};
  (riskRanking || []).forEach(r => { rankById[r.consolidated_incident_id] = r; });
  liveIncidents.forEach(incident => {
    const rank = rankById[incident.id];
    incident.rank = rank ? rank.rank : null;
    incident.cumulativePct = rank ? rank.cumulative_pct : null;
  });
}

function buildLiveScenario(dashboard, liveIncidents, unresolvedCandidates) {
  applyRiskRanking(liveIncidents, dashboard.risk_ranking);
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
    unresolvedCandidates,
    countries,
    monitoredTraffic: dashboard.monitored_traffic,
    executiveSummary: dashboard.executive_summary || EMPTY_EXECUTIVE_SUMMARY,
    riskConcentration: dashboard.risk_concentration || [],
    lastUpdated: dashboard.last_updated,
    marker: findMarkerIndex(history, liveIncidents)
  };
}

const EMPTY_EXECUTIVE_SUMMARY = {
  active_incident_count: 0, total_gmv_at_risk_usd: 0, total_gmv_at_risk_adjusted_usd: 0,
  total_platform_revenue_at_risk_usd: 0, total_merchant_economic_impact_usd: 0, total_economic_impact_usd: 0
};

function connectingScenario() {
  return {
    tone: "healthy", pill: "CONNECTING…", title: "Connecting to the live payment network",
    description: "Fetching current incidents and conversion data from Control Tower.",
    conversion: 0, expected: 0, chart: [], expectedChart: [], timeLabels: [],
    incidents: [], unresolvedCandidates: [], countries: { MX: ["healthy", 0], CO: ["healthy", 0], BR: ["healthy", 0] },
    monitoredTraffic: { attempts_total: 0, merchants: 0, providers: 0 }, executiveSummary: EMPTY_EXECUTIVE_SUMMARY, marker: undefined
  };
}

function liveErrorScenario(message) {
  return {
    tone: "warning", pill: "LIVE DATA UNAVAILABLE", title: "Could not reach the Control Tower API",
    description: message,
    conversion: 0, expected: 0, chart: [], expectedChart: [], timeLabels: [],
    incidents: [], unresolvedCandidates: [], countries: { MX: ["healthy", 0], CO: ["healthy", 0], BR: ["healthy", 0] },
    monitoredTraffic: { attempts_total: 0, merchants: 0, providers: 0 }, executiveSummary: EMPTY_EXECUTIVE_SUMMARY, marker: undefined
  };
}

const QUIET_PERIOD_AS_OF = "2026-08-31T10:02:00";

const state = { selectedIncident: null, liveData: null, liveError: null, liveTimer: null, reviewUi: { modifying: false }, asOf: null };

function getStoredViewMode() {
  try { return localStorage.getItem("prsm_view_mode") === "executive" ? "executive" : "analyst"; }
  catch (error) { return "analyst"; }
}

function applyViewMode(mode) {
  const isExecutive = mode === "executive";
  document.body.classList.toggle("view-executive", isExecutive);
  const toggle = document.getElementById("viewModeToggle");
  toggle.classList.toggle("is-active", isExecutive);
  toggle.setAttribute("aria-pressed", String(isExecutive));
  toggle.textContent = isExecutive ? "Executive view" : "Analyst view";
  try { localStorage.setItem("prsm_view_mode", mode); } catch (error) { /* per-viewer convenience only */ }
}

function setTimeView(view) {
  state.asOf = view === "quiet" ? QUIET_PERIOD_AS_OF : null;
  document.querySelectorAll("#timeViewToggle [data-view]").forEach(b => b.classList.toggle("is-active", b.dataset.view === view));
  state.liveData = null;
  closeDrawer();
  render();
  fetchLive();
}

function money(value) {
  if (value >= 1000000) return `$${(value / 1000000).toFixed(1)}M`;
  if (value >= 1000) return `$${(value / 1000).toFixed(1)}K`;
  return `$${Math.round(value)}`;
}
function formatCount(value) { return value >= 1000 ? `${(value/1000).toFixed(1)}K` : `${Math.round(value)}`; }

function currentView() {
  if (state.liveData) return state.liveData;
  if (state.liveError) return liveErrorScenario(state.liveError);
  return connectingScenario();
}

async function fetchLive() {
  try {
    const asOf = state.asOf;
    const [dashboard, liveIncidents, unresolvedCandidates] = await Promise.all([
      loadDashboard(asOf), loadLiveIncidents(asOf), loadUnresolvedCandidates(asOf)
    ]);
    const hadError = Boolean(state.liveError);
    state.liveData = buildLiveScenario(dashboard, liveIncidents, unresolvedCandidates);
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
  renderUnresolved(s.unresolvedCandidates || []);
  renderExecutiveSummary(s.executiveSummary || EMPTY_EXECUTIVE_SUMMARY);
  renderRiskConcentration(s.riskConcentration || []);
  renderChart(s.chart, s.expectedChart, s.marker);
  renderAnnunciators(s.incidents);
}

function renderExecutiveSummary(summary) {
  document.getElementById("execTotalImpact").textContent = money(summary.total_economic_impact_usd);
  document.getElementById("execIncidentCount").textContent = summary.active_incident_count;
  document.getElementById("execGmvAdjusted").textContent = money(summary.total_gmv_at_risk_adjusted_usd);
  document.getElementById("execGmvGross").textContent = money(summary.total_gmv_at_risk_usd);
  document.getElementById("execPlatformRisk").textContent = money(summary.total_platform_revenue_at_risk_usd);
  document.getElementById("execMerchantImpact").textContent = money(summary.total_merchant_economic_impact_usd);
}

const RISK_DIMENSION_LABELS = {
  root_cause_type: "Root cause", country: "Country", provider: "Provider",
  issuing_bank: "Issuing bank", payment_method: "Method", decline_code: "Decline code"
};
const RISK_DIMENSION_ORDER = ["root_cause_type", "country", "provider", "issuing_bank", "payment_method", "decline_code"];

function renderRiskConcentration(signals) {
  const el = document.getElementById("riskConcentration");
  if (!signals.length) { el.innerHTML = ""; return; }
  const byDimension = {};
  signals.forEach(s => { (byDimension[s.dimension] = byDimension[s.dimension] || []).push(s); });
  const rows = RISK_DIMENSION_ORDER.filter(dim => byDimension[dim]).map(dim => {
    const chips = byDimension[dim].map(s => `<span class="risk-chip">${humanizeMerchant(s.value)}<strong>${Math.round(s.concentration_pct * 100)}%</strong></span>`).join("");
    return `<div class="risk-dim-row"><span class="risk-dim-label">${RISK_DIMENSION_LABELS[dim] || dim}</span><span class="risk-dim-chips">${chips}</span></div>`;
  }).join("");
  el.innerHTML = `<div class="risk-concentration-heading">Where the current GMV at risk concentrates — diagnostic signal, not the confirmed root cause</div>${rows}`;
}

function renderUnresolved(list) {
  document.getElementById("unresolvedCount").textContent = `${list.length} candidate${list.length === 1 ? "" : "s"}`;
  const el = document.getElementById("unresolvedList");
  if (!list.length) {
    el.innerHTML = `<div class="unresolved-empty">No open anomalies are waiting on more evidence right now.</div>`;
    return;
  }
  el.innerHTML = list.map(c => `<div class="unresolved-card">
    <div class="unresolved-top"><span class="unresolved-tag">${c.confidenceLevel} confidence · ${c.confidence}%</span><span class="unresolved-confidence">Since ${c.started}</span></div>
    <h4 class="unresolved-title">${c.incidentType} suspected in ${c.country} — ${c.declineCode}</h4>
    <p class="unresolved-note">Approval rate is ${c.dropPoints.toFixed(1)} pp below baseline, concentrated around ${c.suspects}, but the evidence isn't strong enough yet to name a confirmed root cause. Control Tower is continuing to monitor rather than guess.</p>
  </div>`).join("");
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
    <p class="exec-recommendation"><strong>Recommendation</strong> ${i.playbookAction || i.recommendation || "—"}</p>
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

async function generateAnalysis(incidentId) {
  const button = document.getElementById("generateAnalysisButton");
  const output = document.getElementById("aiAnalysisOutput");
  if (button) { button.disabled = true; button.textContent = "Analyzing…"; }
  try {
    const response = await fetch(`${API_URL}/incidents/${incidentId}/analysis`, { method: "POST" });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.detail || `Request failed (${response.status})`);
    if (output) { output.textContent = payload.analysis; output.hidden = false; }
    if (button) button.hidden = true;
  } catch (error) {
    showToast(error.message || "Could not generate analysis");
    if (button) { button.disabled = false; button.textContent = "Generate analysis"; }
  }
}

function horizonLabel(hours) {
  if (hours < 24) return `Next ${hours}h`;
  const days = Math.round(hours / 24);
  return days === 1 ? "Next 24h" : `Next ${days} days`;
}

function buildProjectionSection(i) {
  if (!i.projections || !i.projections.length) return "";
  const headerCells = i.projections.map(p => `<th>${horizonLabel(p.horizon_hours)}</th>`).join("");
  const atRiskCells = i.projections.map(p => `<td>${money(p.projected_gmv_at_risk_adjusted_usd)}</td>`).join("");
  const netCells = i.projections.map(p => `<td>${money(p.projected_net_impact_usd)}</td>`).join("");
  return `<div class="drawer-section"><h3>PROJECTED IMPACT IF UNRESOLVED</h3>
    <p class="priority-summary">Assumes a ${i.mttrHours}h average time to resolve — net impact plateaus once the incident is expected to be fixed rather than growing forever.</p>
    <table class="projection-table">
      <thead><tr><th></th>${headerCells}</tr></thead>
      <tbody>
        <tr><td>At risk</td>${atRiskCells}</tr>
        <tr><td>Net impact</td>${netCells}</tr>
      </tbody>
    </table>
  </div>`;
}

function formatDateTime(timestamp) {
  if (!timestamp) return "—";
  return new Date(timestamp).toLocaleString("en-GB", {
    day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", hour12: false
  });
}

function buildRepeatBanner(i) {
  if (!i.isRepeatIncident) return "";
  const times = i.repeatOccurrenceCount === 1 ? "time" : "times";
  return `<div class="repeat-banner">
    <span class="eyebrow">RECOGNIZED PATTERN</span><br>
    This same failure (root cause, dimensions, and decline code) has been seen ${i.repeatOccurrenceCount} prior ${times} — first recorded ${formatDateTime(i.repeatFirstSeenAt)}, most recently ${formatDateTime(i.repeatLastSeenAt)}.
  </div>`;
}

function renderSegmentBreakdown(segments) {
  const el = document.getElementById("segmentBreakdown");
  if (!el) return;
  if (!segments || !segments.length) {
    el.innerHTML = `<p class="priority-summary">No underlying segment breakdown available for this incident.</p>`;
    return;
  }
  const rows = segments.map(s => `<tr>
    <td>${humanizeMerchant(s.segment)}</td>
    <td>${s.attempts_in_scope.toLocaleString()}</td>
    <td>${s.expected_declines.toFixed(1)}</td>
    <td>${s.actual_declines.toLocaleString()}</td>
    <td>${s.excess_declines.toFixed(1)}</td>
    <td>${(s.contribution_pct * 100).toFixed(1)}%</td>
    <td>${(s.cumulative_pct * 100).toFixed(1)}%</td>
    <td>${s.confidence !== null && s.confidence !== undefined ? (s.confidence * 100).toFixed(1) + "%" : "—"}</td>
  </tr>`).join("");
  el.innerHTML = `<div class="segment-table-wrap"><table class="projection-table segment-table">
    <thead><tr><th>Segment</th><th>Attempts</th><th>Expected</th><th>Actual</th><th>Excess</th><th>Contrib.</th><th>Cumul.</th><th>Confidence</th></tr></thead>
    <tbody>${rows}</tbody>
  </table></div>`;
}

async function loadAndRenderSegments(incidentId) {
  try {
    const response = await fetch(`${API_URL}/incidents/${incidentId}/segments`);
    if (!response.ok) throw new Error(`Request failed (${response.status})`);
    const payload = await response.json();
    renderSegmentBreakdown(payload.segments);
  } catch (error) {
    const el = document.getElementById("segmentBreakdown");
    if (el) el.innerHTML = `<p class="priority-summary">Could not load segment breakdown.</p>`;
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
    ${buildRepeatBanner(i)}
    <div class="drawer-section" id="aiAnalysisSection">
      <h3>AI ANALYSIS</h3>
      <button class="drawer-action" id="generateAnalysisButton">Generate analysis</button>
      <div class="ai-analysis-output" id="aiAnalysisOutput" hidden></div>
    </div>
    <div class="drawer-section detail-only-section"><h3>${rootCauseHeading}</h3>${rootCauseBody}</div>
    <div class="drawer-section detail-only-section"><h3>EVIDENCE</h3><div class="evidence-list">${i.evidence.map(e=>`<div class="evidence-item"><span class="evidence-check">✓</span><span>${e}</span></div>`).join("")}</div></div>
    <div class="drawer-section"><h3>PRIORITY</h3><span class="severity-label ${i.priority === "P1" ? "" : "warning"}">${i.priorityLabel || `${i.priority} · ${i.severity}`}</span><p class="priority-summary">${money(i.risk)}/h at risk · ${i.confidence}% confidence${i.priorityCriteria ? ` — ${i.priorityCriteria}` : ""}</p>${i.rank ? `<p class="priority-summary">Rank ${i.rank} of the active incidents — explains ${Math.round(i.cumulativePct * 100)}% of total adjusted GMV at risk so far (cumulative).</p>` : ""}</div>
    <div class="drawer-section"><h3>OPERATIONAL PLAYBOOK</h3><div class="metric-grid"><div class="metric-pair"><span>Owner</span><strong>${i.operationalOwner || "—"}</strong></div><div class="metric-pair"><span>Escalation</span><strong>${i.escalationLevel || "—"}</strong></div></div><div class="recommendation"><strong>Recommended action</strong><br>${i.playbookAction || i.recommendation}</div></div>
    <div class="drawer-section detail-only-section"><h3>OBSERVED VS EXPECTED · AFFECTED SEGMENT</h3><div class="conversion-compare"><div><span>Expected</span><strong>${i.expected.toFixed(1)}%</strong></div><span class="compare-arrow">→</span><div class="drop-value"><span>Observed</span><strong>${i.actual.toFixed(1)}%</strong></div></div></div>
    <div class="drawer-section"><h3>ECONOMIC IMPACT</h3><div class="metric-grid"><div class="metric-pair"><span>GMV at risk</span><strong>${money(i.risk)}/h</strong></div><div class="metric-pair"><span>Recoverable</span><strong>${i.recovery}</strong></div><div class="metric-pair"><span>Affected attempts</span><strong>${i.attempts.toLocaleString()}</strong></div><div class="metric-pair"><span>Excess declines</span><strong>${i.excess.toLocaleString()}</strong></div></div></div>
    <div class="detail-only-section">${buildProjectionSection(i)}</div>
    <div class="drawer-section detail-only-section"><h3>DIAGNOSIS CONFIDENCE</h3><div class="confidence-head"><span>${i.root}</span><strong>${i.confidence}%</strong></div><div class="confidence-track"><div class="confidence-fill ${i.confidence < 60 ? "warning" : ""}" style="width:${i.confidence}%"></div></div><div class="attribution"><div class="attribution-label"><span>Conversion loss explained</span><strong>${i.attribution}%</strong></div><div class="confidence-track"><div class="confidence-fill ${i.attribution < 60 ? "warning" : ""}" style="width:${i.attribution}%"></div></div></div>${i.dataQuality ? `<div class="attribution"><div class="attribution-label"><span>Baseline data quality — ${i.baselineSource}${i.baselineHistoricalAttempts ? ` (${i.baselineHistoricalAttempts.toLocaleString()} historical attempts)` : ""}</span><strong>${i.dataQuality}</strong></div></div>` : ""}</div>
    <div class="drawer-section detail-only-section"><h3>SEGMENT BREAKDOWN</h3><p class="priority-summary">Which underlying segment explains the excess declines, ranked Pareto-style.</p><div id="segmentBreakdown"><p class="priority-summary">Loading…</p></div></div>
    <div class="drawer-section" id="humanDecisionSection"></div>`;
  state.reviewUi = { modifying: false };
  renderHumanDecision(i);
  const generateButton = document.getElementById("generateAnalysisButton");
  if (generateButton) generateButton.addEventListener("click", () => generateAnalysis(i.id));
  loadAndRenderSegments(i.id);
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
document.getElementById("timeViewToggle").addEventListener("click", e => { const b = e.target.closest("[data-view]"); if (b) setTimeView(b.dataset.view); });
document.getElementById("closeDrawer").addEventListener("click",closeDrawer);
document.getElementById("drawerBackdrop").addEventListener("click",closeDrawer);
document.addEventListener("keydown",e=>{ if(e.key==="Escape") closeDrawer(); });
document.getElementById("viewModeToggle").addEventListener("click", () => {
  applyViewMode(document.body.classList.contains("view-executive") ? "analyst" : "executive");
});
applyViewMode(getStoredViewMode());
setInterval(updateClock, 1000);
updateClock();
render();
startLivePolling();

// --- Ask PRISM: conversational agent over the live dashboard data ---
const agentState = { open: false, messages: [], sending: false };
const AGENT_HISTORY_LIMIT = 10;

function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

function renderAgentMessages() {
  const container = document.getElementById("agentMessages");
  if (agentState.messages.length === 0) {
    container.innerHTML = `<div class="agent-empty">Ask about the current incident state — e.g. "how many P1 incidents are there?" or "what's driving the highest-priority incident?". Every answer is grounded in the same live data on this dashboard, nothing invented.</div>`;
    return;
  }
  container.innerHTML = agentState.messages
    .map(m => {
      const cls = m.role === "user" ? "is-user" : m.role === "error" ? "is-error" : "is-assistant";
      const pendingCls = m.pending ? " is-pending" : "";
      return `<div class="agent-message ${cls}${pendingCls}">${escapeHtml(m.content)}</div>`;
    })
    .join("");
  container.scrollTop = container.scrollHeight;
}

function toggleAgentPanel(open) {
  agentState.open = open !== undefined ? open : !agentState.open;
  const panel = document.getElementById("agentPanel");
  panel.hidden = !agentState.open;
  panel.classList.toggle("is-open", agentState.open);
  panel.setAttribute("aria-hidden", String(!agentState.open));
  if (agentState.open) {
    renderAgentMessages();
    document.getElementById("agentInput").focus();
  }
}

async function sendAgentMessage(text) {
  if (!text.trim() || agentState.sending) return;

  agentState.messages.push({ role: "user", content: text.trim() });
  const pending = { role: "assistant", content: "Thinking…", pending: true };
  agentState.messages.push(pending);
  agentState.sending = true;
  renderAgentMessages();

  const history = agentState.messages
    .filter(m => !m.pending && m.role !== "error")
    .slice(-AGENT_HISTORY_LIMIT)
    .map(m => ({ role: m.role, content: m.content }));

  try {
    const response = await fetch(`${API_URL}/agent/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages: history }),
    });
    const index = agentState.messages.indexOf(pending);

    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      const detail = body.detail || `Request failed (${response.status}).`;
      agentState.messages[index] = { role: "error", content: detail };
    } else {
      const body = await response.json();
      agentState.messages[index] = { role: "assistant", content: body.answer || "No answer returned." };
    }
  } catch (error) {
    const index = agentState.messages.indexOf(pending);
    agentState.messages[index] = { role: "error", content: "Could not reach the agent — check your connection." };
  } finally {
    agentState.sending = false;
    renderAgentMessages();
  }
}

document.getElementById("agentToggle").addEventListener("click", () => toggleAgentPanel());
document.getElementById("agentClose").addEventListener("click", () => toggleAgentPanel(false));
document.getElementById("agentForm").addEventListener("submit", e => {
  e.preventDefault();
  const input = document.getElementById("agentInput");
  const text = input.value;
  input.value = "";
  sendAgentMessage(text);
});
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && agentState.open) toggleAgentPanel(false);
});

// --- Trial by fire: inject a live incident and run detection, no terminal ---
const tbfState = { options: null, open: false, running: false };

async function loadTbfOptions() {
  if (tbfState.options) return tbfState.options;
  const response = await fetch(`${API_URL}/trial-by-fire/options`);
  if (!response.ok) throw new Error("Could not load trial-by-fire options");
  tbfState.options = await response.json();
  return tbfState.options;
}

function populateSelect(select, values, keepFirst) {
  const first = keepFirst ? select.firstElementChild : null;
  select.innerHTML = "";
  if (first) select.appendChild(first);
  values.forEach(value => {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = value;
    select.appendChild(option);
  });
}

function refreshTbfMethodAndBankOptions() {
  const opts = tbfState.options;
  if (!opts) return;
  const country = document.getElementById("tbfCountry").value;
  const methodSelect = document.getElementById("tbfMethod");
  const bankSelect = document.getElementById("tbfBank");
  const methods = country
    ? opts.payment_methods_by_country[country]
    : [...new Set(Object.values(opts.payment_methods_by_country).flat())];
  const banks = country
    ? opts.issuing_banks_by_country[country]
    : [...new Set(Object.values(opts.issuing_banks_by_country).flat())];
  const prevMethod = methodSelect.value;
  const prevBank = bankSelect.value;
  populateSelect(methodSelect, methods, true);
  populateSelect(bankSelect, banks, true);
  if (methods.includes(prevMethod)) methodSelect.value = prevMethod;
  if (banks.includes(prevBank)) bankSelect.value = prevBank;
}

async function initTbfForm() {
  const opts = await loadTbfOptions();
  populateSelect(document.getElementById("tbfMerchant"), opts.merchants, true);
  populateSelect(document.getElementById("tbfProvider"), opts.providers, true);
  populateSelect(document.getElementById("tbfCountry"), opts.countries, true);
  populateSelect(document.getElementById("tbfDeclineCode"), opts.decline_codes, false);
  refreshTbfMethodAndBankOptions();
}

async function attemptLoadTbfOptions() {
  const submitButton = document.getElementById("tbfSubmit");
  const randomizeButton = document.getElementById("tbfRandomize");
  submitButton.disabled = true;
  randomizeButton.disabled = true;
  setTbfStatus("is-pending", "Loading available merchants, providers, and decline codes from the API…");

  try {
    await initTbfForm();
    document.getElementById("tbfStatus").hidden = true;
    submitButton.disabled = false;
    randomizeButton.disabled = false;
  } catch (error) {
    setTbfStatus(
      "is-error",
      "Could not load options from the API — it may be waking up from idle " +
      "(Render free tier can take 30-50s on the first request). " +
      '<button type="button" id="tbfRetryOptions" class="tbf-secondary" style="margin-top:10px;width:auto;padding:0 14px;">Retry</button>'
    );
    document.getElementById("tbfRetryOptions").addEventListener("click", attemptLoadTbfOptions);
  }
}

function toggleTbfModal(open) {
  tbfState.open = open !== undefined ? open : !tbfState.open;
  document.getElementById("tbfBackdrop").hidden = !tbfState.open;
  document.getElementById("tbfModal").hidden = !tbfState.open;
  document.getElementById("tbfModal").setAttribute("aria-hidden", String(!tbfState.open));
  if (tbfState.open && !tbfState.options) {
    attemptLoadTbfOptions();
  }
}

function randomChoice(list) { return list[Math.floor(Math.random() * list.length)]; }

function randomizeTbfForm() {
  const opts = tbfState.options;
  if (!opts) return;
  const country = randomChoice(opts.countries);
  document.getElementById("tbfCountry").value = country;
  refreshTbfMethodAndBankOptions();
  document.getElementById("tbfProvider").value = randomChoice(opts.providers);
  document.getElementById("tbfMerchant").value = Math.random() < 0.5 ? randomChoice(opts.merchants) : "";
  document.getElementById("tbfMethod").value = Math.random() < 0.6 ? randomChoice(opts.payment_methods_by_country[country]) : "";
  document.getElementById("tbfBank").value = Math.random() < 0.4 ? randomChoice(opts.issuing_banks_by_country[country]) : "";
  document.getElementById("tbfDeclineCode").value = randomChoice(opts.decline_codes);
  const approvalRateSteps = 4 + Math.floor(Math.random() * 8); // 0.20 .. 0.55 in 0.05 steps
  document.getElementById("tbfApprovalRate").value = (approvalRateSteps * 0.05).toFixed(2);
  document.getElementById("tbfMinutes").value = String(3 + Math.floor(Math.random() * 5));
}

function setTbfStatus(cls, html) {
  stopTbfProgress();
  const el = document.getElementById("tbfStatus");
  el.hidden = false;
  el.className = `tbf-status ${cls}`;
  el.innerHTML = html;
}

// Progress is estimated, not streamed from the backend (the pipeline runs
// as one blocking request) — the moving bar and rotating stage labels exist
// so a ~15-20s wait doesn't read as "nothing is happening."
const TBF_ESTIMATED_SECONDS = 19;
const TBF_PROGRESS_STAGES_AFTER_FIRST = [
  { at: 2, label: "Aggregating live traffic across detection levels…" },
  { at: 5, label: "Scanning for statistically significant drops…" },
  { at: 9, label: "Clustering validated anomalies and inferring root cause…" },
  { at: 13, label: "Estimating financial impact and priority…" },
  { at: 16, label: "Finalizing recommendations…" },
];
let tbfProgressTimer = null;

function startTbfProgress(firstStageLabel) {
  stopTbfProgress();
  const stages = [{ at: 0, label: firstStageLabel }, ...TBF_PROGRESS_STAGES_AFTER_FIRST];
  const el = document.getElementById("tbfStatus");
  el.hidden = false;
  el.className = "tbf-status is-pending";
  el.innerHTML = `
    <div class="tbf-progress-label" id="tbfProgressLabel">${escapeHtml(firstStageLabel)}</div>
    <div class="tbf-progress-track"><div class="tbf-progress-fill" id="tbfProgressFill"></div></div>
    <div class="tbf-progress-meta"><span id="tbfProgressElapsed">0s elapsed</span><span>~15-20s total</span></div>
  `;

  const startedAt = Date.now();
  tbfProgressTimer = setInterval(() => {
    const fill = document.getElementById("tbfProgressFill");
    const elapsedEl = document.getElementById("tbfProgressElapsed");
    const labelEl = document.getElementById("tbfProgressLabel");
    if (!fill || !elapsedEl || !labelEl) { stopTbfProgress(); return; }

    const elapsedSeconds = (Date.now() - startedAt) / 1000;
    const pct = Math.min(95, (elapsedSeconds / TBF_ESTIMATED_SECONDS) * 100);
    fill.style.width = `${pct}%`;
    elapsedEl.textContent = `${Math.floor(elapsedSeconds)}s elapsed`;
    const stage = [...stages].reverse().find(s => elapsedSeconds >= s.at);
    if (stage) labelEl.textContent = stage.label;
  }, 250);
}

function stopTbfProgress() {
  if (tbfProgressTimer) {
    clearInterval(tbfProgressTimer);
    tbfProgressTimer = null;
  }
}

async function submitTbfForm(event) {
  event.preventDefault();
  if (tbfState.running) return;
  tbfState.running = true;
  document.getElementById("tbfSubmit").disabled = true;
  document.getElementById("tbfRandomize").disabled = true;
  startTbfProgress("Appending matching transactions to the live feed…");

  const payload = {
    merchant: document.getElementById("tbfMerchant").value || null,
    provider: document.getElementById("tbfProvider").value || null,
    country: document.getElementById("tbfCountry").value || null,
    payment_method: document.getElementById("tbfMethod").value || null,
    issuing_bank: document.getElementById("tbfBank").value || null,
    decline_code: document.getElementById("tbfDeclineCode").value,
    approval_rate: parseFloat(document.getElementById("tbfApprovalRate").value),
    minutes: parseInt(document.getElementById("tbfMinutes").value, 10),
  };

  try {
    const response = await fetch(`${API_URL}/trial-by-fire`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const body = await response.json();

    if (!response.ok) {
      setTbfStatus("is-error", escapeHtml(body.detail || `Request failed (${response.status}).`));
    } else {
      const cls = body.outcome === "confirmed_incident" ? "is-confirmed"
        : body.outcome === "unresolved_candidate" ? "is-unresolved" : "is-missed";
      const injected = body.injection;
      setTbfStatus(
        cls,
        `${escapeHtml(body.message)}<div class="tbf-status-detail">Incident ${escapeHtml(injected.incident_id)} · ` +
        `${injected.matched_transactions.toLocaleString()} matching transactions, ` +
        `${injected.declined_transactions.toLocaleString()} declined</div>`
      );
      fetchLive();
    }
  } catch (error) {
    setTbfStatus("is-error", "Could not reach the API — check your connection.");
  } finally {
    tbfState.running = false;
    document.getElementById("tbfSubmit").disabled = false;
    document.getElementById("tbfRandomize").disabled = false;
  }
}

async function resetTbfDemo() {
  if (tbfState.running) return;
  const confirmed = window.confirm(
    "Reset the live feed to its baseline? This removes every incident " +
    "injected via Trial by fire (including the rehearsed demo incidents' " +
    "current state) and reruns detection — takes about 15-20 seconds."
  );
  if (!confirmed) return;

  tbfState.running = true;
  document.getElementById("tbfSubmit").disabled = true;
  document.getElementById("tbfRandomize").disabled = true;
  document.getElementById("tbfReset").disabled = true;
  startTbfProgress("Restoring the baseline live feed…");

  try {
    const response = await fetch(`${API_URL}/trial-by-fire/reset`, { method: "POST" });
    const body = await response.json();
    if (!response.ok) {
      setTbfStatus("is-error", escapeHtml(body.detail || `Request failed (${response.status}).`));
    } else {
      setTbfStatus(
        "is-missed",
        `${escapeHtml(body.message)}<div class="tbf-status-detail">${body.active_incidents} active incident(s) after reset</div>`
      );
      fetchLive();
    }
  } catch (error) {
    setTbfStatus("is-error", "Could not reach the API — check your connection.");
  } finally {
    tbfState.running = false;
    document.getElementById("tbfSubmit").disabled = false;
    document.getElementById("tbfRandomize").disabled = false;
    document.getElementById("tbfReset").disabled = false;
  }
}

document.getElementById("tbfToggle").addEventListener("click", () => toggleTbfModal());
document.getElementById("tbfClose").addEventListener("click", () => toggleTbfModal(false));
document.getElementById("tbfBackdrop").addEventListener("click", () => toggleTbfModal(false));
document.getElementById("tbfCountry").addEventListener("change", refreshTbfMethodAndBankOptions);
document.getElementById("tbfRandomize").addEventListener("click", randomizeTbfForm);
document.getElementById("tbfForm").addEventListener("submit", submitTbfForm);
document.getElementById("tbfReset").addEventListener("click", resetTbfDemo);
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && tbfState.open) toggleTbfModal(false);
});
