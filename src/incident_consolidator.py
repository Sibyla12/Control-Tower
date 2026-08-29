from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd


INPUT_PATH = "data/root_cause_incidents.csv"
OUTPUT_PATH = "data/consolidated_incidents.csv"


ROOT_TYPE_WEIGHT = {
    "provider": 1.00,
    "issuing_bank": 1.00,
    "payment_method": 0.70,
    "merchant": 0.65,
    "unknown": 0.35,
}

ROOT_CAUSE_PRIORITY = {
    "provider": 4,
    "issuing_bank": 4,
    "payment_method": 2,
    "merchant": 1,
    "unknown": 0,
}


TECHNICAL_CODES = {
    "PROCESSOR_ERROR",
    "ISSUER_UNAVAILABLE",
}


NORMAL_DECLINE_CODES = {
    "INSUFFICIENT_FUNDS",
    "DO_NOT_HONOR",
    "INVALID_CARD",
    "SUSPECTED_FRAUD",
}


def split_values(value) -> set[str]:
    if pd.isna(value):
        return set()

    return {
        item.strip()
        for item in str(value).split("|")
        if item.strip()
    }


def overlap_in_time(
    row_a: pd.Series,
    row_b: pd.Series,
    tolerance_minutes: int = 2,
) -> bool:
    tolerance = pd.Timedelta(minutes=tolerance_minutes)

    return (
        row_a["start_time"]
        <= row_b["end_time"] + tolerance
        and row_b["start_time"]
        <= row_a["end_time"] + tolerance
    )


def calculate_confidence_score(row: pd.Series) -> float:
    root_weight = ROOT_TYPE_WEIGHT.get(
        str(row["root_cause_type"]),
        0.35,
    )

    window_score = min(
        float(row["validated_windows"]) / 12,
        1.0,
    )

    candidate_score = min(
        float(row["candidate_count"]) / 4,
        1.0,
    )

    drop_score = min(
        float(row["approval_rate_drop"]) / 0.30,
        1.0,
    )

    z_score = min(
        float(row["maximum_z_score"]) / 8,
        1.0,
    )

    decline_code = str(
        row["dominant_decline_code"]
    )

    if decline_code in TECHNICAL_CODES:
        code_score = 1.0
    elif decline_code in NORMAL_DECLINE_CODES:
        code_score = 0.20
    else:
        code_score = 0.50

    score = (
        root_weight * 0.20
        + window_score * 0.20
        + candidate_score * 0.15
        + drop_score * 0.20
        + z_score * 0.15
        + code_score * 0.10
    )

    return round(score, 4)


def classify_confidence(score: float) -> str:
    if score >= 0.80:
        return "high"

    if score >= 0.60:
        return "medium"

    return "low"


def incident_strength(row: pd.Series) -> tuple:
    return (
        ROOT_CAUSE_PRIORITY.get(str(row["root_cause_type"]), 0),
        float(row["confidence_score"]),
        int(row["validated_windows"]),
        float(row["approval_rate_drop"]),
    )


def same_country(
    candidate: pd.Series,
    parent: pd.Series,
) -> bool:
    return bool(
        split_values(candidate["country"])
        & split_values(parent["country"])
    )


def same_decline_code(
    candidate: pd.Series,
    parent: pd.Series,
) -> bool:
    candidate_code = str(candidate["dominant_decline_code"])
    parent_code = str(parent["dominant_decline_code"])

    return (
        candidate_code == parent_code
        and candidate_code not in {"nan", "None", ""}
    )


def candidate_explained_by_provider(
    candidate: pd.Series,
    provider_incident: pd.Series,
) -> bool:
    if provider_incident["root_cause_type"] != "provider":
        return False

    if not overlap_in_time(
        candidate,
        provider_incident,
    ):
        return False

    if not same_country(candidate, provider_incident):
        return False

    if not same_decline_code(candidate, provider_incident):
        return False

    provider_overlap = bool(
        split_values(candidate["provider"])
        & split_values(provider_incident["provider"])
    )

    symptom_type = candidate["root_cause_type"] in {
        "issuing_bank",
        "merchant",
        "payment_method",
        "unknown",
    }

    return provider_overlap or symptom_type


def candidate_explained_by_bank(
    candidate: pd.Series,
    bank_incident: pd.Series,
) -> bool:
    if bank_incident["root_cause_type"] != "issuing_bank":
        return False

    if not overlap_in_time(candidate, bank_incident):
        return False

    if not same_country(candidate, bank_incident):
        return False

    if not same_decline_code(candidate, bank_incident):
        return False

    bank_overlap = bool(
        split_values(candidate["issuing_bank"])
        & split_values(bank_incident["issuing_bank"])
    )

    merchant_overlap = bool(
        split_values(candidate["merchant"])
        & split_values(bank_incident["merchant"])
    )

    # Provider-level aggregates do not carry a merchant dimension. Matching
    # country, time and technical decline code is therefore the available
    # evidence that the provider signal is a symptom of the bank incident.
    provider_symptom = candidate["root_cause_type"] == "provider"

    return (
        bank_overlap
        or merchant_overlap
        or provider_symptom
    )


