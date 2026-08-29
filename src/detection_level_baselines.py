from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/transactions_history_60_days.csv"
OUTPUT_PATH = "data/detection_level_baselines.csv"

MIN_HISTORICAL_ATTEMPTS = 30

BASELINE_LEVELS = {
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

ALL_DIMENSIONS = [
    "merchant",
    "provider",
    "payment_method",
    "country",
    "issuing_bank",
    "weekday",
    "hour",
]


def load_original_attempts() -> pd.DataFrame:
    dataframe = pd.read_csv(
        INPUT_PATH,
        parse_dates=["timestamp"],
        date_format="mixed",
    )

    retry_column = (
        "retry_flag"
        if "retry_flag" in dataframe.columns
        else "is_retry"
    )
    dataframe = dataframe[dataframe[retry_column].eq(False)].copy()
    dataframe["weekday"] = dataframe["timestamp"].dt.weekday
    dataframe["hour"] = dataframe["timestamp"].dt.hour

    return dataframe


def aggregate_level(
    dataframe: pd.DataFrame,
    level_name: str,
    dimensions: list[str],
) -> pd.DataFrame:
    baseline = (
        dataframe
        .groupby(dimensions, dropna=False)
        .agg(
            historical_attempts=("transaction_id", "count"),
            historical_approvals=(
                "status",
                lambda values: int(values.eq("approved").sum()),
            ),
            historical_declines=(
                "status",
                lambda values: int(values.eq("declined").sum()),
            ),
            average_amount=("amount", "mean"),
        )
        .reset_index()
    )

    baseline["expected_approval_rate"] = (
        baseline["historical_approvals"]
        / baseline["historical_attempts"]
    )
    baseline["baseline_reliable"] = (
        baseline["historical_attempts"] >= MIN_HISTORICAL_ATTEMPTS
    )
    baseline["detection_level"] = level_name

    for dimension in ALL_DIMENSIONS:
        if dimension not in baseline.columns:
            baseline[dimension] = None

    return baseline[
        [
            "detection_level",
            *ALL_DIMENSIONS,
            "historical_attempts",
            "historical_approvals",
            "historical_declines",
            "expected_approval_rate",
            "average_amount",
            "baseline_reliable",
        ]
    ]


def build_baselines(dataframe: pd.DataFrame) -> pd.DataFrame:
    results = []

    for level_name, dimensions in BASELINE_LEVELS.items():
        results.append(
            aggregate_level(
                dataframe=dataframe,
                level_name=level_name,
                dimensions=dimensions,
            )
        )

    return pd.concat(results, ignore_index=True)


def print_summary(dataframe: pd.DataFrame) -> None:
    summary = (
        dataframe
        .groupby("detection_level")
        .agg(
            segments=("detection_level", "size"),
            reliable_segments=("baseline_reliable", "sum"),
            average_attempts=("historical_attempts", "mean"),
            minimum_attempts=("historical_attempts", "min"),
            maximum_attempts=("historical_attempts", "max"),
        )
    )
    summary["reliable_percentage"] = (
        summary["reliable_segments"] / summary["segments"] * 100
    ).round(2)

    print("\n=== DETECTION-LEVEL BASELINE SUMMARY ===")
    print(summary.to_string())


def main() -> None:
    transactions = load_original_attempts()
    baselines = build_baselines(transactions)

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    baselines.to_csv(output, index=False)

    print_summary(baselines)
    print("\nDetection-level baselines generated successfully.")
    print(f"Rows: {len(baselines):,}")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
