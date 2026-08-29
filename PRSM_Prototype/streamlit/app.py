from __future__ import annotations

import html
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from control_tower import COUNTRY_NAMES, run_scenario


APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "data"

st.set_page_config(
    page_title="PagoTotal Control Tower",
    page_icon="◫",
    layout="wide",
    initial_sidebar_state="collapsed",
)


@st.cache_data(show_spinner=False)
def load_data() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    transactions = pd.read_csv(DATA_DIR / "transactions_normal.csv", parse_dates=["timestamp"])
    config = pd.read_csv(DATA_DIR / "merchant_financial_config.csv")
    rates = pd.read_csv(DATA_DIR / "exchange_rates.csv")
    transactions["decline_code"] = transactions["decline_code"].fillna("")
    transactions["issuing_bank"] = transactions["issuing_bank"].fillna("")
    rate_map = rates.set_index("currency")["rate_to_usd"]
    missing_rates = sorted(set(transactions["currency"]) - set(rate_map.index))
    if missing_rates:
        raise ValueError(f"Missing USD exchange rate for: {', '.join(missing_rates)}")
    # Normalize every transaction to USD from the supplied FX table so the
    # economic impact calculation always uses the attached exchange rates.
    transactions["amount_usd"] = (transactions["amount"] * transactions["currency"].map(rate_map)).round(2)
    return transactions, config, rates


def money(value: float) -> str:
    return f"${value / 1000:,.1f}K" if value >= 1000 else f"${value:,.0f}"


def pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def safe(value: object) -> str:
    return html.escape(str(value))


