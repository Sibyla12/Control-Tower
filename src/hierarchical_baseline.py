from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/transactions_history_60_days.csv"
OUTPUT_PATH = "data/hierarchical_baselines.csv"

MIN_ATTEMPTS = 30


def approval_rate(status: pd.Series) -> float:
    if status.empty:
        return 0.0

    return float(status.eq("approved").mean())


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

    original_attempts = dataframe[
        dataframe[retry_column].eq(False)
    ].copy()

    original_attempts["weekday"] = (
        original_attempts["timestamp"].dt.weekday
    )
    original_attempts["hour"] = (
        original_attempts["timestamp"].dt.hour
    )

    return original_attempts


def aggregate_baseline(
    dataframe: pd.DataFrame,
    level_name: str,
    grouping_columns: list[str],
) -> pd.DataFrame:
    baseline = (
        dataframe
        .groupby(grouping_columns, dropna=False)
        .agg(
            attempts=("transaction_id", "count"),
            approvals=(
                "status",
                lambda values: values.eq("approved").sum(),
            ),
            declines=(
                "status",
                lambda values: values.eq("declined").sum(),
            ),
            approval_rate=("status", approval_rate),
            average_amount=("amount", "mean"),
        )
        .reset_index()
    )

    baseline["baseline_level"] = level_name
    baseline["is_reliable"] = (
        baseline["attempts"] >= MIN_ATTEMPTS
    )

    baseline["approval_rate"] = (
        baseline["approval_rate"].round(4)
    )
    baseline["average_amount"] = (
        baseline["average_amount"].round(2)
    )

    all_dimension_columns = [
        "merchant",
        "provider",
        "payment_method",
        "country",
        "weekday",
        "hour",
    ]

    for column in all_dimension_columns:
        if column not in baseline.columns:
            baseline[column] = None

    return baseline[
        [
            "baseline_level",
            "merchant",
            "provider",
            "payment_method",
            "country",
            "weekday",
            "hour",
            "attempts",
            "approvals",
            "declines",
            "approval_rate",
            "average_amount",
            "is_reliable",
        ]
    ]


def build_hierarchical_baselines(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    levels = [
        (
            "L1_FULL",
            [
                "merchant",
                "provider",
                "payment_method",
                "country",
                "weekday",
                "hour",
            ],
        ),
        (
            "L2_NO_MERCHANT",
            [
                "provider",
                "payment_method",
                "country",
                "weekday",
                "hour",
            ],
        ),
        (
            "L3_NO_PROVIDER",
            [
                "payment_method",
                "country",
                "weekday",
                "hour",
            ],
        ),
        (
            "L4_HOUR",
            [
                "payment_method",
                "country",
                "hour",
            ],
        ),
        (
            "L5_METHOD_COUNTRY",
            [
                "payment_method",
                "country",
            ],
        ),
        (
            "L6_GLOBAL",
            [],
        ),
    ]

    baselines = []

    for level_name, columns in levels:
        if columns:
            level_baseline = aggregate_baseline(
                dataframe=dataframe,
                level_name=level_name,
                grouping_columns=columns,
            )
        else:
            level_baseline = pd.DataFrame(
                [
                    {
                        "baseline_level": level_name,
                        "merchant": None,
                        "provider": None,
                        "payment_method": None,
                        "country": None,
                        "weekday": None,
                        "hour": None,
                        "attempts": len(dataframe),
                        "approvals": int(
                            dataframe["status"]
                            .eq("approved")
                            .sum()
                        ),
                        "declines": int(
                            dataframe["status"]
                            .eq("declined")
                            .sum()
                        ),
                        "approval_rate": round(
                            approval_rate(dataframe["status"]),
                            4,
                        ),
                        "average_amount": round(
                            dataframe["amount"].mean(),
                            2,
                        ),
                        "is_reliable": True,
                    }
                ]
            )

        baselines.append(level_baseline)

    return pd.concat(
        baselines,
        ignore_index=True,
    )


def print_summary(
    hierarchical_baselines: pd.DataFrame,
) -> None:
    summary = (
        hierarchical_baselines
        .groupby("baseline_level")
        .agg(
            segments=("baseline_level", "size"),
            reliable_segments=("is_reliable", "sum"),
            average_attempts=("attempts", "mean"),
            minimum_attempts=("attempts", "min"),
            maximum_attempts=("attempts", "max"),
        )
    )

    summary["reliable_percentage"] = (
        summary["reliable_segments"]
        / summary["segments"]
        * 100
    ).round(2)

    print("\n=== HIERARCHICAL BASELINE SUMMARY ===")
    print(summary.to_string())


def save_baselines(
    dataframe: pd.DataFrame,
) -> None:
    path = Path(OUTPUT_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)

    dataframe.to_csv(path, index=False)


def main() -> None:
    original_attempts = load_original_attempts()

    hierarchical_baselines = (
        build_hierarchical_baselines(
            original_attempts
        )
    )

    save_baselines(hierarchical_baselines)
    print_summary(hierarchical_baselines)

    print("\nHierarchical baselines generated successfully.")
    print(f"Original attempts: {len(original_attempts):,}")
    print(f"Total baseline rows: {len(hierarchical_baselines):,}")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()