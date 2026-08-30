from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/source/transactions_live_multisegment.csv"
OUTPUT_PATH = "data/generated/live_segment_windows.csv"


GROUPING_COLUMNS = [
    "minute",
    "merchant",
    "provider",
    "payment_method",
    "country",
    "issuing_bank",
]


def load_live_transactions(
    path: str = INPUT_PATH,
) -> pd.DataFrame:
    dataframe = pd.read_csv(
        path,
        parse_dates=["timestamp"],
        date_format="mixed",
    )

    return dataframe


def add_time_features(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    result = dataframe.copy()

    result["minute"] = (
        result["timestamp"]
        .dt.floor("min")
    )

    result["weekday"] = (
        result["timestamp"]
        .dt.weekday
    )

    result["hour"] = (
        result["timestamp"]
        .dt.hour
    )

    return result


def aggregate_live_segments(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    aggregated = (
        dataframe
        .groupby(
            GROUPING_COLUMNS,
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
                    values.eq("approved").sum(),
            ),
            declines=(
                "status",
                lambda values:
                    values.eq("declined").sum(),
            ),
            average_amount=(
                "amount",
                "mean",
            )
            if "amount" in dataframe.columns
            else (
                "transaction_id",
                lambda _: None,
            ),
            dominant_decline_code=(
                "decline_code",
                lambda values:
                    values.dropna().mode().iloc[0]
                    if not values.dropna().empty
                    else None,
            ),
            injected_incident_id=(
                "injected_incident_id",
                lambda values:
                    values.dropna().mode().iloc[0]
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

    aggregated["weekday"] = (
        aggregated["minute"]
        .dt.weekday
    )

    aggregated["hour"] = (
        aggregated["minute"]
        .dt.hour
    )

    aggregated["approval_rate"] = (
        aggregated["approval_rate"]
        .round(4)
    )

    return aggregated


def validate_aggregated_data(
    dataframe: pd.DataFrame,
) -> None:
    if dataframe.empty:
        raise ValueError(
            "Aggregated dataframe is empty."
        )

    invalid_counts = dataframe[
        dataframe["attempts"]
        != dataframe["approvals"]
        + dataframe["declines"]
    ]

    if not invalid_counts.empty:
        raise ValueError(
            "Attempts do not equal approvals plus declines."
        )

    invalid_rates = dataframe[
        ~dataframe["approval_rate"].between(0, 1)
    ]

    if not invalid_rates.empty:
        raise ValueError(
            "Invalid approval rates found."
        )


def print_summary(
    dataframe: pd.DataFrame,
) -> None:
    print("\n=== LIVE AGGREGATION SUMMARY ===")
    print(
        f"Segment windows: "
        f"{len(dataframe):,}"
    )
    print(
        f"Unique minutes: "
        f"{dataframe['minute'].nunique()}"
    )
    print(
        f"Average attempts per window: "
        f"{dataframe['attempts'].mean():.2f}"
    )
    print(
        f"Maximum attempts in one window: "
        f"{dataframe['attempts'].max()}"
    )

    low_volume = dataframe[
        dataframe["attempts"] < 30
    ]

    print(
        f"Windows with fewer than 30 attempts: "
        f"{len(low_volume):,}"
    )

    incident_summary = (
        dataframe[
            dataframe["injected_incident_id"].notna()
        ]
        .groupby("injected_incident_id")
        .agg(
            windows=("minute", "count"),
            attempts=("attempts", "sum"),
            approvals=("approvals", "sum"),
        )
    )

    if not incident_summary.empty:
        incident_summary["approval_rate"] = (
            incident_summary["approvals"]
            / incident_summary["attempts"]
        )

        print("\n=== INCIDENT WINDOWS ===")
        print(incident_summary.to_string())


def save_aggregated_data(
    dataframe: pd.DataFrame,
    path: str = OUTPUT_PATH,
) -> None:
    output = Path(path)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    dataframe.to_csv(
        output,
        index=False,
    )


def main() -> None:
    transactions = load_live_transactions()
    transactions = add_time_features(
        transactions
    )

    aggregated = aggregate_live_segments(
        transactions
    )

    validate_aggregated_data(
        aggregated
    )

    save_aggregated_data(
        aggregated
    )

    print_summary(
        aggregated
    )

    print(
        "\nSaved at: "
        f"{OUTPUT_PATH}"
    )


if __name__ == "__main__":
    main()