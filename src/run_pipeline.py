"""Runs the full Control Tower detection-to-diagnosis pipeline with one command.

Chains every stage from raw live transactions through human review, so that
after injecting new data (see inject_live_incident.py) a single command
regenerates everything the API serves:

    python3 src/run_pipeline.py

Each stage is its own standalone script (own INPUT_PATH/OUTPUT_PATH globals),
so stages are run as subprocesses rather than imported, to avoid clashing
module-level names between them.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# multisegment_aggregator.py feeds /dashboard directly from raw transactions,
# independent of the detection -> ... -> human_review chain below.
AGGREGATION_STAGE = "src/multisegment_aggregator.py"

DETECTION_STAGES = [
    "src/detection_aggregator.py",
    "src/adaptive_windows.py",
    "src/anomaly_scanner.py",
    "src/anomaly_validator.py",
    "src/incident_clusterer.py",
    "src/root_cause_engine.py",
    "src/incident_consolidator.py",
    "src/financial_impact.py",
    "src/priority_engine.py",
    "src/recommendation_engine.py",
    "src/human_review.py",
]


def run_stage(script_path: str) -> None:
    print(f"\n{'=' * 70}\nRunning {script_path}\n{'=' * 70}")
    result = subprocess.run(
        [sys.executable, script_path],
        cwd=REPO_ROOT,
    )
    if result.returncode != 0:
        raise SystemExit(
            f"Pipeline stopped: {script_path} exited with code "
            f"{result.returncode}"
        )


def main() -> None:
    run_stage(AGGREGATION_STAGE)

    for stage in DETECTION_STAGES:
        run_stage(stage)

    print(
        "\nPipeline completed. /dashboard and /incidents will reflect "
        "the new data on their next request (no restart needed)."
    )


if __name__ == "__main__":
    main()
