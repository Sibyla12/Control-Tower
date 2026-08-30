from __future__ import annotations

import asyncio
import json
import os
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import openai
import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from scipy.stats import norm


REVIEWED_INCIDENTS_PATH = Path("data/reviewed_incidents.csv")
RECOMMENDED_INCIDENTS_PATH = Path(
    "data/incidents_with_recommendations.csv"
)
AUDIT_LOG_PATH = Path("data/recommendation_audit_log.csv")
UNRESOLVED_CANDIDATES_PATH = Path(
    "data/unresolved_incident_candidates.csv"
)
ROOT_CAUSE_INCIDENTS_PATH = Path("data/root_cause_incidents.csv")
CLUSTERED_INCIDENTS_PATH = Path("data/clustered_incidents.csv")
INCIDENT_MEMORY_PATH = Path("data/incident_memory.csv")
INCIDENT_MEMORY_COLUMNS = [
    "fingerprint",
    "consolidated_incident_id",
    "incident_title",
    "priority",
    "recorded_at",
]
LIVE_SEGMENT_WINDOWS_PATH = Path("data/live_segment_windows.csv")
BASELINE_BY_SEGMENT_PATH = Path("data/baseline_by_segment.csv")
NOTIFIED_INCIDENTS_PATH = Path("data/notified_incidents.json")
INCIDENT_TAXONOMY_PATH = Path("data/incident_taxonomy.csv")
OPERATIONAL_PLAYBOOK_PATH = Path("data/operational_playbook.csv")
PRIORITY_MATRIX_PATH = Path("data/priority_matrix.csv")
MERCHANT_FINANCIAL_CONFIG_PATH = Path(
    "data/merchant_financial_config.csv"
)
DETECTION_LEVEL_BASELINES_PATH = Path(
    "data/detection_level_baselines.csv"
)

# Which detection level (and matching incident field) backs each root
# cause type's historical comparison. decline_code has no dedicated
# level - it falls back to a live-evidence-volume heuristic instead.
ROOT_CAUSE_TO_DETECTION_LEVEL = {
    "provider": ("L1_PROVIDER_COUNTRY", "provider"),
    "issuing_bank": ("L4_BANK_COUNTRY", "issuing_bank"),
    "merchant": ("L3_MERCHANT_COUNTRY", "merchant"),
    "payment_method": ("L2_METHOD_COUNTRY", "payment_method"),
}
MIN_RELIABLE_ATTEMPTS = 30

NTFY_TOPIC = os.environ.get("NTFY_TOPIC", "")
NOTIFY_POLL_SECONDS = 30

ROOT_CAUSE_TO_INCIDENT_TYPE = {
    "provider": "Provider Degradation",
    "issuing_bank": "Issuing Bank Degradation",
    "payment_method": "Payment Method Degradation",
    "merchant": "Merchant-Specific Issue",
    "decline_code": "Decline Code Spike",
    "unknown": "Unknown Root Cause",
}

# The taxonomy and playbook sheets name the no-root-cause case differently.
PLAYBOOK_INCIDENT_TYPE_ALIASES = {
    "Unknown Root Cause": "Unknown / Insufficient Evidence",
}

# Forward-looking cost projection, methodology from the finance workbook:
# exposure keeps accruing linearly at the current rate, then gets a
# mean-time-to-resolve haircut once the horizon passes the MTTR assumption.
PROJECTION_HORIZONS_HOURS = [4, 24, 168]
MTTR_ASSUMPTION_HOURS = 6

MONITORED_COUNTRIES = ["MX", "CO", "BR"]
CONVERSION_HISTORY_MINUTES = 30