def inject_css() -> None:
    st.markdown(
        """
        <style>
        :root { --pt-cyan:#69e4df; --pt-green:#4adeaa; --pt-yellow:#f4ba52; --pt-red:#ff6f80; --pt-panel:#0b1925; --pt-line:rgba(142,190,203,.15); }
        html, body, [class*="css"] { font-feature-settings: "tnum" 1, "ss01" 1; }
        .stApp { background: radial-gradient(circle at 75% -10%, rgba(35,175,169,.12), transparent 32%), linear-gradient(180deg,#061019,#07121b); }
        [data-testid="stHeader"], [data-testid="stToolbar"] { background: transparent; }
        [data-testid="stSidebar"] { background: #08141e; }
        .block-container { max-width: 1500px; padding-top: 1rem; padding-bottom: 3rem; }
        .pt-header { display:flex; align-items:center; justify-content:space-between; min-height:64px; border-bottom:1px solid var(--pt-line); margin-bottom:14px; }
        .pt-brand { display:flex; align-items:center; gap:12px; }
        .pt-mark { width:36px; height:36px; display:grid; place-items:center; border:1px solid rgba(105,228,223,.28); border-radius:10px; color:var(--pt-cyan); background:rgba(105,228,223,.08); font-size:20px; }
        .pt-brand-name { font-size:16px; letter-spacing:-.01em; }.pt-brand-name b { color:var(--pt-cyan); font-weight:650; }
        .pt-brand-sub { color:#7f98a4; font-size:10px; margin-top:2px; letter-spacing:.05em; }
        .pt-live { display:inline-flex; align-items:center; gap:7px; color:#a1efd2; font-size:10px; letter-spacing:.1em; padding:7px 10px; border:1px solid rgba(74,222,170,.24); border-radius:999px; background:rgba(74,222,170,.08); }
        .pt-live i { width:6px; height:6px; border-radius:50%; background:var(--pt-green); box-shadow:0 0 10px var(--pt-green); }
        .pt-eyebrow { color:var(--pt-cyan); font-size:9px; font-weight:800; letter-spacing:.14em; }
        .pt-demo-label { padding:4px 0 8px; color:#6e8895; font-size:10px; }
        div[data-testid="stButton"] > button { min-height:38px; border-color:var(--pt-line); background:rgba(255,255,255,.018); color:#a8bbc3; font-size:11px; border-radius:9px; }
        div[data-testid="stButton"] > button:hover { border-color:rgba(105,228,223,.42); color:#e5ffff; background:rgba(105,228,223,.075); }
        div[data-testid="stButton"] > button[kind="primary"] { background:rgba(105,228,223,.13); border-color:rgba(105,228,223,.45); color:#e3ffff; }
        .pt-status { display:flex; align-items:center; justify-content:space-between; gap:18px; min-height:80px; margin:10px 0 12px; padding:15px 18px; border:1px solid rgba(74,222,170,.18); border-radius:15px; background:linear-gradient(90deg,rgba(74,222,170,.075),rgba(74,222,170,.015)); }
        .pt-status.critical { border-color:rgba(255,111,128,.28); background:linear-gradient(90deg,rgba(255,111,128,.11),rgba(255,111,128,.015)); }
        .pt-status.warning { border-color:rgba(244,186,82,.28); background:linear-gradient(90deg,rgba(244,186,82,.10),rgba(244,186,82,.015)); }
        .pt-status-left { display:flex; align-items:center; gap:16px; }.pt-pill { min-width:125px; text-align:center; color:var(--pt-green); border:1px solid rgba(74,222,170,.34); border-radius:7px; padding:9px 10px; font-size:9px; font-weight:850; letter-spacing:.1em; }
        .critical .pt-pill { color:#ff9baa; border-color:rgba(255,111,128,.42); }.warning .pt-pill { color:#ffd482; border-color:rgba(244,186,82,.42); }
        .pt-status h1 { margin:0; font-size:17px; font-weight:620; letter-spacing:-.015em; }.pt-status p { margin:4px 0 0; color:#8fa7b3; font-size:11px; }
        .pt-updated { color:#647c88; font-size:9px; text-transform:uppercase; letter-spacing:.08em; white-space:nowrap; }
        .pt-kpi { min-height:126px; padding:16px 17px; border:1px solid var(--pt-line); border-radius:14px; background:linear-gradient(145deg,rgba(14,31,45,.94),rgba(9,22,33,.96)); box-shadow:0 20px 50px rgba(0,0,0,.18); }
        .pt-kpi-label { color:#91a8b2; font-size:10px; letter-spacing:.03em; }.pt-kpi-main { display:flex; align-items:center; justify-content:space-between; margin-top:10px; }.pt-kpi-main strong { font-size:29px; letter-spacing:-.045em; font-weight:590; }
        .pt-delta { padding:5px 7px; border-radius:6px; color:#b4c6cc; background:rgba(143,167,179,.09); font-size:9px; font-weight:700; }.pt-delta.bad { color:#ff9baa; background:rgba(255,111,128,.12); }.pt-delta.good { color:var(--pt-green); background:rgba(74,222,170,.11); }
        .pt-kpi-foot { display:flex; justify-content:space-between; color:#657e8a; font-size:9px; padding-top:11px; margin-top:11px; border-top:1px solid rgba(142,190,203,.09); }.pt-kpi-foot b { color:#b9cbd1; font-weight:600; }
        .pt-panel-title { margin:10px 0 0; font-size:15px; font-weight:600; }.pt-panel-sub { color:#6d8590; font-size:9px; }
        .pt-map { height:390px; position:relative; overflow:hidden; margin-top:10px; border:1px solid var(--pt-line); border-radius:15px; background:radial-gradient(circle at 48% 48%,rgba(31,107,119,.13),transparent 34%),linear-gradient(145deg,rgba(14,31,45,.94),rgba(9,22,33,.96)); }
        .pt-map::before { content:""; position:absolute; inset:0; opacity:.15; background-image:linear-gradient(rgba(142,190,203,.16) 1px,transparent 1px),linear-gradient(90deg,rgba(142,190,203,.14) 1px,transparent 1px); background-size:64px 64px; }
        .pt-route { position:absolute; height:1px; transform-origin:left center; border-top:1px dashed rgba(105,228,223,.23); }.route-a{left:22%;top:24%;width:45%;transform:rotate(32deg)}.route-b{left:47%;top:56%;width:30%;transform:rotate(27deg)}
        .pt-node { position:absolute; color:var(--pt-green); }.pt-node.warning,.pt-node.investigating{color:var(--pt-yellow)}.pt-node.critical{color:var(--pt-red)}
        .pt-node.mx{left:19%;top:19%}.pt-node.co{left:46%;top:51%}.pt-node.br{right:17%;bottom:19%}.pt-dot{width:12px;height:12px;border:3px solid rgba(5,16,25,.9);border-radius:50%;background:currentColor;box-shadow:0 0 17px currentColor}
        .pt-node span { position:absolute; left:22px; top:-9px; min-width:155px; }.pt-node.br span{left:auto;right:22px;text-align:right}.pt-node b{display:block;color:#f2f8f8;font-size:12px}.pt-node small{display:block;color:currentColor;font-size:8px;font-weight:850;letter-spacing:.1em;margin-top:3px}.pt-node em{display:block;color:#637d89;font-size:9px;font-style:normal;margin-top:3px}
        .pt-map-note { position:absolute; left:17px; bottom:13px; color:#607984; font-size:9px; }
        .pt-incident { margin-top:9px; padding:14px; border:1px solid var(--pt-line); border-radius:12px; background:linear-gradient(145deg,rgba(14,31,45,.90),rgba(9,22,33,.95)); }
        .pt-incident-top { display:flex; justify-content:space-between; align-items:center; }.pt-priority{padding:4px 7px;border-radius:5px;background:rgba(255,111,128,.12);color:#ff9baa;font-size:8px;font-weight:850;letter-spacing:.07em}.pt-priority.secondary{background:rgba(244,186,82,.12);color:#ffd482}.pt-start{color:#647c88;font-size:9px}
        .pt-incident h3{font-size:13px;margin:11px 0 4px}.pt-incident p{color:#8ca4af;font-size:10px;margin:0}.pt-inc-metrics{display:grid;grid-template-columns:repeat(3,1fr);gap:7px;margin-top:12px;padding-top:10px;border-top:1px solid rgba(142,190,203,.09)}.pt-inc-metrics span{color:#607985;font-size:8px;text-transform:uppercase;letter-spacing:.06em}.pt-inc-metrics b{display:block;color:#dce9eb;font-size:10px;text-transform:none;letter-spacing:0;margin-top:3px}
        .pt-empty { min-height:265px; display:grid; place-items:center; text-align:center; margin-top:9px; border:1px solid var(--pt-line); border-radius:15px; background:linear-gradient(145deg,rgba(14,31,45,.9),rgba(9,22,33,.95)); }.pt-empty i{display:grid;place-items:center;width:48px;height:48px;margin:auto;border-radius:50%;border:1px solid rgba(74,222,170,.28);color:var(--pt-green);background:rgba(74,222,170,.10);font-style:normal}.pt-empty h3{font-size:13px;margin:12px 0 4px}.pt-empty p{max-width:290px;color:#839ba6;font-size:10px;line-height:1.5}
        .pt-card { padding:15px; border:1px solid var(--pt-line); border-radius:12px; background:rgba(255,255,255,.015); }.pt-card h3{margin:0 0 11px;color:#8da5af;font-size:9px;letter-spacing:.13em}.pt-exec{padding:13px 14px;border-left:2px solid var(--pt-cyan);border-radius:0 8px 8px 0;background:rgba(105,228,223,.055);color:#d2e5e7;font-size:12px;line-height:1.55}.pt-evidence{display:grid;grid-template-columns:18px 1fr;gap:8px;margin:8px 0;color:#c1d2d6;font-size:11px;line-height:1.45}.pt-check{width:17px;height:17px;display:grid;place-items:center;border-radius:50%;color:var(--pt-cyan);background:rgba(105,228,223,.10);font-size:8px}.pt-reco{padding:13px;border:1px solid rgba(105,228,223,.18);border-radius:9px;background:rgba(105,228,223,.045);color:#d6e5e7;font-size:11px;line-height:1.55}.pt-reco b{color:var(--pt-cyan)}
        [data-testid="stMetric"] { border:1px solid var(--pt-line); border-radius:10px; padding:11px 12px; background:rgba(255,255,255,.015); }
        [data-testid="stMetricLabel"] { color:#7f98a4; } hr { border-color:var(--pt-line); }
        [data-testid="stDialog"] { background:#0a1721; border:1px solid rgba(142,190,203,.22); }
        @media(max-width:900px){.pt-status{align-items:flex-start;flex-direction:column}.pt-updated{display:none}.pt-map{height:330px}.pt-brand-sub{display:none}}
        </style>
        """,
        unsafe_allow_html=True,
    )


