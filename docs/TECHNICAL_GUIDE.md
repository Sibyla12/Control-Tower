# Control Tower: Complete Technical Guide

This document explains the system architecture, end-to-end data flow, the
responsibility of every module, the statistical methods, and the controls used
to reduce false positives.

## 1. Purpose

Control Tower turns payment attempts into actionable incidents. It does not stop
at detecting a conversion drop: it also attempts to identify the root cause,
estimate financial exposure, assign an operational priority, recommend actions,
and keep a human reviewer responsible for the final decision.

The LATAM demo includes:

- Countries: MX, CO, and BR.
- Merchants: Merchant_A, Merchant_B, and Merchant_C.
- Providers: Stripe, Adyen, and dLocal.
- Methods: card, wallet, cash_in_store, PSE, and PIX.
- Country-specific issuing banks.

All transactions, rates, incidents, and amounts are synthetic.

## 2. End-to-end architecture

```text
60-day transaction history              Multi-segment live traffic
transactions_history_60_days.csv        transactions_live_multisegment.csv
              |                                      |
              v                                      v
     historical baselines              minute/dimension aggregation
              |                                      |
              +------------- comparison -------------+
                                     |
                                     v
                            anomaly candidates
                                     |
                          FDR + persistence
                                     |
                                     v
                           validated windows
                                     |
                    temporal clustering by segment
                                     |
                   diagnosis and root consolidation
                                     |
          financial impact -> priority -> recommendations
                                     |
                       human review + audit trail
                                     |
                              FastAPI -> UI
```

## 3. Data contracts

### Historical transactions

`data/transactions_history_60_days.csv` contains 500,000 attempts over 60 days.
It includes payment dimensions, status, decline code, amount, currency, retry
relationships, recovery, and processing latency.

Only original attempts are used to build baselines. Mixing retries into the
baseline would artificially lower expected conversion: original attempts in the
simulation convert near 90%, while retries recover at a much lower rate.

### Live transactions

`data/transactions_live_multisegment.csv` contains 12 minutes with 1,200
attempts per minute. Every row keeps `injected_incident_id`. This is laboratory
ground truth and would not exist in a production payment stream.

Injected incidents:

- INC-001: Adyen degradation in Brazil with `PROCESSOR_ERROR`.
- INC-002: BBVA unavailability for Merchant_A in Mexico with
  `ISSUER_UNAVAILABLE`.

### Financial configuration

- `merchant_financial_config.csv`: fees, margin, retry recovery, merchant
  criticality, and monthly volume.
- `exchange_rates.csv`: fixed demo exchange rates to USD.

## 4. Simulation modules

### `src/simulator.py`

Generates the historical dataset. It models hourly traffic, country, method,
provider, bank, approval, amount, currency, retries, and latency. Its validations
ensure that:

- approved payments have no decline code;
- declined payments have a decline code;
- every retry references an existing original transaction;
- `amount_usd` matches the configured exchange rate.

### `src/validate_history.py`

Audits dates, nulls, daily/hourly volume, statuses, and approval by country,
provider, method, and combined segment. This prevents the detector from learning
from a historical dataset that is already degraded.

### `src/incident_injector.py`

Defines `IncidentRule`: active minutes, degraded approval rate, decline code,
and optional dimension filters. If multiple rules match a transaction, the live
simulator selects the rule with the lowest approval rate.

### `src/live_simulator.py`

Generates reproducible live traffic with Python and NumPy seeds. It assigns
amounts and currencies, applies incident rules, and records ground truth. Normal
approval depends on country, provider, and payment method.

## 5. Historical baselines

A baseline is the expected conversion for a comparable segment. Comparing a
granular live segment with a global average can produce false anomalies.

### `src/baseline.py`

Builds the original segment baseline from non-retry attempts and adds `weekday`
and `hour` features.

### `src/hierarchical_baseline.py`

Builds multiple fallback levels. When the most detailed combination lacks enough
history, the system can move to a broader reference.

### `src/baseline_selector.py`

Selects the first reliable baseline in the hierarchy. The current minimum is 30
historical attempts. It returns the expected rate, average ticket, historical
sample size, selected level, and dimensions actually used.

### `src/detection_level_baselines.py`

Builds baselines aligned exactly with every live detection level:

| Level | Main dimensions |
|---|---|
| L1 | provider + country |
| L2 | method + country |
| L3 | merchant + country |
| L4 | bank + country |
| L5 | provider + method + country |
| L6 | merchant + bank + country |

Every level also includes `weekday` and `hour`. The scanner tries an exact match
first and uses the hierarchical selector as a fallback.

