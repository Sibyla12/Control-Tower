#!/usr/bin/env bash
# Stops the API and dashboard servers started by run_demo.sh.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$REPO_ROOT"

for pid_file in .demo_api.pid .demo_frontend.pid; do
  if [ -f "$pid_file" ]; then
    pid="$(cat "$pid_file")"
    if kill "$pid" 2>/dev/null; then
      echo "Stopped process $pid ($pid_file)"
    fi
    rm -f "$pid_file"
  fi
done
