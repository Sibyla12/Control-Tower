from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/source/transactions_history_60_days.csv"
OUTPUT_PATH = "data/generated/baseline_by_segment.csv"


def approval_rate(status: pd.Series) -> float:
    return float(status.eq("approved").mean())


def load_transactions(path: str = INPUT_PATH) -> pd.DataFrame:
    dataframe = pd.read_csv(
        path,
        parse_dates=["timestamp"],
        date_format="mixed",
    )

    return dataframe


def filter_original_attempts(dataframe: pd.DataFrame) -> pd.DataFrame:
    if "retry_flag" in dataframe.columns:
        return dataframe[
            dataframe["retry_flag"].eq(False)
        ].copy()

    if "is_retry" in dataframe.columns:
        return dataframe[
            dataframe["is_retry"].eq(False)
        ].copy()

    raise ValueError(
        "The dataset must contain retry_flag or is_retry."
    )


def add_time_features(dataframe: pd.DataFrame) -> pd.DataFrame:
    result = dataframe.copy()

    result["weekday"] = result["timestamp"].dt.weekday
    result["hour"] = result["timestamp"].dt.hour
    result["date"] = result["timestamp"].dt.date

    return result


def build_baseline(dataframe: pd.DataFrame) -> pd.DataFrame:
    grouping_columns = [
        "merchant",
        "provider",
        "payment_method",
        "country",
        "weekday",
        "hour",
    ]

    baseline = (
        dataframe
        .groupby(grouping_columns, dropna=False)
        .agg(
            attempts=("transaction_id", "count"),
            approvals=(
                "status",
                lambda status: status.eq("approved").sum(),
            ),
            declines=(
                "status",
                lambda status: status.eq("declined").sum(),
            ),
            approval_rate=("status", approval_rate),
            average_amount=("amount", "mean"),
        )
        .reset_index()
    )

    baseline["approval_rate"] = baseline[
        "approval_rate"
    ].round(4)

    baseline["average_amount"] = baseline[
        "average_amount"
    ].round(2)

    return baseline


def validate_baseline(baseline: pd.DataFrame) -> None:
    if baseline.empty:
        raise ValueError("Baseline is empty.")

    invalid_rates = baseline[
        ~baseline["approval_rate"].between(0, 1)
    ]

    if not invalid_rates.empty:
        raise ValueError(
            "Some approval rates are outside the valid range."
        )

    low_volume_segments = baseline[
        baseline["attempts"] < 30
    ]

    print(
        f"Segments with fewer than 30 attempts: "
        f"{len(low_volume_segments):,}"
    )


def save_baseline(
    baseline: pd.DataFrame,
    output_path: str = OUTPUT_PATH,
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    baseline.to_csv(path, index=False)


def main() -> None:
    transactions = load_transactions()
    original_attempts = filter_original_attempts(transactions)
    original_attempts = add_time_features(original_attempts)

    baseline = build_baseline(original_attempts)
    validate_baseline(baseline)
    save_baseline(baseline)

    print("\nBaseline generated successfully.")
    print(f"Original attempts used: {len(original_attempts):,}")
    print(f"Baseline segments: {len(baseline):,}")
    print(
        f"Average approval rate: "
        f"{baseline['approval_rate'].mean():.2%}"
    )
    print(f"Saved at: {OUTPUT_PATH}")

    print("\nSample:")
    print(baseline.head(10).to_string(index=False))


if __name__ == "__main__":
    main()
    