from __future__ import annotations

from pathlib import Path

import pandas as pd


INPUT_PATH = "data/generated/detection_windows.csv"
OUTPUT_PATH = "data/generated/adaptive_detection_windows.csv"

MIN_ATTEMPTS = 30

DIMENSION_COLUMNS = [
    "merchant",
    "provider",
    "payment_method",
    "country",
    "issuing_bank",
]


def load_detection_windows() -> pd.DataFrame:
    dataframe = pd.read_csv(
        INPUT_PATH,
        parse_dates=["minute"],
        date_format="mixed",
    )

    return dataframe.sort_values(
        ["detection_level", "minute"]
    ).reset_index(drop=True)


def dominant_value(values: pd.Series) -> str | None:
    clean_values = values.dropna()

    if clean_values.empty:
        return None

    mode = clean_values.mode()

    if mode.empty:
        return None

    return str(mode.iloc[0])


def get_grouping_dimensions(
    dataframe: pd.DataFrame,
) -> list[str]:
    dimensions = []

    for column in DIMENSION_COLUMNS:
        if column not in dataframe.columns:
            continue

        if dataframe[column].notna().any():
            dimensions.append(column)

    return dimensions


def build_rolling_windows_for_level(
    level_data: pd.DataFrame,
    window_minutes: int = 5,
) -> pd.DataFrame:
    level_name = str(
        level_data["detection_level"].iloc[0]
    )

    dimensions = get_grouping_dimensions(level_data)

    grouping_columns = [
        "detection_level",
        *dimensions,
    ]

    results: list[dict] = []

    for group_values, group in level_data.groupby(
        grouping_columns,
        dropna=False,
    ):
        group = group.sort_values("minute").copy()

        if not isinstance(group_values, tuple):
            group_values = (group_values,)

        group_metadata = dict(
            zip(grouping_columns, group_values)
        )

        group = group.set_index("minute")

        attempts = group["attempts"].rolling(
            f"{window_minutes}min",
            closed="both",
        ).sum()

        approvals = group["approvals"].rolling(
            f"{window_minutes}min",
            closed="both",
        ).sum()

        declines = group["declines"].rolling(
            f"{window_minutes}min",
            closed="both",
        ).sum()

        injected_records = group[
            "injected_records"
        ].rolling(
            f"{window_minutes}min",
            closed="both",
        ).sum()

        for timestamp in group.index:
            window_attempts = int(attempts.loc[timestamp])
            window_approvals = int(approvals.loc[timestamp])
            window_declines = int(declines.loc[timestamp])
            window_injected_records = int(
                injected_records.loc[timestamp]
            )

            recent_start = (
                timestamp
                - pd.Timedelta(
                    minutes=window_minutes - 1
                )
            )

            recent_rows = group.loc[
                (group.index >= recent_start)
                & (group.index <= timestamp)
            ]

            row = {
                **group_metadata,
                "minute": timestamp,
                "weekday": timestamp.weekday(),
                "hour": timestamp.hour,
                "window_minutes": window_minutes,
                "attempts": window_attempts,
                "approvals": window_approvals,
                "declines": window_declines,
                "approval_rate": (
                    window_approvals / window_attempts
                    if window_attempts > 0
                    else 0.0
                ),
                "injected_records": window_injected_records,
                "injected_share": (
                    window_injected_records / window_attempts
                    if window_attempts > 0
                    else 0.0
                ),
                "incident_ids": "|".join(
                    sorted(
                        {
                            incident_id
                            for value in recent_rows[
                                "incident_ids"
                            ].dropna()
                            for incident_id in str(value).split("|")
                            if incident_id
                        }
                    )
                )
                or None,
                "dominant_decline_code": dominant_value(
                    recent_rows[
                        "dominant_decline_code"
                    ]
                ),
                "injected_incident_id": dominant_value(
                    recent_rows[
                        "injected_incident_id"
                    ]
                ),
            }

            for dimension in DIMENSION_COLUMNS:
                if dimension not in row:
                    row[dimension] = None

            results.append(row)

    return pd.DataFrame(results)


def build_adaptive_windows(
    dataframe: pd.DataFrame,
) -> pd.DataFrame:
    one_minute = dataframe.copy()
    one_minute["window_minutes"] = 1

    rolling_results = []

    for _, level_data in dataframe.groupby(
        "detection_level"
    ):
        rolling_results.append(
            build_rolling_windows_for_level(
                level_data=level_data,
                window_minutes=5,
            )
        )

    five_minute = pd.concat(
        rolling_results,
        ignore_index=True,
    )

    one_minute["window_usable"] = (
        one_minute["attempts"] >= MIN_ATTEMPTS
    )

    five_minute["window_usable"] = (
        five_minute["attempts"] >= MIN_ATTEMPTS
    )

    one_minute["window_strategy"] = "fast_1m"
    five_minute["window_strategy"] = "fallback_5m"

    return pd.concat(
        [one_minute, five_minute],
        ignore_index=True,
    )


def select_best_windows(
    adaptive_windows: pd.DataFrame,
) -> pd.DataFrame:
    identity_columns = [
        "minute",
        "detection_level",
        *DIMENSION_COLUMNS,
    ]

    selected_rows = []

    for _, group in adaptive_windows.groupby(
        identity_columns,
        dropna=False,
    ):
        one_minute = group[
            group["window_minutes"].eq(1)
        ]

        five_minute = group[
            group["window_minutes"].eq(5)
        ]

        if (
            not one_minute.empty
            and bool(
                one_minute.iloc[0]["window_usable"]
            )
        ):
            selected_rows.append(one_minute.iloc[0])
            continue

        if (
            not five_minute.empty
            and bool(
                five_minute.iloc[0]["window_usable"]
            )
        ):
            selected_rows.append(five_minute.iloc[0])
            continue

        fallback = (
            five_minute.iloc[0]
            if not five_minute.empty
            else one_minute.iloc[0]
        )

        fallback = fallback.copy()
        fallback["window_strategy"] = (
            "insufficient_data"
        )

        selected_rows.append(fallback)

    return pd.DataFrame(selected_rows)


def print_summary(
    selected_windows: pd.DataFrame,
) -> None:
    summary = (
        selected_windows
        .groupby(
            [
                "detection_level",
                "window_strategy",
            ]
        )
        .agg(
            windows=("minute", "count"),
            average_attempts=("attempts", "mean"),
            minimum_attempts=("attempts", "min"),
            maximum_attempts=("attempts", "max"),
        )
    )

    print("\n=== ADAPTIVE WINDOW SUMMARY ===")
    print(summary.to_string())

    insufficient = selected_windows[
        selected_windows[
            "window_strategy"
        ].eq("insufficient_data")
    ]

    print(
        "\nWindows still lacking evidence: "
        f"{len(insufficient):,}"
    )


def main() -> None:
    detection_windows = load_detection_windows()

    adaptive_windows = build_adaptive_windows(
        detection_windows
    )

    selected_windows = select_best_windows(
        adaptive_windows
    )

    output = Path(OUTPUT_PATH)
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    selected_windows.to_csv(
        output,
        index=False,
    )

    print_summary(selected_windows)

    print(
        "\nAdaptive windows generated successfully."
    )
    print(
        f"Selected windows: "
        f"{len(selected_windows):,}"
    )
    print(f"Saved at: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
