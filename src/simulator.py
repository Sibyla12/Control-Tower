from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import random
import uuid

import numpy as np
import pandas as pd


MERCHANTS = ["Merchant_A", "Merchant_B", "Merchant_C"]
PROVIDERS = ["Stripe", "Adyen", "dLocal"]
COUNTRIES = ["MX", "CO", "BR"]

PAYMENT_METHODS_BY_COUNTRY = {
    "MX": ["card", "wallet", "cash_in_store"],
    "CO": ["card", "PSE", "wallet"],
    "BR": ["card", "PIX", "wallet"],
}

BANKS_BY_COUNTRY = {
    "MX": ["BBVA", "Santander", "Banorte", "Citibanamex"],
    "CO": ["Bancolombia", "Davivienda", "Banco de Bogota"],
    "BR": ["Itau", "Bradesco", "Nubank", "Banco do Brasil"],
}

CURRENCY_BY_COUNTRY = {
    "MX": "MXN",
    "CO": "COP",
    "BR": "BRL",
}

EXCHANGE_RATES_TO_USD = {
    "MXN": 0.055,
    "COP": 0.00025,
    "BRL": 0.20,
    "USD": 1.00,
}

MERCHANT_FINANCIAL_CONFIG = {
    "Merchant_A": (0.007, 0.25, 0.35, "high", "USD", 2_500_000),
    "Merchant_B": (0.006, 0.18, 0.28, "medium", "USD", 1_200_000),
    "Merchant_C": (0.008, 0.22, 0.40, "high", "USD", 3_100_000),
}

PROVIDER_LATENCY_MS = {
    "Stripe": (310, 75),
    "Adyen": (360, 90),
    "dLocal": (440, 120),
}

DECLINE_CODES = [
    "INSUFFICIENT_FUNDS",
    "DO_NOT_HONOR",
    "SUSPECTED_FRAUD",
    "INVALID_CARD",
]

BASE_APPROVAL_RATES = {
    ("MX", "Stripe", "card"): 0.91,
    ("MX", "Adyen", "card"): 0.93,
    ("MX", "dLocal", "card"): 0.88,
    ("CO", "Stripe", "card"): 0.89,
    ("CO", "Adyen", "card"): 0.91,
    ("CO", "dLocal", "card"): 0.90,
    ("BR", "Stripe", "card"): 0.90,
    ("BR", "Adyen", "card"): 0.92,
    ("BR", "dLocal", "card"): 0.89,
}


def get_approval_rate(
    country: str,
    provider: str,
    payment_method: str,
) -> float:
    key = (country, provider, payment_method)

    if key in BASE_APPROVAL_RATES:
        return BASE_APPROVAL_RATES[key]

    method_defaults = {
        "PSE": 0.87,
        "PIX": 0.95,
        "wallet": 0.92,
        "cash_in_store": 0.84,
    }

    return method_defaults.get(payment_method, 0.88)


def generate_amount(country: str) -> float:
    amount_parameters = {
        "MX": (900, 500),
        "CO": (120_000, 70_000),
        "BR": (280, 160),
    }

    mean, std = amount_parameters[country]
    amount = np.random.normal(mean, std)

    return round(max(amount, mean * 0.1), 2)


def generate_processing_time(provider: str) -> int:
    mean, std = PROVIDER_LATENCY_MS[provider]
    return max(50, int(np.random.normal(mean, std)))


def generate_realistic_timestamp(
    start_time: datetime,
    end_time: datetime,
) -> datetime:
    total_days = (end_time.date() - start_time.date()).days
    random_day = random.randint(0, total_days)
    selected_date = (start_time + timedelta(days=random_day)).date()

    hours = list(range(24))
    hour_weights = [
        0.01,   # 00
        0.005,  # 01
        0.004,  # 02
        0.003,  # 03
        0.004,  # 04
        0.008,  # 05
        0.02,   # 06
        0.04,   # 07
        0.06,   # 08
        0.08,   # 09
        0.09,   # 10
        0.10,   # 11
        0.11,   # 12
        0.10,   # 13
        0.09,   # 14
        0.09,   # 15
        0.08,   # 16
        0.08,   # 17
        0.07,   # 18
        0.06,   # 19
        0.04,   # 20
        0.025,  # 21
        0.015,  # 22
        0.01,   # 23
    ]

    selected_hour = random.choices(
        hours,
        weights=hour_weights,
        k=1,
    )[0]
    selected_minute = random.randint(0, 59)
    selected_second = random.randint(0, 59)

    timestamp = datetime.combine(
        selected_date,
        datetime.min.time(),
    ).replace(
        hour=selected_hour,
        minute=selected_minute,
        second=selected_second,
    )

    return min(max(timestamp, start_time), end_time)


def generate_transaction(timestamp: datetime) -> dict:
    country = random.choice(COUNTRIES)
    merchant = random.choice(MERCHANTS)
    provider = random.choice(PROVIDERS)
    payment_method = random.choice(PAYMENT_METHODS_BY_COUNTRY[country])

    issuing_bank = (
        random.choice(BANKS_BY_COUNTRY[country])
        if payment_method == "card"
        else None
    )
    approval_rate = get_approval_rate(country, provider, payment_method)
    approved = random.random() < approval_rate
    amount = generate_amount(country)
    currency = CURRENCY_BY_COUNTRY[country]

    return {
        "transaction_id": f"tx_{uuid.uuid4().hex[:12]}",
        "timestamp": timestamp,
        "merchant": merchant,
        "provider": provider,
        "payment_method": payment_method,
        "country": country,
        "issuing_bank": issuing_bank,
        "status": "approved" if approved else "declined",
        "decline_code": None if approved else random.choice(DECLINE_CODES),
        "amount": amount,
        "currency": currency,
        "retry_flag": False,
        "original_transaction_id": None,
        "recovered_after_retry": False,
        "processing_time_ms": generate_processing_time(provider),
        "amount_usd": round(amount * EXCHANGE_RATES_TO_USD[currency], 2),
    }


