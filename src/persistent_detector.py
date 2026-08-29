from __future__ import annotations

from dataclasses import dataclass, field

from anomaly_detector import AnomalyResult


MIN_CONSECUTIVE_ANOMALIES = 2


@dataclass
class PersistentIncidentState:
    segment_id: str
    consecutive_anomalies: int = 0
    consecutive_normal_windows: int = 0
    incident_status: str = "normal"
    results: list[AnomalyResult] = field(default_factory=list)


def update_incident_state(
    state: PersistentIncidentState,
    result: AnomalyResult,
) -> PersistentIncidentState:
    state.results.append(result)

    if result.detection_status == "confirmed_anomaly":
        state.consecutive_anomalies += 1
        state.consecutive_normal_windows = 0

        if (
            state.consecutive_anomalies
            >= MIN_CONSECUTIVE_ANOMALIES
        ):
            state.incident_status = "confirmed"
        else:
            state.incident_status = "investigating"

    elif result.detection_status == "insufficient_data":
        state.incident_status = "insufficient_data"

    else:
        state.consecutive_normal_windows += 1
        state.consecutive_anomalies = 0

        if (
            state.incident_status == "confirmed"
            and state.consecutive_normal_windows < 2
        ):
            state.incident_status = "recovering"
        else:
            state.incident_status = "normal"

    return state


def print_state(
    window_number: int,
    state: PersistentIncidentState,
    result: AnomalyResult,
) -> None:
    print(f"\n=== WINDOW {window_number} ===")
    print(
        f"Observed conversion: "
        f"{result.observed_approval_rate:.2%}"
    )
    print(
        f"Detection result: "
        f"{result.detection_status}"
    )
    print(
        f"Consecutive anomalies: "
        f"{state.consecutive_anomalies}"
    )
    print(
        f"Incident status: "
        f"{state.incident_status}"
    )


if __name__ == "__main__":
    from anomaly_detector import detect_anomaly
    from baseline_selector import (
        get_expected_baseline,
        load_baselines,
    )

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

    live_windows = [
        {"attempts": 100, "approvals": 88},
        {"attempts": 100, "approvals": 62},
        {"attempts": 100, "approvals": 59},
        {"attempts": 100, "approvals": 61},
        {"attempts": 100, "approvals": 87},
        {"attempts": 100, "approvals": 89},
    ]

    state = PersistentIncidentState(
        segment_id="Merchant_A-Adyen-PIX-BR"
    )

    for index, window in enumerate(
        live_windows,
        start=1,
    ):
        result = detect_anomaly(
            segment=segment,
            attempts=window["attempts"],
            approvals=window["approvals"],
            baseline=baseline,
        )

        state = update_incident_state(
            state=state,
            result=result,
        )

        print_state(
            window_number=index,
            state=state,
            result=result,
        )
