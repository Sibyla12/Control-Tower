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
- method level -> `payment_method`;
- no dedicated detection level resolved a provider/bank/merchant/method (e.g.
  a decline code spiking across several banks or merchants at once, with no
  single one attributable) -> `decline_code`, grouped by matching decline
  code, country, and time overlap.

It merges compatible candidates by dimension, country, and time overlap.

### `src/incident_consolidator.py`

Prevents each symptom from becoming a separate incident. Confidence combines
cause type, validated windows, candidate count, conversion drop, z-score, and
whether the decline code is technical.

Candidates are ordered and strong primary causes are selected sequentially.
Provider, bank, and decline-code roots require at least 0.70 confidence. A
second pass absorbs symptoms sharing country, time, and technical decline
code.

Examples:

- Itaú, Bradesco, PIX, and wallet `PROCESSOR_ERROR` signals are absorbed by the
  Adyen + BR root incident.
- Provider-level `ISSUER_UNAVAILABLE` signals can be symptoms of BBVA +
  Merchant_A + MX because an issuer outage crosses providers.
- Bradesco- and Nubank-issued `PROCESSOR_ERROR` windows across several
  merchants in BR form their own `decline_code` root when no single provider
  or bank explains them, distinct from and additional to the Adyen root
  above.

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

Exposes health, dashboard data, incidents, incident detail, unresolved
(insufficient-evidence) candidates, assisted analysis, audit history,
reviews, and test notifications. It enriches incidents with the taxonomy,
operational playbook, and priority matrix when those tables exist, plus:

- forward-looking cost projections (4h / 24h / 7 days, with an MTTR-based
  recovery haircut so net impact plateaus once the incident is expected to
  be fixed);
- merchant economic impact (GMV at risk adjusted × the merchant's own margin
  rate) alongside platform revenue at risk;
- a network-wide executive summary and a risk-concentration breakdown by
  dimension, both computed over the currently active incidents;
- a Pareto-style ranking of active incidents by adjusted GMV at risk;
- a baseline data-quality signal per incident, sourced from the real
  `baseline_reliable` flags in `detection_level_baselines.csv` for the
  relevant detection level (falling back to a live-evidence-volume heuristic
  for `decline_code`, which has no dedicated level);
- incident memory: incidents are fingerprinted by root cause type,
  provider/bank, country, and decline code (not by
  `consolidated_incident_id`, which is random on every pipeline run) and
  persisted to `data/incident_memory.csv` with a real wall-clock timestamp.
  A later run producing a new ID for an already-seen fingerprint is flagged
  `is_repeat_incident` with the real first/last-seen times and occurrence
  count. Recording is idempotent per incident ID, so repeated polling of
  the same live incident doesn't inflate the count;