app = FastAPI(
    title="Control Tower API",
    version="1.0.0",
    description=(
        "Payment incident detection, diagnosis and "
        "human-review API."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ReviewRequest(BaseModel):
    action: Literal["approve", "reject", "modify", "execute"]
    reviewer: str = Field(min_length=2, max_length=100)
    comment: str | None = Field(default=None, max_length=1000)
    modified_primary_action: str | None = Field(
        default=None,
        max_length=2000,
    )


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
    return datetime.now(timezone.utc).isoformat()


def clean_record(record: dict) -> dict:
    cleaned = {}

    for key, value in record.items():
        if pd.isna(value):
            cleaned[key] = None
        elif isinstance(value, pd.Timestamp):
            cleaned[key] = value.isoformat()
        else:
            cleaned[key] = value

    return cleaned


def load_lookup_table(path: Path, key_column: str) -> dict[str, dict]:
    if not path.exists():
        return {}

    dataframe = pd.read_csv(path)
    return {
        str(row[key_column]): clean_record(row.to_dict())
        for _, row in dataframe.iterrows()
    }


def load_merchant_margin_rates() -> dict[str, float]:
    if not MERCHANT_FINANCIAL_CONFIG_PATH.exists():
        return {}

    dataframe = pd.read_csv(MERCHANT_FINANCIAL_CONFIG_PATH)
    return dict(
        zip(dataframe["merchant"], dataframe["merchant_margin_rate"])
    )


def resolve_merchant_margin_rate(
    record: dict,
    margin_rates: dict[str, float],
) -> float | None:
    if not margin_rates:
        return None

    merchant = record.get("merchant")
    if merchant and merchant in margin_rates:
        return margin_rates[merchant]

    affected = record.get("affected_merchants")
    matched = [
        margin_rates[name]
        for name in str(affected or "").split("|")
        if name in margin_rates
    ]
    if matched:
        return sum(matched) / len(matched)

    # No merchant identified at all - fall back to the network average
    # so the network-wide rollup still has a number to sum.
    return sum(margin_rates.values()) / len(margin_rates)


def build_data_quality(record: dict) -> dict:
    """How much to trust the baseline this diagnosis was compared
    against - not the diagnosis's own confidence_score. Mirrors the
    finance workbook's Confidence sheet, but sourced from the real
    baseline_reliable flags in detection_level_baselines.csv rather
    than re-derived.
    """
    root_cause_type = str(record.get("root_cause_type"))
    mapping = ROOT_CAUSE_TO_DETECTION_LEVEL.get(root_cause_type)

    if mapping and DETECTION_LEVEL_BASELINES_PATH.exists():
        detection_level, dimension_column = mapping
        dimension_value = record.get(dimension_column)
        country = record.get("country")

        if dimension_value and country:
            baselines = pd.read_csv(DETECTION_LEVEL_BASELINES_PATH)
            matches = baselines[
                baselines["detection_level"].eq(detection_level)
                & baselines[dimension_column].eq(dimension_value)
                & baselines["country"].eq(country)
            ]
            if not matches.empty:
                reliable_share = float(matches["baseline_reliable"].mean())
                if reliable_share >= 0.8:
                    level = "high"
                elif reliable_share >= 0.5:
                    level = "medium"
                else:
                    level = "low"
                return {
                    "data_quality": level,
                    "baseline_source": f"{detection_level} historical baseline",
                    "baseline_reliable_share": round(reliable_share, 2),
                    "baseline_historical_attempts": int(
                        matches["historical_attempts"].sum()
                    ),
                }

    # No dedicated baseline level for this root cause type (decline_code)
    # or no matching historical rows - fall back to how much live evidence
    # backs the diagnosis itself.
    attempts = record.get("attempts_in_scope") or record.get("attempts") or 0
    validated_windows = record.get("validated_windows") or 0
    if attempts >= 500 and validated_windows >= 10:
        level = "high"
    elif attempts >= MIN_RELIABLE_ATTEMPTS and validated_windows >= 3:
        level = "medium"
    else:
        level = "low"

    return {
        "data_quality": level,
        "baseline_source": (
            "live validated-window volume "
            "(no per-segment historical baseline for this dimension)"
        ),
        "baseline_reliable_share": None,
        "baseline_historical_attempts": None,
    }


def build_risk_ranking(incident_records: list[dict]) -> list[dict]:
    """Pareto-style ranking: which incidents explain what share of the
    total adjusted GMV at risk, from the finance workbook's Ranking
    sheet, applied to the live active incidents.
    """
    ranked = sorted(
        incident_records,
        key=lambda record: record.get("net_unrecovered_value_usd") or 0,
        reverse=True,
    )
    total_risk = sum(
        record.get("net_unrecovered_value_usd") or 0 for record in ranked
    )

    rows = []
    cumulative = 0.0
    for index, record in enumerate(ranked, start=1):
        risk = record.get("net_unrecovered_value_usd") or 0
        cumulative += risk
        rows.append({
            "rank": index,
            "consolidated_incident_id": record.get(
                "consolidated_incident_id"
            ),
            "incident_title": record.get("incident_title"),
            "gmv_at_risk_adjusted_usd": round(risk, 2),
            "cumulative_gmv_at_risk_adjusted_usd": round(cumulative, 2),
            "cumulative_pct": (
                round(cumulative / total_risk, 4) if total_risk else 0.0
            ),
        })

    return rows


RISK_CONCENTRATION_DIMENSIONS = {
    "root_cause_type": "root_cause_type",
    "country": "country",
    "provider": "provider",
    "issuing_bank": "issuing_bank",
    "payment_method": "payment_method",
    "decline_code": "dominant_decline_code",
}


def build_risk_concentration(incident_records: list[dict]) -> list[dict]:
    """Diagnostic signal, not a confirmed root cause: how the current
    active incidents' adjusted GMV at risk concentrates by dimension.
    Methodology from the finance workbook's Root_Cause_Analysis sheet,
    applied to the live incident set instead of a static historical one.
    """
    total_risk = sum(
        record.get("net_unrecovered_value_usd") or 0
        for record in incident_records
    )
    if total_risk <= 0:
        return []

    signals = []
    for dimension, field in RISK_CONCENTRATION_DIMENSIONS.items():
        totals: dict[str, float] = {}
        incident_counts: dict[str, int] = {}

        for record in incident_records:
            value = record.get(field)
            if not value or pd.isna(value) or "|" in str(value):
                # A pipe-joined value means this dimension wasn't the
                # isolated root cause for this incident (it lists every
                # affected value, e.g. "Bradesco|Nubank") - crediting it
                # as one opaque bucket would misrepresent it.
                continue
            risk = record.get("net_unrecovered_value_usd") or 0
            totals[value] = totals.get(value, 0) + risk
            incident_counts[value] = incident_counts.get(value, 0) + 1

        for value, risk in totals.items():
            signals.append({
                "dimension": dimension,
                "value": value,
                "gmv_at_risk_adjusted_usd": round(risk, 2),
                "concentration_pct": round(risk / total_risk, 4),
                "incident_count": incident_counts[value],
            })

    signals.sort(key=lambda signal: signal["concentration_pct"], reverse=True)
    return signals


def build_economic_impact(
    record: dict,
    margin_rates: dict[str, float],
) -> dict:
    gmv_at_risk_adjusted = record.get("net_unrecovered_value_usd")
    platform_revenue_at_risk = record.get("platform_revenue_at_risk_usd")
    margin_rate = resolve_merchant_margin_rate(record, margin_rates)

    if gmv_at_risk_adjusted is None or margin_rate is None:
        return {
            "merchant_margin_rate": margin_rate,
            "merchant_economic_impact_usd": None,
            "total_economic_impact_usd": None,
        }

    merchant_economic_impact = gmv_at_risk_adjusted * margin_rate
    total_economic_impact = merchant_economic_impact + (
        platform_revenue_at_risk or 0
    )

    return {
        "merchant_margin_rate": round(margin_rate, 4),
        "merchant_economic_impact_usd": round(
            merchant_economic_impact, 2
        ),
        "total_economic_impact_usd": round(total_economic_impact, 2),
    }


def build_projections(record: dict) -> list[dict]:
    value_per_minute = record.get("value_at_risk_per_minute_usd")
    retry_recovery_rate = record.get("retry_recovery_rate")

    if value_per_minute is None or retry_recovery_rate is None:
        return []

    projections = []

    for horizon_hours in PROJECTION_HORIZONS_HOURS:
        gross_at_risk = value_per_minute * 60 * horizon_hours
        adjusted_at_risk = gross_at_risk * (1 - retry_recovery_rate)
        # Fraction of the horizon assumed to fall after the incident is
        # fixed (per the MTTR assumption); clamped at 0 for horizons
        # shorter than the MTTR, since it wouldn't be fixed within them yet.
        recovery_factor = max(
            0.0,
            (horizon_hours - MTTR_ASSUMPTION_HOURS) / horizon_hours,
        )
        net_impact = adjusted_at_risk * (1 - recovery_factor)

        projections.append({
            "horizon_hours": horizon_hours,
            "projected_gmv_at_risk_usd": round(gross_at_risk, 2),
            "projected_gmv_at_risk_adjusted_usd": round(adjusted_at_risk, 2),
            "recovery_factor": round(recovery_factor, 4),
            "projected_net_impact_usd": round(net_impact, 2),
        })

    return projections


def incident_fingerprint(record: dict) -> str:
    """A stable identity for 'the same failure pattern', independent of
    the random consolidated_incident_id a fresh pipeline run assigns.
    """
    parts = [
        str(record.get("root_cause_type") or ""),
        str(record.get("provider") or ""),
        str(record.get("issuing_bank") or ""),
        str(record.get("country") or ""),
        str(record.get("dominant_decline_code") or ""),
    ]
    return "|".join(parts)


def load_incident_memory() -> pd.DataFrame:
    if not INCIDENT_MEMORY_PATH.exists():
        return pd.DataFrame(columns=INCIDENT_MEMORY_COLUMNS)

    return pd.read_csv(INCIDENT_MEMORY_PATH)


def build_incident_memory(record: dict) -> dict:
    """Recognizes when the current incident matches a pattern already
    seen in an earlier pipeline run (real wall-clock time, not the
    simulated demo clock), and records this occurrence for future
    lookups. Idempotent per consolidated_incident_id, so repeated API
    polls of the same incident don't inflate the count.
    """
    fingerprint = incident_fingerprint(record)
    incident_id = record.get("consolidated_incident_id")
    memory = load_incident_memory()

    prior = memory[
        memory["fingerprint"].eq(fingerprint)
        & memory["consolidated_incident_id"].ne(incident_id)
    ]
    is_repeat = not prior.empty

    already_recorded = bool((
        memory["fingerprint"].eq(fingerprint)
        & memory["consolidated_incident_id"].eq(incident_id)
    ).any())

    if incident_id and not already_recorded:
        new_row = pd.DataFrame([{
            "fingerprint": fingerprint,
            "consolidated_incident_id": incident_id,
            "incident_title": record.get("incident_title"),
            "priority": record.get("priority"),
            "recorded_at": utc_now(),
        }])
        updated = pd.concat([memory, new_row], ignore_index=True)
        INCIDENT_MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        updated.to_csv(INCIDENT_MEMORY_PATH, index=False)

    return {
        "is_repeat_incident": is_repeat,
        "repeat_occurrence_count": int(prior["consolidated_incident_id"].nunique()),
        "repeat_first_seen_at": (
            prior["recorded_at"].min() if is_repeat else None
        ),
        "repeat_last_seen_at": (
            prior["recorded_at"].max() if is_repeat else None
        ),
    }


def build_segment_breakdown(source_incident_ids: str | None) -> list[dict]:
    """Per-incident Pareto breakdown of which underlying segment (provider,
    bank, merchant, method - whichever the cluster actually isolated)
    contributed how much of the excess declines. Traces
    consolidated_incidents -> source_incident_ids -> root_cause_incidents
    -> source_candidates -> clustered_incidents, the same lineage the
    pipeline itself used to build the incident.
    """
    if (
        not source_incident_ids
        or not ROOT_CAUSE_INCIDENTS_PATH.exists()
        or not CLUSTERED_INCIDENTS_PATH.exists()
    ):
        return []

    root_cause = pd.read_csv(ROOT_CAUSE_INCIDENTS_PATH)
    clustered = pd.read_csv(CLUSTERED_INCIDENTS_PATH)

    incident_ids = [
        value for value in str(source_incident_ids).split("|") if value
    ]
    matching_root_causes = root_cause[
        root_cause["incident_id"].isin(incident_ids)
    ]

    candidate_ids: list[str] = []
    for candidates in matching_root_causes["source_candidates"].dropna():
        candidate_ids.extend(str(candidates).split("|"))

    segments = clustered[
        clustered["incident_candidate_id"].isin(candidate_ids)
    ].copy()
    if segments.empty:
        return []

    def label_segment(row: pd.Series) -> str:
        parts = [
            row.get("provider"),
            row.get("issuing_bank"),
            row.get("merchant"),
            row.get("payment_method"),
        ]
        labeled = [str(part) for part in parts if pd.notna(part) and str(part)]
        if labeled:
            return " · ".join(labeled)

        # Every specific dimension was null (a coarse detection level) -
        # fall back to something identifying rather than a blank row.
        fallback = [row.get("detection_level"), row.get("country")]
        labeled_fallback = [
            str(part) for part in fallback if pd.notna(part) and str(part)
        ]
        return " · ".join(labeled_fallback) or "Unlabeled segment"

    segments["segment"] = segments.apply(label_segment, axis=1)
    segments["expected_declines"] = segments["attempts"] * (
        1 - segments["expected_approval_rate"]
    )
    segments["actual_declines"] = segments["attempts"] - segments["approvals"]
    segments["excess_declines"] = (
        segments["actual_declines"] - segments["expected_declines"]
    ).clip(lower=0)
    segments["confidence"] = segments["maximum_z_score"].apply(
        lambda z: float(1 - norm.sf(z)) if pd.notna(z) else None
    )

    total_excess = segments["excess_declines"].sum()
    segments["contribution_pct"] = (
        segments["excess_declines"] / total_excess if total_excess else 0.0
    )
    segments = segments.sort_values("excess_declines", ascending=False)
    segments["cumulative_pct"] = segments["contribution_pct"].cumsum()

    rows = []
    for _, row in segments.iterrows():
        confidence = row["confidence"]
        rows.append({
            "segment": row["segment"],
            "expected_declines": round(float(row["expected_declines"]), 2),
            "actual_declines": int(row["actual_declines"]),
            "excess_declines": round(float(row["excess_declines"]), 2),
            "contribution_pct": round(float(row["contribution_pct"]), 4),
            "cumulative_pct": round(float(row["cumulative_pct"]), 4),
            "attempts_in_scope": int(row["attempts"]),
            "confidence": round(confidence, 4) if confidence is not None else None,
        })

    return rows


def enrich_with_playbook(record: dict) -> dict:
    taxonomy = load_lookup_table(INCIDENT_TAXONOMY_PATH, "incident_type")
    playbook = load_lookup_table(OPERATIONAL_PLAYBOOK_PATH, "incident_type")
    priority_matrix = load_lookup_table(PRIORITY_MATRIX_PATH, "priority_code")
    margin_rates = load_merchant_margin_rates()

    incident_type = ROOT_CAUSE_TO_INCIDENT_TYPE.get(
        str(record.get("root_cause_type")), "Unknown Root Cause"
    )
    taxonomy_row = taxonomy.get(incident_type, {})
    playbook_row = playbook.get(
        PLAYBOOK_INCIDENT_TYPE_ALIASES.get(incident_type, incident_type), {}
    )
    matrix_row = priority_matrix.get(str(record.get("priority")), {})

    return {
        **record,
        **build_economic_impact(record, margin_rates),
        "incident_type": incident_type,
        "root_cause_dimensions": taxonomy_row.get("main_dimensions"),
        "taxonomy_evidence": taxonomy_row.get("evidence"),
        "operational_owner": playbook_row.get("owner"),
        "playbook_action": playbook_row.get("recommended_action"),
        "priority_label": matrix_row.get("priority"),
        "priority_criteria": matrix_row.get("criteria"),
        "system_response": matrix_row.get("system_response"),
        "escalation_level": matrix_row.get("escalation"),
        "expected_attention": matrix_row.get("expected_attention"),
        "mttr_assumption_hours": MTTR_ASSUMPTION_HOURS,
        "projections": build_projections(record),
        **build_data_quality(record),
        **build_incident_memory(record),
    }


ANALYSIS_MODEL = "gpt-4o"
ANALYSIS_FIELDS = [
    "consolidated_incident_id",
    "incident_title",
    "incident_type",
    "root_cause_type",
    "provider",
    "issuing_bank",
    "merchant",
    "payment_method",
    "country",
    "dominant_decline_code",
    "start_time",
    "end_time",
    "confidence_score",
    "observed_approval_rate",
    "expected_approval_rate",
    "validated_windows",
    "attempts_in_scope",
    "estimated_lost_approvals",
    "value_at_risk_per_minute_usd",
    "net_unrecovered_value_usd",
    "priority",
    "priority_label",
    "priority_criteria",
    "root_cause_dimensions",
    "taxonomy_evidence",
    "operational_owner",
    "playbook_action",
    "escalation_level",
    "expected_attention",
    "recommendation_status",
]
ANALYSIS_SYSTEM_PROMPT = """You are a payments operations analyst embedded in a \
real-time incident dashboard. You will receive one incident's structured data \
(JSON) from an automated anomaly-detection and root-cause pipeline.

Write a short, plain-language analysis (3-5 sentences) for a human operator who \
is about to approve, modify, or reject the recommended action.

Rules:
- Use only the facts present in the JSON. Never invent numbers, causes, \
providers, banks, or outcomes that are not stated in the data.
- If a field is null or missing, do not guess a value for it or dwell on its \
absence unless directly relevant.
- Do not just restate the JSON field by field; synthesize it into a natural \
narrative a busy operator can read in ten seconds.
- End with one sentence naming the recommended action and who owns it.
- You are explaining the situation, not deciding it. Never tell the operator to \
approve or reject."""

_openai_client: openai.OpenAI | None = None


def get_openai_client() -> openai.OpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = openai.OpenAI()
    return _openai_client


def load_incidents() -> pd.DataFrame:
    path = (
        REVIEWED_INCIDENTS_PATH
        if REVIEWED_INCIDENTS_PATH.exists()
        else RECOMMENDED_INCIDENTS_PATH
    )

    if not path.exists():
        raise HTTPException(
            status_code=503,
            detail="Incident data is not available.",
        )

    dataframe = pd.read_csv(
        path,
        parse_dates=["start_time", "end_time"],
        date_format="mixed",
    )

    optional_columns = {
        "reviewed_by": None,
        "reviewed_at": None,
        "review_comment": None,
        "executed_at": None,
    }
    for column, default in optional_columns.items():
        if column not in dataframe.columns:
            dataframe[column] = default
        # An all-empty column is read back as float64 NaN, which then
        # rejects string assignment later (e.g. setting executed_at).
        dataframe[column] = dataframe[column].astype(object)

    return dataframe


def save_incidents(dataframe: pd.DataFrame) -> None:
    REVIEWED_INCIDENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    dataframe.to_csv(REVIEWED_INCIDENTS_PATH, index=False)


def load_live_windows() -> pd.DataFrame:
    if not LIVE_SEGMENT_WINDOWS_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Live traffic data is not available.",
        )

    return pd.read_csv(LIVE_SEGMENT_WINDOWS_PATH, parse_dates=["minute"])


def load_segment_baseline() -> pd.DataFrame:
    if not BASELINE_BY_SEGMENT_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail="Baseline data is not available.",
        )

    return pd.read_csv(BASELINE_BY_SEGMENT_PATH)


