import pandas as pd


DATA_PATH = "data/source/transactions_history_60_days.csv"


def approval_rate(series: pd.Series) -> float:
    return (series == "approved").mean()


def main() -> None:
    df = pd.read_csv(
        DATA_PATH,
        parse_dates=["timestamp"],
        date_format="mixed",
    )

    print("\n=== DATASET SUMMARY ===")
    print(f"Transactions: {len(df):,}")
    print(f"Start date: {df['timestamp'].min()}")
    print(f"End date: {df['timestamp'].max()}")
    print(f"Global approval rate: {approval_rate(df['status']):.2%}")

    print("\n=== NULL VALUES ===")
    print(df.isna().sum())

    print("\n=== STATUS COUNTS ===")
    print(df["status"].value_counts())

    print("\n=== APPROVAL RATE BY COUNTRY ===")
    country_rates = (
        df.groupby("country")["status"]
        .apply(approval_rate)
        .sort_values()
    )
    print(country_rates.apply(lambda value: f"{value:.2%}"))

    print("\n=== APPROVAL RATE BY PROVIDER ===")
    provider_rates = (
        df.groupby("provider")["status"]
        .apply(approval_rate)
        .sort_values()
    )
    print(provider_rates.apply(lambda value: f"{value:.2%}"))

    print("\n=== APPROVAL RATE BY PAYMENT METHOD ===")
    method_rates = (
        df.groupby("payment_method")["status"]
        .apply(approval_rate)
        .sort_values()
    )
    print(method_rates.apply(lambda value: f"{value:.2%}"))

    print("\n=== APPROVAL RATE BY COUNTRY / PROVIDER / METHOD ===")
    segment_rates = (
        df.groupby(
            ["country", "provider", "payment_method"]
        )["status"]
        .agg(
            attempts="count",
            approval_rate=approval_rate,
        )
        .reset_index()
        .sort_values("approval_rate")
    )

    segment_rates["approval_rate"] = (
        segment_rates["approval_rate"]
        .map(lambda value: f"{value:.2%}")
    )

    print(segment_rates.to_string(index=False))

    print("\n=== TRANSACTIONS BY DAY ===")
    daily_volume = (
        df.set_index("timestamp")
        .resample("D")
        .size()
    )

    print(daily_volume.describe())

    print("\n=== TRANSACTIONS BY HOUR ===")
    hourly_volume = (
        df.assign(hour=df["timestamp"].dt.hour)
        .groupby("hour")
        .size()
    )

    print(hourly_volume)

    approved_with_decline_code = df[
        (df["status"] == "approved")
        & df["decline_code"].notna()
    ]

    declined_without_code = df[
        (df["status"] == "declined")
        & df["decline_code"].isna()
    ]

    print("\n=== DATA QUALITY RULES ===")
    print(
        "Approved transactions with decline code:",
        len(approved_with_decline_code),
    )
    print(
        "Declined transactions without decline code:",
        len(declined_without_code),
    )


if __name__ == "__main__":
    main()
