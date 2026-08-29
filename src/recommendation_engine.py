from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/prioritized_incidents.csv"
OUTPUT_PATH = "data/incidents_with_recommendations.csv"


TECHNICAL_CODES = {
    "PROCESSOR_ERROR",
    "ISSUER_UNAVAILABLE",
}


def clean_value(value) -> str | None:
    if pd.isna(value):
        return None

    text = str(value).strip()

    if not text or text.lower() == "nan":
        return None

    return text


def build_incident_title(
    incident: pd.Series,
) -> str:
    root_type = str(
        incident["root_cause_type"]
    )

    country = clean_value(
        incident.get("country")
    )

    if root_type == "provider":
        provider = clean_value(
            incident.get("provider")
        )

        return (
            f"{provider} degradation in {country}"
        )

    if root_type == "issuing_bank":
        bank = clean_value(
            incident.get("issuing_bank")
        )

        merchant = clean_value(
            incident.get("merchant")
        )

        if merchant:
            return (
                f"{bank} issuer outage affecting "
                f"{merchant} in {country}"
            )

        return (
            f"{bank} issuer outage in {country}"
        )

    if root_type == "decline_code":
        decline_code = clean_value(
            incident.get("dominant_decline_code")
        )

        return f"{decline_code} spike in {country}"

    return f"Payment degradation in {country}"


def build_operations_recommendation(
    incident: pd.Series,
) -> str:
    root_type = str(
        incident["root_cause_type"]
    )

    provider = clean_value(
        incident.get("provider")
    )

    bank = clean_value(
        incident.get("issuing_bank")
    )

    country = clean_value(
        incident.get("country")
    )

    decline_code = clean_value(
        incident.get("dominant_decline_code")
    )

    if root_type == "provider":
        return (
            f"Reduce routing exposure to {provider} in "
            f"{country}. Shift eligible traffic to healthy "
            f"providers and monitor approval recovery."
        )

    if root_type == "issuing_bank":
        return (
            f"Keep acquiring routes active, isolate traffic "
            f"issued by {bank}, and apply controlled retry "
            f"rules instead of rerouting all traffic."
        )

    if root_type == "decline_code":
        return (
            f"Hold routing changes until the {decline_code} "
            f"spike in {country} is attributed to a specific "
            f"provider or bank; it currently spans more than "
            f"one, so rerouting a single provider would not "
            f"fix it."
        )

    return (
        "Limit the affected payment segment and monitor "
        "approval recovery before changing global routing."
    )


def build_engineering_recommendation(
    incident: pd.Series,
) -> str:
    root_type = str(
        incident["root_cause_type"]
    )

    provider = clean_value(
        incident.get("provider")
    )

    bank = clean_value(
        incident.get("issuing_bank")
    )

    decline_code = clean_value(
        incident.get("dominant_decline_code")
    )

    if root_type == "provider":
        return (
            f"Inspect {provider} response latency, timeout "
            f"rates, connector errors and decline mappings. "
            f"Validate whether {decline_code} increased "
            f"across multiple merchants and methods."
        )

    if root_type == "issuing_bank":
        return (
            f"Confirm that {decline_code} is concentrated "
            f"in cards issued by {bank}. Check issuer "
            f"response patterns and prevent aggressive "
            f"retries that could duplicate transactions."
        )

    if root_type == "decline_code":
        return (
            f"Identify which provider, bank, merchant, or "
            f"payment method is generating {decline_code} in "
            f"the affected country, and investigate the "
            f"shared dependency behind it rather than any "
            f"single connector."
        )

    return (
        "Review connector logs, response codes and latency "
        "for the affected segment."
    )


def build_finance_recommendation(
    incident: pd.Series,
) -> str:
    gross_risk = float(
        incident[
            "gross_payment_value_at_risk_usd"
        ]
    )

    net_risk = float(
        incident[
            "net_unrecovered_value_usd"
        ]
    )

    revenue_risk = float(
        incident[
            "platform_revenue_at_risk_usd"
        ]
    )

    return (
        f"Track USD {gross_risk:,.2f} in gross payment "
        f"value at risk, with USD {net_risk:,.2f} expected "
        f"to remain unrecovered after retries. Estimated "
        f"platform revenue exposure is USD "
        f"{revenue_risk:,.2f}."
    )


