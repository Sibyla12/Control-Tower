# Decision log

Real trade-offs made while building Control Tower / PRISM, not a changelog.
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

**Options considered:**  
(a) always assign the best-available root cause to every statistically
validated anomaly, even below the confidence gate, so nothing remains
undiagnosed;  
(b) silently drop candidates that do not clear the confidence gate;  
(c) surface sub-threshold candidates explicitly as “not enough evidence yet,”
without forcing a diagnosis.

**Decision:** option (c). `incident_consolidator.py` promotes a candidate to a
confirmed root-cause incident only when `confidence_score >= 0.70`.
Candidates below that threshold are written to
`unresolved_incident_candidates.csv`, exposed through
`GET /unresolved-candidates`, and rendered in the dashboard’s
“UNDER INVESTIGATION” panel rather than the confirmed incident queue.

**Trade-off:** actionability vs. diagnostic honesty. Forcing a root cause onto
every anomaly maximizes apparent coverage and gives operators a decisive
answer, but it risks confidently misdiagnosing the affected segment and
sending a team to fix the wrong component. Silently dropping low-confidence
candidates avoids false diagnoses, but hides real signals that operators may
still need to monitor and can make the system appear blind when the anomaly
is visible in the underlying data.

We accepted a system that can explicitly say, “an anomaly is present, but the
current evidence is insufficient to assign a reliable root cause.” That is
less decisive than forcing an answer, but safer and more operationally honest
than directing a team toward the wrong diagnosis.

## 4. Automatic remediation vs. human approval

**Options considered:**
(a) automatically execute the recommended mitigation as soon as an incident
is confirmed;
(b) generate recommendations but leave execution entirely outside the
system;
(c) require a human operator to approve, modify, or reject the
recommendation before execution.

**Decision:** option (c). PRISM generates a proposed action, but the
recommendation remains in `proposed` status until an operator reviews it.
The valid transitions are enforced by the API:
`proposed → approved / modified / rejected`, and only an `approved`
recommendation can move to `executed`. Every decision records the reviewer,
timestamp, comment, previous action, new action, and status transition in
`recommendation_audit_log.csv`.

**Trade-off:** response speed vs. operational control. Fully automatic
remediation would minimize time to mitigation, especially for high-impact
provider incidents, but a wrong diagnosis or overly broad routing change
could worsen conversion, duplicate retries, or move traffic into a less
healthy path. Keeping recommendations completely outside the system would
reduce technical risk, but would make PRISM little more than an alerting
dashboard and would leave no structured decision trail.

We accepted a small delay between diagnosis and execution in exchange for
explicit accountability, reversible actions, and a complete audit trail.
PRISM can recommend and prioritize, but it does not silently change
production payment routing without human approval.