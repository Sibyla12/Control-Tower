"""Injects a judge-specified incident into the running demo ("trial by fire").

Appends new transactions to data/transactions_live_multisegment.csv for a
combination of dimensions given on the command line, using the same
generation model as live_simulator.py (background noise + a matching
IncidentRule), then prints the next command to run.

Example — a provider degrading in a country it wasn't rehearsed in:

    python3 src/inject_live_incident.py \\
        --provider Stripe --country CO --decline-code SUSPECTED_FRAUD \\
        --approval-rate 0.35 --minutes 5

Any dimension left out stays a wildcard (matches every value of it), exactly
like the existing INCIDENT_RULES in live_simulator.py. Dimension values
should be ones the demo has historical baselines for (merchants Merchant_A/
Merchant_B/Merchant_C, providers Stripe/Adyen/dLocal, countries MX/CO/BR,
issuing banks from live_simulator.BANKS_BY_COUNTRY) so the detector has
something to compare the drop against.

After this, run:

    python3 src/run_pipeline.py
"""
from __future__ import annotations

import argparse
import random
import sys
import uuid
from datetime import timedelta
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

from incident_injector import IncidentRule, get_matching_incidents
from live_simulator import (
    BANKS_BY_COUNTRY,
    COUNTRIES,
    CURRENCY_BY_COUNTRY,
    MERCHANTS,
    PAYMENT_METHODS_BY_COUNTRY,
    PROVIDERS,
    generate_amount,
    generate_transaction_dimensions,
    get_normal_approval_rate,
)

TRANSACTIONS_PATH = Path("data/transactions_live_multisegment.csv")
ATTEMPTS_PER_MINUTE = 1200
NORMAL_DECLINE_CODES = [
    "INSUFFICIENT_FUNDS",
    "DO_NOT_HONOR",
    "SUSPECTED_FRAUD",
    "INVALID_CARD",
]


def generate_transaction(minute_number: int, timestamp, rules: list[IncidentRule]) -> dict:
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
        rules=rules,
    )

    if matching_incidents:
        selected = min(matching_incidents, key=lambda rule: rule.degraded_approval_rate)
        approval_rate = selected.degraded_approval_rate
        decline_code = selected.decline_code
        transaction["injected_incident_id"] = selected.incident_id
    else:
        approval_rate = normal_rate
        decline_code = random.choice(NORMAL_DECLINE_CODES)

    approved = random.random() < approval_rate
    transaction["status"] = "approved" if approved else "declined"
    transaction["decline_code"] = None if approved else decline_code

    return transaction


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inject a live incident into the running Control Tower demo.",
    )
    parser.add_argument("--merchant", help=f"one of {MERCHANTS}, or omit for all")
    parser.add_argument("--provider", help=f"one of {PROVIDERS}, or omit for all")
    parser.add_argument("--payment-method", dest="payment_method", help="e.g. card, wallet, PIX, PSE, cash_in_store")
    parser.add_argument("--country", help=f"one of {COUNTRIES}, or omit for all")
    parser.add_argument("--issuing-bank", dest="issuing_bank", help="e.g. BBVA, Itau, Bancolombia")
    parser.add_argument("--decline-code", dest="decline_code", required=True)
    parser.add_argument(
        "--approval-rate", dest="approval_rate", type=float, required=True,
        help="degraded approval rate during the incident, e.g. 0.35 for 35%%",
    )
    parser.add_argument("--minutes", type=int, default=5, help="how many minutes the incident lasts")
    parser.add_argument("--incident-id", dest="incident_id", default=None)
    args = parser.parse_args()

    if not 0 <= args.approval_rate <= 1:
        parser.error("--approval-rate must be between 0 and 1")
    if args.minutes < 1:
        parser.error("--minutes must be at least 1")

    return args


def main() -> None:
    args = parse_args()

    if not TRANSACTIONS_PATH.exists():
        raise SystemExit(
            f"{TRANSACTIONS_PATH} not found. Run src/live_simulator.py first "
            "to create the base live dataset."
        )

    existing = pd.read_csv(
        TRANSACTIONS_PATH,
        parse_dates=["timestamp"],
        date_format="mixed",
    )
    last_timestamp = existing["timestamp"].max()
    incident_id = args.incident_id or f"JUDGE-{uuid.uuid4().hex[:6].upper()}"

    rule = IncidentRule(
        incident_id=incident_id,
        start_minute=1,
        end_minute=args.minutes,
        degraded_approval_rate=args.approval_rate,
        decline_code=args.decline_code,
        merchant=args.merchant,
        provider=args.provider,
        payment_method=args.payment_method,
        country=args.country,
        issuing_bank=args.issuing_bank,
    )

    new_rows = []
    for minute_number in range(1, args.minutes + 1):
        timestamp = last_timestamp + timedelta(minutes=minute_number)
        for _ in range(ATTEMPTS_PER_MINUTE):
            new_rows.append(generate_transaction(minute_number, timestamp, [rule]))

    new_transactions = pd.DataFrame(new_rows)
    combined = pd.concat([existing, new_transactions], ignore_index=True)
    combined.to_csv(TRANSACTIONS_PATH, index=False)

    declined = new_transactions["injected_incident_id"].eq(incident_id) & new_transactions["status"].eq("declined")
    matched = new_transactions["injected_incident_id"].eq(incident_id)

    print(f"Injected incident {incident_id}")
    print(
        f"  dimensions: merchant={args.merchant or 'ALL'} provider={args.provider or 'ALL'} "
        f"method={args.payment_method or 'ALL'} country={args.country or 'ALL'} "
        f"bank={args.issuing_bank or 'ALL'}"
    )
    print(f"  decline_code={args.decline_code}  target approval_rate={args.approval_rate:.0%}")
    print(
        f"  {matched.sum():,} matching transactions generated across {args.minutes} minute(s) "
        f"({last_timestamp + timedelta(minutes=1)} to {last_timestamp + timedelta(minutes=args.minutes)}), "
        f"{declined.sum():,} declined"
    )
    print(f"\nNow run:\n  python3 src/run_pipeline.py")


if __name__ == "__main__":
    main()
