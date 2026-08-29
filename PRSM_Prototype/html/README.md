# PagoTotal Control Tower — HTML prototype

Open `index.html` in a modern browser. No installation or build step is required. An internet connection is needed to reach the live Control Tower API (`API_URL` in `app.js`).

The dashboard polls the real Control Tower API (`/dashboard` and `/incidents`) every 20 seconds: status strip, KPIs, LATAM map, incident queue, and the conversion chart all reflect real data computed from `data/live_segment_windows.csv` and the incident pipeline — no invented numbers. If the API is unreachable, the strip shows "LIVE DATA UNAVAILABLE" instead of silently substituting fake data.

Click a country marker or an incident card to open the investigation panel.
