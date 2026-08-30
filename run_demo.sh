#!/usr/bin/env bash
# One-command bootstrap: sets up the environment, regenerates every pipeline
# artifact from the committed live transaction data, starts the API and the
# dashboard, and opens the browser — no other typing required.
#
# Usage:   ./run_demo.sh
# Stop:    ./stop_demo.sh
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"
mkdir -p logs

echo "== Control Tower / PRISM — bootstrap =="

# The codebase uses "X | None" type syntax (PEP 604), which requires Python
# 3.10+. On some machines (notably macOS with only Xcode Command Line Tools
# installed) "python3" silently resolves to a bundled Python 3.9, which
# creates a venv that looks fine but crashes uvicorn on import. Find an
# actually-compatible interpreter instead of assuming "python3" is it.
find_python() {
  for candidate in python3.13 python3.12 python3.11 python3.10 python3; do
    if command -v "$candidate" >/dev/null 2>&1; then
      version="$("$candidate" -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || true)"
      major="${version%%.*}"
      minor="${version##*.}"
      if [ -n "$major" ] && [ -n "$minor" ] && [ "$major" -eq 3 ] 2>/dev/null && [ "$minor" -ge 10 ] 2>/dev/null; then
        echo "$candidate"
        return 0
      fi
    fi
  done
  return 1
}

PYTHON_BIN="$(find_python)" || {
  echo "Error: no Python 3.10+ interpreter found on PATH." >&2
  echo "This project needs Python 3.10 or newer (uses 'X | None' type syntax)." >&2
  echo "Install one (e.g. https://www.python.org/downloads/ or 'brew install python@3.12') and re-run." >&2
  exit 1
}
echo "Using $("$PYTHON_BIN" --version) ($(command -v "$PYTHON_BIN"))"

if [ -d .venv ]; then
  existing_version="$(.venv/bin/python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")' 2>/dev/null || echo "0.0")"
  existing_minor="${existing_version##*.}"
  if [ "${existing_version%%.*}" != "3" ] || [ "$existing_minor" -lt 10 ] 2>/dev/null; then
    echo "[1/5] Existing .venv uses an incompatible Python ($existing_version) — recreating it..."
    rm -rf .venv
  fi
fi

if [ ! -d .venv ]; then
  echo "[1/5] Creating virtual environment (.venv)..."
  "$PYTHON_BIN" -m venv .venv
else
  echo "[1/5] Reusing existing virtual environment (.venv)."
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "[2/5] Installing dependencies..."
pip install -q -r requirements.txt

echo "[3/5] Running the detection-to-diagnosis pipeline on the live dataset..."
python3 src/run_pipeline.py

echo "[4/5] Starting the API on http://localhost:8000 ..."
nohup uvicorn src.api:app --port 8000 > logs/api.log 2>&1 &
echo $! > .demo_api.pid

for _ in $(seq 1 30); do
  if curl -s -o /dev/null http://localhost:8000/health; then
    break
  fi
  sleep 1
done
if ! curl -s -o /dev/null http://localhost:8000/health; then
  echo "API did not become healthy in time — check logs/api.log" >&2
  exit 1
fi

echo "[5/5] Starting the dashboard on http://localhost:5500 ..."
(cd PRSM_Prototype/html && nohup python3 -m http.server 5500 > "$REPO_ROOT/logs/frontend.log" 2>&1 &
 echo $! > "$REPO_ROOT/.demo_frontend.pid")

sleep 1

echo
echo "Everything is running:"
echo "  API:       http://localhost:8000  (logs/api.log)"
echo "  Dashboard: http://localhost:5500  (logs/frontend.log)"
echo "  Stop with: ./stop_demo.sh"
echo

if command -v open >/dev/null 2>&1; then
  open "http://localhost:5500"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://localhost:5500"
fi
