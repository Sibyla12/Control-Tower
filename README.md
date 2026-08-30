# Control Tower

A payment operations intelligence platform that detects conversion anomalies,
validates their persistence, diagnoses root causes, estimates financial impact,
and proposes actions subject to human review.

The demo monitors synthetic traffic from Mexico, Colombia, and Brazil across
three merchants, three providers, local payment methods, and issuing banks.

**Live demo:** https://sibyla12.github.io/Control-Tower/ — dashboard hosted
on GitHub Pages (redeploys automatically on every push to
`PRSM_Prototype/html/`, see
[.github/workflows/deploy-pages.yml](.github/workflows/deploy-pages.yml)),
talking to the API on Render. Two caveats if you're reviewing this without
us present: the Render free tier sleeps after inactivity, so the first load
can take 30-50s to wake up; and the "Generate Analysis" button in the
incident drawer needs `OPENAI_API_KEY` configured on the backend to work,
otherwise it returns a clean, explicit error instead of failing silently.

## Capabilities

- A synthetic 60-day history with 500,000 transactions.
- Multi-segment live traffic with controlled incident injection, plus a live
  injector (`src/inject_live_incident.py`) for judge-specified, unrehearsed
  incidents during a demo.
- Historical baselines aligned with every live detection level.
- Adaptive one-minute and five-minute windows.
- Statistical detection with FDR correction and temporal persistence.
- Consolidation of symptoms into provider, issuing-bank, or decline-code root
  causes, backed by a taxonomy, operational playbook, and priority matrix.
- Financial impact normalized to USD, with forward-looking cost projections,
  a network-wide executive summary, risk concentration by dimension, and a
  Pareto ranking across active incidents.
- A baseline data-quality signal distinguishing diagnostic confidence from
  how much historical evidence backs the comparison.
- Incident memory: recognizes when an incident's fingerprint (root cause,
  provider/bank, country, decline code) was already seen in an earlier
  pipeline run, with real first/last-seen timestamps.
- A per-incident segment breakdown, tracing the pipeline's own candidate
  lineage to show which underlying segment explains what share of the
  excess declines, Pareto-ranked.
- Explainable P1–P4 prioritization with operational guardrails.
- An "under investigation" view for anomalies without enough evidence to
  confirm a root cause, instead of forcing a guess.
- Team-specific recommendations, AI-assisted narrative analysis (OpenAI), and
  human approval with an audit trail.
- Phone push notifications (ntfy) on new incidents.
- A FastAPI backend and an HTML dashboard connected to the API.

## Repository structure

```text
Control-Tower/
├── src/                     # Simulation, detection, diagnosis, and API
├── data/                    # Synthetic CSV and JSON demo data
├── docs/                    # UI contracts and technical documentation
├── PRSM_Prototype/
│   ├── html/                # HTML/CSS/JavaScript dashboard
│   └── streamlit/           # Alternative Streamlit prototype
├── requirements.txt
└── Procfile
```

## Quickstart (one command)

```bash
./run_demo.sh
```

This creates the virtual environment, installs dependencies, runs the full
detection-to-diagnosis pipeline on the committed live dataset, starts the API
on `http://localhost:8000`, serves the dashboard on `http://localhost:5500`,
and opens it in your browser — no manual steps in between. Stop everything
with `./stop_demo.sh`. Logs are written to `logs/api.log` and
`logs/frontend.log`.

The steps below are the same thing done manually, useful if you want to run
a piece in isolation (e.g. re-run just the pipeline after
`inject_live_incident.py`, or start the API with `--reload` during
development).

## Installation

Python 3.12 or a compatible version is required.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install numpy scipy
```

## API

Start the backend from the repository root:

```bash
uvicorn src.api:app --reload --port 8000
```

Available routes:

- `GET /`
- `GET /health`
- `GET /dashboard`
- `GET /incidents`
- `GET /incidents/{incident_id}`
- `GET /incidents/{incident_id}/segments`
- `GET /unresolved-candidates`
- `POST /incidents/{incident_id}/analysis`
- `GET /audit-log`
- `POST /incidents/{incident_id}/review`
- `GET /notify/test`

Interactive local documentation is available at
`http://127.0.0.1:8000/docs`.

