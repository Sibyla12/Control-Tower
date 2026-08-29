# Control Tower — demo guide

The dashboard (`PRSM_Prototype/html/`) always shows **live data** from the real
API — there is no demo/scripted mode anymore. Everything below is driven by
what's actually in `data/` at the moment you present, so run
`python3 src/run_pipeline.py` once before the demo starts to make sure the
data on disk matches this script.

## 0:00–0:30 — Establish the normal state

Open the dashboard. With the baseline data, conversion is within expected
range and the incident queue is empty or shows only the two rehearsed
incidents (see below).

> "Control Tower watches every payment attempt against what's historically
> expected for that merchant, provider, method, country and hour — not a
> flat threshold. Right now the network is within normal variation, so it
> doesn't bother anyone."

## 0:30–1:20 — Isolate the Brazil provider failure

Point to the Brazil country node (critical) and open the Adyen incident card.

> "Adyen starts over-declining only in Brazil. Control Tower isolates it to
> the provider, not the merchants or methods riding on top of it, and shows
> the evidence: validated anomaly windows, the dominant decline code, and
> comparable providers that stayed healthy."

Open the drawer: show ROOT CAUSE, EVIDENCE, PRIORITY, and OPERATIONAL
PLAYBOOK sections.

## 1:20–2:05 — Separate two simultaneous incidents

Point to the Mexico country node (warning) and open the BBVA incident card.

> "At the same time, BBVA fails only for one merchant in Mexico. Control
> Tower doesn't collapse both events into one alert — it creates two
> independent incidents and ranks Brazil P1 over Mexico P2 by
> confidence-adjusted economic impact."

## 2:05–2:45 — Demonstrate measured uncertainty

Scroll to the **UNDER INVESTIGATION** panel below the incident queue.

> "When the evidence isn't strong enough to name a confirmed root cause,
> Control Tower doesn't guess — it keeps the anomaly here, with its real
> confidence level, instead of forcing it into the incident queue."

## 2:45–3:00 — Human decision, live

Open an incident that's still `proposed` and walk through **HUMAN DECISION**:
enter a name, hit Approve (or Modify, to show the editable action text).
Show the drawer re-render with the new status — this is a real call to
`POST /incidents/{id}/review`, not a mock.

## 3:00–3:45 — Trial by fire (judges inject a live incident)

This is the moment a judge names a combination of dimensions the team never
rehearsed. From a terminal, with the backend already running:

```bash
python3 src/inject_live_incident.py \
  --provider <provider named by the judge> \
  --country <country named by the judge> \
  --merchant <merchant, if named> \
  --payment-method <method, if named> \
  --issuing-bank <bank, if named> \
  --decline-code <decline code, e.g. SUSPECTED_FRAUD> \
  --approval-rate 0.35 \
  --minutes 5

python3 src/run_pipeline.py
```

Leave out any flag the judge didn't specify — it stays a wildcard, matching
every value of that dimension (a provider issue across every merchant, a
bank issue across every merchant, etc.). `run_pipeline.py` re-runs all 11
detection/diagnosis stages against the newly appended transactions; the
dashboard picks it up on its next poll (every 20s) with no restart.

> "The simulator just generated traffic matching exactly what you asked for.
> Control Tower doesn't know this combination in advance — it runs the same
> detection and diagnosis pipeline it always runs."

Open the new incident and walk through root cause, evidence, priority and
the recommended action, same as the rehearsed ones.

## 3:45–4:00 — Close on value

> "Other tools tell payment teams that conversion dropped. Control Tower
> tells them what broke, proves why, quantifies what it costs, and
> recommends the next step — reducing time to understanding from hours to
> minutes, without ever executing the fix itself."

## Resetting after the demo

`inject_live_incident.py` only appends — it never deletes. To return to a
clean baseline before the next run-through:

```bash
git checkout -- data/
python3 src/run_pipeline.py
```
