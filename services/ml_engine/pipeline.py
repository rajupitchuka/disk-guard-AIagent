"""Pipeline orchestration: pull telemetry → fit Prophet per host → score with
XGBoost → write to ml_predictions → flag agent triggers."""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from shared.config import settings
from shared.db import timescale_conn
from shared.schemas import MLPrediction

from .anomaly import DEFAULT_MODEL_PATH, load as load_anomaly_model, score_batch
from .features import HostSeries, fetch_all_host_series, fetch_host_series
from .prophet_forecast import fit_and_forecast

log = logging.getLogger(__name__)

# Threshold for flagging "this anomaly score warrants the LLM agent"
# (separate from the 90%/7d forecast trigger; either alone is sufficient)
ANOMALY_TRIGGER_SCORE = 0.6


def _persist(predictions: list[MLPrediction]) -> None:
    if not predictions:
        return
    rows = [p.model_dump() for p in predictions]
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO ml_predictions
                  (prediction_id, ts, host_id, device,
                   forecast_1d_pct, forecast_3d_pct, forecast_7d_pct, forecast_14d_pct,
                   hours_to_90pct, anomaly_score, triggered_agent, model_version)
                VALUES
                  (%(prediction_id)s, %(ts)s, %(host_id)s, %(device)s,
                   %(forecast_1d_pct)s, %(forecast_3d_pct)s, %(forecast_7d_pct)s, %(forecast_14d_pct)s,
                   %(hours_to_90pct)s, %(anomaly_score)s, %(triggered_agent)s, %(model_version)s)
                """,
                rows,
            )
        conn.commit()


def _build_prediction(
    series: HostSeries,
    forecast: dict[str, float | None],
    anomaly_score: float,
) -> MLPrediction:
    """Apply the architecture-diagram trigger rule:
       trigger if forecast crosses 90% within 7 days OR anomaly_score is high."""
    forecast_7d = forecast.get("forecast_7d_pct")
    hours = forecast.get("hours_to_90pct")
    horizon_hours = settings.ml_trigger_horizon_days * 24

    forecast_trigger = (
        forecast_7d is not None and forecast_7d >= settings.ml_trigger_fill_pct
    ) or (hours is not None and hours <= horizon_hours)
    anomaly_trigger = anomaly_score >= ANOMALY_TRIGGER_SCORE

    return MLPrediction(
        prediction_id=f"pred-{uuid.uuid4().hex[:12]}",
        ts=datetime.now(timezone.utc),
        host_id=series.host_id,
        device=series.device,
        forecast_1d_pct=forecast.get("forecast_1d_pct"),
        forecast_3d_pct=forecast.get("forecast_3d_pct"),
        forecast_7d_pct=forecast.get("forecast_7d_pct"),
        forecast_14d_pct=forecast.get("forecast_14d_pct"),
        hours_to_90pct=forecast.get("hours_to_90pct"),
        anomaly_score=float(anomaly_score),
        triggered_agent=bool(forecast_trigger or anomaly_trigger),
        model_version="prophet-1.x+xgb-3.x",
    )


def run_predictions_for_host(host_id: str, model_path: Path = DEFAULT_MODEL_PATH) -> MLPrediction:
    """Single-host on-demand prediction (called by the UI 'Run ML' button)."""
    series = fetch_host_series(host_id)
    if series.df.empty:
        raise ValueError(f"no telemetry for host {host_id}")

    forecast = fit_and_forecast(series, settings.predict_horizon_days)
    clf = load_anomaly_model(model_path)
    score = score_batch(clf, [series]).get(host_id, 0.0)
    pred = _build_prediction(series, forecast, score)
    _persist([pred])
    return pred


def run_full_cycle(model_path: Path = DEFAULT_MODEL_PATH) -> dict[str, int]:
    """Run Prophet + XGBoost over every host. Persist all predictions."""
    log.info("ML cycle starting")
    series_list = fetch_all_host_series(days=settings.synthetic_history_days)
    log.info("fetched %d host series", len(series_list))
    if not series_list:
        return {"hosts": 0, "predictions": 0, "triggered": 0}

    clf = load_anomaly_model(model_path)
    anomaly_scores = score_batch(clf, series_list)
    log.info("XGBoost scored %d hosts (max=%.3f, mean=%.3f)",
             len(anomaly_scores),
             max(anomaly_scores.values()) if anomaly_scores else 0,
             sum(anomaly_scores.values()) / max(1, len(anomaly_scores)))

    predictions: list[MLPrediction] = []
    for i, s in enumerate(series_list, 1):
        forecast = fit_and_forecast(s, settings.predict_horizon_days)
        pred = _build_prediction(s, forecast, anomaly_scores.get(s.host_id, 0.0))
        predictions.append(pred)
        if i % 10 == 0:
            log.info("  fitted Prophet for %d/%d hosts", i, len(series_list))

    _persist(predictions)
    triggered = sum(1 for p in predictions if p.triggered_agent)
    log.info(
        "ML cycle done: %d predictions, %d triggered agent",
        len(predictions), triggered,
    )
    return {
        "hosts": len(series_list),
        "predictions": len(predictions),
        "triggered": triggered,
    }


def latest_predictions(host_ids: Iterable[str] | None = None) -> list[MLPrediction]:
    """Most recent prediction per (host, device). Used by the UI fleet view."""
    sql = """
        SELECT DISTINCT ON (host_id, device)
            prediction_id, ts, host_id, device,
            forecast_1d_pct, forecast_3d_pct, forecast_7d_pct, forecast_14d_pct,
            hours_to_90pct, anomaly_score, triggered_agent, model_version
        FROM ml_predictions
    """
    params: tuple = ()
    if host_ids is not None:
        sql += " WHERE host_id = ANY(%s)"
        params = (list(host_ids),)
    sql += " ORDER BY host_id, device, ts DESC"

    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            rows = cur.fetchall()
    return [MLPrediction.model_validate(r) for r in rows]
