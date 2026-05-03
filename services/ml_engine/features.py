"""Feature engineering — turns the raw disk_telemetry hypertable into
per-host time series suitable for Prophet, and per-host feature vectors
for the XGBoost anomaly classifier.

Why these features for XGBoost:
  - mean, std, min, max, range:    overall behavior
  - slope_full, slope_recent_24h:  long vs short-term trend
  - slope_acceleration:            short slope minus long slope (positive = recent worsening)
  - residual_std vs sample_std:    how much of variation is random vs structural
  - max_jump_24h:                  largest single-step delta in last 24h (anomaly indicator)

These are the signals that distinguish the four synthetic patterns:
  - stable     -> low std, ~zero slope
  - declining  -> low std, small steady positive slope
  - anomalous  -> low std historically + sharp positive recent slope (large acceleration)
  - critical   -> high mean (already at the wall)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from shared.db import timescale_conn

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HostSeries:
    host_id: str
    device: str
    df: pd.DataFrame  # columns: ds (datetime), y (in_use_pct)


def fetch_host_series(host_id: str, device: str | None = None, days: int = 7) -> HostSeries:
    """Pull the most recent `days` of telemetry for one host."""
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            if device is None:
                cur.execute(
                    """
                    SELECT ts, device, in_use_pct
                    FROM disk_telemetry
                    WHERE host_id = %s AND ts >= NOW() - %s::INTERVAL
                    ORDER BY ts
                    """,
                    (host_id, f"{days} days"),
                )
            else:
                cur.execute(
                    """
                    SELECT ts, device, in_use_pct
                    FROM disk_telemetry
                    WHERE host_id = %s AND device = %s AND ts >= NOW() - %s::INTERVAL
                    ORDER BY ts
                    """,
                    (host_id, device, f"{days} days"),
                )
            rows = cur.fetchall()

    if not rows:
        return HostSeries(host_id=host_id, device=device or "", df=pd.DataFrame())

    df = pd.DataFrame(rows)
    actual_device = df["device"].iloc[0] if device is None else device
    df = df[df["device"] == actual_device].copy()
    df = df.rename(columns={"ts": "ds", "in_use_pct": "y"})[["ds", "y"]]
    df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_convert(None)
    df = df.sort_values("ds").reset_index(drop=True)
    return HostSeries(host_id=host_id, device=actual_device, df=df)


def fetch_all_host_series(days: int = 7) -> list[HostSeries]:
    """Pull recent telemetry for every host. One query, sliced in pandas."""
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT ts, host_id, device, in_use_pct
                FROM disk_telemetry
                WHERE ts >= NOW() - %s::INTERVAL
                ORDER BY host_id, device, ts
                """,
                (f"{days} days",),
            )
            rows = cur.fetchall()

    if not rows:
        return []

    df = pd.DataFrame(rows)
    df = df.rename(columns={"ts": "ds", "in_use_pct": "y"})
    df["ds"] = pd.to_datetime(df["ds"], utc=True).dt.tz_convert(None)
    out: list[HostSeries] = []
    for (host_id, device), group in df.groupby(["host_id", "device"]):
        sub = group[["ds", "y"]].sort_values("ds").reset_index(drop=True)
        out.append(HostSeries(host_id=host_id, device=device, df=sub))
    return out


# ---------------------------------------------------------------------------
# XGBoost feature extraction
# ---------------------------------------------------------------------------

ANOMALY_FEATURE_NAMES: tuple[str, ...] = (
    "mean", "std", "min", "max", "range",
    "slope_full",
    "slope_recent_24h",
    "slope_acceleration",
    "residual_std",
    "max_abs_jump_24h",
    "p90_minus_p10",
    "current_value",
)


def _slope(y: np.ndarray, t_hours: np.ndarray) -> float:
    """Least-squares slope; returns 0.0 for degenerate inputs."""
    if y.size < 2 or t_hours.size != y.size:
        return 0.0
    n = y.size
    tx = t_hours - t_hours.mean()
    ty = y - y.mean()
    denom = float(np.sum(tx * tx))
    if denom == 0.0:
        return 0.0
    return float(np.sum(tx * ty) / denom)


def extract_anomaly_features(series: HostSeries) -> dict[str, float]:
    df = series.df
    if df.empty or len(df) < 5:
        return {name: 0.0 for name in ANOMALY_FEATURE_NAMES}

    y = df["y"].to_numpy(dtype=float)
    ds = df["ds"].to_numpy()
    t_hours = (ds - ds[0]) / np.timedelta64(1, "h")
    t_hours = t_hours.astype(float)

    slope_full = _slope(y, t_hours)

    cutoff_24h = t_hours[-1] - 24.0
    recent_mask = t_hours >= cutoff_24h
    if recent_mask.sum() >= 2:
        slope_recent = _slope(y[recent_mask], t_hours[recent_mask])
    else:
        slope_recent = slope_full

    # Residuals from a global linear fit (how noisy vs. how trending)
    intercept = y.mean() - slope_full * t_hours.mean()
    fit = slope_full * t_hours + intercept
    residual_std = float(np.std(y - fit))

    diffs = np.abs(np.diff(y[recent_mask])) if recent_mask.sum() >= 2 else np.array([0.0])
    max_abs_jump_24h = float(diffs.max()) if diffs.size > 0 else 0.0

    return {
        "mean": float(y.mean()),
        "std": float(y.std()),
        "min": float(y.min()),
        "max": float(y.max()),
        "range": float(y.max() - y.min()),
        "slope_full": slope_full,
        "slope_recent_24h": slope_recent,
        "slope_acceleration": slope_recent - slope_full,
        "residual_std": residual_std,
        "max_abs_jump_24h": max_abs_jump_24h,
        "p90_minus_p10": float(np.percentile(y, 90) - np.percentile(y, 10)),
        "current_value": float(y[-1]),
    }


def features_dataframe(series_list: list[HostSeries]) -> pd.DataFrame:
    rows = []
    for s in series_list:
        feat = extract_anomaly_features(s)
        feat["host_id"] = s.host_id
        feat["device"] = s.device
        rows.append(feat)
    cols = ["host_id", "device", *ANOMALY_FEATURE_NAMES]
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=cols)
    return df[cols]