def expected_rate_for(
    baseline: pd.DataFrame,
    weekday: int,
    hour: int,
    country: str | None = None,
) -> float | None:
    subset = baseline[
        (baseline["weekday"] == weekday) & (baseline["hour"] == hour)
    ]

    if country:
        subset = subset[subset["country"].eq(country)]

    total_attempts = subset["attempts"].sum()

    if total_attempts == 0:
        return None

    return float(subset["approvals"].sum() / total_attempts)


def country_status(
    country: str,
    incidents: pd.DataFrame,
) -> str:
    country_incidents = incidents[incidents["country"].eq(country)]

    if country_incidents.empty:
        return "healthy"

    if country_incidents["priority"].eq("P1").any():
        return "critical"

    return "warning"


def parse_as_of(as_of: str | None) -> pd.Timestamp | None:
    """Parses the ?as_of= query param used to replay the dashboard/incidents
    view from an earlier point in the live window, e.g. to demo the system
    watching quietly before any incident started.
    """
    if not as_of:
        return None

    try:
        return pd.Timestamp(as_of)
    except (ValueError, TypeError) as error:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid as_of timestamp: {as_of!r}",
        ) from error


def build_dashboard_payload(as_of: pd.Timestamp | None = None) -> dict:
    live = load_live_windows()
    baseline = load_segment_baseline()

    if as_of is not None:
        live = live[live["minute"] <= as_of]
        if live.empty:
            raise HTTPException(
                status_code=404,
                detail="No live data exists at or before that timestamp.",
            )

    try:
        incidents = load_incidents()
        if as_of is not None:
            incidents = incidents[incidents["start_time"] <= as_of]
    except HTTPException:
        incidents = pd.DataFrame(
            columns=["country", "priority", "value_at_risk_per_minute_usd"]
        )

    latest_minute = live["minute"].max()
    recent_window = live[
        live["minute"] > latest_minute - pd.Timedelta(minutes=5)
    ]

    global_attempts = int(recent_window["attempts"].sum())
    global_approvals = int(recent_window["approvals"].sum())
    approval_rate = (
        global_approvals / global_attempts if global_attempts else None
    )
    expected_approval_rate = expected_rate_for(
        baseline,
        weekday=int(latest_minute.dayofweek),
        hour=int(latest_minute.hour),
    )
    window_minutes = recent_window["minute"].nunique() or 1

    countries = {}
    for code in MONITORED_COUNTRIES:
        country_window = recent_window[recent_window["country"].eq(code)]
        country_attempts = int(country_window["attempts"].sum())
        country_approvals = int(country_window["approvals"].sum())
        countries[code] = {
            "status": country_status(code, incidents),
            "approval_rate": (
                country_approvals / country_attempts
                if country_attempts
                else None
            ),
            "expected_approval_rate": expected_rate_for(
                baseline,
                weekday=int(latest_minute.dayofweek),
                hour=int(latest_minute.hour),
                country=code,
            ),
            "attempts_per_minute": country_attempts / window_minutes,
        }

    history_source = live[
        live["minute"]
        > latest_minute - pd.Timedelta(minutes=CONVERSION_HISTORY_MINUTES)
    ]
    per_minute = history_source.groupby("minute").agg(
        attempts=("attempts", "sum"),
        approvals=("approvals", "sum"),
    )
    conversion_history = []
    for minute, row in per_minute.sort_index().iterrows():
        observed_rate = (
            row["approvals"] / row["attempts"] if row["attempts"] else None
        )
        conversion_history.append({
            "timestamp": minute.isoformat(),
            "observed_rate": observed_rate,
            "expected_rate": expected_rate_for(
                baseline,
                weekday=int(minute.dayofweek),
                hour=int(minute.hour),
            ),
        })

    active_incidents = incidents[
        incidents.get(
            "recommendation_status",
            pd.Series(dtype=str),
        ).ne("rejected")
    ] if "recommendation_status" in incidents.columns else incidents

    if active_incidents["priority"].eq("P1").any():
        system_status = "critical"
    elif not active_incidents.empty:
        system_status = "warning"
    else:
        system_status = "healthy"

    value_at_risk_per_minute = (
        float(active_incidents["value_at_risk_per_minute_usd"].sum())
        if "value_at_risk_per_minute_usd" in active_incidents.columns
        and not active_incidents.empty
        else None
    )

    def summed(column: str) -> float:
        return (
            float(active_incidents[column].sum())
            if column in active_incidents.columns
            and not active_incidents.empty
            else 0.0
        )

    margin_rates = load_merchant_margin_rates()
    economic_impacts = [
        build_economic_impact(record, margin_rates)
        for record in active_incidents.to_dict(orient="records")
    ]

    return {
        "system_status": system_status,
        "last_updated": latest_minute.isoformat(),
        "global_metrics": {
            "approval_rate": approval_rate,
            "expected_approval_rate": expected_approval_rate,
            "attempts_per_minute": global_attempts / window_minutes,
            "approved_per_minute": global_approvals / window_minutes,
            "active_incidents": int(len(active_incidents)),
            "value_at_risk_per_minute": value_at_risk_per_minute,
        },
        "countries": countries,
        "conversion_history": conversion_history,
        "monitored_traffic": {
            "attempts_total": int(live["attempts"].sum()),
            "merchants": int(live["merchant"].nunique()),
            "providers": int(live["provider"].nunique()),
        },
        "executive_summary": {
            "active_incident_count": int(len(active_incidents)),
            "total_gmv_at_risk_usd": round(
                summed("gross_payment_value_at_risk_usd"), 2
            ),
            "total_gmv_at_risk_adjusted_usd": round(
                summed("net_unrecovered_value_usd"), 2
            ),
            "total_platform_revenue_at_risk_usd": round(
                summed("platform_revenue_at_risk_usd"), 2
            ),
            "total_merchant_economic_impact_usd": round(
                sum(
                    e["merchant_economic_impact_usd"] or 0
                    for e in economic_impacts
                ),
                2,
            ),
            "total_economic_impact_usd": round(
                sum(
                    e["total_economic_impact_usd"] or 0
                    for e in economic_impacts
                ),
                2,
            ),
        },
        "risk_concentration": build_risk_concentration(
            active_incidents.to_dict(orient="records")
        ),
        "risk_ranking": build_risk_ranking(
            active_incidents.to_dict(orient="records")
        ),
    }


