# Control Tower — Architecture

Two diagrams: the system as a whole, and the detection/diagnosis pipeline in
detail. Both are Mermaid — they render natively on GitHub and in most
markdown viewers (VS Code needs the "Markdown Preview Mermaid Support"
extension, already built into most modern Markdown previewers).

## 1. System overview

```mermaid
flowchart TB
    subgraph SOURCES["Data sources (data/*.csv)"]
        HIST["transactions_history_60_days.csv<br/>500K attempts, 60 days"]
        LIVE["transactions_live_multisegment.csv<br/>live traffic, injected_incident_id ground truth"]
    end

    subgraph SIM["Simulation (src/)"]
        SIMPY["simulator.py"]
        LIVESIM["live_simulator.py"]
        INJECT["inject_live_incident.py<br/>trial-by-fire: appends a judge-named<br/>combination to the live file"]
    end

    subgraph BASE["Baselines (src/)"]
        BASELINE["baseline.py + hierarchical_baseline.py<br/>+ baseline_selector.py<br/>+ detection_level_baselines.py"]
    end

    subgraph PIPE["Detection & diagnosis pipeline (src/, 11 stages)"]
        AGG["multisegment_aggregator.py"]
        DET["detection_aggregator.py -> adaptive_windows.py<br/>-> anomaly_scanner.py -> anomaly_validator.py<br/>(z-test + Benjamini-Hochberg FDR + 2-min persistence)"]
        DIAG["incident_clusterer.py -> root_cause_engine.py<br/>-> incident_consolidator.py<br/>(provider / issuing_bank / merchant /<br/>payment_method / decline_code, confidence >= 0.70)"]
        FIN["financial_impact.py -> priority_engine.py<br/>-> recommendation_engine.py -> human_review.py"]
    end

    subgraph ORCH["Orchestration"]
        RUNALL["run_pipeline.py<br/>runs every stage above, one command"]
    end

    subgraph STATE["Persistent state (data/*.csv + *.json)"]
        LSW["live_segment_windows.csv"]
        REV["reviewed_incidents.csv"]
        AUDIT["recommendation_audit_log.csv"]
        UNRES["unresolved_incident_candidates.csv<br/>(confidence < 0.70 - not shown as an incident)"]
        MEM["incident_memory.csv<br/>(fingerprint -> first/last seen, gitignored)"]
        NOTIF["notified_incidents.json<br/>(ntfy dedup, gitignored)"]
    end

    subgraph CONFIG["Config tables (data/*.csv)"]
        TAX["incident_taxonomy.csv"]
        PLAY["operational_playbook.csv"]
        PRIO["priority_matrix.csv"]
        MERCH["merchant_financial_config.csv"]
    end

    subgraph API["FastAPI backend (src/api.py)"]
        ENDPOINTS["/dashboard  /incidents  /incidents/{id}<br/>/incidents/{id}/segments<br/>/unresolved-candidates  /audit-log<br/>POST /incidents/{id}/review<br/>POST /incidents/{id}/analysis"]
        ENRICH["Enrichment layer: taxonomy + playbook + priority<br/>matrix, cost projections, economic impact,<br/>executive summary, risk concentration,<br/>Pareto ranking, data quality, incident memory"]
        LOOP["Background task:<br/>notify_new_incidents_loop (every 30s)"]
    end

    subgraph EXT["External services"]
        OPENAI["OpenAI gpt-4o<br/>grounded incident narrative"]
        NTFY["ntfy.sh<br/>phone push notifications"]
    end

    subgraph UI["HTML dashboard (PRSM_Prototype/html/)"]
        DASH["Live view: KPIs, map, incident queue,<br/>executive summary, under-investigation panel"]
        DRAWER["Incident drawer: root cause, evidence,<br/>priority, playbook, projections, segment<br/>breakdown, human decision"]
    end

    HIST --> BASE
    LIVE --> AGG --> LSW
    LIVE --> DET
    SIMPY --> HIST
    LIVESIM --> LIVE
    INJECT -->|appends rows| LIVE
    RUNALL -->|runs, in order| AGG
    RUNALL -->|runs, in order| DET

    BASE --> DET
    DET --> DIAG --> FIN --> REV
    FIN --> AUDIT
    DIAG --> UNRES

    REV --> API
    AUDIT --> API
    UNRES --> API
    LSW --> API
    CONFIG --> ENRICH
    MEM --> ENRICH
    ENRICH --> ENDPOINTS
    ENDPOINTS --> ENRICH
    LOOP --> NOTIF
    REV --> LOOP

    ENRICH -. on demand, costs money .-> OPENAI
    LOOP -. new incident detected .-> NTFY

    ENDPOINTS <-->|polls every 20s, GET| DASH
    DASH --> DRAWER
    DRAWER -->|POST review / analysis| ENDPOINTS
```

