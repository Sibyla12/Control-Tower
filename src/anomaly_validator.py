from __future__ import annotations

from pathlib import Path

import pandas as pd
from scipy.stats import norm


INPUT_PATH = "data/generated/anomaly_candidates.csv"
OUTPUT_PATH = "data/generated/validated_anomalies.csv"

FDR_ALPHA = 0.05
MIN_CONSECUTIVE_WINDOWS = 2

DIMENSION_COLUMNS = [
    "merchant",
    "provider",
    "payment_method",
    "country",
    "issuing_bank",
]


def calculate_p_values(dataframe: pd.DataFrame) -> pd.DataFrame:
    result = dataframe.copy()

    # One-sided test: probability of observing an equal or larger drop.
    result["p_value"] = norm.sf(result["z_score"].fillna(0))
    result.loc[
        result["detection_status"].ne("confirmed_anomaly"),
        "p_value",
    ] = 1.0

    return result


def apply_benjamini_hochberg(
    group: pd.DataFrame,
) -> pd.DataFrame:
    """Control the false discovery rate within each minute."""
    result = group.copy()
    result = result.sort_values("p_value").reset_index(drop=False)
    number_of_tests = len(result)

    result["bh_rank"] = range(1, number_of_tests + 1)
    result["bh_threshold"] = (
        result["bh_rank"] / number_of_tests * FDR_ALPHA
    )
    result["passes_fdr"] = result["p_value"] <= result["bh_threshold"]

    passing_rows = result[result["passes_fdr"]]
    if passing_rows.empty:
        result["passes_fdr"] = False
    else:
        maximum_rank = int(passing_rows["bh_rank"].max())
        result["passes_fdr"] = result["bh_rank"] <= maximum_rank

    return result.set_index("index")


def apply_fdr_by_minute(dataframe: pd.DataFrame) -> pd.DataFrame:
    corrected_groups = []

    for _, group in dataframe.groupby("minute", dropna=False):
        corrected_groups.append(apply_benjamini_hochberg(group))

    result = pd.concat(corrected_groups, axis=0)
    return result.sort_index().reset_index(drop=True)


def create_segment_key(row: pd.Series) -> str:
    dimensions = []

    for column in DIMENSION_COLUMNS:
        value = row[column]
        if pd.notna(value):
            dimensions.append(f"{column}={value}")

    return f"{row['detection_level']}|" + "|".join(dimensions)


def add_persistence(dataframe: pd.DataFrame) -> pd.DataFrame:
    result = dataframe.copy()
    result["segment_key"] = result.apply(create_segment_key, axis=1)
    result = result.sort_values(
        ["segment_key", "minute"]
    ).reset_index(drop=True)
    result["consecutive_significant_windows"] = 0

    for _, indices in result.groupby("segment_key").groups.items():
        consecutive_count = 0
        previous_minute = None

        for index in indices:
            row = result.loc[index]
            current_minute = row["minute"]
            is_significant = bool(
                row["passes_fdr"]
                and row["detection_status"] == "confirmed_anomaly"
            )
            is_consecutive_minute = (
                previous_minute is not None
                and (current_minute - previous_minute).total_seconds() == 60
            )

            if is_significant:
                if previous_minute is None or is_consecutive_minute:
                    consecutive_count += 1
                else:
                    consecutive_count = 1
            else:
                consecutive_count = 0

            result.loc[
                index,
                "consecutive_significant_windows",
            ] = consecutive_count
            previous_minute = current_minute

    result["validated_anomaly"] = (
        result["passes_fdr"]
        & (
            result["consecutive_significant_windows"]
            >= MIN_CONSECUTIVE_WINDOWS
        )
    )

    return result


def print_summary(dataframe: pd.DataFrame) -> None:
    raw_confirmed = dataframe[
        dataframe["detection_status"].eq("confirmed_anomaly")
    ]
    fdr_confirmed = dataframe[dataframe["passes_fdr"]]
    validated = dataframe[dataframe["validated_anomaly"]]

    print("\n=== ANOMALY VALIDATION SUMMARY ===")
    print(f"Raw confirmed windows: {len(raw_confirmed):,}")
    print(f"Windows passing FDR: {len(fdr_confirmed):,}")
    print(
        "Windows passing FDR + persistence: "
        f"{len(validated):,}"
    )

    if validated.empty:
        return

    direct = validated[validated["injected_share"] >= 0.50]
    partial = validated[
        validated["injected_share"].between(0.01, 0.499999)
    ]
    clean = validated[validated["injected_share"].eq(0)]

    print(f"\nValidated directly affected: {len(direct):,}")
    print(f"Validated partially affected: {len(partial):,}")
    print(f"Validated with zero injected traffic: {len(clean):,}")

    print("\nValidated anomalies by level:")
    by_level = (
        validated
        .groupby("detection_level")
        .agg(
            windows=("minute", "count"),
            segments=("segment_key", "nunique"),
            average_drop=("approval_rate_drop", "mean"),
        )
        .sort_values("windows", ascending=False)
    )
    print(by_level.to_string())

    truth_rows = validated[validated["incident_ids"].notna()].copy()
    if not truth_rows.empty:
        truth_rows["incident_id"] = truth_rows["incident_ids"].str.split("|")
        truth_rows = truth_rows.explode("incident_id")
        truth_summary = (
            truth_rows
            .groupby("incident_id")
            .agg(
                validated_windows=("minute", "count"),
                first_validation=("minute", "min"),
                last_validation=("minute", "max"),
            )
        )

        print("\nGround-truth validation:")
        print(truth_summary.to_string())


def main() -> None:
    candidates = pd.read_csv(
        INPUT_PATH,
        parse_dates=["minute"],
        date_format="mixed",
    )
    candidates = calculate_p_values(candidates)
    candidates = apply_fdr_by_minute(candidates)
    validated = add_persistence(candidates)

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(parents=True, exist_ok=True)
    validated.to_csv(output, index=False)

    print_summary(validated)
    print("\nAnomaly validation completed.")
    print(f"Rows analyzed: {len(validated):,}")
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