def load_notified_incident_ids() -> set[str]:
    if not NOTIFIED_INCIDENTS_PATH.exists():
        return set()

    try:
        return set(json.loads(NOTIFIED_INCIDENTS_PATH.read_text()))
    except (json.JSONDecodeError, OSError):
        return set()


def save_notified_incident_ids(incident_ids: set[str]) -> None:
    NOTIFIED_INCIDENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    NOTIFIED_INCIDENTS_PATH.write_text(json.dumps(sorted(incident_ids)))


def send_ntfy_notification(incident: dict) -> None:
    is_p1 = incident.get("priority") == "P1"
    risk_per_minute = incident.get("value_at_risk_per_minute_usd")
    risk_text = (
        f"${risk_per_minute * 60:,.0f}/h at risk"
        if risk_per_minute is not None
        else None
    )
    message = " · ".join(
        part for part in [
            incident.get("incident_title"),
            risk_text,
            incident.get("primary_action"),
        ] if part
    )
    payload = {
        "topic": NTFY_TOPIC,
        "title": f"{incident.get('priority', 'ALERT')} - Control Tower incident",
        "message": message,
        "priority": 5 if is_p1 else 3,
        "tags": ["rotating_light"] if is_p1 else ["large_orange_diamond"],
    }
    request = urllib.request.Request(
        "https://ntfy.sh/",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        response.read()


async def notify_new_incidents_loop() -> None:
    if not NTFY_TOPIC:
        return

    notified = load_notified_incident_ids()

    while True:
        try:
            dataframe = load_incidents()
            current_ids = set(dataframe["consolidated_incident_id"])
            new_ids = current_ids - notified

            for incident_id in new_ids:
                match = dataframe[
                    dataframe["consolidated_incident_id"].eq(incident_id)
                ]
                incident = clean_record(match.iloc[0].to_dict())
                await asyncio.to_thread(send_ntfy_notification, incident)

            if new_ids:
                notified |= new_ids
                save_notified_incident_ids(notified)
        except Exception as error:
            print(f"ntfy notification loop error: {error}")

        await asyncio.sleep(NOTIFY_POLL_SECONDS)


@app.on_event("startup")
async def start_notification_loop() -> None:
    asyncio.create_task(notify_new_incidents_loop())


@app.get("/notify/test")
def send_test_notification():
    if not NTFY_TOPIC:
        raise HTTPException(
            status_code=503,
            detail="NTFY_TOPIC is not configured on this deployment.",
        )

    send_ntfy_notification({
        "priority": "P1",
        "incident_title": "Control Tower test alert",
        "value_at_risk_per_minute_usd": 100.0,
        "primary_action": "This is a test notification — no action needed.",
    })
    return {"message": f"Test notification sent to ntfy.sh/{NTFY_TOPIC}."}


def load_audit_log() -> pd.DataFrame:
    if not AUDIT_LOG_PATH.exists():
        return pd.DataFrame()

    return pd.read_csv(AUDIT_LOG_PATH)


def append_audit_entry(entry: dict) -> None:
    existing = load_audit_log()
    updated = pd.concat(
        [existing, pd.DataFrame([entry])],
        ignore_index=True,
    )
    AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    updated.to_csv(AUDIT_LOG_PATH, index=False)


def validate_transition(current_status: str, action: str) -> str:
    allowed = STATUS_TRANSITIONS.get(current_status, {})

    if action not in allowed:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Action '{action}' is not allowed "
                f"from status '{current_status}'."
            ),
        )

    return allowed[action]