- `GET /incidents/{id}/segments`: a per-incident Pareto breakdown. It
  retraces the pipeline's own lineage
  (`consolidated_incidents` → `source_incident_ids` → `root_cause_incidents`
  → `source_candidates` → `clustered_incidents`) to recover the individual
  provider/bank/merchant/method segments folded into the incident, then
  computes `expected_declines`, `actual_declines`, `excess_declines`,
  `contribution_pct`, `cumulative_pct`, and a per-segment confidence
  (`1 - p_value` from that segment's own z-score) - every field derived
  from real pipeline output, nothing fabricated.

OpenAI (`gpt-4o`) can generate a short narrative from structured incident
JSON. This layer does not replace statistical detection or decide priority.
It requires `OPENAI_API_KEY` in the environment; without it, the analysis
endpoint returns a clean 503 instead of executing. ntfy notifications are
enabled when `NTFY_TOPIC` is configured.

API reviews persist to `reviewed_incidents.csv` and
`recommendation_audit_log.csv`.

### `PRSM_Prototype/html/app.js`

Polls `/dashboard`, `/incidents`, and `/unresolved-candidates` from the public
API every 20 seconds and maps the backend contract to the visual model. There
is no demo mode: if the API fails, the status strip shows "LIVE DATA
UNAVAILABLE" instead of substituting fake data.

### `PRSM_Prototype/streamlit/`

Contains an alternative prototype. It uses data bundled in its own directory
and is not the primary FastAPI-connected frontend.

## 13. Execution order

`./run_demo.sh` (repo root) does the full bootstrap in one command: creates
the virtual environment, installs dependencies, runs the pipeline below,
starts the API on port 8000, serves the dashboard on port 5500, and opens
it in the browser — `./stop_demo.sh` shuts both servers down. The rest of
this section is what that script runs internally, useful when running a
piece in isolation.

`src/run_pipeline.py` runs every stage below in order as a single command,
including `multisegment_aggregator.py` (required for `/dashboard`, which the
detection chain alone does not regenerate):

```bash
python src/run_pipeline.py
```

Equivalent to running each stage by hand, from the existing live transaction
file:

```bash
python src/multisegment_aggregator.py
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

To inject a judge-specified, unrehearsed incident during a live demo (any
combination of merchant/provider/country/method/issuing bank, all optional
wildcards), append matching transactions first, then run the pipeline:

```bash
python src/inject_live_incident.py \
  --provider Stripe --country CO --decline-code SUSPECTED_FRAUD \
  --approval-rate 0.35 --minutes 5
python src/run_pipeline.py
```

The API re-reads every CSV on each request, so `/dashboard` and `/incidents`
reflect the new data on their next poll with no restart needed.

Regenerate live traffic from scratch when needed (this replaces
`transactions_live_multisegment.csv`, discarding any injected incidents):

```bash
python src/live_simulator.py
```

Rebuild historical baselines:

```bash
python src/baseline.py
python src/hierarchical_baseline.py
python src/detection_level_baselines.py
```

## 14. Evaluation metrics (KPIs)

Measured on the reference run described throughout this document (12 minutes
of live traffic, two injected incidents: INC-001 Adyen/BR provider and
INC-002 BBVA/MX issuing bank). Every figure below is computed from the actual
pipeline output files, not estimated.

| KPI | What it measures | Result |
|---|---|---|
| Mean Time to Detect (MTTD) | Time from the anomaly's real start to statistical validation | **60 s** for both INC-001 and INC-002 |
| Mean Time to Diagnose (MTTDx) | Time from detection to root cause confidence ≥ 70% | **30 s average** (0 s for INC-001, 60 s for INC-002) |
| Root Cause Accuracy | % of injected incidents diagnosed with the exact correct dimension values | **100%** (2/2: Adyen+BR and BBVA+MX matched exactly) |
| False Alert Rate | % of alerts that reach the dashboard from normal fluctuation | **0%** of the 3 incidents shown to the operator. Before FDR + persistence, 66/217 (30.4%) of raw confirmed windows were noise; after the full validator, 23/111 (20.7%) of validated *windows* were still noise, but none survived clustering and consolidation into a dashboard incident |
| Precision | % of surfaced incidents that correspond to a real injected incident | **100%** (3/3) |
| Recall | % of injected incidents successfully surfaced | **100%** (2/2) |
| F1 Score | Harmonic mean of precision and recall | **100%** |
| Payment Volume at Risk | Estimated monetary exposure across active incidents | **$73,029.60/hour** |
| Affected Transactions | Transactions inside the diagnosed incident scope | **1,552** |
| Excess Declines | Declines above the expected baseline | **257** |
| Anomaly Confidence | Statistical confidence that the deviation is real (1 − p-value) | **99.95%** average across validated ground-truth windows |
| Root Cause Confidence | `confidence_score` of the surfaced incidents | **90.5%** average (100%, 87%, 85%) |

Methodology notes:

- MTTD/MTTDx were computed by replaying `validated_anomalies.csv` minute by
  minute against `incident_consolidator.py`'s own confidence formula, finding
  the earliest cutoff where each injected incident's accumulated evidence
  would have cleared detection and the 0.70 diagnosis threshold.
- Precision, Recall, and Root Cause Accuracy are measured against **n = 2**
  ground-truth incidents — the only ones this synthetic demo injects. A 100%
  score here demonstrates correctness on the available validation set, not a
  production-scale accuracy claim.
- A third incident (`decline_code` / PROCESSOR_ERROR spike) is also linked to
  INC-001's ground truth as a related secondary signal, not a duplicate false
  positive — it is counted as a true positive above but excluded from the
  "exact match" Root Cause Accuracy figure since it identifies a different,
  also-correct facet of the same outage rather than the primary injected rule.

## 15. Demo limitations

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

## 16. Evaluating SQL

CSV was kept for this build (see
[docs/DECISIONS.md](DECISIONS.md#2-storage-csv-files-vs-a-sql-database)); this
section scopes what a migration would actually involve, without committing to
one.

- **What would move.** Every file in `data/*.csv` maps naturally to a table:
  the pipeline stage outputs (`detection_windows`, `clustered_incidents`,
  `consolidated_incidents`, `incidents_with_financial_impact`,
  `prioritized_incidents`, `incidents_with_recommendations`,
  `reviewed_incidents`) and the config tables (`incident_taxonomy`,
  `operational_playbook`, `priority_matrix`, `merchant_financial_config`).
  `reviewed_incidents` is the one table a human-driven UI would actually
  write concurrently (Approve/Modify/Reject/Execute) — everything upstream of
  it is written once per pipeline run by a single process.
- **What it would buy.** Row-level locking instead of whole-file rewrites,
  so a human reviewing an incident can't race a pipeline re-run; indexed
  lookups instead of a full pandas read per API request; and a real place to
  enforce foreign keys (e.g. `source_incident_ids` linking
  `consolidated_incidents` back to `clustered_incidents`) instead of joining
  on string columns in Python.
- **What it would cost.** Every stage script currently reads/writes a CSV
  with its own hardcoded `INPUT_PATH`/`OUTPUT_PATH` and is runnable and
  diffable standalone — a judge or teammate can open any intermediate file
  directly. Moving to SQL means introducing a schema migration tool, a
  connection-managed session per script, and losing the "just open the CSV"
  transparency that the pipeline's `run_pipeline.py` orchestration and the
  trial-by-fire demo flow depend on for inspectability.
- **Recommended path if this became necessary:** SQLite first, not a
  networked database. It keeps the "single file, no server to provision"
  property that makes the CSV approach easy to demo, while adding real
  transactions and indexing; only `reviewed_incidents` needs write
  concurrency, so that table alone could move first with everything else
  staying CSV, if a partial migration was preferred over a full rewrite.
