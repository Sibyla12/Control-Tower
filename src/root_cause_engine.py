from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd


INPUT_PATH = "data/clustered_incidents.csv"
OUTPUT_PATH = "data/root_cause_incidents.csv"


def time_overlap(
    row_a: pd.Series,
    row_b: pd.Series,
    tolerance_minutes: int = 2,
) -> bool:
    start_a = row_a["start_time"]
    end_a = row_a["end_time"]
    start_b = row_b["start_time"]
    end_b = row_b["end_time"]

    tolerance = pd.Timedelta(minutes=tolerance_minutes)

    return (
        start_a <= end_b + tolerance
        and start_b <= end_a + tolerance
    )


def same_value(
    row_a: pd.Series,
    row_b: pd.Series,
    column: str,
) -> bool:
    value_a = row_a[column]
    value_b = row_b[column]

    if pd.isna(value_a) or pd.isna(value_b):
        return False

    return str(value_a) == str(value_b)


def provider_root_match(
    row_a: pd.Series,
    row_b: pd.Series,
) -> bool:
    return (
        same_value(row_a, row_b, "provider")
        and same_value(row_a, row_b, "country")
        and time_overlap(row_a, row_b)
    )


def bank_root_match(
    row_a: pd.Series,
    row_b: pd.Series,
) -> bool:
    return (
        same_value(row_a, row_b, "issuing_bank")
        and same_value(row_a, row_b, "country")
        and time_overlap(row_a, row_b)
    )


def merchant_root_match(
    row_a: pd.Series,
    row_b: pd.Series,
) -> bool:
    return (
        same_value(row_a, row_b, "merchant")
        and same_value(row_a, row_b, "country")
        and time_overlap(row_a, row_b)
    )


def method_root_match(
    row_a: pd.Series,
    row_b: pd.Series,
) -> bool:
    return (
        same_value(row_a, row_b, "payment_method")
        and same_value(row_a, row_b, "country")
        and time_overlap(row_a, row_b)
    )


def decline_code_root_match(
    row_a: pd.Series,
    row_b: pd.Series,
) -> bool:
    return (
        same_value(row_a, row_b, "dominant_decline_code")
        and same_value(row_a, row_b, "country")
        and time_overlap(row_a, row_b)
    )


def infer_candidate_type(row: pd.Series) -> str:
    level = str(row["detection_level"])

    if level in {
        "L1_PROVIDER_COUNTRY",
        "L5_PROVIDER_METHOD_COUNTRY",
    } and pd.notna(row["provider"]):
        return "provider"

    if level in {
        "L4_BANK_COUNTRY",
        "L6_MERCHANT_BANK_COUNTRY",
    } and pd.notna(row["issuing_bank"]):
        return "issuing_bank"

    if level == "L3_MERCHANT_COUNTRY":
        return "merchant"

    if level == "L2_METHOD_COUNTRY":
        return "payment_method"

    # The detection level couldn't attribute this candidate to a specific
    # provider/bank/merchant/method (e.g. the issuing bank behind the drop
    # wasn't resolved). A concentrated decline code is still a diagnosable
    # dimension on its own - fall back to it before giving up entirely.
    if pd.notna(row["dominant_decline_code"]):
        return "decline_code"

    return "unknown"


def candidate_matches_group(
    row: pd.Series,
    group_seed: pd.Series,
    root_type: str,
) -> bool:
    if root_type == "provider":
        return provider_root_match(row, group_seed)

    if root_type == "issuing_bank":
        return bank_root_match(row, group_seed)

    if root_type == "merchant":
        return merchant_root_match(row, group_seed)

    if root_type == "payment_method":
        return method_root_match(row, group_seed)

    if root_type == "decline_code":
        return decline_code_root_match(row, group_seed)

    return False


def group_candidates(
    candidates: pd.DataFrame,
) -> list[pd.DataFrame]:
    unassigned = set(candidates.index.tolist())
    groups: list[pd.DataFrame] = []

    ordered_indices = (
        candidates
        .sort_values(
            ["validated_windows", "approval_rate_drop"],
            ascending=False,
        )
        .index
        .tolist()
    )

    for seed_index in ordered_indices:
        if seed_index not in unassigned:
            continue

        seed = candidates.loc[seed_index]
        root_type = infer_candidate_type(seed)

        current_indices = [seed_index]
        unassigned.remove(seed_index)

        if root_type != "unknown":
            for candidate_index in list(unassigned):
                candidate = candidates.loc[candidate_index]

                if candidate_matches_group(
                    candidate,
                    seed,
                    root_type,
                ):
                    current_indices.append(candidate_index)
                    unassigned.remove(candidate_index)

        groups.append(
            candidates.loc[current_indices].copy()
        )

    return groups