@app.get("/")
def root():
    return {
        "service": "Control Tower API",
        "status": "ok",
        "health": "/health",
        "documentation": "/docs",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "service": "control-tower-api",
        "timestamp": utc_now(),
    }


@app.get("/unresolved-candidates")
def get_unresolved_candidates(as_of: str | None = None):
    if not UNRESOLVED_CANDIDATES_PATH.exists():
        return {"count": 0, "candidates": []}

    dataframe = pd.read_csv(
        UNRESOLVED_CANDIDATES_PATH,
        parse_dates=["start_time", "end_time"],
        date_format="mixed",
    )

    as_of_timestamp = parse_as_of(as_of)
    if as_of_timestamp is not None:
        dataframe = dataframe[dataframe["start_time"] <= as_of_timestamp]

    dataframe = dataframe.sort_values(
        "confidence_score", ascending=False
    )

    records = []
    for record in dataframe.to_dict(orient="records"):
        cleaned = clean_record(record)
        cleaned["incident_type"] = ROOT_CAUSE_TO_INCIDENT_TYPE.get(
            str(cleaned.get("root_cause_type")), "Unknown Root Cause"
        )
        records.append(cleaned)

    return {"count": len(records), "candidates": records}


@app.get("/dashboard")
def get_dashboard(as_of: str | None = None):
    return build_dashboard_payload(as_of=parse_as_of(as_of))


