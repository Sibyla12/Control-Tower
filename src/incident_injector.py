from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class IncidentRule:
    incident_id: str
    start_minute: int
    end_minute: int
    degraded_approval_rate: float
    decline_code: str

    merchant: str | None = None
    provider: str | None = None
    payment_method: str | None = None
    country: str | None = None
    issuing_bank: str | None = None


def transaction_matches_rule(
    transaction: dict[str, Any],
    rule: IncidentRule,
) -> bool:
    filters = {
        "merchant": rule.merchant,
        "provider": rule.provider,
        "payment_method": rule.payment_method,
        "country": rule.country,
        "issuing_bank": rule.issuing_bank,
    }

    for field, expected_value in filters.items():
        if expected_value is None:
            continue

        if transaction.get(field) != expected_value:
            return False

    return True


def incident_is_active(
    minute_number: int,
    rule: IncidentRule,
) -> bool:
    return (
        rule.start_minute
        <= minute_number
        <= rule.end_minute
    )


def get_matching_incidents(
    transaction: dict[str, Any],
    minute_number: int,
    rules: list[IncidentRule],
) -> list[IncidentRule]:
    matching_rules = []

    for rule in rules:
        if not incident_is_active(minute_number, rule):
            continue

        if transaction_matches_rule(transaction, rule):
            matching_rules.append(rule)

    return matching_rules