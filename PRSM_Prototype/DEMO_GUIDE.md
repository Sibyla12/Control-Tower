# PRSM — 4-minute demo guide

## 0:00–0:30 — Establish the normal state

Start on **Normal**.

> “PRSM watches conversion relative to what is historically expected for each market. Right now, 50,000 payment attempts are within normal variation, so the system does not bother the operator.”

Point to the healthy country states and the zero-incident queue.

## 0:30–1:20 — Isolate the Brazil provider failure

Select **Brazil provider failure**.

> “A provider starts over-declining only in Brazil. PRSM detects the deterioration, isolates it to dLocal, and confirms that comparable providers remain healthy.”

Open the Brazil incident. Show observed vs expected, conversion loss explained, evidence, confidence, and GMV at risk.

## 1:20–2:05 — Separate two simultaneous incidents

Select **Both**.

> “At the same time, Banorte fails only for Merchant C in Mexico. PRSM does not collapse both events into a generic global alert. It creates two independent incidents and ranks Brazil first because its confidence-adjusted economic impact is higher.”

Open P2 briefly to show that the evidence and recommendation are different.

## 2:05–2:45 — Demonstrate measured uncertainty

Select **Ambiguous**.

> “When the evidence is weak, the product refuses to invent a root cause. Two hypotheses remain plausible, so the recommendation is to collect more transactions before acting.”

Show the 51% / 43% hypothesis split.

## 2:45–3:35 — Run the blind test

Select **Random incident** and open the investigation.

> “The simulator selected a combination we did not reveal to the interface. The system diagnosed it from the same incident contract.”

Present the diagnosis, then click **Reveal injected failure**.

## 3:35–4:00 — Close on value

> “Others tell payment teams that conversion dropped. PRSM tells them what broke, proves why, quantifies what it costs, and models the next investigation—reducing time to understanding from hours to seconds.”

Use **Reset** before questions so the product returns to a calm, credible operating state.