@app.get("/incidents")
def get_incidents(
    priority: str | None = None,
    status: str | None = None,
    as_of: str | None = None,
):
    dataframe = load_incidents()

    if priority:
        dataframe = dataframe[dataframe["priority"].eq(priority)]

    if status:
        dataframe = dataframe[
            dataframe["recommendation_status"].eq(status)
        ]

    as_of_timestamp = parse_as_of(as_of)
    if as_of_timestamp is not None:
        dataframe = dataframe[dataframe["start_time"] <= as_of_timestamp]

    dataframe = dataframe.sort_values(
        ["priority_score", "value_at_risk_per_minute_usd"],
        ascending=False,
    )
    records = [
        enrich_with_playbook(clean_record(record))
        for record in dataframe.to_dict(orient="records")
    ]

    return {"count": len(records), "incidents": records}


@app.get("/incidents/{incident_id}")
def get_incident(incident_id: str):
    dataframe = load_incidents()
    matches = dataframe[
        dataframe["consolidated_incident_id"].eq(incident_id)
    ]

    if matches.empty:
        raise HTTPException(status_code=404, detail="Incident not found.")

    return enrich_with_playbook(clean_record(matches.iloc[0].to_dict()))


@app.get("/incidents/{incident_id}/segments")
def get_incident_segments(incident_id: str):
    dataframe = load_incidents()
    matches = dataframe[
        dataframe["consolidated_incident_id"].eq(incident_id)
    ]

    if matches.empty:
        raise HTTPException(status_code=404, detail="Incident not found.")

    record = clean_record(matches.iloc[0].to_dict())
    segments = build_segment_breakdown(record.get("source_incident_ids"))

    return {"consolidated_incident_id": incident_id, "segments": segments}


