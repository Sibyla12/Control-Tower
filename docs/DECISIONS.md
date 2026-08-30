# Decision log

Real trade-offs made while building Control Tower / PRSM, not a changelog.
Each entry states the alternatives that were actually considered, what we
picked, and what we gave up by picking it.

## 1. How PRISM decides a conversion drop is an incident

**Options considered:** fixed conversion thresholds, pure statistical anomaly
detection, historical baseline + adaptive thresholds, LLM-based anomaly
detection.

**Decision:** historical baseline + adaptive thresholds, combining
deviation, statistical confidence, volume, persistence, and economic impact
(`src/baseline.py`, `src/hierarchical_baseline.py`, `src/anomaly_scanner.py`,
`src/anomaly_validator.py`).

**Trade-off:** early detection vs. false positives. Fixed thresholds are
simple but ignore normal differences across merchants, providers, countries,
and payment methods — the same absolute conversion rate can be healthy for
one segment and a crisis for another. Pure statistical detection catches
deviation but can flag events that are statistically unusual yet
financially irrelevant. LLM-based detection would add interpretive
flexibility but no auditable, reproducible threshold — unacceptable for a
system whose output drives P1 pages. Historical baselines per segment are
more context-aware and explainable, but they need enough historical volume
to be reliable and react more slowly in low-traffic segments (see
`detection_level_baselines.csv` and the `baseline_reliable` flag). We
accepted that slower reaction in thin segments to reduce alert fatigue and
keep every flagged incident explainable in terms an operator can verify.

## 2. Storage: CSV files vs. a SQL database

**Options considered:** keep every pipeline stage's output as a CSV in
`data/`, or move to a SQL database (e.g. SQLite/Postgres) with the pipeline
writing to and the API reading from tables.

**Decision:** stay on CSV files, one per pipeline stage, read fresh by the
API on every request — no caching, no database.

**Trade-off:** inspectability and zero-setup reproducibility vs. concurrency
safety and query power. CSVs mean every intermediate artifact
(`detection_windows.csv`, `clustered_incidents.csv`,
`consolidated_incidents.csv`, ...) can be opened and diffed by hand during
the demo or a judge review, and the whole pipeline runs with no database to
provision. The cost is that CSV writes are not transactional — two
processes writing the same file concurrently can corrupt it — and there is
no indexed querying, so the API pays a full-file pandas read on every
request. We accepted that cost because the demo's write pattern is
single-writer (the pipeline runs, then the API only reads, plus the small
`reviewed_incidents.csv`/`incident_memory.csv`/`notified_incidents.json`
state the API itself owns) and because a database would add setup friction
without changing what a judge can observe. If Control Tower had to support
concurrent human reviewers or larger data volumes, SQL would be the right
next step — see the "Evaluating SQL" note in
[docs/TECHNICAL_GUIDE.md](TECHNICAL_GUIDE.md) for the migration path we
scoped but did not build.

## 3. Low-confidence anomalies: force a root cause, drop them, or surface them as unresolved

**Options considered:** (a) always assign the best-available root cause to
every statistically validated anomaly, even below the confidence gate, so
nothing is left undiagnosed; (b) silently drop candidates that don't clear
the confidence gate; (c) surface every sub-threshold candidate explicitly as
"not enough evidence yet," with no forced diagnosis.

**Decision:** option (c). `incident_consolidator.py` only promotes a
candidate to a real incident at `confidence_score >= 0.70`; everything below
that is written to `unresolved_incident_candidates.csv` and served from
`GET /unresolved-candidates`, rendered in the dashboard's "UNDER
INVESTIGATION" panel instead of the incident queue.

**Trade-off:** actionability vs. honesty. Forcing a root cause onto every
anomaly gives operators zero ambiguity and maximizes apparent detection
coverage, but risks confidently misdiagnosing a segment and sending a team
to fix the wrong thing — which is worse than not diagnosing it yet. Dropping
sub-threshold candidates silently avoids false diagnoses but hides real
signal an operator would want to know about, and would look like a
detection blind spot when a judge or an operator later noticed the anomaly
in the raw data. We accepted a UI that sometimes says "we see something
unusual, we don't have enough evidence to say what yet" — a weaker-sounding
claim than a confident wrong one, and a truthful one.
