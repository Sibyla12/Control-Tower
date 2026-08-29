from __future__ import annotations

from dataclasses import dataclass
from math import sqrt

from baseline_selector import (
    BaselineResult,
    get_expected_baseline,
    load_baselines,
)


MIN_LIVE_ATTEMPTS = 30
MIN_DROP_POINTS = 0.05
MIN_Z_SCORE = 2.0


@dataclass
class AnomalyResult:
    detected: bool
    detection_status: str
    observed_approval_rate: float
    expected_approval_rate: float
    approval_rate_drop: float
    attempts: int
    approvals: int
    z_score: float
    severity: str | None
    reason: str
    baseline_level: str
    historical_attempts: int


def calculate_z_score(
    observed_rate: float,
    expected_rate: float,
    attempts: int,
) -> float:
    if attempts <= 0:
        return 0.0

    variance = expected_rate * (1 - expected_rate) / attempts

    if variance <= 0:
        return 0.0

    standard_error = sqrt(variance)

    return (expected_rate - observed_rate) / standard_error


def classify_severity(
    rate_drop: float,
    z_score: float,
) -> str:
    if rate_drop >= 0.20 and z_score >= 4:
        return "critical"

    if rate_drop >= 0.10 and z_score >= 3:
        return "high"

    if rate_drop >= 0.05 and z_score >= 2:
        return "medium"

    return "low"


def detect_anomaly(
    segment: dict,
    attempts: int,
    approvals: int,
    baseline: BaselineResult,
) -> AnomalyResult:
    if attempts <= 0:
        raise ValueError("Attempts must be greater than zero.")

    if approvals < 0 or approvals > attempts:
        raise ValueError(
            "Approvals must be between zero and attempts."
        )

    observed_rate = approvals / attempts
    expected_rate = baseline.expected_approval_rate
    rate_drop = expected_rate - observed_rate

    z_score = calculate_z_score(
        observed_rate=observed_rate,
        expected_rate=expected_rate,
        attempts=attempts,
    )

    enough_volume = attempts >= MIN_LIVE_ATTEMPTS
    meaningful_drop = rate_drop >= MIN_DROP_POINTS
    statistically_significant = z_score >= MIN_Z_SCORE

    detected = (
        enough_volume
        and meaningful_drop
        and statistically_significant
    )

    if not enough_volume:
        detection_status = "insufficient_data"
        severity = None
        reason = "Insufficient live transaction volume."

    elif not meaningful_drop:
        detection_status = "normal"
        severity = None
        reason = "Observed drop is within normal variation."

    elif not statistically_significant:
        detection_status = "potential_anomaly"
        severity = None
        reason = (
            "A conversion drop exists, but the statistical "
            "evidence is not yet strong enough."
        )

    else:
        detection_status = "confirmed_anomaly"
        severity = classify_severity(
            rate_drop=rate_drop,
            z_score=z_score,
        )
        reason = (
            "Approval rate is meaningfully below the "
            "historical baseline."
        )

    return AnomalyResult(
        detected=detected,
        detection_status=detection_status,
        observed_approval_rate=observed_rate,
        expected_approval_rate=expected_rate,
        approval_rate_drop=rate_drop,
        attempts=attempts,
        approvals=approvals,
        z_score=z_score,
        severity=severity,
        reason=reason,
        baseline_level=baseline.baseline_level,
        historical_attempts=baseline.historical_attempts,
    )


def print_result(
    name: str,
    result: AnomalyResult,
) -> None:
    print(f"\n=== {name} ===")
    print(f"Detected: {result.detected}")
    print(f"Detection status: {result.detection_status}")
    print(
        f"Observed approval rate: "
        f"{result.observed_approval_rate:.2%}"
    )
    print(
        f"Expected approval rate: "
        f"{result.expected_approval_rate:.2%}"
    )
    print(
        f"Drop: "
        f"{result.approval_rate_drop:.2%}"
    )
    print(f"Attempts: {result.attempts}")
    print(f"Z-score: {result.z_score:.2f}")
    print(
        f"Severity: "
        f"{result.severity or 'Not assigned'}"
    )
    print(f"Reason: {result.reason}")
    print(f"Baseline level: {result.baseline_level}")
    print(
        f"Historical attempts: "
        f"{result.historical_attempts}"
    )


def main() -> None:
    baselines = load_baselines()

    segment = {
        "merchant": "Merchant_A",
        "provider": "Adyen",
        "payment_method": "PIX",
        "country": "BR",
        "weekday": 0,
        "hour": 10,
    }

    baseline = get_expected_baseline(
        baselines=baselines,
        segment=segment,
    )

    normal_case = detect_anomaly(
        segment=segment,
        attempts=100,
        approvals=87,
        baseline=baseline,
    )

    real_drop_case = detect_anomaly(
        segment=segment,
        attempts=100,
        approvals=60,
        baseline=baseline,
    )

    low_volume_case = detect_anomaly(
        segment=segment,
        attempts=10,
        approvals=5,
        baseline=baseline,
    )

    print_result("NORMAL CASE", normal_case)
    print_result("REAL DROP CASE", real_drop_case)
    print_result("LOW VOLUME CASE", low_volume_case)


if __name__ == "__main__":
    main()