@app.post("/incidents/{incident_id}/analysis")
def analyze_incident(incident_id: str):
    dataframe = load_incidents()
    matches = dataframe[
        dataframe["consolidated_incident_id"].eq(incident_id)
    ]

    if matches.empty:
        raise HTTPException(status_code=404, detail="Incident not found.")

    record = enrich_with_playbook(clean_record(matches.iloc[0].to_dict()))
    grounding = {field: record.get(field) for field in ANALYSIS_FIELDS}

    try:
        client = get_openai_client()
        response = client.chat.completions.create(
            model=ANALYSIS_MODEL,
            max_tokens=500,
            messages=[
                {"role": "system", "content": ANALYSIS_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        "Incident data (JSON):\n"
                        + json.dumps(grounding, default=str)
                    ),
                },
            ],
        )
    except openai.APIStatusError as error:
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis request failed: {error.message}",
        ) from error
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail=f"AI analysis is not configured: {error}",
        ) from error

    analysis_text = (response.choices[0].message.content or "").strip()

    return {
        "consolidated_incident_id": incident_id,
        "analysis": analysis_text,
    }


@app.get("/audit-log")
def get_audit_log(incident_id: str | None = None):
    dataframe = load_audit_log()

    if dataframe.empty:
        return {"count": 0, "entries": []}

    if incident_id:
        dataframe = dataframe[
            dataframe["consolidated_incident_id"].eq(incident_id)
        ]

    if "timestamp" in dataframe.columns:
        dataframe = dataframe.sort_values("timestamp", ascending=False)

    records = [
        clean_record(record)
        for record in dataframe.to_dict(orient="records")
    ]
    return {"count": len(records), "entries": records}


