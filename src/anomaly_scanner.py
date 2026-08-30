from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from anomaly_detector import detect_anomaly
from baseline_selector import (
    BaselineResult,
    get_expected_baseline,
    load_baselines,
)


INPUT_PATH = "data/generated/adaptive_detection_windows.csv"
OUTPUT_PATH = "data/generated/anomaly_candidates.csv"
DETECTION_BASELINES_PATH = "data/generated/detection_level_baselines.csv"

DETECTION_DIMENSIONS = {
    "L1_PROVIDER_COUNTRY": ["provider", "country", "weekday", "hour"],
    "L2_METHOD_COUNTRY": [
        "payment_method", "country", "weekday", "hour"
    ],
    "L3_MERCHANT_COUNTRY": ["merchant", "country", "weekday", "hour"],
    "L4_BANK_COUNTRY": ["issuing_bank", "country", "weekday", "hour"],
    "L5_PROVIDER_METHOD_COUNTRY": [
        "provider", "payment_method", "country", "weekday", "hour"
    ],
    "L6_MERCHANT_BANK_COUNTRY": [
        "merchant", "issuing_bank", "country", "weekday", "hour"
    ],
}


def clean_dimension_value(value: Any) -> Any:
    if pd.isna(value):
        return None

    return value


def row_to_segment(row: pd.Series) -> dict[str, Any]:
    weekday = clean_dimension_value(row["weekday"])
    hour = clean_dimension_value(row["hour"])

    return {
        "merchant": clean_dimension_value(row["merchant"]),
        "provider": clean_dimension_value(row["provider"]),
        "payment_method": clean_dimension_value(
            row["payment_method"]
        ),
        "country": clean_dimension_value(row["country"]),
        "issuing_bank": clean_dimension_value(
            row["issuing_bank"]
        ),
        "weekday": int(weekday) if weekday is not None else None,
        "hour": int(hour) if hour is not None else None,
    }


def detection_baseline_key(
    level: str,
    dimensions: list[str],
    row: pd.Series,
) -> tuple:
    return (level,) + tuple(
        None if pd.isna(row[dimension]) else row[dimension]
        for dimension in dimensions
    )


def build_detection_baseline_index(
    baselines: pd.DataFrame,
) -> dict[tuple, pd.Series]:
    """Precomputes the same exact-match lookup
    find_exact_detection_baseline used to redo per row (filtering the
    whole dataframe down by detection_level + every dimension column,
    every single time) as a single dict, built once. Same matching rules
    - reliable rows only, first match wins per key - just O(rows) instead
    of O(rows x candidates) to build, and O(1) instead of O(candidates)
    to look up.
    """
    reliable = baselines[baselines["baseline_reliable"].eq(True)]
    index: dict[tuple, pd.Series] = {}

    for level, dimensions in DETECTION_DIMENSIONS.items():
        level_rows = reliable[reliable["detection_level"].eq(level)]

        for _, baseline_row in level_rows.iterrows():
            key = detection_baseline_key(level, dimensions, baseline_row)
            index.setdefault(key, baseline_row)

    return index


def find_exact_detection_baseline(
    index: dict[tuple, pd.Series],
    row: pd.Series,
) -> pd.Series | None:
    level = row["detection_level"]
    dimensions = DETECTION_DIMENSIONS[level]
    return index.get(detection_baseline_key(level, dimensions, row))


