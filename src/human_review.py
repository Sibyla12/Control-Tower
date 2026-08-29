from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json

import pandas as pd


INPUT_PATH = "data/incidents_with_recommendations.csv"
OUTPUT_PATH = "data/reviewed_incidents.csv"
AUDIT_PATH = "data/recommendation_audit_log.csv"


VALID_ACTIONS = {
    "approve",
    "reject",
    "modify",
    "execute",
}


STATUS_TRANSITIONS = {
    "proposed": {
        "approve": "approved",
        "reject": "rejected",
        "modify": "modified",
    },
    "modified": {
        "approve": "approved",
        "reject": "rejected",
        "modify": "modified",
    },
    "approved": {
        "execute": "executed",
        "reject": "rejected",
        "modify": "modified",
    },
    "rejected": {},
    "executed": {},
}


def utc_now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def load_incidents() -> pd.DataFrame:
    dataframe = pd.read_csv(
        INPUT_PATH,
        parse_dates=[
            "start_time",
            "end_time",
        ],
        date_format="mixed",
    )

    required_columns = {
        "consolidated_incident_id",
        "recommendation_status",
        "primary_action",
    }

    missing = required_columns - set(
        dataframe.columns
    )

    if missing:
        raise ValueError(
            f"Missing required columns: {sorted(missing)}"
        )

    return dataframe


def validate_transition(
    current_status: str,
    action: str,
) -> str:
    if action not in VALID_ACTIONS:
        raise ValueError(
            f"Invalid action: {action}"
        )

    allowed = STATUS_TRANSITIONS.get(
        current_status,
        {},
    )

    if action not in allowed:
        raise ValueError(
            f"Action '{action}' is not allowed "
            f"from status '{current_status}'."
        )

    return allowed[action]


def apply_review(
    incidents: pd.DataFrame,
    incident_id: str,
    action: str,
    reviewer: str,
    comment: str | None = None,
    modified_primary_action: str | None = None,
) -> tuple[pd.DataFrame, dict]:
    result = incidents.copy()

    matches = result[
        "consolidated_incident_id"
    ].eq(incident_id)

    if matches.sum() != 1:
        raise ValueError(
            f"Incident not found or duplicated: {incident_id}"
        )

    index = result[matches].index[0]
    current_status = str(
        result.loc[
            index,
            "recommendation_status",
        ]
    )

    next_status = validate_transition(
        current_status=current_status,
        action=action,
    )

    old_primary_action = str(
        result.loc[index, "primary_action"]
    )

    new_primary_action = old_primary_action

    if action == "modify":
        if not modified_primary_action:
            raise ValueError(
                "modified_primary_action is required "
                "when action='modify'."
            )

        new_primary_action = (
            modified_primary_action.strip()
        )

        result.loc[
            index,
            "primary_action",
        ] = new_primary_action

    timestamp = utc_now()

    result.loc[
        index,
        "recommendation_status",
    ] = next_status

    result.loc[
        index,
        "reviewed_by",
    ] = reviewer

    result.loc[
        index,
        "reviewed_at",
    ] = timestamp

    result.loc[
        index,
        "review_comment",
    ] = comment

    if action == "execute":
        result.loc[
            index,
            "executed_at",
        ] = timestamp

    audit_entry = {
        "audit_id": (
            f"AUD-{pd.Timestamp.now().value}"
        ),
        "consolidated_incident_id": incident_id,
        "action": action,
        "previous_status": current_status,
        "new_status": next_status,
        "reviewer": reviewer,
        "comment": comment,
        "previous_primary_action": old_primary_action,
        "new_primary_action": new_primary_action,
        "timestamp": timestamp,
    }

    return result, audit_entry


def append_audit_log(
    entry: dict,
) -> None:
    output = Path(AUDIT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    audit_row = pd.DataFrame([entry])

    if output.exists():
        existing = pd.read_csv(output)
        audit_row = pd.concat(
            [existing, audit_row],
            ignore_index=True,
        )

    audit_row.to_csv(
        output,
        index=False,
    )


def save_incidents(
    incidents: pd.DataFrame,
) -> None:
    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    incidents.to_csv(
        output,
        index=False,
    )


def print_incidents(
    incidents: pd.DataFrame,
) -> None:
    columns = [
        "consolidated_incident_id",
        "priority",
        "incident_title",
        "primary_action",
        "recommendation_status",
        "reviewed_by",
        "review_comment",
    ]

    available = [
        column
        for column in columns
        if column in incidents.columns
    ]

    print("\n=== HUMAN REVIEW SUMMARY ===")
    print(
        incidents[available]
        .to_string(index=False)
    )


def run_demo_reviews(
    incidents: pd.DataFrame,
) -> pd.DataFrame:
    """
    Demo:
    1. Approve the P1 recommendation.
    2. Modify the P2 recommendation.
    """

    p1 = incidents[
        incidents["priority"].eq("P1")
    ].iloc[0]

    incidents, audit = apply_review(
        incidents=incidents,
        incident_id=p1[
            "consolidated_incident_id"
        ],
        action="approve",
        reviewer="demo_operator",
        comment=(
            "Approved provider rerouting mitigation."
        ),
    )

    append_audit_log(audit)

    p2 = incidents[
        incidents["priority"].eq("P2")
    ].iloc[0]

    incidents, audit = apply_review(
        incidents=incidents,
        incident_id=p2[
            "consolidated_incident_id"
        ],
        action="modify",
        reviewer="demo_operator",
        comment=(
            "Added customer communication guidance."
        ),
        modified_primary_action=(
            "Isolate BBVA-issued card failures, "
            "apply controlled retries, and advise "
            "affected customers to use another card."
        ),
    )

    append_audit_log(audit)

    return incidents


def main() -> None:
    incidents = load_incidents()

    for column in [
        "reviewed_by",
        "reviewed_at",
        "review_comment",
        "executed_at",
    ]:
        if column not in incidents.columns:
            incidents[column] = None

    incidents = run_demo_reviews(
        incidents
    )

    save_incidents(incidents)
    print_incidents(incidents)

    print("\nHuman review completed.")
    print(f"Saved at: {OUTPUT_PATH}")
    print(f"Audit log saved at: {AUDIT_PATH}")


if __name__ == "__main__":
    main()