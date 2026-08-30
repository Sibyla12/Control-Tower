# Complete dashboard guide — what everything is and what it's for

This document explains **every button, panel, and screen** of the Control
Tower / PRISM dashboard, so you can walk someone through it confidently
without relying on memory. Everything described here is real — nothing is
invented or "fake" simulated: every number comes from the real detection
pipeline running over simulated traffic.

For the timed 4-minute script (what to say and when), use
[DEMO_GUIDE.md](DEMO_GUIDE.md). This document is the background reference:
what each piece is and why it exists.

---

## 1. Top bar

| Element | What it is | What it's for |
|---|---|---|
| **PRISM logo** | Product brand | — |
| **Signals (Signal caution / Critical signal)** | Two bracket-shaped counters, top left | Counts how many incidents are medium priority (caution, amber) and how many are critical (critical, red). A one-second glance at overall state before reading anything else. Only shown in Analyst mode. |
| **LIVE SIMULATION** | Label with an animated green dot | Makes clear you're watching live simulated traffic, not a static mockup — the system is actually running. |
| **Clock** | Local browser time | A real-time reference, unrelated to the data's own timestamps (which belong to the simulation). |
| **Notifications icon** | Bell | Visual only in the dashboard; real notifications reach the phone via ntfy.sh (push notifications), configured separately on the backend. |
| **"Analyst view" / "Executive view" toggle** | Button that switches the whole screen's mode | See section 4. The most important thing you can show: same data, two different audiences. |
| **"OP" avatar** | Represents the user (Payment Operations) | Decorative — identifies the role of whoever is using the dashboard. |

---

## 2. Time selector (below the top bar)

Three buttons in a row:

- **"Live now"** — the current, live state. The default mode.
- **"Replay: before the incidents (10:00–10:02)"** — rewinds the clock and
  shows exactly how the dashboard looked *before* the incidents started
  (healthy network, 0 incidents). Not an animation or an invented version:
  it uses the API's `?as_of=` parameter, which filters the real data down
  to only what existed up to that minute. Useful for proving the system
  doesn't "always show incidents" — the healthy state is real and
  verifiable.
- **"Trial by fire"** — opens the live injection panel. See section 8.

---

## 3. Analyst view (the full view, default)

### 3.1 Status strip (the wide bar right below the time selector)

Shows the network's overall state in one sentence: "SYSTEM HEALTHY" /
"Multiple live incidents detected and prioritized", with a short
description below, and on the right when it last updated and the baseline
window used (6 hours).

### 3.2 Main KPIs (4 cards)

| Card | What it shows |
|---|---|
| **Network conversion** | % of approved payments over attempts, network-wide, compared against what's expected |
| **Active incidents** | How many confirmed incidents exist right now, and what the highest priority is |
| **GMV at risk** | Money at risk per hour (USD), with a "confidence-adjusted" version below |
| **Monitored traffic** | How many transactions are being watched and how many merchants/providers it covers |

### 3.3 Executive Summary (panel with 4 cards + breakdown)

The financial rollup of **all** active incidents combined: total economic
impact, adjusted GMV at risk (vs. gross unadjusted), platform revenue at
risk (fees), and merchant economic impact (lost margin). Below it,
**"Where the current GMV at risk concentrates"** — a series of chip rows
showing, per dimension (root cause, country, provider, bank, decline
code), what percentage of the total risk each value represents. This is a
diagnostic signal ("where is the problem concentrated?"), explicitly
labeled as *not* the confirmed root cause.

### 3.4 Geographic Operations (the map)

A 3D orthographic globe with Mexico, Colombia, and Brazil marked. Each
country changes color based on its status (green = healthy, amber =
investigating, red = incident), measured against **its own historical
baseline**, not an absolute number — the map's caption makes this clear.
Click any country to see its detail (or expand/collapse it in the list
below the map).

### 3.5 Incident Priority (incident list)

Each card is a confirmed incident, sorted by economic impact: priority
(P1–P4) + severity, how long ago it started, title, subtitle, and three
quick metrics (conversion drop, diagnosis confidence, GMV at risk per
hour). Click any of them to open the full detail (section 5).

### 3.6 Under Investigation