def kpi_card(label: str, value: str, badge: str, badge_class: str, foot_label: str, foot_value: str) -> None:
    st.markdown(
        f"""<div class="pt-kpi"><div class="pt-kpi-label">{safe(label)}</div>
        <div class="pt-kpi-main"><strong>{safe(value)}</strong><span class="pt-delta {badge_class}">{safe(badge)}</span></div>
        <div class="pt-kpi-foot"><span>{safe(foot_label)}</span><b>{safe(foot_value)}</b></div></div>""",
        unsafe_allow_html=True,
    )


def render_map(countries: dict[str, dict]) -> None:
    nodes = []
    labels = {"MX": "mx", "CO": "co", "BR": "br"}
    for code in ("MX", "CO", "BR"):
        item = countries[code]
        status = item["status"]
        label = "INVESTIGATING" if status == "investigating" else status.upper()
        nodes.append(
            f'<div class="pt-node {labels[code]} {safe(status)}"><div class="pt-dot"></div><span>'
            f'<b>{safe(item["name"])}</b><small>{safe(label)}</small><em>{pct(item["actual"])} conversion</em></span></div>'
        )
    st.markdown(
        '<div class="pt-map"><div class="pt-route route-a"></div><div class="pt-route route-b"></div>'
        + "".join(nodes)
        + '<div class="pt-map-note">Health is relative to each country’s own historical baseline.</div></div>',
        unsafe_allow_html=True,
    )


