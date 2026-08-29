# PRSM prototypes

Two coordinated prototypes for a payment-operations incident intelligence product.

## 1. HTML / CSS / JavaScript

Open `html/index.html` directly in a browser. It is a polished, dependency-free UX prototype intended for pitch rehearsal, visual review, and interaction design. Every scenario is deterministic and works offline.

## 2. Python + Streamlit

Open `streamlit/start.command` on macOS, or follow `streamlit/README.md`. This version reads the three included CSV files and recalculates baselines, live conversion, incident evidence, confidence, GMV at risk, and priority.

## Shared product behavior

Both prototypes include:

- LATAM network view for Mexico, Colombia, and Brazil
- Network conversion, active incidents, and GMV-at-risk KPIs
- Incident queue sorted by confidence-adjusted economic impact
- Actual conversion vs expected historical behavior
- Normal, single-incident, multiple-incident, and insufficient-evidence states
- Incident investigation with root-cause evidence, confidence, financial impact, and cautious recommendations
- Normal, Brazil provider failure, Mexico bank failure, Both, Random incident, Ambiguous incident, and Reset controls
- Blind-test ground-truth reveal for Random Incident

## Product principle

Traditional monitoring tells payment teams that conversion dropped. PRSM tells them what broke, proves why, quantifies what it costs, and recommends what a human operator should investigate next.

## Reliability boundary

The HTML version is intentionally presentation-deterministic. The Streamlit version uses deterministic injectors but calculates the resulting metrics from the attached data. It is an MVP demonstration of the product contract, not a production-grade anomaly detector.
