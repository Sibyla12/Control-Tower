from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/transactions_live_multisegment.csv"
OUTPUT_PATH = "data/detection_windows.csv"


DETECTION_LEVELS = {
    "L1_PROVIDER_COUNTRY": [
        "provider",
        "country",
    ],
    "L2_METHOD_COUNTRY": [
        "payment_method",
        "country",
    ],
    "L3_MERCHANT_COUNTRY": [
        "merchant",
        "country",
    ],
    "L4_BANK_COUNTRY": [
        "issuing_bank",
        "country",
    ],
    "L5_PROVIDER_METHOD_COUNTRY": [
        "provider",
        "payment_method",
        "country",
    ],
    "L6_MERCHANT_BANK_COUNTRY": [
        "merchant",
        "issuing_bank",
        "country",
    ],
}


def dominant_value(series: pd.Series) -> str | None:
    values = series.dropna()

    if values.empty:
        return None

    mode = values.mode()

    if mode.empty:
        return None

    return str(mode.iloc[0])


def aggregate_level(
    dataframe: pd.DataFrame,
    level_name: str,
    dimensions: list[str],
) -> pd.DataFrame:
    grouping_columns = [
        "minute",
        *dimensions,
    ]

    aggregated = (
        dataframe
        .groupby(
            grouping_columns,
            dropna=False,
        )
        .agg(
            attempts=(
                "transaction_id",
                "count",
            ),
            approvals=(
                "status",
                lambda values:
                    int(values.eq("approved").sum()),
            ),
            declines=(
                "status",
                lambda values:
                    int(values.eq("declined").sum()),
            ),
            dominant_decline_code=(
                "decline_code",
                dominant_value,
            ),
            injected_incident_id=(
                "injected_incident_id",
                dominant_value,
            ),
            injected_records=(
                "injected_incident_id",
                lambda values: int(values.notna().sum()),
            ),
            incident_ids=(
                "injected_incident_id",
                lambda values: "|".join(
                    sorted(
                        {
                            str(value)
                            for value in values.dropna()
                        }
                    )
                )
                if not values.dropna().empty
                else None,
            ),
        )
        .reset_index()
    )

    aggregated["approval_rate"] = (
        aggregated["approvals"]
        / aggregated["attempts"]
    )
    aggregated["injected_share"] = (
        aggregated["injected_records"]
        / aggregated["attempts"]
    )

    aggregated["detection_level"] = level_name
    aggregated["weekday"] = (
        aggregated["minute"].dt.weekday
    )
    aggregated["hour"] = (
        aggregated["minute"].dt.hour
    )

    all_dimensions = [
        "merchant",
        "provider",
        "payment_method",
        "country",
        "issuing_bank",
    ]

    for dimension in all_dimensions:
        if dimension not in aggregated.columns:
            aggregated[dimension] = None

    return aggregated[
        [
            "minute",
            "detection_level",
            "merchant",
            "provider",
            "payment_method",
            "country",
            "issuing_bank",
            "weekday",
            "hour",
            "attempts",
            "approvals",
            "declines",
            "approval_rate",
            "dominant_decline_code",
            "injected_incident_id",
            "injected_records",
            "injected_share",
            "incident_ids",
        ]
    ]


def build_detection_windows(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    results = []

    for level_name, dimensions in DETECTION_LEVELS.items():
        level_data = aggregate_level(
            dataframe=dataframe,
            level_name=level_name,
            dimensions=dimensions,
        )

        results.append(level_data)

    return pd.concat(
        results,
        ignore_index=True,
    )


def print_summary(
    dataframe: pd.DataFrame,
) -> None:
    summary = (
        dataframe
        .groupby("detection_level")
        .agg(
            windows=("minute", "count"),
            average_attempts=("attempts", "mean"),
            minimum_attempts=("attempts", "min"),
            maximum_attempts=("attempts", "max"),
            windows_over_30=(
                "attempts",
                lambda values: int(
                    values.ge(30).sum()
                ),
            ),
        )
    )

    summary["usable_percentage"] = (
        summary["windows_over_30"]
        / summary["windows"]
        * 100
    ).round(2)

    print("\n=== DETECTION LEVEL SUMMARY ===")
    print(summary.to_string())


def main() -> None:
    transactions = pd.read_csv(
        INPUT_PATH,
        parse_dates=["timestamp"],
        date_format="mixed",
    )

    transactions["minute"] = (
        transactions["timestamp"]
        .dt.floor("min")
    )

    detection_windows = build_detection_windows(
        transactions
    )

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    detection_windows.to_csv(
        output,
        index=False,
    )

    print_summary(detection_windows)

    print("\nDetection windows generated successfully.")
    print(f"Rows: {len(detection_windows):,}")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