def scan_windows(
    windows: pd.DataFrame,
    baselines: pd.DataFrame,
    detection_baselines: pd.DataFrame,
) -> pd.DataFrame:
    results = []
    detection_baseline_index = build_detection_baseline_index(
        detection_baselines
    )

    for _, row in windows.iterrows():
        if row["window_strategy"] == "insufficient_data":
            results.append(
                {
                    **row.to_dict(),
                    "detected": False,
                    "detection_status": "insufficient_data",
                    "expected_approval_rate": None,
                    "approval_rate_drop": None,
                    "z_score": None,
                    "severity": None,
                    "baseline_level": None,
                    "historical_attempts": None,
                    "reason": (
                        "Insufficient live transaction volume."
                    ),
                }
            )
            continue

        segment = row_to_segment(row)

        baseline_row = find_exact_detection_baseline(
            index=detection_baseline_index,
            row=row,
        )

        if baseline_row is not None:
            baseline = BaselineResult(
                expected_approval_rate=float(
                    baseline_row["expected_approval_rate"]
                ),
                average_amount=float(baseline_row["average_amount"]),
                historical_attempts=int(
                    baseline_row["historical_attempts"]
                ),
                baseline_level=str(baseline_row["detection_level"]),
                dimensions_used={
                    dimension: row[dimension]
                    for dimension in DETECTION_DIMENSIONS[
                        row["detection_level"]
                    ]
                },
                is_reliable=True,
            )
        else:
            try:
                baseline = get_expected_baseline(
                    baselines=baselines,
                    segment=segment,
                )

            except LookupError:
                results.append(
                    {
                        **row.to_dict(),
                        "detected": False,
                        "detection_status": "baseline_unavailable",
                        "expected_approval_rate": None,
                        "approval_rate_drop": None,
                        "z_score": None,
                        "severity": None,
                        "baseline_level": None,
                        "historical_attempts": None,
                        "reason": "No reliable historical baseline found.",
                    }
                )
                continue

        anomaly = detect_anomaly(
            segment=segment,
            attempts=int(row["attempts"]),
            approvals=int(row["approvals"]),
            baseline=baseline,
        )

        results.append(
            {
                **row.to_dict(),
                "detected": anomaly.detected,
                "detection_status": (
                    anomaly.detection_status
                ),
                "expected_approval_rate": (
                    anomaly.expected_approval_rate
                ),
                "approval_rate_drop": (
                    anomaly.approval_rate_drop
                ),
                "z_score": anomaly.z_score,
                "severity": anomaly.severity,
                "baseline_level": anomaly.baseline_level,
                "historical_attempts": (
                    anomaly.historical_attempts
                ),
                "reason": anomaly.reason,
            }
        )

    return pd.DataFrame(results)


def print_summary(results: pd.DataFrame) -> None:
    print("\n=== ANOMALY SCANNER SUMMARY ===")

    status_summary = (
        results["detection_status"]
        .value_counts(dropna=False)
    )

    print("\nDetection statuses:")
    print(status_summary.to_string())

    confirmed = results[
        results["detection_status"].eq(
            "confirmed_anomaly"
        )
    ]

    print(
        f"\nConfirmed anomaly windows: "
        f"{len(confirmed):,}"
    )

    if confirmed.empty:
        return

    by_level = (
        confirmed
        .groupby("detection_level")
        .agg(
            anomaly_windows=("minute", "count"),
            average_drop=(
                "approval_rate_drop",
                "mean",
            ),
            average_z_score=("z_score", "mean"),
        )
        .sort_values(
            "anomaly_windows",
            ascending=False,
        )
    )

    print("\nConfirmed anomalies by level:")
    print(by_level.to_string())

    expanded_truth = confirmed[
        confirmed["incident_ids"].notna()
    ].copy()

    expanded_truth["incident_id"] = (
        expanded_truth["incident_ids"]
        .str.split("|")
    )
    expanded_truth = expanded_truth.explode(
        "incident_id"
    )

    truth_check = (
        expanded_truth
        .groupby("incident_id")
        .agg(
            detected_windows=("minute", "count"),
            first_detection=("minute", "min"),
            last_detection=("minute", "max"),
            average_drop=(
                "approval_rate_drop",
                "mean",
            ),
            average_injected_share=(
                "injected_share",
                "mean",
            ),
        )
    )

    print("\nGround-truth evaluation:")
    if truth_check.empty:
        print(
            "No confirmed anomaly matched an injected incident."
        )
    else:
        print(truth_check.to_string())

    direct_incident_windows = confirmed[
        confirmed["injected_share"] >= 0.50
    ]

    partial_incident_windows = confirmed[
        confirmed["injected_share"].between(
            0.01,
            0.499999,
        )
    ]

    clean_anomaly_windows = confirmed[
        confirmed["injected_share"].eq(0)
    ]

    print(
        "\nConfirmed windows directly affected: "
        f"{len(direct_incident_windows):,}"
    )
    print(
        "Confirmed windows partially affected: "
        f"{len(partial_incident_windows):,}"
    )
    print(
        "Confirmed windows with zero injected traffic: "
        f"{len(clean_anomaly_windows):,}"
    )


def main() -> None:
    windows = pd.read_csv(
        INPUT_PATH,
        parse_dates=["minute"],
        date_format="mixed",
    )

    baselines = load_baselines()
    detection_baselines = pd.read_csv(
        DETECTION_BASELINES_PATH
    )

    results = scan_windows(
        windows=windows,
        baselines=baselines,
        detection_baselines=detection_baselines,
    )

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    results.to_csv(
        output,
        index=False,
    )

    print_summary(results)

    print("\nAnomaly scan completed.")
    print(f"Rows analyzed: {len(results):,}")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