def generate_retry(original: dict, timestamp: datetime) -> dict:
    provider = random.choice(PROVIDERS)
    recovery_rate = MERCHANT_FINANCIAL_CONFIG[original["merchant"]][2]
    approved = random.random() < recovery_rate

    retry = {
        **original,
        "transaction_id": f"tx_{uuid.uuid4().hex[:12]}",
        "timestamp": timestamp,
        "provider": provider,
        "status": "approved" if approved else "declined",
        "decline_code": None if approved else random.choice(DECLINE_CODES),
        "retry_flag": True,
        "original_transaction_id": original["transaction_id"],
        "recovered_after_retry": approved,
        "processing_time_ms": generate_processing_time(provider),
    }

    if approved:
        original["recovered_after_retry"] = True

    return retry


def generate_transactions(
    number_of_transactions: int = 500_000,
    end_time: datetime | None = None,
    history_days: int = 60,
) -> pd.DataFrame:
    if number_of_transactions <= 0:
        raise ValueError("number_of_transactions must be greater than zero.")
    if history_days <= 0:
        raise ValueError("history_days must be greater than zero.")

    end_time = end_time or datetime.now()
    history_window = timedelta(days=history_days)
    start_time = end_time - history_window
    timestamps = sorted(
        generate_realistic_timestamp(
            start_time=start_time,
            end_time=end_time,
        )
        for _ in range(number_of_transactions)
    )

    transactions = []
    retry_candidates = []

    for timestamp in timestamps:
        if retry_candidates and random.random() < 0.10:
            original = retry_candidates.pop(random.randrange(len(retry_candidates)))
            transactions.append(generate_retry(original, timestamp))
            continue

        transaction = generate_transaction(timestamp)
        transactions.append(transaction)
        if transaction["status"] == "declined":
            retry_candidates.append(transaction)

    return pd.DataFrame(transactions)


def validate_dataset(dataframe: pd.DataFrame) -> None:
    required_columns = {
        "transaction_id",
        "timestamp",
        "merchant",
        "provider",
        "payment_method",
        "country",
        "issuing_bank",
        "decline_code",
        "status",
        "amount",
        "currency",
        "retry_flag",
        "original_transaction_id",
        "recovered_after_retry",
        "processing_time_ms",
        "amount_usd",
    }

    missing_columns = required_columns - set(dataframe.columns)

    if missing_columns:
        raise ValueError(f"Missing columns: {sorted(missing_columns)}")

    approved_with_decline_code = dataframe[
        (dataframe["status"] == "approved")
        & dataframe["decline_code"].notna()
    ]

    declined_without_code = dataframe[
        (dataframe["status"] == "declined")
        & dataframe["decline_code"].isna()
    ]

    if not approved_with_decline_code.empty:
        raise ValueError(
            "Approved transactions cannot contain a decline code."
        )

    if not declined_without_code.empty:
        raise ValueError(
            "Declined transactions must contain a decline code."
        )

    retries = dataframe[dataframe["retry_flag"]]
    non_retries = dataframe[~dataframe["retry_flag"]]
    if non_retries["original_transaction_id"].notna().any():
        raise ValueError("Only retries may reference an original transaction.")

    original_ids = set(dataframe["transaction_id"])
    invalid_originals = set(retries["original_transaction_id"]) - original_ids
    if invalid_originals:
        raise ValueError("Every retry must reference an existing transaction.")

    expected_amount_usd = dataframe["amount"] * dataframe["currency"].map(
        EXCHANGE_RATES_TO_USD
    )
    if not np.allclose(dataframe["amount_usd"], expected_amount_usd, atol=0.01):
        raise ValueError("amount_usd does not match the configured exchange rate.")


def save_dataset(
    dataframe: pd.DataFrame,
    output_path: str = "data/transactions_normal.csv",
) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    dataframe.to_csv(path, index=False)


def save_reference_tables(output_directory: str = "data") -> None:
    output_path = Path(output_directory)
    output_path.mkdir(parents=True, exist_ok=True)

    financial_rows = []
    for merchant, values in MERCHANT_FINANCIAL_CONFIG.items():
        financial_rows.append(
            {
                "merchant": merchant,
                "platform_fee_rate": values[0],
                "merchant_margin_rate": values[1],
                "retry_recovery_rate": values[2],
                "merchant_priority": values[3],
                "reporting_currency": values[4],
                "monthly_payment_volume": values[5],
            }
        )

    pd.DataFrame(financial_rows).to_csv(
        output_path / "merchant_financial_config.csv", index=False
    )
    pd.DataFrame(
        [
            {"currency": currency, "rate_to_usd": rate}
            for currency, rate in EXCHANGE_RATES_TO_USD.items()
        ]
    ).to_csv(output_path / "exchange_rates.csv", index=False)


if __name__ == "__main__":
    np.random.seed(42)
    random.seed(42)

    df = generate_transactions(
        number_of_transactions=500_000,
        history_days=60,
    )

    validate_dataset(df)
    save_reference_tables()

    save_dataset(
        df,
        output_path="data/transactions_history_60_days.csv",
    )

    approval_rate = (
        df["status"] == "approved"
    ).mean()

    print("Dataset generated successfully.")
    print(f"Transactions: {len(df):,}")
    print(f"Start date: {df['timestamp'].min()}")
    print(f"End date: {df['timestamp'].max()}")
    print(
        f"Global approval rate: {approval_rate:.2%}"
    )
    print(
        "Saved at: "
        "data/transactions_history_60_days.csv"
    )
