from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
import random
import uuid

import numpy as np
import pandas as pd

from incident_injector import IncidentRule, get_matching_incidents


MERCHANTS = ["Merchant_A", "Merchant_B", "Merchant_C"]
PROVIDERS = ["Stripe", "Adyen", "dLocal"]
COUNTRIES = ["MX", "CO", "BR"]

CURRENCY_BY_COUNTRY = {
    "MX": "MXN",
    "CO": "COP",
    "BR": "BRL",
}

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

METHOD_DEFAULTS = {
    "PSE": 0.87,
    "PIX": 0.95,
    "wallet": 0.92,
    "cash_in_store": 0.84,
}

INCIDENT_RULES = [
    IncidentRule(
        incident_id="INC-001",
        start_minute=4,
        end_minute=8,
        degraded_approval_rate=0.55,
        decline_code="PROCESSOR_ERROR",
        provider="Adyen",
        country="BR",
    ),
    IncidentRule(
        incident_id="INC-002",
        start_minute=5,
        end_minute=9,
        degraded_approval_rate=0.25,
        decline_code="ISSUER_UNAVAILABLE",
        merchant="Merchant_A",
        payment_method="card",
        country="MX",
        issuing_bank="BBVA",
    ),
]


def get_normal_approval_rate(
    country: str,
    provider: str,
    payment_method: str,
) -> float:
    return BASE_APPROVAL_RATES.get(
        (country, provider, payment_method),
        METHOD_DEFAULTS.get(payment_method, 0.88),
    )


def generate_amount(country: str) -> float:
    amount_parameters = {
        "MX": (900, 500),
        "CO": (120_000, 70_000),
        "BR": (280, 160),
    }
    mean, std = amount_parameters[country]
    amount = np.random.normal(
        loc=mean,
        scale=std,
    )
    minimum_amount = mean * 0.10

    return round(max(amount, minimum_amount), 2)


def generate_transaction_dimensions() -> dict:
    country = random.choice(COUNTRIES)
    merchant = random.choice(MERCHANTS)
    provider = random.choice(PROVIDERS)
    payment_method = random.choice(
        PAYMENT_METHODS_BY_COUNTRY[country]
    )

    issuing_bank = None
    if payment_method == "card":
        issuing_bank = random.choice(BANKS_BY_COUNTRY[country])

    return {
        "merchant": merchant,
        "provider": provider,
        "payment_method": payment_method,
        "country": country,
        "issuing_bank": issuing_bank,
    }


def generate_live_transaction(
    minute_number: int,
    timestamp: datetime,
) -> dict:
    dimensions = generate_transaction_dimensions()

    transaction = {
        "transaction_id": f"live_{uuid.uuid4().hex[:12]}",
        "timestamp": timestamp,
        **dimensions,
        "amount": generate_amount(dimensions["country"]),
        "currency": CURRENCY_BY_COUNTRY[dimensions["country"]],
        "status": None,
        "decline_code": None,
        "is_retry": False,
        "injected_incident_id": None,
    }

    normal_rate = get_normal_approval_rate(
        country=transaction["country"],
        provider=transaction["provider"],
        payment_method=transaction["payment_method"],
    )
    matching_incidents = get_matching_incidents(
        transaction=transaction,
        minute_number=minute_number,
        rules=INCIDENT_RULES,
    )

    if matching_incidents:
        selected_incident = min(
            matching_incidents,
            key=lambda rule: rule.degraded_approval_rate,
        )
        approval_rate = selected_incident.degraded_approval_rate
        decline_code = selected_incident.decline_code
        transaction["injected_incident_id"] = selected_incident.incident_id
    else:
        approval_rate = normal_rate
        decline_code = random.choice(
            [
                "INSUFFICIENT_FUNDS",
                "DO_NOT_HONOR",
                "SUSPECTED_FRAUD",
                "INVALID_CARD",
            ]
        )

    approved = random.random() < approval_rate
    transaction["status"] = "approved" if approved else "declined"
    transaction["decline_code"] = None if approved else decline_code

    return transaction


def run_simulation(
    minutes: int = 12,
    attempts_per_minute: int = 1200,
) -> pd.DataFrame:
    random.seed(42)
    np.random.seed(42)

    start_time = datetime(2026, 8, 31, 10, 0)
    rows = []

    for minute_number in range(1, minutes + 1):
        minute_timestamp = start_time + timedelta(
            minutes=minute_number - 1
        )

        for _ in range(attempts_per_minute):
            rows.append(
                generate_live_transaction(
                    minute_number=minute_number,
                    timestamp=minute_timestamp,
                )
            )

        print(
            f"Minute {minute_number}: "
            f"{attempts_per_minute} transactions generated"
        )

    dataframe = pd.DataFrame(rows)
    output_path = Path("data/transactions_live_multisegment.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(output_path, index=False)

    return dataframe


def print_incident_summary(dataframe: pd.DataFrame) -> None:
    print("\n=== INJECTED INCIDENT SUMMARY ===")

    summary = (
        dataframe[dataframe["injected_incident_id"].notna()]
        .groupby("injected_incident_id")
        .agg(
            affected_records=("transaction_id", "count"),
            declines=(
                "status",
                lambda values: values.eq("declined").sum(),
            ),
            approval_rate=(
                "status",
                lambda values: values.eq("approved").mean(),
            ),
        )
    )
    print(summary.to_string())

    print("\n=== INCIDENT DIMENSION CHECK ===")

    for incident_id in ["INC-001", "INC-002"]:
        incident_rows = dataframe[
            dataframe["injected_incident_id"].eq(incident_id)
        ]

        print(f"\n{incident_id}")
        if incident_rows.empty:
            print("No matching traffic generated.")
            continue

        print(
            incident_rows[
                [
                    "merchant",
                    "provider",
                    "payment_method",
                    "country",
                    "issuing_bank",
                    "decline_code",
                ]
            ]
            .drop_duplicates()
            .head(20)
            .to_string(index=False)
        )


if __name__ == "__main__":
    live_data = run_simulation()
    print_incident_summary(live_data)

    print("\nSimulation completed.")
    print(f"Transactions: {len(live_data):,}")
    print("Saved at: data/transactions_live_multisegment.csv")