def render_incident_card(incident: dict) -> None:
    secondary = "secondary" if incident["priority"] != "P1" else ""
    st.markdown(
        f"""<div class="pt-incident"><div class="pt-incident-top">
        <span class="pt-priority {secondary}">{safe(incident['priority'])} · {safe(incident['severity'])}</span>
        <span class="pt-start">Since {safe(incident['started'])}</span></div>
        <h3>{safe(incident['title'])}</h3><p>{safe(incident['subtitle'])}</p>
        <div class="pt-inc-metrics"><span>Drop<b>−{incident['drop'] * 100:.1f} pp</b></span>
        <span>Confidence<b>{incident['confidence'] * 100:.0f}%</b></span>
        <span>GMV risk<b>{money(incident['gmv_risk'])}/h</b></span></div></div>""",
        unsafe_allow_html=True,
    )


@st.dialog("Incident investigation", width="large")
def show_incident(incident: dict, is_random: bool) -> None:
    secondary = "secondary" if incident["priority"] != "P1" else ""
    st.markdown(
        f"""<span class="pt-priority {secondary}">{safe(incident['priority'])} · {safe(incident['severity'])}</span>
        <h2 style="margin:12px 0 3px">{safe(incident['title'])}</h2>
        <div style="color:#8199a4;font-size:11px;margin-bottom:16px">{safe(incident['id'])} · {safe(incident['root_path'])} · Since {safe(incident['started'])}</div>
        <div class="pt-exec"><span class="pt-eyebrow">EXECUTIVE SUMMARY</span><br><br>{safe(incident['executive'])}</div>""",
        unsafe_allow_html=True,
    )
    st.write("")
    left, right, third, fourth = st.columns(4)
    left.metric("Expected", pct(incident["expected"]))
    right.metric("Observed", pct(incident["actual"]), f"−{incident['drop'] * 100:.1f} pp")
    third.metric("GMV at risk", f"{money(incident['gmv_risk'])}/h")
    fourth.metric("Excess declines", f"{incident['excess_declines']:,}")

    st.markdown('<div class="pt-eyebrow" style="margin-top:18px">DIAGNOSIS CONFIDENCE</div>', unsafe_allow_html=True)
    st.write(f"**{incident['confidence'] * 100:.0f}%** confidence · **{incident['attribution'] * 100:.0f}%** of country-level conversion loss explained")
    st.progress(float(incident["confidence"]))

    st.markdown('<div class="pt-eyebrow" style="margin-top:18px">ROOT-CAUSE EVIDENCE</div>', unsafe_allow_html=True)
    for evidence in incident["evidence"]:
        st.markdown(
            f'<div class="pt-evidence"><span class="pt-check">✓</span><span>{safe(evidence)}</span></div>',
            unsafe_allow_html=True,
        )

    if incident.get("hypotheses"):
        st.markdown('<div class="pt-eyebrow" style="margin-top:18px">PLAUSIBLE HYPOTHESES</div>', unsafe_allow_html=True)
        for label, probability in incident["hypotheses"]:
            st.write(f"{label} — **{probability * 100:.0f}%**")
            st.progress(float(probability))

    st.markdown('<div class="pt-eyebrow" style="margin-top:18px">ECONOMIC IMPACT</div>', unsafe_allow_html=True)
    impact_a, impact_b, impact_c = st.columns(3)
    impact_a.metric("Average ticket", money(incident["avg_ticket"]))
    impact_b.metric("Confidence adjusted", f"{money(incident['adjusted_risk'])}/h")
    impact_c.metric("Potentially recoverable", f"{money(incident['recovery'])}/h" if incident["recovery"] else "Not modeled")

    st.markdown('<div class="pt-eyebrow" style="margin-top:18px">RECOMMENDED NEXT STEP</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="pt-reco"><b>Human decision required</b><br>{safe(incident["recommendation"])}</div>',
        unsafe_allow_html=True,
    )

    if is_random:
        st.markdown('<div class="pt-eyebrow" style="margin-top:18px">BLIND TEST VALIDATION</div>', unsafe_allow_html=True)
        if st.session_state.get("reveal_truth", False):
            st.success(f"GROUND TRUTH MATCH — {incident['ground_truth']}")
        elif st.button("Reveal injected failure", type="primary", width="stretch"):
            st.session_state.reveal_truth = True
            st.success(f"GROUND TRUTH MATCH — {incident['ground_truth']}")


