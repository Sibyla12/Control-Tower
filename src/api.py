from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


REVIEWED_INCIDENTS_PATH = Path("data/reviewed_incidents.csv")
RECOMMENDED_INCIDENTS_PATH = Path(
    "data/incidents_with_recommendations.csv"
)
AUDIT_LOG_PATH = Path("data/recommendation_audit_log.csv")
LIVE_SEGMENT_WINDOWS_PATH = Path("data/live_segment_windows.csv")
BASELINE_BY_SEGMENT_PATH = Path("data/baseline_by_segment.csv")

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


def build_dashboard_payload() -> dict:
    live = load_live_windows()
    baseline = load_segment_baseline()

    try:
        incidents = load_incidents()
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
    }


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


@app.get("/dashboard")
def get_dashboard():
    return build_dashboard_payload()


@app.get("/incidents")
def get_incidents(
    priority: str | None = None,
    status: str | None = None,
):
    dataframe = load_incidents()

    if priority:
        dataframe = dataframe[dataframe["priority"].eq(priority)]

    if status:
        dataframe = dataframe[
            dataframe["recommendation_status"].eq(status)
        ]

    dataframe = dataframe.sort_values(
        ["priority_score", "value_at_risk_per_minute_usd"],
        ascending=False,
    )
    records = [
        clean_record(record)
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

    return clean_record(matches.iloc[0].to_dict())


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
        "incident": clean_record(updated),
        "audit_entry": clean_record(audit_entry),
    }