## 2. Detection & diagnosis pipeline (data flow)

```mermaid
flowchart LR
    LIVE["transactions_live_multisegment.csv"] --> DA["detection_aggregator.py"]
    DA -->|"detection_windows.csv<br/>(6 detection levels)"| AW["adaptive_windows.py"]
    AW -->|"adaptive_detection_windows.csv<br/>(1-min, falls back to 5-min)"| AS["anomaly_scanner.py"]
    AS -->|"anomaly_candidates.csv<br/>z >= 2, drop >= 5pp, n >= 30"| AV["anomaly_validator.py"]
    AV -->|"validated_anomalies.csv<br/>FDR + 2 consecutive minutes"| IC["incident_clusterer.py"]
    IC -->|"clustered_incidents.csv<br/>temporal clusters, gap <= 2 min"| RCE["root_cause_engine.py"]
    RCE -->|"root_cause_incidents.csv<br/>provider / bank / merchant / method / decline_code"| CONS["incident_consolidator.py"]
    CONS -->|"consolidated_incidents.csv<br/>confidence >= 0.70 to be a primary incident"| FI["financial_impact.py"]
    CONS -.->|"confidence < 0.70"| UNRES["unresolved_incident_candidates.csv"]
    FI -->|"incidents_with_financial_impact.csv"| PE["priority_engine.py"]
    PE -->|"prioritized_incidents.csv (P1-P4)"| RE["recommendation_engine.py"]
    RE -->|"incidents_with_recommendations.csv"| HR["human_review.py"]
    HR -->|"reviewed_incidents.csv"| API["src/api.py"]
    UNRES --> API
```

## Reading the diagrams

- **Two independent branches feed `data/`**: the statistical detection chain
  (top-left of diagram 1, detailed in diagram 2) and
  `multisegment_aggregator.py`, which only produces `live_segment_windows.csv`
  for `/dashboard`'s network-wide metrics. `run_pipeline.py` runs both.
- **`incident_consolidator.py` is the only gate** between a statistically
  validated anomaly and a real incident: `confidence_score >= 0.70` and a
  root cause in `{provider, issuing_bank, decline_code}`. Everything else
  lands in `unresolved_incident_candidates.csv` and is shown honestly as
  "not enough evidence," never forced into a diagnosis.
- **The API never trusts a cache**: every endpoint re-reads the relevant
  CSVs on each request, so a pipeline re-run (manual, or via the trial-by-fire
  flow) is visible on the dashboard's next 20-second poll with no restart.
- **OpenAI and ntfy are optional, isolated dependencies.** Without
  `OPENAI_API_KEY` the analysis endpoint returns a clean 503; without
  `NTFY_TOPIC` the notification loop simply never fires. Neither failure
  touches detection, diagnosis, or the rest of the API.
- **`data/incident_memory.csv` and `data/notified_incidents.json`** are
  runtime state written by the running API, not source data — gitignored,
  regenerated on first use.