def scenario_button(label: str, key: str, active: str) -> bool:
    return st.button(label, key=f"scenario_{key}", type="primary" if active == key else "secondary", width="stretch")


inject_css()
transactions, config, rates = load_data()

if "scenario" not in st.session_state:
    st.session_state.scenario = "normal"
if "random_seed" not in st.session_state:
    st.session_state.random_seed = 1
if "reveal_truth" not in st.session_state:
    st.session_state.reveal_truth = False

st.markdown(
    """<div class="pt-header"><div class="pt-brand"><div class="pt-mark">▥</div><div>
    <div class="pt-brand-name">PagoTotal <b>Control Tower</b></div><div class="pt-brand-sub">Payment incident intelligence</div>
    </div></div><div class="pt-live"><i></i> LIVE DATA SIMULATION</div></div>""",
    unsafe_allow_html=True,
)

st.markdown('<span class="pt-eyebrow">DEMO CONTROL</span><div class="pt-demo-label">Deterministic injectors for a reliable live presentation</div>', unsafe_allow_html=True)
controls = st.columns([0.85, 1.35, 1.25, 0.72, 0.96, 1.02, 0.62])
buttons = [
    ("Normal", "normal"), ("Brazil provider failure", "brazil"), ("Mexico bank failure", "mexico"),
    ("Both", "both"), ("Random incident", "random"), ("Ambiguous", "ambiguous"), ("↺ Reset", "reset"),
]
for column, (label, key) in zip(controls, buttons):
    with column:
        if scenario_button(label, key, st.session_state.scenario):
            if key == "reset":
                st.session_state.scenario = "normal"
            elif key == "random":
                st.session_state.scenario = "random"
                st.session_state.random_seed += 1
                st.session_state.reveal_truth = False
            else:
                st.session_state.scenario = key
                st.session_state.reveal_truth = False
            st.rerun()

result = run_scenario(transactions, config, st.session_state.scenario, st.session_state.random_seed)

tone = "" if result["tone"] == "healthy" else result["tone"]
st.markdown(
    f"""<div class="pt-status {tone}"><div class="pt-status-left"><div class="pt-pill">{safe(result['pill'])}</div><div>
    <h1>{safe(result['title'])}</h1><p>{safe(result['description'])}</p></div></div>
    <div class="pt-updated">Updated just now · {result['window_attempts']:,} attempts in live window</div></div>""",
    unsafe_allow_html=True,
)

delta_pp = (result["actual_conversion"] - result["expected_conversion"]) * 100
kpis = st.columns(4)
with kpis[0]:
    kpi_card("Network conversion", pct(result["actual_conversion"]), f"{delta_pp:+.1f} pp", "bad" if delta_pp < -1 else "", "Expected", pct(result["expected_conversion"]))
with kpis[1]:
    active_label = "Quiet" if not result["active_incidents"] else ("Separated" if result["active_incidents"] > 1 else "Detected")
    kpi_card("Active incidents", str(result["active_incidents"]), active_label, "good" if not result["active_incidents"] else "bad", "Highest priority", result["incidents"][0]["priority"] if result["incidents"] else "—")
with kpis[2]:
    kpi_card("GMV at risk", money(result["gmv_risk"]), "USD / hour", "", "Confidence adjusted", money(result["adjusted_risk"]))
