# Control Tower — demo guide

The dashboard (`PRSM_Prototype/html/`) always shows **live data** from the real
API — there is no demo/scripted mode anymore. Everything below is driven by
what's actually in `data/` at the moment you present, so run `./run_demo.sh`
from the repo root once before the demo starts (creates the venv, installs
dependencies, runs the pipeline, starts the API and the dashboard, and opens
the browser — one command, nothing else to type) to make sure the data on
disk matches this script. For a field-by-field explanation of every button
and panel, see [GUIA_DEMO_COMPLETA.md](GUIA_DEMO_COMPLETA.md) (Spanish).

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
rehearsed. Click the **"Trial by fire"** button in the dashboard (next to
the time-view toggle) — no terminal needed. Pick the dimensions the judge
named (leave any unnamed field as "Any" — it stays a wildcard, matching
every value of that dimension), or hit **"Randomize"** for a one-click
version, then **"Inject & run detection"**. It takes ~15-20 seconds: real
transactions get appended to the live feed, the full 11-stage
detection-to-diagnosis pipeline reruns against them, and the panel reports
whether it was confirmed as an incident, flagged as low-confidence, or
missed — the dashboard refreshes automatically either way.

Same mechanism from a terminal, if you'd rather script an exact scenario in
advance:

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

> "The simulator just generated traffic matching exactly what you asked for.
> Control Tower doesn't know this combination in advance — it runs the same
> detection and diagnosis pipeline it always runs."

Open the new incident and walk through root cause, evidence, priority and
the recommended action, same as the rehearsed ones.

## Bonus, if there's extra time or a judge asks

Two features that don't have a dedicated slot in the 4 minutes above, worth
showing if there's room:

- **Executive view** (toggle top right, next to the "OP" avatar) — swaps
  the analyst dashboard for a one-screen brief: overall status, incident
  count, financial exposure, a trend reading, per-country chips, and one
  card per P1 incident with its own confidence and recommended action. It's
  a pure display filter (same data, same API calls) — good for showing that
  the same system serves both an analyst and someone who just needs to
  decide fast.
- **Ask PRISM** (floating button, bottom right) — a chat that answers
  questions about the live incident state by calling the same backend
  functions the REST endpoints use, so it can't invent an answer. Try:
  "how many P1 incidents are there right now?" or, to show it chaining
  more than one lookup, "what's the highest-priority incident and which
  segment explains most of its excess declines?"

## 3:45–4:00 — Close on value

> "Other tools tell payment teams that conversion dropped. Control Tower
> tells them what broke, proves why, quantifies what it costs, and
> recommends the next step — reducing time to understanding from hours to
> minutes, without ever executing the fix itself."

## Resetting after the demo

Injection only appends — it never deletes. Click **"Reset live feed to
baseline"** inside the Trial by fire panel (confirm the dialog) to undo
every injected incident and rerun detection — no terminal needed, same
~15-20 second cost as an injection.

From a terminal, the equivalent is:

```bash
git checkout -- data/
python3 src/run_pipeline.py
```