Anomalies the system detected statistically but that **didn't reach the
0.70 confidence threshold** required to declare them a confirmed
incident. Instead of forcing a diagnosis with weak evidence, the system
leaves them here, explicitly marked as "not enough evidence yet." This is
one of the project's most important design decisions — we chose to be
honest about uncertainty rather than invent a cause.

### 3.7 Live Performance (the chart)

Real conversion vs. expected over the last 30 minutes, with a dotted red
line marking the exact moment the incident was detected. The same kind of
chart an on-call engineer would see on a real monitoring dashboard.

---

## 4. Executive view (the "Executive view" toggle)

Built for someone who needs to decide fast, not diagnose. It's a **pure
display filter** — it doesn't change any data or make a different API
request, it only hides/shows what's already loaded.

| Block | What it shows |
|---|---|
| **Big status (NORMAL / WARNING / CRITICAL)** | The same status classification as the status strip, in large colored text |
| **Active incidents** | Total count + breakdown "1 P1 · 2 P2" |
| **Financial exposure** | The same $/hour as the "GMV at risk" KPI |
| **Trend** | "Recovering" / "Worsening" / "Stable" — compares conversion right now against ~5 minutes ago, using the same real chart data |
| **Country chips** | A quick look at which country(ies) are in trouble, same status as the map |
| **One card per P1 incident** | Country, confidence %, the problem explained in one plain-language sentence (no jargon), and the recommended action — with a **"Review & decide →"** button that opens the full detail for that specific incident |
| **Conversion chart** | The same one from Analyst mode, to visually back up the "Trend" reading |

What gets **hidden** in this mode: the breakdown by cause/country/
provider/bank, the geographic map, the full incident list, the "Under
investigation" panel, and inside each incident's detail — technical root
cause, evidence, diagnosis confidence, segment breakdown, and financial
projections.

---

## 5. Incident detail (the side panel / "drawer")

Opens when you click any incident. Contains, in order:

1. **Title + executive summary** — one plain-language sentence with the
   economic impact.
2. **"Recognized pattern" banner** (if applicable) — appears only when
   this exact type of failure (same root cause, same dimensions, same
   decline code) has already been seen in an earlier pipeline run, with
   the real date/time it was first and most recently seen. This is
   "incident memory" — the system recognizes repeated patterns.
3. **AI Analysis** — a "Generate analysis" button that calls GPT-4o with
   the incident's structured data and returns a natural-language
   narrative. Without `OPENAI_API_KEY` configured, it gives an explicit
   503 error instead of failing silently.
4. **Root cause** *(Analyst mode only)* — a tree/summary of the
   diagnosed root cause (provider, bank, merchant, payment method, or
   decline code).
5. **Evidence** *(Analyst mode only)* — a checklist of the statistical
   evidence backing the diagnosis.
6. **Priority** — the assigned priority, how much money is at risk per
   hour, the confidence %, and (if applicable) this incident's Pareto
   rank against the other active ones.
7. **Operational Playbook** — who owns it operationally, the escalation
   level, and the **recommended action** — the same text also shown in
   Executive view.
8. **Observed vs Expected** *(Analyst mode only)* — a direct comparison
   of the observed approval rate against the expected one.
9. **Economic Impact** — GMV at risk, how much is recoverable, affected
   attempts, and excess declines.
10. **Projections** *(Analyst mode only)* — impact projection at 4h, 24h,
    and 7 days, with a recovery curve assuming a 6h MTTR (mean time to
    resolve).
11. **Diagnosis Confidence** *(Analyst mode only)* — a confidence bar for
    the diagnosis and how reliable the historical baseline it was
    compared against is.
12. **Segment Breakdown** *(Analyst mode only)* — a Pareto table of which
    specific segments (provider/bank/merchant/method) explain what share
    of the excess declines.
13. **Human Decision** — see section 6.

---

## 6. Human Decision (approve / modify / reject / execute)

No incident ever executes its recommendation automatically. A human has
to decide:

- **Approve** — approves the recommended action as-is.
- **Modify** — opens a textarea to write a different action before
  approving.
- **Reject** — rejects the recommendation.
- **Execute** — only available after approving; marks the action as
  executed (with a timestamp).