with kpis[3]:
    kpi_card("Monitored traffic", f"{result['transactions_monitored']/1000:.1f}K", "100%", "good", "Merchants / providers", f"{transactions['merchant'].nunique()} / {transactions['provider'].nunique()}")

st.write("")
map_col, incident_col = st.columns([1.55, 1], gap="medium")
clicked_incident: dict | None = None
with map_col:
    st.markdown('<span class="pt-eyebrow">GEOGRAPHIC OPERATIONS</span><div class="pt-panel-title">LATAM payment network</div>', unsafe_allow_html=True)
    render_map(result["countries"])
    country_buttons = st.columns(3)
    for col, code in zip(country_buttons, ("MX", "CO", "BR")):
        country = result["countries"][code]
        with col:
            if st.button(f"{COUNTRY_NAMES[code]} · {country['status'].title()}", key=f"country_{code}", width="stretch"):
                match = next((item for item in result["incidents"] if item["country"] == code), None)
                if match:
                    clicked_incident = match
                else:
                    st.toast(f"{COUNTRY_NAMES[code]} is healthy and within its own baseline", icon="✓")

with incident_col:
    st.markdown('<span class="pt-eyebrow">INCIDENT PRIORITY</span><div class="pt-panel-title">What needs attention</div><div class="pt-panel-sub">Sorted by confidence-adjusted economic impact</div>', unsafe_allow_html=True)
    if not result["incidents"]:
        st.markdown('<div class="pt-empty"><div><i>✓</i><h3>No incidents require attention</h3><p>PagoTotal is monitoring normal payment variation without firing a false alert.</p></div></div>', unsafe_allow_html=True)
    else:
        for incident in result["incidents"]:
            render_incident_card(incident)
            if st.button("View investigation →", key=f"open_{incident['id']}", width="stretch"):
                clicked_incident = incident

st.write("")
st.markdown('<span class="pt-eyebrow">LIVE PERFORMANCE</span><div class="pt-panel-title">Conversion vs expected baseline</div>', unsafe_allow_html=True)
chart_data = result["chart"].melt("timestamp", var_name="Series", value_name="Conversion")
chart_data["Conversion"] *= 100
chart = (
    alt.Chart(chart_data)
    .mark_line(strokeWidth=2.4)
    .encode(
        x=alt.X("timestamp:T", title=None, axis=alt.Axis(format="%H:%M", labelColor="#718a96", grid=False)),
        y=alt.Y("Conversion:Q", title=None, scale=alt.Scale(domain=[max(35, chart_data["Conversion"].min() - 5), 95]), axis=alt.Axis(labelExpr="datum.value + '%'", labelColor="#718a96", gridColor="rgba(142,190,203,.10)")),
        color=alt.Color("Series:N", scale=alt.Scale(domain=["Actual", "Expected"], range=["#69e4df", "#6f8792"]), legend=alt.Legend(orient="top-right", title=None, labelColor="#9bb0b8")),
        strokeDash=alt.StrokeDash("Series:N", scale=alt.Scale(domain=["Actual", "Expected"], range=[[1, 0], [7, 6]]), legend=None),
        tooltip=[alt.Tooltip("timestamp:T", title="Time", format="%H:%M"), alt.Tooltip("Series:N"), alt.Tooltip("Conversion:Q", format=".1f", title="Conversion %")],
    )
    .properties(height=245)
    .configure_view(stroke="rgba(142,190,203,.14)", fill="rgba(11,25,37,.58)")
)
st.altair_chart(chart, width="stretch")

with st.expander("Data & calculation notes"):
    st.write(
        "The app reads all three attached CSV files. Historical rows form the expected conversion baseline; "
        "the latest window is copied and modified by the selected injector. GMV at risk is calculated from "
        "excess declines × average USD ticket ÷ incident-window hours, with merchant priority used only as a small prioritization weight."
    )
    st.dataframe(
        pd.DataFrame(
            {
                "Source": ["transactions_normal.csv", "merchant_financial_config.csv", "exchange_rates.csv"],
                "Rows": [len(transactions), len(config), len(rates)],
                "Purpose": ["Baselines, live window, diagnosis evidence", "Merchant priority and financial context", "Currency conversion fallback"],
            }
        ),
        hide_index=True,
        width="stretch",
    )

if clicked_incident is not None:
    show_incident(clicked_incident, st.session_state.scenario == "random")
