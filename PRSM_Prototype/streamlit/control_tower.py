"""Deterministic payment-incident simulation and evidence calculations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


COUNTRY_NAMES = {"MX": "Mexico", "CO": "Colombia", "BR": "Brazil"}


@dataclass(frozen=True)
class Injection:
    title: str
    subtitle: str
    country: str
    filters: dict[str, str]
    target_rate: float
    decline_code: str
    root_path: str
    recommendation: str
    control_description: str
    seed_offset: int = 0


BRAZIL = Injection(
    title="dLocal degradation in Brazil",
    subtitle="Provider × country · all merchants",
    country="BR",
    filters={"country": "BR", "provider": "dLocal"},
    target_rate=0.34,
    decline_code="DO_NOT_HONOR",
    root_path="Brazil › dLocal",
    recommendation=(
        "Investigate dLocal's Brazil processing and consider temporarily rerouting "
        "affected traffic through a currently healthy provider."
    ),
    control_description="Stripe and Adyen remain within their historical ranges for comparable Brazil traffic.",
    seed_offset=11,
)

MEXICO = Injection(
    title="Banorte issuer failure for Merchant C",
    subtitle="Merchant × country × issuing bank",
    country="MX",
    filters={"country": "MX", "merchant": "Merchant_C", "issuing_bank": "Banorte"},
    target_rate=0.08,
    decline_code="DO_NOT_HONOR",
    root_path="Mexico › Merchant C › Banorte",
    recommendation=(
        "Escalate the Merchant C / Banorte pattern with the acquiring partner and monitor "
        "bank-specific declines before changing routing."
    ),
    control_description="Other Mexican issuing banks remain inside their expected conversion ranges.",
    seed_offset=23,
)

RANDOM_INJECTIONS = [
    Injection(
        title="Adyen wallet failure in Colombia",
        subtitle="Merchant × provider × method × country",
        country="CO",
        filters={"country": "CO", "merchant": "Merchant_B", "provider": "Adyen", "payment_method": "wallet"},
        target_rate=0.23,
        decline_code="SUSPECTED_FRAUD",
        root_path="Colombia › Merchant B › Adyen › Wallet",
        recommendation="Investigate Adyen wallet processing for Merchant B in Colombia and consider shifting only the affected wallet traffic.",
        control_description="dLocal and Stripe wallet traffic in Colombia remain within baseline.",
        seed_offset=37,
    ),
    Injection(
        title="Stripe card degradation in Mexico",
        subtitle="Provider × method × country",
        country="MX",
        filters={"country": "MX", "provider": "Stripe", "payment_method": "card"},
        target_rate=0.18,
        decline_code="INVALID_CARD",
        root_path="Mexico › Stripe › Card",
        recommendation="Investigate Stripe card processing in Mexico and simulate a limited reroute to the strongest healthy provider.",
        control_description="Wallet and cash-in-store traffic in Mexico remain within range.",
        seed_offset=41,
    ),
    Injection(
        title="Merchant A wallet anomaly in Brazil",
        subtitle="Merchant × method × country",
        country="BR",
        filters={"country": "BR", "merchant": "Merchant_A", "payment_method": "wallet"},
        target_rate=0.21,
        decline_code="DO_NOT_HONOR",
        root_path="Brazil › Merchant A › Wallet",
        recommendation="Review recent Merchant A wallet configuration changes in Brazil before changing provider routing.",
        control_description="Other merchants' Brazil wallet traffic remains healthy.",
        seed_offset=53,
    ),
]


def _mask(frame: pd.DataFrame, filters: dict[str, str]) -> pd.Series:
    result = pd.Series(True, index=frame.index)
    for column, value in filters.items():
        result &= frame[column].fillna("").astype(str).eq(value)
    return result


def _inject_declines(
    frame: pd.DataFrame,
    injection: Injection,
    incident_start: pd.Timestamp,
    seed: int,
) -> int:
    mask = _mask(frame, injection.filters) & frame["timestamp"].ge(incident_start)
    segment = frame.loc[mask]
    if segment.empty:
        return 0
    approved_idx = segment.index[segment["status"].eq("approved")].to_numpy()
    desired_approvals = int(round(len(segment) * injection.target_rate))
    flip_count = max(0, len(approved_idx) - desired_approvals)
    if not flip_count:
        return 0
    rng = np.random.default_rng(seed + injection.seed_offset)
    selected = rng.choice(approved_idx, size=min(flip_count, len(approved_idx)), replace=False)
    frame.loc[selected, "status"] = "declined"
    frame.loc[selected, "decline_code"] = injection.decline_code
    frame.loc[selected, "recovered_after_retry"] = False
    return len(selected)


def _rate(frame: pd.DataFrame) -> float:
    return float(frame["status"].eq("approved").mean()) if len(frame) else 0.0


def _expected_rate(history: pd.DataFrame, filters: dict[str, str]) -> float:
    segment = history.loc[_mask(history, filters)]
    global_rate = _rate(history)
    if segment.empty:
        return global_rate
    # Small Bayesian shrinkage makes low-volume baselines stable for the demo.
    approvals = int(segment["status"].eq("approved").sum())
    return float((approvals + global_rate * 40) / (len(segment) + 40))


def _merchant_weight(config: pd.DataFrame, filters: dict[str, str]) -> float:
    merchant = filters.get("merchant")
    if not merchant or merchant not in set(config["merchant"]):
        return 1.0
    row = config.loc[config["merchant"].eq(merchant)].iloc[0]
    priority = {"high": 1.08, "medium": 1.0, "low": 0.94}.get(str(row["merchant_priority"]).lower(), 1.0)
    return float(priority)


def _build_incident(
    history: pd.DataFrame,
    live: pd.DataFrame,
    injection: Injection,
    incident_start: pd.Timestamp,
    config: pd.DataFrame,
    ordinal: int,
) -> dict[str, Any]:
    current = live.loc[live["timestamp"].ge(incident_start) & _mask(live, injection.filters)].copy()
    baseline = history.loc[_mask(history, injection.filters)].copy()
    expected = _expected_rate(history, injection.filters)
    actual = _rate(current)
    attempts = len(current)
    approvals = int(current["status"].eq("approved").sum())
    expected_approvals = expected * attempts
    excess = max(0.0, expected_approvals - approvals)
    drop = max(0.0, expected - actual)
    hours = max((live["timestamp"].max() - incident_start).total_seconds() / 3600, 0.15)
    avg_ticket = float(current["amount_usd"].mean()) if attempts else 0.0
    gmv_risk = excess * avg_ticket / hours * _merchant_weight(config, injection.filters)

    se = np.sqrt(max(expected * (1 - expected) / max(attempts, 1), 0.00001))
    z_score = drop / se if se else 0.0
    confidence = min(0.99, 0.58 + 0.30 * (1 - np.exp(-z_score / 2.4)) + 0.10 * min(attempts / 250, 1))

    country_live = live.loc[live["timestamp"].ge(incident_start) & live["country"].eq(injection.country)]
    country_expected = _expected_rate(history, {"country": injection.country})
    country_excess = max(
        1.0,
        country_expected * len(country_live) - int(country_live["status"].eq("approved").sum()),
    )
    attribution = min(0.98, excess / country_excess)

    base_code_share = float(baseline["decline_code"].fillna("").eq(injection.decline_code).mean()) if len(baseline) else 0
    live_code_share = float(current["decline_code"].fillna("").eq(injection.decline_code).mean()) if len(current) else 0
    code_multiple = min(9.9, live_code_share / max(base_code_share, 0.005))

    dimension_label = " × ".join(
        f"{column.replace('_', ' ').title()} {value}" for column, value in injection.filters.items()
    )
    merchant_name = injection.filters.get("merchant", "all merchants").replace("_", " ")
    severity = "CRITICAL" if gmv_risk >= 18000 or drop >= 0.34 else "HIGH"

    return {
        "id": f"INC-{2050 + ordinal}",
        "priority": "P1",
        "severity": severity,
        "title": injection.title,
        "subtitle": injection.subtitle,
        "country": injection.country,
        "country_name": COUNTRY_NAMES[injection.country],
        "started": incident_start.strftime("%H:%M"),
        "expected": expected,
        "actual": actual,
        "drop": drop,
        "confidence": confidence,
        "gmv_risk": gmv_risk,
        "adjusted_risk": gmv_risk * confidence,
        "attempts": attempts,
        "excess_declines": int(round(excess)),
        "attribution": attribution,
        "avg_ticket": avg_ticket,
        "root_path": injection.root_path,
        "affected": dimension_label,
        "executive": (
            f"{injection.title} is putting approximately ${gmv_risk:,.0f} of GMV per hour at risk."
        ),
        "evidence": [
            f"Observed conversion is {drop * 100:.1f} percentage points below the {expected * 100:.1f}% expected baseline.",
            f"This slice explains {attribution * 100:.0f}% of excess declines in {COUNTRY_NAMES[injection.country]}.",
            injection.control_description,
            f"{injection.decline_code.replace('_', ' ')} is {code_multiple:.1f}× its normal share in the affected flow.",
            f"The affected sample contains {attempts:,} attempts across {merchant_name}.",
        ],
        "recommendation": injection.recommendation,
        "recovery": gmv_risk * min(0.92, attribution),
        "ground_truth": injection.root_path,
    }


def _ambiguous_observation(
    history: pd.DataFrame,
    live: pd.DataFrame,
    incident_start: pd.Timestamp,
    config: pd.DataFrame,
) -> dict[str, Any]:
    filters = {"country": "CO"}
    current = live.loc[live["timestamp"].ge(incident_start) & _mask(live, filters)]
    expected = _expected_rate(history, filters)
    actual = _rate(current)
    excess = max(0.0, expected * len(current) - int(current["status"].eq("approved").sum()))
    hours = max((live["timestamp"].max() - incident_start).total_seconds() / 3600, 0.15)
    gmv_risk = excess * float(current["amount_usd"].mean()) / hours if len(current) else 0.0
    return {
        "id": "OBS-731",
        "priority": "OBS",
        "severity": "INSUFFICIENT EVIDENCE",
        "title": "Conversion anomaly in Colombia",
        "subtitle": "Two plausible hypotheses remain",
        "country": "CO",
        "country_name": "Colombia",
        "started": incident_start.strftime("%H:%M"),
        "expected": expected,
        "actual": actual,
        "drop": max(0.0, expected - actual),
        "confidence": 0.44,
        "gmv_risk": gmv_risk,
        "adjusted_risk": gmv_risk * 0.44,
        "attempts": len(current),
        "excess_declines": int(round(excess)),
        "attribution": 0.51,
        "avg_ticket": float(current["amount_usd"].mean()) if len(current) else 0.0,
        "root_path": "Colombia › unresolved",
        "affected": "Country Colombia × mixed card traffic",
        "executive": "Colombia conversion is below baseline, but there is not enough evidence to name a root cause reliably.",
        "evidence": [
            f"Colombia conversion is {(expected - actual) * 100:.1f} percentage points below expected behavior.",
            "The signal is split across provider and issuer dimensions; neither explains a decisive share.",
            "Traffic volume is not yet sufficient to distinguish the two leading hypotheses.",
            "No isolated remediation is justified at the current confidence level.",
        ],
        "recommendation": "Continue monitoring and collect approximately 312 additional transactions before deciding between the provider and issuer hypotheses.",
        "recovery": 0.0,
        "hypotheses": [("dLocal × Colombia", 0.51), ("Bancolombia issuing cards", 0.43), ("Other", 0.06)],
        "ground_truth": "Intentionally ambiguous mixed signal",
    }


def _conversion_chart(history: pd.DataFrame, live: pd.DataFrame) -> pd.DataFrame:
    end = live["timestamp"].max()
    start = end - pd.Timedelta(minutes=60)
    window = live.loc[live["timestamp"].ge(start)].copy()
    window["approved"] = window["status"].eq("approved").astype(float)
    actual = (
        window.set_index("timestamp")["approved"]
        .resample("5min")
        .mean()
        .rename("Actual")
    )
    expected_value = _rate(history)
    result = actual.to_frame().reset_index()
    result["Expected"] = expected_value
    return result


def run_scenario(
    transactions: pd.DataFrame,
    config: pd.DataFrame,
    scenario: str,
    random_seed: int = 1,
) -> dict[str, Any]:
    frame = transactions.sort_values("timestamp").copy()
    split_at = frame["timestamp"].quantile(0.80)
    history = frame.loc[frame["timestamp"].lt(split_at)].copy()
    live = frame.loc[frame["timestamp"].ge(split_at)].copy()
    incident_start = live["timestamp"].max() - pd.Timedelta(minutes=22)

    injections: list[Injection] = []
    ground_truth: list[str] = []
    if scenario == "brazil":
        injections = [BRAZIL]
    elif scenario == "mexico":
        injections = [MEXICO]
    elif scenario == "both":
        injections = [BRAZIL, MEXICO]
    elif scenario == "random":
        chosen = RANDOM_INJECTIONS[(random_seed - 1) % len(RANDOM_INJECTIONS)]
        injections = [chosen]
    elif scenario == "ambiguous":
        weak_provider = Injection(
            title="Weak provider signal", subtitle="", country="CO",
            filters={"country": "CO", "provider": "dLocal"}, target_rate=0.76,
            decline_code="DO_NOT_HONOR", root_path="Colombia › dLocal",
            recommendation="Continue monitoring.", control_description="Competing issuer signal remains plausible.", seed_offset=61,
        )
        weak_bank = Injection(
            title="Weak issuer signal", subtitle="", country="CO",
            filters={"country": "CO", "issuing_bank": "Bancolombia"}, target_rate=0.64,
            decline_code="DO_NOT_HONOR", root_path="Colombia › Bancolombia",
            recommendation="Continue monitoring.", control_description="Competing provider signal remains plausible.", seed_offset=67,
        )
        for injection in (weak_provider, weak_bank):
            _inject_declines(live, injection, incident_start, random_seed)
        ground_truth = ["Intentionally ambiguous mixed signal"]

    for injection in injections:
        _inject_declines(live, injection, incident_start, random_seed)
        ground_truth.append(injection.root_path)

    incidents = [
        _build_incident(history, live, injection, incident_start, config, i)
        for i, injection in enumerate(injections, start=1)
    ]
    if scenario == "ambiguous":
        incidents = [_ambiguous_observation(history, live, incident_start, config)]

    incidents.sort(key=lambda item: item["adjusted_risk"], reverse=True)
    for index, incident in enumerate(incidents, start=1):
        if incident["priority"] != "OBS":
            incident["priority"] = f"P{index}"

    current_start = live["timestamp"].max() - pd.Timedelta(minutes=30)
    current = live.loc[live["timestamp"].ge(current_start)]
    actual_conversion = _rate(current)
    expected_conversion = _rate(history)
    country_rows: dict[str, dict[str, Any]] = {}
    for country in ("MX", "CO", "BR"):
        current_country = current.loc[current["country"].eq(country)]
        actual = _rate(current_country)
        expected = _expected_rate(history, {"country": country})
        related = [item for item in incidents if item["country"] == country]
        status = "healthy"
        if related:
            status = "investigating" if related[0]["priority"] == "OBS" else ("critical" if related[0]["priority"] == "P1" else "warning")
        country_rows[country] = {
            "name": COUNTRY_NAMES[country], "actual": actual, "expected": expected,
            "status": status, "incident_count": len(related),
            "risk": sum(item["gmv_risk"] for item in related),
        }

    risk = sum(item["gmv_risk"] for item in incidents)
    adjusted_risk = sum(item["adjusted_risk"] for item in incidents)
    if scenario == "normal":
        tone, pill = "healthy", "SYSTEM HEALTHY"
        title = "Payment network operating within expected range"
        description = "No meaningful deterioration detected across monitored payment flows."
    elif scenario == "both":
        tone, pill = "critical", "2 ACTIVE INCIDENTS"
        title = "Two independent incidents separated and prioritized"
        description = "The system treats Brazil provider degradation and Mexico issuer failure as separate stories."
    elif scenario == "ambiguous":
        tone, pill = "warning", "INSUFFICIENT EVIDENCE"
        title = "Anomaly detected; root cause intentionally unresolved"
        description = "Two hypotheses remain plausible. PagoTotal will not invent a diagnosis."
    elif scenario == "random":
        tone, pill = "critical" if incidents[0]["severity"] == "CRITICAL" else "warning", "BLIND TEST · INCIDENT FOUND"
        title = "A previously unrehearsed failure was diagnosed"
        description = "The injected dimensions stay hidden until the presenter reveals the ground truth."
    else:
        tone = "critical" if incidents and incidents[0]["severity"] == "CRITICAL" else "warning"
        pill = "1 ACTIVE INCIDENT"
        title = incidents[0]["title"] if incidents else "Incident detected"
        description = incidents[0]["subtitle"] if incidents else ""

    return {
        "scenario": scenario,
        "tone": tone,
        "pill": pill,
        "title": title,
        "description": description,
        "actual_conversion": actual_conversion,
        "expected_conversion": expected_conversion,
        "incidents": incidents,
        "active_incidents": len(incidents),
        "gmv_risk": risk,
        "adjusted_risk": adjusted_risk,
        "countries": country_rows,
        "chart": _conversion_chart(history, live),
        "ground_truth": ground_truth,
        "incident_start": incident_start,
        "transactions_monitored": len(frame),
        "window_attempts": len(current),
    }
