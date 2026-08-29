const BASE_CHART = [85.4, 85.2, 85.6, 85.1, 85.5, 85.0, 85.3, 84.9, 85.6, 85.2, 85.4, 85.1, 85.5, 84.9, 85.2, 85.1];
const EXPECTED = [85.4, 85.4, 85.3, 85.4, 85.4, 85.3, 85.4, 85.4, 85.4, 85.3, 85.4, 85.4, 85.4, 85.3, 85.4, 85.4];

const API_URL = "https://control-tower-vl22.onrender.com";
const LIVE_POLL_MS = 20000;

function pipeToText(value, fallback = "All") {
  if (!value) return fallback;
  return value.split("|").map(item => item.trim()).filter(Boolean).join(", ");
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

function mapApiIncident(apiIncident) {
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
    title: apiIncident.incident_title,
    subtitle: apiIncident.root_cause_type === "provider" ? "Provider × country · multiple merchants" : "Merchant × country × issuing bank",
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
    executiveAction: apiIncident.executive_action
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
    marker: undefined
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

const incidents = {
  brazil: {
    id: "INC-2048", priority: "P1", severity: "CRITICAL", country: "BR", started: "10:03",
    title: "dLocal degradation in Brazil", subtitle: "Provider × country · all merchants",
    expected: 88.0, actual: 61.8, confidence: 97, risk: 39800, adjustedRisk: 38600,
    attempts: 1248, excess: 327, attribution: 89,
    evidence: [
      "dLocal approval in Brazil fell 26.2 percentage points below its expected baseline.",
      "The provider explains 89% of excess declines observed in the affected Brazilian flow.",
      "Stripe and Adyen remain within their historical ranges for comparable Brazil traffic.",
      "DO_NOT_HONOR increased 4.2× after the incident began."
    ],
    executive: "dLocal degradation in Brazil is putting approximately $39.8K of GMV per hour at risk.",
    recommendation: "Investigate dLocal’s Brazil processing and consider temporarily rerouting affected traffic through a currently healthy provider.",
    root: "Brazil › dLocal", affected: "Brazil · dLocal · All payment methods", recovery: "$35.2K / hour",
    method: "All payment methods", merchants: "All merchants",
    tree: { label: "Brazil", children: [
      { label: "Stripe", state: "normal" },
      { label: "Adyen", state: "normal" },
      { label: "dLocal", state: "root", children: [
        { label: "DO_NOT_HONOR ↑ 4.2×", state: "root" }
      ] }
    ] }
  },
  mexico: {
    id: "INC-2051", priority: "P2", severity: "HIGH", country: "MX", started: "10:06",
    title: "Banorte issuer failure for Merchant C", subtitle: "Merchant × country × issuing bank",
    expected: 84.1, actual: 55.6, confidence: 93, risk: 11600, adjustedRisk: 10800,
    attempts: 416, excess: 119, attribution: 82,
    evidence: [
      "Merchant C card approvals issued by Banorte fell 28.5 percentage points below baseline.",
      "The same bank remains normal for other merchants, isolating the issue to Merchant C’s flow.",
      "Other Mexican issuing banks remain inside their expected conversion ranges.",
      "DO_NOT_HONOR is 3.6× above its normal share for the affected segment."
    ],
    executive: "A Banorte-specific failure for Merchant C in Mexico is putting approximately $11.6K of GMV per hour at risk.",
    recommendation: "Escalate the Merchant C / Banorte pattern with the acquiring partner and monitor bank-specific declines before changing routing.",
    root: "Mexico › Merchant C › Banorte", affected: "Mexico · Merchant C · Cards · Banorte", recovery: "$8.9K / hour",
    method: "Cards", merchants: "Merchant C",
    tree: { label: "Mexico", children: [
      { label: "Merchant C", state: "anomaly", children: [
        { label: "Other issuing banks", state: "normal" },
        { label: "Banorte", state: "root", children: [
          { label: "DO_NOT_HONOR ↑ 3.6×", state: "root" }
        ] }
      ] }
    ] }
  },
  ambiguous: {
    id: "OBS-731", priority: "OBS", severity: "INSUFFICIENT EVIDENCE", country: "CO", started: "10:08",
    title: "Conversion anomaly in Colombia", subtitle: "Two plausible hypotheses remain",
    expected: 84.3, actual: 78.9, confidence: 44, risk: 6400, adjustedRisk: 2800,
    attempts: 238, excess: 13, attribution: 51,
    evidence: [
      "Colombia conversion is 5.4 percentage points below expected behavior.",
      "The signal is split across provider and issuer dimensions; neither explains a decisive share.",
      "Traffic volume is not yet sufficient to distinguish the two leading hypotheses.",
      "No isolated remediation is justified at the current confidence level."
    ],
    hypotheses: [["dLocal × Colombia", 51], ["Bancolombia issuing cards", 43], ["Other", 6]],
    executive: "Colombia conversion is below baseline, but there is not yet enough evidence to name a root cause reliably.",
    recommendation: "Continue monitoring. Collect approximately 312 additional transactions before deciding between the provider and issuer hypotheses.",
    root: "Colombia › unresolved", affected: "Colombia · Mixed card traffic", recovery: "Not modeled",
    method: "Cards (mixed)", merchants: "All merchants",
    tree: { label: "Colombia", children: [
      { label: "dLocal", state: "hypothesis", pct: 51 },
      { label: "Bancolombia issuing", state: "hypothesis", pct: 43 },
      { label: "Other", state: "normal", pct: 6 }
    ] }
  }
};

const randomTemplates = [
  { id:"INC-R17", priority:"P2", severity:"HIGH", country:"CO", started:"10:09", title:"Adyen wallet failure in Colombia", subtitle:"Merchant B × provider × method", expected:87.5, actual:60.2, confidence:95, risk:14200, adjustedRisk:13500, attempts:382, excess:104, attribution:86, evidence:["Adyen wallet conversion in Colombia is 27.3pp below baseline.","86% of excess declines are concentrated in Merchant B traffic.","dLocal and Stripe wallet traffic in Colombia remain normal.","SUSPECTED_FRAUD increased 3.9× in the affected slice."], executive:"A newly injected Adyen wallet failure in Colombia is putting about $14.2K of GMV per hour at risk.", recommendation:"Investigate Adyen wallet processing for Merchant B in Colombia and consider shifting only the affected wallet traffic.", root:"Colombia › Merchant B › Adyen › Wallet", affected:"Colombia · Merchant B · Adyen · Wallet", recovery:"$11.7K / hour", method:"Wallet", merchants:"Merchant B",
    tree: { label:"Colombia", children:[ { label:"Merchant B", state:"anomaly", children:[ { label:"dLocal", state:"normal" }, { label:"Stripe", state:"normal" }, { label:"Adyen", state:"root", children:[ { label:"SUSPECTED_FRAUD ↑ 3.9×", state:"root" } ] } ] } ] } },
  { id:"INC-R24", priority:"P1", severity:"CRITICAL", country:"MX", started:"10:09", title:"Stripe card degradation in Mexico", subtitle:"Provider × method × country", expected:83.7, actual:49.8, confidence:98, risk:27300, adjustedRisk:26700, attempts:691, excess:234, attribution:91, evidence:["Stripe card conversion in Mexico is 33.9pp below baseline.","The slice explains 91% of the current excess declines in Mexico.","Wallet and cash-in-store traffic remain within range.","INVALID_CARD increased 4.5× after 10:09."], executive:"A newly injected Stripe card failure in Mexico is putting about $27.3K of GMV per hour at risk.", recommendation:"Investigate Stripe card processing in Mexico and simulate a limited reroute to the strongest healthy provider.", root:"Mexico › Stripe › Card", affected:"Mexico · Stripe · Cards · All merchants", recovery:"$23.5K / hour", method:"Cards", merchants:"All merchants",
    tree: { label:"Mexico", children:[ { label:"Stripe", state:"anomaly", children:[ { label:"Wallet", state:"normal" }, { label:"Cash-in-store", state:"normal" }, { label:"Card", state:"root", children:[ { label:"INVALID_CARD ↑ 4.5×", state:"root" } ] } ] } ] } },
  { id:"INC-R31", priority:"P2", severity:"HIGH", country:"BR", started:"10:09", title:"Merchant A wallet anomaly in Brazil", subtitle:"Merchant × method × country", expected:89.1, actual:62.7, confidence:92, risk:9700, adjustedRisk:8900, attempts:306, excess:81, attribution:79, evidence:["Merchant A wallet conversion in Brazil is 26.4pp below baseline.","The pattern spans providers, making merchant configuration the stronger hypothesis.","Other merchants’ Brazil wallet traffic remains healthy.","Processing time increased 2.3× alongside the decline spike."], executive:"A newly injected Merchant A wallet anomaly in Brazil is putting about $9.7K of GMV per hour at risk.", recommendation:"Review recent Merchant A wallet configuration changes in Brazil before changing provider routing.", root:"Brazil › Merchant A › Wallet", affected:"Brazil · Merchant A · Wallet · All providers", recovery:"$7.4K / hour", method:"Wallet", merchants:"Merchant A",
    tree: { label:"Brazil", children:[ { label:"Other merchants", state:"normal" }, { label:"Merchant A", state:"root", children:[ { label:"Wallet — processing time ↑ 2.3×", state:"root" } ] } ] } }
];

const state = { mode: "live", scenario: "normal", selectedIncident: null, randomIncident: null, randomCounter: 0, groundTruthRevealed: false, liveData: null, liveError: null, liveTimer: null };

const DEMO_DEFAULTS = {
  expectedChart: EXPECTED,
  timeLabels: ["09:42", "09:52", "10:02", "Now"],
  monitoredTraffic: { attempts_total: 50000, merchants: 3, providers: 3 }
};
function withDemoDefaults(scenario) { return { ...DEMO_DEFAULTS, ...scenario }; }

const scenarios = {
  normal: {
    tone: "healthy", pill: "SYSTEM HEALTHY", title: "Payment network operating within expected range",
    description: "No meaningful deterioration detected across monitored payment flows.", conversion: 85.1, expected: 85.4,
    chart: BASE_CHART, incidents: [], countries: { MX:["healthy",83.2], CO:["healthy",84.3], BR:["healthy",88.0] }
  },
  brazil: {
    tone: "critical", pill: "1 ACTIVE INCIDENT", title: "Critical provider degradation isolated in Brazil",
    description: "The incident is concentrated on dLocal; comparable provider traffic remains healthy.", conversion: 78.9, expected: 85.4,
    chart: [85.4,85.2,85.6,85.1,85.5,85.0,85.3,84.9,85.2,84.8,82.1,79.3,77.8,78.6,78.7,78.9], incidents:[incidents.brazil], countries:{ MX:["healthy",83.2], CO:["healthy",84.3], BR:["critical",61.8] }, marker: 10
  },
  mexico: {
    tone: "warning", pill: "1 ACTIVE INCIDENT", title: "Issuer-specific incident detected in Mexico",
    description: "The anomaly is isolated to Merchant C card traffic issued by Banorte.", conversion: 82.7, expected: 85.4,
    chart: [85.4,85.2,85.6,85.1,85.5,85.0,85.3,84.9,85.6,85.0,84.1,83.7,82.6,83.1,82.8,82.7], incidents:[incidents.mexico], countries:{ MX:["warning",72.5], CO:["healthy",84.3], BR:["healthy",88.0] }, marker: 11
  },
  both: {
    tone: "critical", pill: "2 ACTIVE INCIDENTS", title: "Two independent incidents separated and prioritized",
    description: "Brazil provider degradation is P1 by economic impact; Mexico issuer failure is P2.", conversion: 76.4, expected: 85.4,
    chart: [85.4,85.2,85.6,85.1,85.5,85.0,85.3,84.9,85.0,83.1,79.7,77.2,76.0,76.7,76.2,76.4], incidents:[incidents.brazil,incidents.mexico], countries:{ MX:["warning",72.5], CO:["healthy",84.3], BR:["critical",61.8] }, marker: 9
  },
  ambiguous: {
    tone: "warning", pill: "INSUFFICIENT EVIDENCE", title: "Anomaly detected; root cause intentionally unresolved",
    description: "Two hypotheses remain plausible. PRSM will not invent a diagnosis.", conversion: 82.1, expected: 85.4,
    chart: [85.4,85.2,85.6,85.1,85.5,85.0,85.3,84.9,85.1,84.7,83.8,82.9,82.0,82.5,82.2,82.1], incidents:[incidents.ambiguous], countries:{ MX:["healthy",83.2], CO:["warning",78.9], BR:["healthy",88.0] }, marker: 10
  }
};

function money(value) { return value >= 1000 ? `$${(value/1000).toFixed(1)}K` : `$${Math.round(value)}`; }
function formatCount(value) { return value >= 1000 ? `${(value/1000).toFixed(1)}K` : `${Math.round(value)}`; }

function currentScenario() {
  if (state.mode === "live") {
    if (state.liveData) return state.liveData;
    if (state.liveError) return liveErrorScenario(state.liveError);
    return connectingScenario();
  }
  if (state.scenario !== "random") return withDemoDefaults(scenarios[state.scenario]);
  const i = state.randomIncident;
  const countries = { MX:["healthy",83.2], CO:["healthy",84.3], BR:["healthy",88.0] };
  countries[i.country] = [i.severity === "CRITICAL" ? "critical" : "warning", i.actual];
  return withDemoDefaults({
    tone: i.severity === "CRITICAL" ? "critical" : "warning", pill: "BLIND TEST · INCIDENT FOUND",
    title: "A previously unrehearsed failure was diagnosed", description: "The injected dimensions stay hidden until you reveal the ground truth.",
    conversion: +(85.1 - (i.expected-i.actual)*.18).toFixed(1), expected:85.4,
    chart:[85.4,85.2,85.6,85.1,85.5,85.0,85.3,84.9,85.2,84.7,83.1,81.2,80.4,79.5,79.2,79.0], incidents:[i], countries, marker:10
  });
}

function setScenario(key) {
  if (key === "reset") key = "normal";
  if (key === "random") {
    state.randomCounter += 1;
    state.randomIncident = randomTemplates[(state.randomCounter - 1) % randomTemplates.length];
    state.groundTruthRevealed = false;
  }
  state.scenario = key;
  closeDrawer();
  render();
  document.querySelectorAll("[data-scenario]").forEach(b => b.classList.toggle("is-active", b.dataset.scenario === key));
  showToast(key === "normal" ? "Demo reset to normal operation" : `${currentScenario().pill.toLowerCase()} loaded`);
}

function setMode(view) {
  state.mode = view;
  document.querySelectorAll("#modeToggle [data-view]").forEach(b => b.classList.toggle("is-active", b.dataset.view === view));
  document.querySelectorAll("#scenarioButtons > [data-scenario]").forEach(b => b.classList.toggle("is-disabled", view !== "demo"));
  document.getElementById("controlNote").textContent = view === "live"
    ? "Live network data from Control Tower"
    : "Deterministic scenarios for a reliable live demo";
  closeDrawer();
  if (view === "live") {
    render();
    startLivePolling();
  } else {
    stopLivePolling();
    setScenario(state.scenario === "random" ? "random" : state.scenario);
  }
}

async function fetchLive() {
  try {
    const [dashboard, liveIncidents] = await Promise.all([loadDashboard(), loadLiveIncidents()]);
    const hadError = Boolean(state.liveError);
    state.liveData = buildLiveScenario(dashboard, liveIncidents);
    state.liveError = null;
    if (state.mode === "live") {
      render();
      if (hadError) showToast("Live connection restored");
    }
  } catch (error) {
    console.error("Could not load live data:", error);
    state.liveError = (error && error.message) || "Control Tower API unavailable";
    if (state.mode === "live") {
      render();
      showToast("Live data unavailable — check the Control Tower API");
    }
  }
}

function startLivePolling() {
  fetchLive();
  clearInterval(state.liveTimer);
  state.liveTimer = setInterval(fetchLive, LIVE_POLL_MS);
}

function stopLivePolling() {
  clearInterval(state.liveTimer);
  state.liveTimer = null;
}

function render() {
  const s = currentScenario();
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
  document.getElementById("statusTimestamp").textContent = state.mode === "live" && s.lastUpdated
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
    document.getElementById(`${names[code]}Metric`).textContent = `${value.toFixed(1)}% conversion`;
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
  const s = currentScenario();
  const hit = s.incidents.find(i => i.country === code);
  const value = s.countries[code][1];
  const roster = document.getElementById("marketRoster");
  const detail = document.getElementById("marketDetail");
  roster.hidden = true;
  detail.hidden = false;
  const body = hit
    ? `<div class="market-incident ${hit.priority === "P1" ? "" : "is-caution"}">
        <h5>${hit.title}</h5>
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
    : `<div class="market-empty">Healthy — no significant incidents. Conversion ${value.toFixed(1)}%, within its own historical baseline.</div>`;
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

function renderChart(rawActual, rawExpected, marker) {
  const svg = document.getElementById("conversionChart");
  if (!rawActual || rawActual.length < 2) { svg.innerHTML = ""; return; }
  const width=1200, height=250, min=55, max=95;
  const actual = fillGaps(rawActual, (min+max)/2);
  const expected = rawExpected && rawExpected.length === actual.length ? fillGaps(rawExpected, (min+max)/2) : actual;
  const x = i => i*(width/(actual.length-1)); const y = v => height-((v-min)/(max-min))*height;
  const points = arr => arr.map((v,i)=>`${x(i)},${y(v)}`).join(" ");
  const area = `0,${height} ${points(actual)} ${width},${height}`;
  const grids = [0,.25,.5,.75,1].map(p=>`<line class="chart-grid" x1="0" y1="${p*height}" x2="${width}" y2="${p*height}"/>`).join("");
  const markerSvg = marker !== undefined ? `<line class="incident-line" x1="${x(marker)}" y1="0" x2="${x(marker)}" y2="${height}"/><text class="chart-label" x="${x(marker)+8}" y="15">ANOMALY DETECTED</text>` : "";
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

function openDrawer(i) {
  if (!i) return;
  state.selectedIncident = i;
  document.getElementById("drawerId").textContent = `${i.id} · Started ${i.started}`;
  const reveal = state.scenario === "random" ? `<div class="drawer-section"><h3>BLIND TEST VALIDATION</h3><div class="recommendation" id="groundTruthBox">${state.groundTruthRevealed ? `<strong>GROUND TRUTH MATCH</strong><br>${i.root}` : "Injected dimensions are hidden. Reveal them after reviewing the system diagnosis."}</div><div class="drawer-actions"><button class="drawer-action primary" id="revealTruth">${state.groundTruthRevealed ? "Ground truth revealed" : "Reveal injected failure"}</button></div></div>` : "";
  const diagnosticPath = i.tree ? `<div class="drawer-section"><h3>DIAGNOSTIC PATH</h3>${renderTree(i.tree)}</div>` : "";
  document.getElementById("drawerContent").innerHTML = `
    <div class="drawer-title-row"><span class="severity-label ${i.priority === "P1" ? "" : "warning"}">${i.priority} · ${i.severity}</span><h2>${i.title}</h2><p>${i.affected}</p></div>
    <div class="executive-summary"><span class="eyebrow">EXECUTIVE SUMMARY</span><br>${i.executive}</div>
    ${diagnosticPath}
    <div class="drawer-section"><h3>OBSERVED VS EXPECTED</h3><div class="conversion-compare"><div><span>Expected</span><strong>${i.expected.toFixed(1)}%</strong></div><span class="compare-arrow">→</span><div class="drop-value"><span>Observed</span><strong>${i.actual.toFixed(1)}%</strong></div></div></div>
    <div class="drawer-section"><h3>ECONOMIC IMPACT</h3><div class="metric-grid"><div class="metric-pair"><span>GMV at risk</span><strong>${money(i.risk)}/h</strong></div><div class="metric-pair"><span>Recoverable</span><strong>${i.recovery}</strong></div><div class="metric-pair"><span>Affected attempts</span><strong>${i.attempts.toLocaleString()}</strong></div><div class="metric-pair"><span>Excess declines</span><strong>${i.excess.toLocaleString()}</strong></div></div></div>
    <div class="drawer-section"><h3>DIAGNOSIS CONFIDENCE</h3><div class="confidence-head"><span>${i.root}</span><strong>${i.confidence}%</strong></div><div class="confidence-track"><div class="confidence-fill ${i.confidence < 60 ? "warning" : ""}" style="width:${i.confidence}%"></div></div><div class="attribution"><div class="attribution-label"><span>Conversion loss explained</span><strong>${i.attribution}%</strong></div><div class="confidence-track"><div class="confidence-fill ${i.attribution < 60 ? "warning" : ""}" style="width:${i.attribution}%"></div></div></div></div>
    <div class="drawer-section"><h3>ROOT-CAUSE EVIDENCE</h3><div class="evidence-list">${i.evidence.map(e=>`<div class="evidence-item"><span class="evidence-check">✓</span><span>${e}</span></div>`).join("")}</div></div>
    <div class="drawer-section"><h3>RECOMMENDED NEXT STEP</h3><div class="recommendation"><strong>Human decision required</strong><br>${i.recommendation}</div></div>
    ${reveal}
    <div class="drawer-actions"><button class="drawer-action">Export incident</button><button class="drawer-action primary">Open investigation</button></div>`;
  const revealButton = document.getElementById("revealTruth");
  if (revealButton) revealButton.addEventListener("click", () => { state.groundTruthRevealed = true; openDrawer(i); showToast("Injected ground truth matches the diagnosis"); });
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

document.getElementById("scenarioButtons").addEventListener("click", e => { const b=e.target.closest("[data-scenario]"); if(b) setScenario(b.dataset.scenario); });
document.getElementById("modeToggle").addEventListener("click", e => { const b=e.target.closest("[data-view]"); if(b) setMode(b.dataset.view); });
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
