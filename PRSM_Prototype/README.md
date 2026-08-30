# PRSM prototypes

Two coordinated prototypes for a payment-operations incident intelligence product.

## 1. HTML / CSS / JavaScript

Open `html/index.html` directly in a browser, or run `./run_demo.sh` from
the repo root for a one-command bootstrap. It polls the real Control Tower
API (`API_URL` in `html/app.js`) and shows live network status, incidents,
and conversion data — no invented numbers, no demo scenarios. It also has
an "Ask PRISM" chat (grounded in the same live data), a "Trial by fire"
panel to inject and detect a judge-named incident with no terminal, and an
"Executive view" toggle that swaps the analyst dashboard for a one-screen
decision brief. See [DASHBOARD_GUIDE.md](DASHBOARD_GUIDE.md) for a
field-by-field explanation of every button and panel.

## 2. Python + Streamlit

Open `streamlit/start.command` on macOS, or follow `streamlit/README.md`. This version reads the three included CSV files and recalculates baselines, live conversion, incident evidence, confidence, GMV at risk, and priority. It still exposes the deterministic scenario injectors (Normal, Brazil provider failure, Mexico bank failure, Both, Random incident, Ambiguous, Reset) described in `streamlit/README.md`, useful for offline pitch rehearsal.

## Shared product behavior

Both prototypes include:

- LATAM network view for Mexico, Colombia, and Brazil
- Network conversion, active incidents, and GMV-at-risk KPIs
- Incident queue sorted by confidence-adjusted economic impact
- Actual conversion vs expected historical behavior
- Incident investigation with root-cause evidence, confidence, financial impact, and cautious recommendations

## Product principle

Traditional monitoring tells payment teams that conversion dropped. PRSM tells them what broke, proves why, quantifies what it costs, and recommends what a human operator should investigate next.

## Reliability boundary

The HTML version reflects the live Control Tower API and pipeline directly. The Streamlit version uses deterministic injectors but calculates the resulting metrics from the attached data. Neither is a production-grade anomaly detector — both are MVP demonstrations of the product contract.
