"""Prophet wrapper — fits one model per host and reports in_use_pct forecasts
at the configured horizons (1/3/7/14 days by default), plus the projected
hours until in_use_pct first crosses 90%.

Prophet's Stan compilation happens once per process, then per-host fits are
~1-3 seconds at 7 days × 5-min cadence (~2000 points).
"""

from __future__ import annotations

import logging
import os

import numpy as np
import pandas as pd

# Prophet logs are noisy; quiet them before import.
os.environ.setdefault("PROPHET_LOGLEVEL", "WARNING")
logging.getLogger("cmdstanpy").setLevel(logging.WARNING)
logging.getLogger("prophet").setLevel(logging.WARNING)

from prophet import Prophet  # noqa: E402

from .features import HostSeries

log = logging.getLogger(__name__)

# 90% fill threshold matches the diagram's ML trigger
DEFAULT_FILL_TRIGGER_PCT = 90.0


def _build_model() -> Prophet:
    return Prophet(
        growth="linear",
        # Disk fill is bounded but for forecasting purposes linear with
        # interpolation works well when capped to [0, 100] downstream.
        daily_seasonality=True,
        weekly_seasonality=False,
        yearly_seasonality=False,
        changepoint_prior_scale=0.1,
        interval_width=0.80,
        uncertainty_samples=0,  # speed: no MC sampling, point estimates only
    )


def fit_and_forecast(
    series: HostSeries, horizons_days: list[int]
) -> dict[str, float | None]:
    """Fit a Prophet model on one host's series and return forecasts at
    each horizon, plus hours_to_90pct (None if not within the longest horizon).

    Returns dict with keys:
      forecast_1d_pct, forecast_3d_pct, forecast_7d_pct, forecast_14d_pct,
      hours_to_90pct
    The first four keys are populated only for horizons present in `horizons_days`.
    """
    out: dict[str, float | None] = {
        "forecast_1d_pct": None,
        "forecast_3d_pct": None,
        "forecast_7d_pct": None,
        "forecast_14d_pct": None,
        "hours_to_90pct": None,
    }
    df = series.df
    if df.empty or len(df) < 24:  # at least ~2 hours of data
        return out

    model = _build_model()
    fit_df = df[["ds", "y"]].copy()
    try:
        model.fit(fit_df)
    except Exception as e:  # noqa: BLE001
        log.warning("Prophet fit failed for %s: %s", series.host_id, e)
        return out

    max_horizon = max(horizons_days) if horizons_days else 7
    sample_minutes = _infer_sample_period_min(fit_df)
    periods = int((max_horizon * 24 * 60) / sample_minutes)
    future = model.make_future_dataframe(periods=periods, freq=f"{sample_minutes}min")
    fcst = model.predict(future)
    fcst = fcst[fcst["ds"] > fit_df["ds"].max()].reset_index(drop=True)
    fcst["yhat_clipped"] = fcst["yhat"].clip(lower=0.0, upper=100.0)

    for horizon in horizons_days:
        if horizon not in (1, 3, 7, 14):
            continue
        target_ts = fit_df["ds"].max() + pd.Timedelta(days=horizon)
        # Take the closest forecast row at or after the target time
        future_at_horizon = fcst[fcst["ds"] >= target_ts]
        if future_at_horizon.empty:
            continue
        out[f"forecast_{horizon}d_pct"] = float(future_at_horizon.iloc[0]["yhat_clipped"])

    # Find first crossing of DEFAULT_FILL_TRIGGER_PCT in the forecast horizon
    crossing = fcst[fcst["yhat_clipped"] >= DEFAULT_FILL_TRIGGER_PCT]
    if not crossing.empty:
        first_ts = crossing.iloc[0]["ds"]
        delta = first_ts - fit_df["ds"].max()
        out["hours_to_90pct"] = float(delta.total_seconds() / 3600.0)
    # If forecast trajectory never crosses 90% in the horizon, leave None.

    return out


def _infer_sample_period_min(df: pd.DataFrame) -> int:
    """Best-effort: median delta between consecutive samples, rounded to minutes.
    Falls back to 5 (matching the synthetic data cadence)."""
    if len(df) < 2:
        return 5
    deltas = df["ds"].diff().dropna()
    if deltas.empty:
        return 5
    median = deltas.median()
    minutes = max(1, int(round(median.total_seconds() / 60)))
    return minutes