def select_primary_incidents(
    incidents: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    ordered = incidents.copy()
    ordered["root_priority"] = (
        ordered["root_cause_type"]
        .map(ROOT_CAUSE_PRIORITY)
        .fillna(0)
    )
    ordered = ordered.sort_values(
        [
            "confidence_score",
            "root_priority",
            "validated_windows",
            "approval_rate_drop",
        ],
        ascending=False,
    )

    primary_rows = []
    assignments = []

    for _, candidate in ordered.iterrows():
        assigned_parent = None

        for parent in primary_rows:
            parent_series = pd.Series(parent)

            if candidate_explained_by_provider(candidate, parent_series):
                assigned_parent = parent["incident_id"]
                break

            if candidate_explained_by_bank(candidate, parent_series):
                assigned_parent = parent["incident_id"]
                break

        if assigned_parent is not None:
            assignments.append(
                {
                    "incident_id": candidate["incident_id"],
                    "parent_incident_id": assigned_parent,
                }
            )
            continue

        eligible_root = candidate["root_cause_type"] in {
            "provider",
            "issuing_bank",
        }
        strong_enough = float(candidate["confidence_score"]) >= 0.70

        if eligible_root and strong_enough:
            primary_rows.append(candidate.to_dict())
        else:
            assignments.append(
                {
                    "incident_id": candidate["incident_id"],
                    "parent_incident_id": None,
                }
            )

    return pd.DataFrame(primary_rows), pd.DataFrame(assignments)


def find_parent_incident(
    candidate: pd.Series,
    primary_incidents: pd.DataFrame,
) -> str | None:
    for _, parent in primary_incidents.iterrows():
        if (
            candidate["incident_id"]
            == parent["incident_id"]
        ):
            continue

        if candidate_explained_by_provider(
            candidate,
            parent,
        ):
            return str(parent["incident_id"])

        if candidate_explained_by_bank(
            candidate,
            parent,
        ):
            return str(parent["incident_id"])

    return None


def build_incident_summary(
    parent: pd.Series,
    children: pd.DataFrame,
) -> dict:
    source_ids = [str(parent["incident_id"])]

    if not children.empty:
        source_ids.extend(
            children["incident_id"]
            .astype(str)
            .tolist()
        )

    all_rows = pd.concat(
        [
            parent.to_frame().T,
            children,
        ],
        ignore_index=True,
    )

    affected_merchants = sorted(
        set().union(
            *all_rows["merchant"].apply(
                split_values
            )
        )
    )

    affected_methods = sorted(
        set().union(
            *all_rows["payment_method"].apply(
                split_values
            )
        )
    )

    affected_banks = sorted(
        set().union(
            *all_rows["issuing_bank"].apply(
                split_values
            )
        )
    )

    affected_providers = sorted(
        set().union(
            *all_rows["provider"].apply(
                split_values
            )
        )
    )

    confidence_score = float(
        parent["confidence_score"]
    )

    return {
        "consolidated_incident_id": (
            f"ROOT-{uuid4().hex[:8].upper()}"
        ),
        "root_cause_type": (
            parent["root_cause_type"]
        ),
        "provider": parent["provider"],
        "issuing_bank": parent["issuing_bank"],
        "merchant": parent["merchant"],
        "payment_method": (
            parent["payment_method"]
        ),
        "country": parent["country"],
        "dominant_decline_code": (
            parent["dominant_decline_code"]
        ),
        "start_time": all_rows[
            "start_time"
        ].min(),
        "end_time": all_rows[
            "end_time"
        ].max(),
        "confidence_score": confidence_score,
        "confidence_level": (
            classify_confidence(
                confidence_score
            )
        ),
        "attempts": int(parent["attempts"]),
        "approvals": int(parent["approvals"]),
        "observed_approval_rate": float(
            parent["observed_approval_rate"]
        ),
        "expected_approval_rate": float(
            parent["expected_approval_rate"]
        ),
        "approval_rate_drop": float(
            parent["approval_rate_drop"]
        ),
        "validated_windows": int(
            all_rows[
                "validated_windows"
            ].sum()
        ),
        "candidate_count": int(
            all_rows[
                "candidate_count"
            ].sum()
        ),
        "supporting_incidents": (
            len(children)
        ),
        "affected_merchants": "|".join(
            affected_merchants
        ) or None,
        "affected_methods": "|".join(
            affected_methods
        ) or None,
        "affected_banks": "|".join(
            affected_banks
        ) or None,
        "affected_providers": "|".join(
            affected_providers
        ) or None,
        "source_incident_ids": "|".join(
            source_ids
        ),
        "ground_truth_ids": "|".join(
            sorted(
                set().union(
                    *all_rows[
                        "ground_truth_ids"
                    ].apply(split_values)
                )
            )
        ) or None,
    }


def consolidate_incidents(
    incidents: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    incidents = incidents.copy()

    incidents["confidence_score"] = (
        incidents.apply(
            calculate_confidence_score,
            axis=1,
        )
    )

    incidents["confidence_level"] = (
        incidents["confidence_score"]
        .apply(classify_confidence)
    )

    primary_incidents, initial_assignments = (
        select_primary_incidents(incidents)
    )

    incidents["parent_incident_id"] = None

    if not initial_assignments.empty:
        assignment_map = dict(
            zip(
                initial_assignments["incident_id"],
                initial_assignments["parent_incident_id"],
            )
        )
        incidents["parent_incident_id"] = (
            incidents["incident_id"].map(assignment_map)
        )

    primary_ids = set(
        primary_incidents["incident_id"]
        if not primary_incidents.empty
        else []
    )

    for index, candidate in incidents.iterrows():
        if candidate["incident_id"] in primary_ids:
            continue

        best_parent = None
        best_parent_score = -1.0

        for _, parent in primary_incidents.iterrows():
            explained = (
                candidate_explained_by_provider(candidate, parent)
                or candidate_explained_by_bank(candidate, parent)
            )

            if not explained:
                continue

            parent_score = float(parent["confidence_score"])
            if parent_score > best_parent_score:
                best_parent = parent["incident_id"]
                best_parent_score = parent_score

        if best_parent is not None:
            incidents.loc[index, "parent_incident_id"] = best_parent

    suppressed_primary_ids = set()

    for _, candidate in primary_incidents.iterrows():
        for _, parent in primary_incidents.iterrows():
            if candidate["incident_id"] == parent["incident_id"]:
                continue

            if float(parent["confidence_score"]) <= float(
                candidate["confidence_score"]
            ):
                continue

            explained = (
                candidate_explained_by_provider(candidate, parent)
                or candidate_explained_by_bank(candidate, parent)
            )

            if explained:
                suppressed_primary_ids.add(candidate["incident_id"])
                candidate_index = incidents[
                    incidents["incident_id"].eq(candidate["incident_id"])
                ].index
                incidents.loc[
                    candidate_index,
                    "parent_incident_id",
                ] = parent["incident_id"]

    primary_incidents = primary_incidents[
        ~primary_incidents["incident_id"].isin(
            suppressed_primary_ids
        )
    ].copy()

    consolidated = []

    for _, parent in primary_incidents.iterrows():
        children = incidents[
            incidents["parent_incident_id"].eq(
                parent["incident_id"]
            )
        ].copy()

        consolidated.append(
            build_incident_summary(
                parent=parent,
                children=children,
            )
        )

    consolidated_df = pd.DataFrame(
        consolidated
    )

    explained_ids = set(
        primary_incidents[
            "incident_id"
        ].astype(str)
    )

    explained_ids.update(
        incidents.loc[
            incidents["parent_incident_id"].notna(),
            "incident_id",
        ].astype(str)
    )

    unresolved = incidents[
        ~incidents["incident_id"]
        .astype(str)
        .isin(explained_ids)
    ].copy()

    return consolidated_df, unresolved


def print_summary(
    consolidated: pd.DataFrame,
    unresolved: pd.DataFrame,
) -> None:
    print(
        "\n=== INCIDENT CONSOLIDATION SUMMARY ==="
    )
    print(
        f"Consolidated incidents: "
        f"{len(consolidated):,}"
    )
    print(
        f"Unresolved candidates: "
        f"{len(unresolved):,}"
    )

    if not consolidated.empty:
        columns = [
            "consolidated_incident_id",
            "root_cause_type",
            "provider",
            "issuing_bank",
            "merchant",
            "country",
            "dominant_decline_code",
            "confidence_score",
            "confidence_level",
            "supporting_incidents",
            "validated_windows",
            "ground_truth_ids",
        ]

        print("\nConsolidated incidents:")
        print(
            consolidated[
                columns
            ]
            .sort_values(
                [
                    "confidence_score",
                    "validated_windows",
                ],
                ascending=False,
            )
            .to_string(index=False)
        )

    if not unresolved.empty:
        print("\nUnresolved candidates:")

        columns = [
            "incident_id",
            "root_cause_type",
            "provider",
            "issuing_bank",
            "merchant",
            "country",
            "dominant_decline_code",
            "confidence_score",
            "confidence_level",
            "validated_windows",
            "ground_truth_ids",
        ]

        print(
            unresolved[
                columns
            ]
            .sort_values(
                [
                    "confidence_score",
                    "validated_windows",
                ],
                ascending=False,
            )
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

    consolidated, unresolved = (
        consolidate_incidents(
            incidents
        )
    )

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    consolidated.to_csv(
        output,
        index=False,
    )

    unresolved.to_csv(
        "data/unresolved_incident_candidates.csv",
        index=False,
    )

    print_summary(
        consolidated=consolidated,
        unresolved=unresolved,
    )

    print(
        "\nIncident consolidation completed."
    )
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