@app.post("/incidents/{incident_id}/review")
def review_incident(incident_id: str, request: ReviewRequest):
    dataframe = load_incidents()
    matches = dataframe[
        dataframe["consolidated_incident_id"].eq(incident_id)
    ]

    if len(matches) != 1:
        raise HTTPException(status_code=404, detail="Incident not found.")

    index = matches.index[0]
    current_status = str(
        dataframe.loc[index, "recommendation_status"]
    )
    new_status = validate_transition(
        current_status=current_status,
        action=request.action,
    )
    previous_action = str(dataframe.loc[index, "primary_action"])
    new_action = previous_action

    if request.action == "modify":
        if not request.modified_primary_action:
            raise HTTPException(
                status_code=422,
                detail=(
                    "modified_primary_action is required "
                    "for modify actions."
                ),
            )

        new_action = request.modified_primary_action.strip()
        dataframe.loc[index, "primary_action"] = new_action

    timestamp = utc_now()
    dataframe.loc[index, "recommendation_status"] = new_status
    dataframe.loc[index, "reviewed_by"] = request.reviewer
    dataframe.loc[index, "reviewed_at"] = timestamp
    dataframe.loc[index, "review_comment"] = request.comment

    if request.action == "execute":
        dataframe.loc[index, "executed_at"] = timestamp

    save_incidents(dataframe)

    audit_entry = {
        "audit_id": f"AUD-{pd.Timestamp.now().value}",
        "consolidated_incident_id": incident_id,
        "action": request.action,
        "previous_status": current_status,
        "new_status": new_status,
        "reviewer": request.reviewer,
        "comment": request.comment,
        "previous_primary_action": previous_action,
        "new_primary_action": new_action,
        "timestamp": timestamp,
    }
    append_audit_entry(audit_entry)

    updated = dataframe.loc[index].to_dict()
    return {
        "message": "Review applied successfully.",
        "incident": enrich_with_playbook(clean_record(updated)),
        "audit_entry": clean_record(audit_entry),
    }
