from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/incidents_with_financial_impact.csv"
CONFIG_PATH = "data/merchant_financial_config.csv"
OUTPUT_PATH = "data/prioritized_incidents.csv"


PRIORITY_WEIGHTS = {
    "financial_impact": 0.40,
    "confidence": 0.20,
    "duration": 0.15,
    "merchant_scope": 0.10,
    "root_cause_scope": 0.10,
    "merchant_criticality": 0.05,
}


MERCHANT_PRIORITY_SCORE = {
    "low": 0.30,
    "medium": 0.60,
    "high": 1.00,
}


ROOT_CAUSE_SCOPE_SCORE = {
    "provider": 1.00,
    "payment_method": 0.85,
    "issuing_bank": 0.75,
    "merchant": 0.55,
    "unknown": 0.30,
}


def split_values(value) -> set[str]:
    if pd.isna(value):
        return set()

    return {
        item.strip()
        for item in str(value).split("|")
        if item.strip()
    }


def normalize_financial_impact(
    value_at_risk_per_minute: float,
) -> float:
    """
    USD 1,000/min or more receives the maximum score.
    """
    return min(
        value_at_risk_per_minute / 1000,
        1.0,
    )


def normalize_duration(
    start_time: pd.Timestamp,
    end_time: pd.Timestamp,
) -> float:
    duration_minutes = max(
        (
            end_time - start_time
        ).total_seconds() / 60 + 1,
        1,
    )

    return min(
        duration_minutes / 15,
        1.0,
    )


def calculate_merchant_scope(
    incident: pd.Series,
) -> float:
    merchants = split_values(
        incident.get("affected_merchants")
    )

    if not merchants:
        merchants = split_values(
            incident.get("merchant")
        )

    merchant_count = len(merchants)

    if merchant_count >= 3:
        return 1.0

    if merchant_count == 2:
        return 0.70

    if merchant_count == 1:
        return 0.40

    return 0.25


def calculate_merchant_criticality(
    incident: pd.Series,
    config: pd.DataFrame,
) -> float:
    merchants = split_values(
        incident.get("affected_merchants")
    )

    if not merchants:
        merchants = split_values(
            incident.get("merchant")
        )

    if not merchants:
        return 0.60

    rows = config[
        config["merchant"].isin(merchants)
    ]

    if rows.empty:
        return 0.60

    scores = (
        rows["merchant_priority"]
        .astype(str)
        .str.lower()
        .map(MERCHANT_PRIORITY_SCORE)
        .fillna(0.60)
    )

    return float(scores.mean())


def calculate_priority_score(
    incident: pd.Series,
    config: pd.DataFrame,
) -> dict:
    financial_score = normalize_financial_impact(
        float(
            incident["value_at_risk_per_minute_usd"]
        )
    )

    confidence_score = float(
        incident["confidence_score"]
    )

    duration_score = normalize_duration(
        incident["start_time"],
        incident["end_time"],
    )

    merchant_scope_score = (
        calculate_merchant_scope(incident)
    )

    root_cause_scope_score = (
        ROOT_CAUSE_SCOPE_SCORE.get(
            str(incident["root_cause_type"]),
            0.30,
        )
    )

    merchant_criticality_score = (
        calculate_merchant_criticality(
            incident=incident,
            config=config,
        )
    )

    score = (
        financial_score
        * PRIORITY_WEIGHTS["financial_impact"]

        + confidence_score
        * PRIORITY_WEIGHTS["confidence"]

        + duration_score
        * PRIORITY_WEIGHTS["duration"]

        + merchant_scope_score
        * PRIORITY_WEIGHTS["merchant_scope"]

        + root_cause_scope_score
        * PRIORITY_WEIGHTS["root_cause_scope"]

        + merchant_criticality_score
        * PRIORITY_WEIGHTS["merchant_criticality"]
    )

    return {
        "priority_score": round(score * 100, 2),
        "financial_score": round(financial_score, 4),
        "confidence_component": round(
            confidence_score,
            4,
        ),
        "duration_score": round(
            duration_score,
            4,
        ),
        "merchant_scope_score": round(
            merchant_scope_score,
            4,
        ),
        "root_cause_scope_score": round(
            root_cause_scope_score,
            4,
        ),
        "merchant_criticality_score": round(
            merchant_criticality_score,
            4,
        ),
    }


def classify_priority(
    score: float,
    incident: pd.Series,
) -> str:
    confidence = float(incident["confidence_score"])
    value_per_minute = float(
        incident["value_at_risk_per_minute_usd"]
    )
    lost_approvals = float(
        incident["estimated_lost_approvals"]
    )
    decline_code = str(incident["dominant_decline_code"])
    root_cause_type = str(incident["root_cause_type"])

    technical_failure = decline_code in {
        "PROCESSOR_ERROR",
        "ISSUER_UNAVAILABLE",
    }

    if (
        technical_failure
        and confidence >= 0.90
        and (
            value_per_minute >= 500
            or (
                root_cause_type == "provider"
                and lost_approvals >= 100
            )
        )
    ):
        return "P1"

    if (
        technical_failure
        and confidence >= 0.80
        and (
            value_per_minute >= 75
            or lost_approvals >= 10
        )
    ):
        return "P2"

    if score >= 80:
        return "P1"

    if score >= 60:
        return "P2"

    if score >= 40:
        return "P3"

    return "P4"


def get_priority_reason(
    priority: str,
    incident: pd.Series,
) -> str:
    decline_code = str(incident["dominant_decline_code"])
    confidence = float(incident["confidence_score"])
    value_per_minute = float(
        incident["value_at_risk_per_minute_usd"]
    )

    if priority == "P1":
        return (
            f"Critical technical failure with "
            f"{confidence:.0%} confidence and "
            f"USD {value_per_minute:,.2f}/min at risk."
        )

    if (
        priority == "P2"
        and decline_code
        in {
            "PROCESSOR_ERROR",
            "ISSUER_UNAVAILABLE",
        }
    ):
        return (
            f"Confirmed technical failure with "
            f"{confidence:.0%} confidence and "
            f"material financial impact."
        )

    return (
        f"Priority assigned from composite score "
        f"{incident.get('priority_score', 0):.2f}."
    )


def add_priority(
    incidents: pd.DataFrame,
    config: pd.DataFrame,
) -> pd.DataFrame:
    rows = []

    for _, incident in incidents.iterrows():
        priority_data = calculate_priority_score(
            incident=incident,
            config=config,
        )

        priority = classify_priority(
            score=priority_data["priority_score"],
            incident=incident,
        )

        row = {
            **incident.to_dict(),
            **priority_data,
            "priority": priority,
        }
        row["priority_reason"] = get_priority_reason(
            priority=priority,
            incident=pd.Series(row),
        )
        rows.append(row)

    result = pd.DataFrame(rows)

    return result.sort_values(
        [
            "priority_score",
            "value_at_risk_per_minute_usd",
        ],
        ascending=False,
    ).reset_index(drop=True)


def print_summary(
    dataframe: pd.DataFrame,
) -> None:
    print("\n=== INCIDENT PRIORITY SUMMARY ===")

    columns = [
        "consolidated_incident_id",
        "root_cause_type",
        "provider",
        "issuing_bank",
        "merchant",
        "country",
        "value_at_risk_per_minute_usd",
        "confidence_score",
        "priority_score",
        "priority",
        "priority_reason",
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

    config = pd.read_csv(
        CONFIG_PATH,
    )

    result = add_priority(
        incidents=incidents,
        config=config,
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

    print("\nPriority calculation completed.")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
