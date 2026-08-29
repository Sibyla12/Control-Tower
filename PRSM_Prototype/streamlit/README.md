# PagoTotal Control Tower — Streamlit prototype

This prototype reads the three included CSV files and calculates every displayed KPI, country baseline, incident metric, confidence score, evidence statement, and GMV-at-risk estimate from the data.

## Run locally

### One-click on macOS

Double-click `start.command`. The first run creates an isolated environment and installs the required packages; later runs reuse it.

### From a terminal

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

## Demo flow

Use the controls from left to right: Normal → Brazil provider failure → Mexico bank failure → Both → Random incident → Ambiguous → Reset.

- Click a country status or **View investigation** to open the root-cause panel.
- The Random scenario cycles through valid data combinations. Its ground truth stays hidden until **Reveal injected failure**.
- The Ambiguous scenario intentionally refuses to select a root cause and shows competing hypotheses.

## Model boundary

This is a reliable hackathon demo engine, not a production detector. It uses deterministic decline injection and transparent statistical calculations over a historical/live split. Productionization would require seasonality-aware baselines, streaming ingestion, persistent incident state, alert deduplication, and formal validation of confidence thresholds.