An exact baseline is not automatically a better baseline. Small samples produce
unstable expected rates. In the demo, granular L6 baselines with roughly 47
historical attempts increased noise. This finding led to FDR and persistence
controls instead of arbitrary threshold changes.

## 6. Live aggregation and adaptive windows

### `src/detection_aggregator.py`

Aggregates live data by minute across six detection levels. It calculates
attempts, approvals, declines, approval rate, dominant decline code, and ground
truth.

It also stores:

- `injected_records`: injected rows inside the window;
- `injected_share`: `injected_records / attempts`;
- `incident_ids`: every incident ID present, separated by `|`.

These fields distinguish direct evidence, partial contamination, and completely
clean windows.

### `src/adaptive_windows.py`

Uses a fast one-minute window when at least 30 attempts are available. Otherwise
it tries a five-minute rolling window. If neither reaches the minimum, the row is
marked `insufficient_data`.

Five-minute windows sum attempts, approvals, declines, and injected records, then
recalculate `injected_share` and merge all incident IDs.

### `src/multisegment_aggregator.py`

This is an earlier, simpler aggregator that produces
`live_segment_windows.csv`. It remains useful for the dashboard payload, while
`detection_aggregator.py` drives the multi-level statistical pipeline.

## 7. Detection statistics

### `src/anomaly_detector.py`

For observed rate `p_obs`, expected rate `p_exp`, and `n` attempts:

```text
standard_error = sqrt(p_exp * (1 - p_exp) / n)
z = (p_exp - p_obs) / standard_error
drop = p_exp - p_obs
```

This is a one-sided test because the system is looking for conversion drops. A
window becomes a confirmed candidate only when all three conditions hold:

- `n >= 30`;
- the drop is at least 5 percentage points;
- `z >= 2`.

Detection statuses:

- `normal`: the change is within expected variation;
- `potential_anomaly`: a meaningful drop exists, but evidence is still weak;
- `confirmed_anomaly`: all three gates pass;
- `insufficient_data`: live volume is too low.

Severity is assigned only to confirmed anomalies.

### `src/anomaly_scanner.py`

Scans every adaptive window, finds the exact baseline for the same level, and
calls the detector. If no exact reliable baseline exists, it uses hierarchical
fallback. It writes `anomaly_candidates.csv` with the selected baseline, drop,
z-score, severity, and explanation.

Confirmed windows are evaluated against ground truth as:

- direct: `injected_share >= 0.50`;
- partial: 1% through 49.9999%;
- clean: `injected_share == 0`.

A clean confirmed window is a false-positive candidate, not definitive proof of
a false positive.

## 8. False-positive control

The scanner performs hundreds of simultaneous comparisons. Even reasonable
per-test thresholds can produce apparently significant results by chance.

### `src/anomaly_validator.py`

Adds two independent safeguards.

#### Benjamini–Hochberg FDR control

Each one-sided z-score becomes a p-value:

```text
p_value = P(Z >= z_score)
```

Within each minute, the validator sorts `m` tests by p-value and computes:

```text
BH_threshold(i) = (i / m) * 0.05
```

It accepts tests through the largest rank satisfying
`p(i) <= BH_threshold(i)`. This controls the expected false discovery rate; it
does not guarantee that exactly 5% of returned rows are false.

#### Segment persistence

A segment key combines detection level and visible dimensions. An anomaly must
pass FDR for at least two consecutive minutes before receiving
`validated_anomaly = True`. An isolated spike is treated as transient noise.

Reference run:

```text
217 initially confirmed windows
171 windows after FDR
111 windows after FDR + persistence
23 validated windows with injected_share = 0
```

Before these safeguards, 66 confirmed windows had no injected traffic. Reducing
that count to 23 demonstrates meaningful noise removal without losing INC-001 or
INC-002.

### `src/persistent_detector.py`

Implements the conceptual state machine for one segment:

```text
normal -> investigating -> confirmed -> recovering -> normal
```

The dataframe validator applies the persistence principle across all segments.

## 9. From windows to incidents

### `src/incident_clusterer.py`

Groups validated windows by level and visible dimensions. It starts a new
temporal cluster when the gap exceeds two minutes. Every cluster summarizes
duration, attempts, rates, z-scores, dominant code, and ground truth.

### `src/root_cause_engine.py`

Infers cause type from the evidence level:

- provider levels -> `provider`;
- bank levels -> `issuing_bank`;
- merchant level -> `merchant`;
- method level -> `payment_method`.

It merges compatible candidates by dimension, country, and time overlap.

### `src/incident_consolidator.py`

