from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pandas as pd


INPUT_PATH = "data/generated/validated_anomalies.csv"
OUTPUT_PATH = "data/generated/clustered_incidents.csv"

MAX_GAP_MINUTES = 2

DIMENSION_COLUMNS = [
    "merchant",
    "provider",
    "payment_method",
    "country",
    "issuing_bank",
]


def clean_value(value):
    if pd.isna(value):
        return None
    return str(value)


def build_cluster_key(row: pd.Series) -> str:
    """
    Agrupa primero por el nivel y las dimensiones visibles.
    Más adelante fusionaremos evidencias de distintos niveles.
    """
    parts = [str(row["detection_level"])]

    for column in DIMENSION_COLUMNS:
        value = clean_value(row[column])

        if value is not None:
            parts.append(f"{column}={value}")

    return "|".join(parts)


def split_temporal_clusters(
    group: pd.DataFrame,
) -> list[pd.DataFrame]:
    group = group.sort_values("minute").copy()

    clusters = []
    current_indices = []
    previous_minute = None

    for index, row in group.iterrows():
        current_minute = row["minute"]

        if previous_minute is None:
            current_indices = [index]

        else:
            gap_minutes = (
                current_minute - previous_minute
            ).total_seconds() / 60

            if gap_minutes <= MAX_GAP_MINUTES:
                current_indices.append(index)
            else:
                clusters.append(
                    group.loc[current_indices].copy()
                )
                current_indices = [index]

        previous_minute = current_minute

    if current_indices:
        clusters.append(
            group.loc[current_indices].copy()
        )

    return clusters


def dominant_non_null(series: pd.Series):
    values = series.dropna().astype(str)

    if values.empty:
        return None

    mode = values.mode()

    if mode.empty:
        return None

    return mode.iloc[0]


def join_unique(series: pd.Series) -> str | None:
    values = sorted(
        {
            item
            for raw_value in series.dropna().astype(str)
            for item in raw_value.split("|")
            if item
        }
    )

    return "|".join(values) if values else None


def summarize_cluster(
    cluster: pd.DataFrame,
) -> dict:
    total_attempts = int(cluster["attempts"].sum())
    total_approvals = int(cluster["approvals"].sum())

    observed_rate = (
        total_approvals / total_attempts
        if total_attempts > 0
        else 0.0
    )

    weighted_expected = (
        (
            cluster["expected_approval_rate"]
            * cluster["attempts"]
        ).sum()
        / total_attempts
        if total_attempts > 0
        else 0.0
    )

    weighted_drop = weighted_expected - observed_rate

    return {
        "incident_candidate_id": (
            f"CAND-{uuid4().hex[:8].upper()}"
        ),
        "cluster_key": cluster["cluster_key"].iloc[0],
        "detection_level": dominant_non_null(
            cluster["detection_level"]
        ),
        "start_time": cluster["minute"].min(),
        "end_time": cluster["minute"].max(),
        "duration_minutes": int(
            (
                cluster["minute"].max()
                - cluster["minute"].min()
            ).total_seconds()
            / 60
        ) + 1,
        "validated_windows": len(cluster),
        "merchant": dominant_non_null(
            cluster["merchant"]
        ),
        "provider": dominant_non_null(
            cluster["provider"]
        ),
        "payment_method": dominant_non_null(
            cluster["payment_method"]
        ),
        "country": dominant_non_null(
            cluster["country"]
        ),
        "issuing_bank": dominant_non_null(
            cluster["issuing_bank"]
        ),
        "attempts": total_attempts,
        "approvals": total_approvals,
        "observed_approval_rate": observed_rate,
        "expected_approval_rate": weighted_expected,
        "approval_rate_drop": weighted_drop,
        "maximum_z_score": float(
            cluster["z_score"].max()
        ),
        "average_z_score": float(
            cluster["z_score"].mean()
        ),
        "dominant_decline_code": dominant_non_null(
            cluster["dominant_decline_code"]
        ),
        "incident_ids": join_unique(
            cluster["incident_ids"]
        ),
        "average_injected_share": float(
            cluster["injected_share"].mean()
        ),
        "maximum_injected_share": float(
            cluster["injected_share"].max()
        ),
    }


def build_incident_candidates(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    validated = dataframe[
        dataframe["validated_anomaly"].eq(True)
    ].copy()

    validated["cluster_key"] = validated.apply(
        build_cluster_key,
        axis=1,
    )

    incidents = []

    for _, group in validated.groupby(
        "cluster_key",
        dropna=False,
    ):
        temporal_clusters = split_temporal_clusters(group)

        for cluster in temporal_clusters:
            incidents.append(
                summarize_cluster(cluster)
            )

    return pd.DataFrame(incidents)


def print_summary(incidents: pd.DataFrame) -> None:
    print("\n=== INCIDENT CLUSTERING SUMMARY ===")
    print(
        f"Validated windows received: "
        f"{incidents['validated_windows'].sum():,}"
    )
    print(
        f"Incident candidates created: "
        f"{len(incidents):,}"
    )

    if incidents.empty:
        return

    truth = (
        incidents[
            incidents["incident_ids"].notna()
        ]
        .groupby("incident_ids")
        .agg(
            candidates=("incident_candidate_id", "count"),
            first_start=("start_time", "min"),
            last_end=("end_time", "max"),
            total_windows=("validated_windows", "sum"),
        )
    )

    print("\nCandidates connected to injected incidents:")
    print(truth.to_string())

    clean = incidents[
        incidents["incident_ids"].isna()
    ]

    print(
        "\nCandidates with zero injected traffic: "
        f"{len(clean):,}"
    )

    print("\nTop candidates:")
    columns = [
        "incident_candidate_id",
        "detection_level",
        "merchant",
        "provider",
        "payment_method",
        "country",
        "issuing_bank",
        "start_time",
        "duration_minutes",
        "validated_windows",
        "approval_rate_drop",
        "incident_ids",
    ]

    print(
        incidents.sort_values(
            ["validated_windows", "approval_rate_drop"],
            ascending=False,
        )[columns]
        .head(20)
        .to_string(index=False)
    )


def main() -> None:
    dataframe = pd.read_csv(
        INPUT_PATH,
        parse_dates=["minute"],
        date_format="mixed",
    )

    incidents = build_incident_candidates(
        dataframe
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

    print("\nIncident clustering completed.")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()