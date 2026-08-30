# PagoTotal Control Tower — HTML prototype

Open `index.html` in a modern browser, or run `./run_demo.sh` from the repo
root to bootstrap everything (venv, pipeline, API, this dashboard) in one
command. An internet connection is needed to reach the live Control Tower
API (`API_URL` in `app.js`) unless you're running it locally.

The dashboard polls the real Control Tower API (`/dashboard`, `/incidents`,
`/unresolved-candidates`) every 20 seconds: status strip, KPIs, LATAM map,
incident queue, and the conversion chart all reflect real data computed
from `data/generated/live_segment_windows.csv` and the incident pipeline —
no invented numbers. If the API is unreachable, the strip shows "LIVE DATA
UNAVAILABLE" instead of silently substituting fake data.

Click a country marker or an incident card to open the investigation panel.
The "Executive view" toggle (top right) swaps the whole dashboard for a
simplified decision brief. "Ask PRISM" (floating button, bottom right) is a
chat grounded in the same live data. "Trial by fire" (next to the time-view
toggle) injects and detects a judge-named incident combination entirely
from the browser, with a matching reset. See
[../GUIA_DEMO_COMPLETA.md](../GUIA_DEMO_COMPLETA.md) for what every button
does.
