from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd


BASELINE_PATH = "data/hierarchical_baselines.csv"
MIN_ATTEMPTS = 30


@dataclass
class BaselineResult:
    expected_approval_rate: float
    average_amount: float
    historical_attempts: int
    baseline_level: str
    dimensions_used: dict[str, Any]
    is_reliable: bool


BASELINE_LEVELS = [
    {
        "name": "L1_FULL",
        "dimensions": [
            "merchant",
            "provider",
            "payment_method",
            "country",
            "weekday",
            "hour",
        ],
    },
    {
        "name": "L2_NO_MERCHANT",
        "dimensions": [
            "provider",
            "payment_method",
            "country",
            "weekday",
            "hour",
        ],
    },
    {
        "name": "L3_NO_PROVIDER",
        "dimensions": [
            "payment_method",
            "country",
            "weekday",
            "hour",
        ],
    },
    {
        "name": "L4_HOUR",
        "dimensions": [
            "payment_method",
            "country",
            "hour",
        ],
    },
    {
        "name": "L5_METHOD_COUNTRY",
        "dimensions": [
            "payment_method",
            "country",
        ],
    },
    {
        "name": "L6_GLOBAL",
        "dimensions": [],
    },
]


def load_baselines(
    path: str = BASELINE_PATH,
) -> pd.DataFrame:
    dataframe = pd.read_csv(path)

    dataframe["is_reliable"] = (
        dataframe["is_reliable"]
        .astype(str)
        .str.lower()
        .eq("true")
    )

    return dataframe


def values_match(
    series: pd.Series,
    expected_value: Any,
) -> pd.Series:
    if pd.isna(expected_value):
        return series.isna()

    if pd.api.types.is_numeric_dtype(series):
        return series.eq(float(expected_value))

    return series.astype(str).eq(str(expected_value))


def find_baseline_row(
    baselines: pd.DataFrame,
    level_name: str,
    dimensions: list[str],
    segment: dict[str, Any],
) -> pd.Series | None:
    candidates = baselines[
        baselines["baseline_level"].eq(level_name)
    ].copy()

    for dimension in dimensions:
        if dimension not in segment:
            return None

        candidates = candidates[
            values_match(
                candidates[dimension],
                segment[dimension],
            )
        ]

    candidates = candidates[
        candidates["attempts"] >= MIN_ATTEMPTS
    ]

    if candidates.empty:
        return None

    return candidates.sort_values(
        by="attempts",
        ascending=False,
    ).iloc[0]


def get_expected_baseline(
    baselines: pd.DataFrame,
    segment: dict[str, Any],
) -> BaselineResult:
    for level in BASELINE_LEVELS:
        row = find_baseline_row(
            baselines=baselines,
            level_name=level["name"],
            dimensions=level["dimensions"],
            segment=segment,
        )

        if row is None:
            continue

        dimensions_used = {
            dimension: segment[dimension]
            for dimension in level["dimensions"]
        }

        return BaselineResult(
            expected_approval_rate=float(
                row["approval_rate"]
            ),
            average_amount=float(
                row["average_amount"]
            ),
            historical_attempts=int(
                row["attempts"]
            ),
            baseline_level=str(
                row["baseline_level"]
            ),
            dimensions_used=dimensions_used,
            is_reliable=bool(
                row["is_reliable"]
            ),
        )

    raise LookupError(
        "No reliable baseline could be found."
    )


def main() -> None:
    baselines = load_baselines()

    test_segments = [
        {
            "merchant": "Merchant_A",
            "provider": "Adyen",
            "payment_method": "PIX",
            "country": "BR",
            "weekday": 0,
            "hour": 0,
        },
        {
            "merchant": "Merchant_A",
            "provider": "Adyen",
            "payment_method": "PIX",
            "country": "BR",
            "weekday": 0,
            "hour": 10,
        },
        {
            "merchant": "Merchant_B",
            "provider": "Stripe",
            "payment_method": "card",
            "country": "MX",
            "weekday": 2,
            "hour": 15,
        },
    ]

    for segment in test_segments:
        result = get_expected_baseline(
            baselines=baselines,
            segment=segment,
        )

        print("\n=== BASELINE RESULT ===")
        print(f"Segment: {segment}")
        print(
            "Expected approval rate: "
            f"{result.expected_approval_rate:.2%}"
        )
        print(
            f"Historical attempts: "
            f"{result.historical_attempts:,}"
        )
        print(
            f"Baseline level: "
            f"{result.baseline_level}"
        )
        print(
            f"Dimensions used: "
            f"{result.dimensions_used}"
        )


if __name__ == "__main__":
    main()
    