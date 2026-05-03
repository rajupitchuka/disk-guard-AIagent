"""Cached query helpers for the Streamlit UI.

Streamlit reruns the script on every interaction, so we wrap DB queries with
@st.cache_data(ttl=...) to avoid hammering TimescaleDB. TTLs are short (seconds)
because the demo flow involves frequent state changes (fill disk → re-run ML →
re-run agent), and stale data ruins the demo.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st

from shared.db import timescale_conn


@st.cache_data(ttl=5)
def fetch_hosts() -> pd.DataFrame:
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT host_id, hostname, os, environment, region, role, "
                "total_disk_gb, monitored_path FROM hosts ORDER BY host_id"
            )
            rows = cur.fetchall()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["is_demo_host"] = df["host_id"].str.startswith("demo-")
    return df


@st.cache_data(ttl=5)
def fetch_latest_predictions() -> pd.DataFrame:
    """One row per host — the most recent ML prediction."""
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (host_id)
                    prediction_id, ts, host_id, device,
                    forecast_1d_pct, forecast_3d_pct, forecast_7d_pct, forecast_14d_pct,
                    hours_to_90pct, anomaly_score, triggered_agent
                FROM ml_predictions
                ORDER BY host_id, ts DESC
                """
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows)


@st.cache_data(ttl=5)
def fetch_latest_telemetry() -> pd.DataFrame:
    """Most recent telemetry sample per host — used for fleet overview."""
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (host_id)
                    host_id, ts, in_use_pct, used_bytes, total_bytes
                FROM disk_telemetry
                ORDER BY host_id, ts DESC
                """
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows)


@st.cache_data(ttl=10)
def fetch_host_telemetry(host_id: str, hours: int = 168) -> pd.DataFrame:
    """Time series for one host. Default = 7 days."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, in_use_pct, used_bytes, free_bytes
                FROM disk_telemetry
                WHERE host_id = %s AND ts >= %s
                ORDER BY ts
                """,
                (host_id, cutoff),
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows)


@st.cache_data(ttl=5)
def fetch_host_predictions(host_id: str, limit: int = 50) -> pd.DataFrame:
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT prediction_id, ts, forecast_1d_pct, forecast_3d_pct,
                       forecast_7d_pct, forecast_14d_pct, hours_to_90pct,
                       anomaly_score, triggered_agent
                FROM ml_predictions
                WHERE host_id = %s
                ORDER BY ts DESC
                LIMIT %s
                """,
                (host_id, limit),
            )
            rows = cur.fetchall()
    return pd.DataFrame(rows)


@st.cache_data(ttl=5)
def fetch_agent_runs(host_id: str | None = None, limit: int = 50) -> pd.DataFrame:
    sql = """
        SELECT run_id, started_at, finished_at, host_id, prediction_id,
               confidence_score, decision, verdict, bytes_freed, files_deleted,
               servicenow_ticket_id, llm_reasoning, tool_calls, rag_context_ids
        FROM agent_runs
    """
    params: tuple = ()
    if host_id is not None:
        sql += " WHERE host_id = %s"
        params = (host_id,)
    sql += " ORDER BY started_at DESC LIMIT %s"
    params = params + (limit,)
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def fleet_overview() -> pd.DataFrame:
    """Single combined frame for the fleet view: host meta + latest telemetry +
    latest prediction. Not cached — composes already-cached pieces."""
    hosts = fetch_hosts()
    telem = fetch_latest_telemetry()
    preds = fetch_latest_predictions()

    if hosts.empty:
        return hosts

    df = hosts.merge(telem, on="host_id", how="left", suffixes=("", "_telem"))
    df = df.merge(
        preds[["host_id", "anomaly_score", "forecast_7d_pct", "hours_to_90pct", "triggered_agent"]],
        on="host_id",
        how="left",
    )

    # Categorize for UI badges
    def _status(row) -> str:
        if pd.isna(row.get("anomaly_score")):
            return "no_prediction"
        if row["anomaly_score"] >= 0.6:
            return "anomalous"
        if row.get("triggered_agent"):
            return "predictive"
        if row.get("in_use_pct", 0) > 90:
            return "critical"
        return "healthy"

    df["status"] = df.apply(_status, axis=1)
    return df


@st.cache_data(ttl=5)
def fetch_tickets(
    status: str | None = None,
    severity: str | None = None,
    limit: int = 200,
) -> pd.DataFrame:
    sql = "SELECT * FROM servicenow_tickets"
    where = []
    params: list = []
    if status:
        where.append("status = %s")
        params.append(status)
    if severity:
        where.append("severity = %s")
        params.append(severity)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY created_at DESC LIMIT %s"
    params.append(limit)

    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, tuple(params))
            rows = cur.fetchall()
    return pd.DataFrame(rows)


def invalidate_caches() -> None:
    """Force fresh reads after an action (fill, run ML, run agent)."""
    fetch_hosts.clear()
    fetch_latest_predictions.clear()
    fetch_latest_telemetry.clear()
    fetch_host_telemetry.clear()
    fetch_host_predictions.clear()
    fetch_agent_runs.clear()
    fetch_tickets.clear()