It asks for your name (minimum 2 characters) and an optional comment.
Every decision is recorded in `recommendation_audit_log.csv` — reviewer,
comment, previous action, new action, and timestamp — visible via
`GET /audit-log`. This is the "human control" part of the system: PRISM
recommends, but never decides on its own.

---

## 7. Ask PRISM (the floating button, bottom right)

An AI chat (GPT-4o with function-calling) that answers questions about
the system's **current, real** state — it can never invent data because
it literally has no other source: every answer comes from calling the
same functions the normal API endpoints use (`/dashboard`, `/incidents`,
`/incidents/{id}/segments`, `/unresolved-candidates`). Example questions
you can ask live:

- "How many P1 incidents are there right now?"
- "What's the highest-priority incident, and which segment explains most
  of its excess declines?" (this forces the agent to chain two tools —
  good for showing it isn't a chatbot with canned answers)
- "Is there any anomaly that hasn't been confirmed yet?"

If it doesn't respond or returns a 503, it's because `OPENAI_API_KEY`
isn't configured on the backend at that moment.

---

## 8. Trial by Fire (inject and detect live, no terminal)

The feature built exactly for the moment a judge says "I'm going to give
you a combination you never rehearsed, let's see if you actually detect
it." All from the browser:

### Form fields

| Field | What it does |
|---|---|
| **Merchant / Provider / Country / Payment method / Issuing bank** | Each one is optional. Left as "Any", that field acts as a wildcard (matches every value of that dimension). If the judge says "an Adyen problem in Brazil", set Provider=Adyen, Country=BR, and leave the rest as "Any". |
| **Decline code** | Required. Which decline code the degraded transactions will carry (e.g. `PROCESSOR_ERROR` for a technical failure, `SUSPECTED_FRAUD` for a fraud spike). |
| **Approval rate during incident** | How severe the drop is (0 to 1). Lower = more severe incident = detected faster. |
| **Duration (minutes)** | How many minutes of degraded traffic get generated. The system needs at least 30 matching attempts to validate statistically — very specific combinations with few minutes might not reach that minimum. |

### Buttons

- **Randomize** — fills the form with a random, valid combination, for a
  one-click demo.
- **Inject & run detection** — injects real transactions into the live
  feed and runs the full 11-stage pipeline (~10-15 seconds, with a real
  progress bar showing which stage it's on). When it finishes, it
  honestly reports one of three outcomes:
  - **Confirmed as an incident** (crossed the 0.70 confidence threshold)
  - **Flagged as an unresolved candidate** (detected but didn't reach
    0.70 — shows up in "Under Investigation")
  - **Not detected** (didn't even validate statistically — suggests
    lowering the approval rate further or increasing the duration)
- **Reset live feed to baseline** — amber button below "Inject & run
  detection" — undoes **every** injection made so far and returns the
  feed exactly to its original committed state, rerunning the pipeline.
  Asks for confirmation before running. Useful for leaving everything
  clean before presenting, or between tests.

**Security note:** if two people use Trial by Fire (or Reset) at the same
time, the system immediately rejects the second request with a clear
message ("one is already running, wait 10-15s") instead of letting them
race on the same files — that would otherwise risk corrupting the system
or hanging it.

---

## 9. Questions you'll probably get asked (and how to answer them)

**"Is this made-up data?"**
No — it's *simulated* traffic (it doesn't come from a real payment
processor because this is a demo), but every number on screen was
genuinely computed from that simulated traffic, running the same
statistical pipeline that would run over real data. Nothing is
hardcoded in the frontend.

**"What happens if the system gets it wrong?"**
That's why "Under Investigation" exists — the system prefers to say "I
don't know yet" rather than invent a cause with weak evidence. And that's
why Human Decision exists — nothing executes without a person approving
it.

**"Why trust a 0.70 threshold?"**
It's documented as an explicit trade-off decision in
[docs/DECISIONS.md](../docs/DECISIONS.md) — actionability vs. diagnostic
honesty.

**"How do I know Trial by Fire isn't rigged/hardcoded?"**
Because "Reset" exists — you can run it, watch it get detected, reset,
and run it again with a different combination as many times as you want.
