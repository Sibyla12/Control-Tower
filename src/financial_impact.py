from __future__ import annotations

from pathlib import Path

import pandas as pd


INCIDENTS_PATH = "data/consolidated_incidents.csv"
TRANSACTIONS_PATH = "data/transactions_live_multisegment.csv"
FINANCIAL_CONFIG_PATH = "data/merchant_financial_config.csv"
EXCHANGE_RATES_PATH = "data/exchange_rates.csv"

OUTPUT_PATH = "data/incidents_with_financial_impact.csv"


def split_values(value) -> set[str]:
    if pd.isna(value):
        return set()

    return {
        item.strip()
        for item in str(value).split("|")
        if item.strip()
    }


def load_data():
    incidents = pd.read_csv(
        INCIDENTS_PATH,
        parse_dates=["start_time", "end_time"],
        date_format="mixed",
    )

    transactions = pd.read_csv(
        TRANSACTIONS_PATH,
        parse_dates=["timestamp"],
        date_format="mixed",
    )

    financial_config = pd.read_csv(
        FINANCIAL_CONFIG_PATH,
    )

    exchange_rates = pd.read_csv(
        EXCHANGE_RATES_PATH,
    )

    return (
        incidents,
        transactions,
        financial_config,
        exchange_rates,
    )


def normalize_currency(
    transactions: pd.DataFrame,
    exchange_rates: pd.DataFrame,
) -> pd.DataFrame:
    result = transactions.copy()

    if "amount" not in result.columns:
        result["amount"] = 0.0

    if "currency" not in result.columns:
        result["currency"] = "USD"

    rates = exchange_rates.rename(
        columns={
            "rate_to_usd": "exchange_rate_to_usd"
        }
    )

    result = result.merge(
        rates,
        on="currency",
        how="left",
    )

    result["exchange_rate_to_usd"] = (
        result["exchange_rate_to_usd"]
        .fillna(1.0)
    )

    result["amount_usd"] = (
        result["amount"]
        * result["exchange_rate_to_usd"]
    )

    return result


def filter_incident_transactions(
    transactions: pd.DataFrame,
    incident: pd.Series,
) -> pd.DataFrame:
    mask = (
        transactions["timestamp"]
        .between(
            incident["start_time"],
            incident["end_time"],
        )
    )

    filtered = transactions[mask].copy()

    filters = {
        "provider": incident["provider"],
        "issuing_bank": incident["issuing_bank"],
        "merchant": incident["merchant"],
        "payment_method": incident["payment_method"],
        "country": incident["country"],
    }

    for column, raw_value in filters.items():
        values = split_values(raw_value)

        if not values:
            continue

        filtered = filtered[
            filtered[column].astype(str).isin(values)
        ]

    return filtered


def weighted_fee_rate(
    transactions: pd.DataFrame,
    financial_config: pd.DataFrame,
) -> float:
    merchants = transactions[
        ["merchant"]
    ].drop_duplicates()

    config = merchants.merge(
        financial_config,
        on="merchant",
        how="left",
    )

    return float(
        config["platform_fee_rate"]
        .fillna(0.007)
        .mean()
    )


def calculate_incident_impact(
    incident: pd.Series,
    transactions: pd.DataFrame,
    financial_config: pd.DataFrame,
) -> dict:
    affected = filter_incident_transactions(
        transactions,
        incident,
    )

    attempts = len(affected)

    actual_approvals = int(
        affected["status"]
        .eq("approved")
        .sum()
    )

    expected_rate = float(
        incident["expected_approval_rate"]
    )

    expected_approvals = (
        attempts * expected_rate
    )

    estimated_lost_approvals = max(
        expected_approvals - actual_approvals,
        0,
    )

    average_ticket_usd = (
        float(affected["amount_usd"].mean())
        if not affected.empty
        else 0.0
    )

    gross_payment_value_at_risk = (
        estimated_lost_approvals
        * average_ticket_usd
    )

    merchants = split_values(
        incident["merchant"]
    )

    merchant_configs = financial_config[
        financial_config["merchant"].isin(
            merchants
        )
    ]

    if merchant_configs.empty:
        retry_recovery_rate = 0.35
    else:
        retry_recovery_rate = float(
            merchant_configs[
                "retry_recovery_rate"
            ].mean()
        )

    expected_recovered_value = (
        gross_payment_value_at_risk
        * retry_recovery_rate
    )

    net_unrecovered_value = (
        gross_payment_value_at_risk
        - expected_recovered_value
    )

    platform_fee_rate = weighted_fee_rate(
        affected,
        financial_config,
    )

    platform_revenue_at_risk = (
        net_unrecovered_value
        * platform_fee_rate
    )

    duration_minutes = max(
        (
            incident["end_time"]
            - incident["start_time"]
        ).total_seconds() / 60 + 1,
        1,
    )

    value_at_risk_per_minute = (
        net_unrecovered_value
        / duration_minutes
    )

    return {
        "attempts_in_scope": attempts,
        "actual_approvals": actual_approvals,
        "expected_approvals": round(
            expected_approvals,
            2,
        ),
        "estimated_lost_approvals": round(
            estimated_lost_approvals,
            2,
        ),
        "average_ticket_usd": round(
            average_ticket_usd,
            2,
        ),
        "gross_payment_value_at_risk_usd": round(
            gross_payment_value_at_risk,
            2,
        ),
        "retry_recovery_rate": round(
            retry_recovery_rate,
            4,
        ),
        "expected_recovered_value_usd": round(
            expected_recovered_value,
            2,
        ),
        "net_unrecovered_value_usd": round(
            net_unrecovered_value,
            2,
        ),
        "platform_fee_rate": round(
            platform_fee_rate,
            4,
        ),
        "platform_revenue_at_risk_usd": round(
            platform_revenue_at_risk,
            2,
        ),
        "value_at_risk_per_minute_usd": round(
            value_at_risk_per_minute,
            2,
        ),
    }


def add_financial_impact(
    incidents: pd.DataFrame,
    transactions: pd.DataFrame,
    financial_config: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, incident in incidents.iterrows():
        impact = calculate_incident_impact(
            incident=incident,
            transactions=transactions,
            financial_config=financial_config,
        )

        rows.append(
            {
                **incident.to_dict(),
                **impact,
            }
        )

    return pd.DataFrame(rows)


def print_summary(dataframe: pd.DataFrame) -> None:
    print("\n=== FINANCIAL IMPACT SUMMARY ===")

    columns = [
        "consolidated_incident_id",
        "root_cause_type",
        "provider",
        "issuing_bank",
        "merchant",
        "country",
        "estimated_lost_approvals",
        "gross_payment_value_at_risk_usd",
        "net_unrecovered_value_usd",
        "value_at_risk_per_minute_usd",
        "platform_revenue_at_risk_usd",
    ]

    print(
        dataframe[columns]
        .sort_values(
            "value_at_risk_per_minute_usd",
            ascending=False,
        )
        .to_string(index=False)
    )


def main() -> None:
    (
        incidents,
        transactions,
        financial_config,
        exchange_rates,
    ) = load_data()

    transactions = normalize_currency(
        transactions,
        exchange_rates,
    )

    result = add_financial_impact(
        incidents=incidents,
        transactions=transactions,
        financial_config=financial_config,
    )

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    result.to_csv(
        output,
        index=False,
    )

    print_summary(result)

    print("\nFinancial impact calculated.")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()