def build_merchant_success_recommendation(
    incident: pd.Series,
) -> str:
    merchant = clean_value(
        incident.get("merchant")
    )

    root_type = str(
        incident["root_cause_type"]
    )

    if root_type == "provider":
        return (
            "Proactively notify materially affected "
            "merchants that routing mitigation is underway. "
            "Avoid attributing the issue to their checkout "
            "or customer behavior."
        )

    if root_type == "decline_code":
        return (
            "Notify affected merchants that Payments "
            "Operations is investigating a shared decline "
            "pattern; it is not specific to their integration "
            "and does not yet have a single confirmed owner."
        )

    if merchant:
        return (
            f"Notify {merchant} that the issue is "
            f"concentrated in the issuing bank rather than "
            f"its integration. Recommend customer retry "
            f"later or use of an alternative card."
        )

    return (
        "Inform affected merchants of the payment segment "
        "involved and the current mitigation status."
    )


def build_executive_recommendation(
    incident: pd.Series,
) -> str:
    priority = str(
        incident["priority"]
    )

    value_per_minute = float(
        incident[
            "value_at_risk_per_minute_usd"
        ]
    )

    confidence = float(
        incident["confidence_score"]
    )

    if priority == "P1":
        return (
            f"Open an incident bridge immediately. Current "
            f"exposure is USD {value_per_minute:,.2f}/min "
            f"with {confidence:.0%} root-cause confidence. "
            f"Assign Payments Operations as incident owner."
        )

    if priority == "P2":
        return (
            f"Assign an incident owner and review recovery "
            f"every five minutes. Current exposure is USD "
            f"{value_per_minute:,.2f}/min with "
            f"{confidence:.0%} confidence."
        )

    return (
        "Continue investigation and escalate only if "
        "financial impact or scope increases."
    )


def build_primary_action(
    incident: pd.Series,
) -> str:
    root_type = str(
        incident["root_cause_type"]
    )

    provider = clean_value(
        incident.get("provider")
    )

    bank = clean_value(
        incident.get("issuing_bank")
    )

    country = clean_value(
        incident.get("country")
    )

    decline_code = clean_value(
        incident.get("dominant_decline_code")
    )

    if root_type == "provider":
        return (
            f"Shift eligible {country} traffic away from "
            f"{provider} and validate conversion recovery."
        )

    if root_type == "issuing_bank":
        return (
            f"Isolate {bank}-issued card failures and "
            f"activate controlled retry guidance."
        )

    if root_type == "decline_code":
        return (
            f"Investigate the {decline_code} spike in "
            f"{country} across the affected providers, banks "
            f"and merchants before changing routing."
        )

    return (
        "Contain the affected segment and monitor recovery."
    )


def calculate_recommendation_confidence(
    incident: pd.Series,
) -> float:
    root_confidence = float(
        incident["confidence_score"]
    )

    priority = str(
        incident["priority"]
    )

    decline_code = clean_value(
        incident.get("dominant_decline_code")
    )

    priority_bonus = {
        "P1": 0.05,
        "P2": 0.03,
        "P3": 0.01,
        "P4": 0.00,
    }.get(priority, 0.00)

    technical_bonus = (
        0.03
        if decline_code in TECHNICAL_CODES
        else 0.00
    )

    return round(
        min(
            root_confidence
            + priority_bonus
            + technical_bonus,
            1.0,
        ),
        4,
    )


def add_recommendations(
    incidents: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, incident in incidents.iterrows():
        row = {
            **incident.to_dict(),
            "incident_title": (
                build_incident_title(incident)
            ),
            "primary_action": (
                build_primary_action(incident)
            ),
            "payments_operations_action": (
                build_operations_recommendation(
                    incident
                )
            ),
            "engineering_action": (
                build_engineering_recommendation(
                    incident
                )
            ),
            "finance_action": (
                build_finance_recommendation(
                    incident
                )
            ),
            "merchant_success_action": (
                build_merchant_success_recommendation(
                    incident
                )
            ),
            "executive_action": (
                build_executive_recommendation(
                    incident
                )
            ),
            "recommendation_confidence": (
                calculate_recommendation_confidence(
                    incident
                )
            ),
            "recommendation_status": "proposed",
        }

        rows.append(row)

    return pd.DataFrame(rows)


def print_summary(
    dataframe: pd.DataFrame,
) -> None:
    print(
        "\n=== INCIDENT RECOMMENDATION SUMMARY ==="
    )

    columns = [
        "consolidated_incident_id",
        "priority",
        "incident_title",
        "primary_action",
        "recommendation_confidence",
        "recommendation_status",
    ]

    print(
        dataframe[columns]
        .to_string(index=False)
    )


def main() -> None:
    incidents = pd.read_csv(
        INPUT_PATH,
        parse_dates=[
            "start_time",
            "end_time",
        ],
        date_format="mixed",
    )

    result = add_recommendations(
        incidents
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

    print(
        "\nRecommendations generated."
    )
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()