Prevents each symptom from becoming a separate incident. Confidence combines
cause type, validated windows, candidate count, conversion drop, z-score, and
whether the decline code is technical.

Candidates are ordered and strong primary causes are selected sequentially.
Provider and bank roots require at least 0.70 confidence. A second pass absorbs
symptoms sharing country, time, and technical decline code.

Examples:

- Itaú, Bradesco, PIX, and wallet `PROCESSOR_ERROR` signals are absorbed by the
  Adyen + BR root incident.
- Provider-level `ISSUER_UNAVAILABLE` signals can be symptoms of BBVA +
  Merchant_A + MX because an issuer outage crosses providers.

Weak candidates or candidates dominated by normal decline codes remain in
`unresolved_incident_candidates.csv`; the system does not invent a diagnosis.

## 10. Financial impact and priority

### `src/financial_impact.py`

Filters transactions matching the incident dimensions and time range, then
estimates:

```text
expected_approvals = attempts * expected_rate
lost_approvals = max(expected_approvals - actual_approvals, 0)
GPV_at_risk = lost_approvals * average_ticket_USD
recoverable_value = GPV_at_risk * retry_recovery_rate
net_unrecovered_value = GPV_at_risk - recoverable_value
revenue_at_risk = net_unrecovered_value * platform_fee_rate
value_per_minute = net_unrecovered_value / duration
```

This is a counterfactual estimate, not final accounting.

### `src/priority_engine.py`

The composite score weighs financial impact, confidence, duration, merchant
scope, root-cause scope, and merchant criticality.

Operational guardrails prevent confirmed technical failures from being
under-prioritized merely because exposure is below USD 1,000 per minute:

- P1 for an extensive technical failure or critical impact with confidence at
  least 90%;
- P2 minimum for a material technical failure with confidence at least 80% and
  enough exposure or lost approvals;
- all other incidents use score boundaries of 80, 60, and 40.

Every incident stores `priority_reason` for explainability.

## 11. Recommendations and human control

### `src/recommendation_engine.py`

Builds the title, primary action, and recommendations for Payments Operations,
Engineering, Finance, Merchant Success, and executives. Recommendations depend
on cause, priority, confidence, and impact. They do not execute external actions.

### `src/human_review.py`

Enforces these transitions:

```text
proposed -> approved | rejected | modified
modified -> approved | rejected | modified
approved -> executed | rejected | modified
```

It records reviewer, comment, timestamps, action edits, and audit entries.
`rejected` and `executed` are terminal states.

## 12. API and dashboard

### `src/api.py`

Exposes health, dashboard data, incidents, incident detail, assisted analysis,
audit history, reviews, and test notifications. It enriches incidents with the
taxonomy, operational playbook, and priority matrix when those tables exist.

Anthropic can generate a short narrative from structured incident JSON. This
layer does not replace statistical detection or decide priority. It requires API
credentials in environment variables. ntfy notifications are enabled when
`NTFY_TOPIC` is configured.

API reviews persist to `reviewed_incidents.csv` and
`recommendation_audit_log.csv`.

### `PRSM_Prototype/html/app.js`

Loads `/incidents` from the public API, maps the backend contract to the visual
model, and builds a live scenario weighted by attempts. If the API fails, it
falls back to deterministic demo scenarios.

### `PRSM_Prototype/streamlit/`

Contains an alternative prototype. It uses data bundled in its own directory
and is not the primary FastAPI-connected frontend.

## 13. Execution order

Rebuild the demo from the existing live transaction file:

```bash
python src/detection_aggregator.py
python src/adaptive_windows.py
python src/anomaly_scanner.py
python src/anomaly_validator.py
python src/incident_clusterer.py
python src/root_cause_engine.py
python src/incident_consolidator.py
python src/financial_impact.py
python src/priority_engine.py
python src/recommendation_engine.py
python src/human_review.py
```

Regenerate live traffic first when needed:

```bash
python src/live_simulator.py
```

Rebuild historical baselines:

```bash
python src/baseline.py
python src/hierarchical_baseline.py
python src/detection_level_baselines.py
```

## 14. Demo limitations

- Data and ground truth are synthetic.
- Exchange rates are fixed and are not market data.
- CSV files act as persistence; there are no ACID transactions or concurrent
  write locks.
- Thresholds were calibrated for this simulation and must be reevaluated before
  production use.
- The z-test uses a binomial normal approximation; small segments require extra
  caution.
- FDR reduces false discoveries but cannot eliminate every false positive.
- Temporal and dimensional correlation alone does not prove causality.
- Recommendations require human approval.
- Production should replace CSV persistence with durable storage and add
  authentication, authorization, observability, and secure secret management.