def join_unique_values(
    series: pd.Series,
) -> str | None:
    values = sorted(
        {
            str(value)
            for value in series.dropna()
            if str(value)
        }
    )

    return "|".join(values) if values else None


def summarize_root_cause(
    group: pd.DataFrame,
) -> dict:
    group = group.copy()

    root_types = group.apply(
        infer_candidate_type,
        axis=1,
    )

    root_type = (
        root_types.value_counts().index[0]
        if not root_types.empty
        else "unknown"
    )

    total_attempts = int(group["attempts"].sum())
    total_approvals = int(group["approvals"].sum())

    observed_rate = (
        total_approvals / total_attempts
        if total_attempts > 0
        else 0.0
    )

    weighted_expected = (
        (
            group["expected_approval_rate"]
            * group["attempts"]
        ).sum()
        / total_attempts
        if total_attempts > 0
        else 0.0
    )

    provider = join_unique_values(group["provider"])
    issuing_bank = join_unique_values(group["issuing_bank"])
    merchant = join_unique_values(group["merchant"])
    payment_method = join_unique_values(
        group["payment_method"]
    )
    country = join_unique_values(group["country"])

    return {
        "incident_id": f"INC-{uuid4().hex[:8].upper()}",
        "root_cause_type": root_type,
        "start_time": group["start_time"].min(),
        "end_time": group["end_time"].max(),
        "candidate_count": len(group),
        "validated_windows": int(
            group["validated_windows"].sum()
        ),
        "provider": provider,
        "issuing_bank": issuing_bank,
        "merchant": merchant,
        "payment_method": payment_method,
        "country": country,
        "attempts": total_attempts,
        "approvals": total_approvals,
        "observed_approval_rate": observed_rate,
        "expected_approval_rate": weighted_expected,
        "approval_rate_drop": (
            weighted_expected - observed_rate
        ),
        "maximum_z_score": float(
            group["maximum_z_score"].max()
        ),
        "dominant_decline_code": (
            group["dominant_decline_code"]
            .dropna()
            .mode()
            .iloc[0]
            if not group[
                "dominant_decline_code"
            ].dropna().empty
            else None
        ),
        "source_candidates": "|".join(
            group["incident_candidate_id"]
            .astype(str)
            .tolist()
        ),
        "ground_truth_ids": join_unique_values(
            group["incident_ids"]
        ),
        "average_injected_share": float(
            group["average_injected_share"].mean()
        ),
    }


def build_root_cause_incidents(
    candidates: pd.DataFrame,
) -> pd.DataFrame:
    groups = group_candidates(candidates)

    incidents = [
        summarize_root_cause(group)
        for group in groups
    ]

    return pd.DataFrame(incidents)


def print_summary(incidents: pd.DataFrame) -> None:
    print("\n=== ROOT CAUSE SUMMARY ===")
    print(
        f"Root-cause incidents created: "
        f"{len(incidents):,}"
    )

    linked = incidents[
        incidents["ground_truth_ids"].notna()
    ]

    clean = incidents[
        incidents["ground_truth_ids"].isna()
    ]

    print(
        f"Incidents connected to injected truth: "
        f"{len(linked):,}"
    )
    print(
        f"Incidents without injected truth: "
        f"{len(clean):,}"
    )

    columns = [
        "incident_id",
        "root_cause_type",
        "provider",
        "issuing_bank",
        "merchant",
        "payment_method",
        "country",
        "candidate_count",
        "validated_windows",
        "approval_rate_drop",
        "dominant_decline_code",
        "ground_truth_ids",
    ]

    print("\nTop incidents:")
    print(
        incidents.sort_values(
            ["validated_windows", "approval_rate_drop"],
            ascending=False,
        )[columns]
        .head(20)
        .to_string(index=False)
    )


def main() -> None:
    candidates = pd.read_csv(
        INPUT_PATH,
        parse_dates=["start_time", "end_time"],
        date_format="mixed",
    )

    incidents = build_root_cause_incidents(
        candidates
    )

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    incidents.to_csv(
        output,
        index=False,
    )

    print_summary(incidents)

    print("\nRoot-cause analysis completed.")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()