### Environment variables

Both are optional — the API runs fully without them, with the affected
feature degrading cleanly instead of failing.

| Variable | Enables | Without it |
|---|---|---|
| `OPENAI_API_KEY` | `POST /incidents/{id}/analysis` — AI-generated incident narrative (`gpt-4o`) | Endpoint returns `503` with an explicit "not configured" message |
| `NTFY_TOPIC` | Phone push notifications on new incidents, via ntfy.sh | The background notification loop simply never fires |

Production uses the command in the `Procfile`, without `--reload`:

```bash
uvicorn src.api:app --host 0.0.0.0 --port $PORT
```

## HTML dashboard

The dashboard lives in `PRSM_Prototype/html/` and consumes the API configured in
the `API_URL` constant in `app.js`. It always shows live data; if the API is
unavailable, the status strip shows "LIVE DATA UNAVAILABLE" instead of
substituting demo data.

Backend CORS is wide open (`allow_origins=["*"]`), so `index.html` can be
opened directly from disk or served from a static server — either works:

```bash
cd PRSM_Prototype/html
python -m http.server 5500
```

Then open `http://localhost:5500`, or just double-click `index.html`.

## Architecture

Two diagrams (system overview and pipeline data flow), as Mermaid source and
as standalone PNGs, live in
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Decision log

Real trade-offs made while building this system — what was considered, what
was picked, and what was given up — are recorded in
[docs/DECISIONS.md](docs/DECISIONS.md).

## Analytics pipeline

The complete explanation of the architecture, statistics, false-positive
controls, and every module is available in
[docs/TECHNICAL_GUIDE.md](docs/TECHNICAL_GUIDE.md).

```text
transactions_live_multisegment.csv
  → detection_aggregator.py
  → adaptive_windows.py
  → anomaly_scanner.py
  → anomaly_validator.py
  → incident_clusterer.py
  → root_cause_engine.py
  → incident_consolidator.py
  → financial_impact.py
  → priority_engine.py
  → recommendation_engine.py
  → human_review.py
  → api.py
```

Intermediate artifacts are written to `data/` so each stage remains inspectable
and reproducible during the demo.

## Evaluation metrics

Measured on the reference run (12 minutes of live traffic, two injected
incidents). Full methodology in
[docs/TECHNICAL_GUIDE.md](docs/TECHNICAL_GUIDE.md#14-evaluation-metrics-kpis).

| KPI | Result |
|---|---|
| Mean Time to Detect (MTTD) | 60 s |
| Mean Time to Diagnose (MTTDx) | 30 s avg |
| Root Cause Accuracy | 100% (2/2 injected incidents) |
| False Alert Rate (reaching the dashboard) | 0% |
| Precision | 100% (3/3) |
| Recall | 100% (2/2) |
| F1 Score | 100% |
| Payment Volume at Risk | $73,029.60/hour |
| Affected Transactions | 1,552 |
| Excess Declines | 257 |
| Anomaly Confidence | 99.95% avg |
| Root Cause Confidence | 90.5% avg |

Precision, Recall, and Root Cause Accuracy are measured against only 2
ground-truth incidents — the demo's entire injected validation set — not a
production-scale sample.

## Data and assumptions

All data is synthetic. Amounts, financial configuration, retry recovery
probabilities, and latency distributions do not represent the actual performance
of any merchant, bank, or provider.

Exchange rates are fixed simulation assumptions:

| Currency | USD per unit |
|---|---:|
| MXN | 0.055 |
| COP | 0.00025 |
| BRL | 0.20 |
| USD | 1.00 |

They must not be interpreted as current market rates.

## Product principle

The system does more than report a conversion drop. It attempts to explain what
failed, present supporting evidence, quantify the cost, and recommend the next
action without executing it automatically. Operational decisions remain under
human control and are recorded in the audit log.
