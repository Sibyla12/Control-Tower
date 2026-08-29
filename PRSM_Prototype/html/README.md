# PagoTotal Control Tower — HTML prototype

Open `index.html` in a modern browser. No installation or build step is required. An internet connection is needed to reach the live Control Tower API (`API_URL` in `app.js`).

## Live network (default)

On load, the dashboard polls the real Control Tower API (`/dashboard` and `/incidents`) every 20 seconds: status strip, KPIs, LATAM map, incident queue, and the conversion chart all reflect real data computed from `data/live_segment_windows.csv` and the incident pipeline — no invented numbers. If the API is unreachable, the strip shows "LIVE DATA UNAVAILABLE" instead of silently substituting fake data.

## Demo mode

Click **Demo mode** in the DATA SOURCE bar to switch to the deterministic, rehearsed scenarios (useful for a pitch where you don't want live variability):

1. Normal operation
2. Brazil provider failure
3. Mexico bank failure
4. Both incidents, separated and prioritized
5. Random incident / blind test
6. Ambiguous incident / insufficient evidence
7. Reset

These figures are intentionally fixed and offline — calibrated to the attached 50,000-transaction baseline. Click **Live network** to return to real data.

Click a country marker or an incident card to open the investigation panel. In Random Incident (Demo mode), use **Reveal injected failure** after presenting the diagnosis.
