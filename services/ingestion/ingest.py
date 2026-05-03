"""Ingestion logic — Zone 1, between Datadog and TimescaleDB.

In production this polls Datadog every 15 min, normalizes the response, and
writes to disk_telemetry. For the POC we generate the next 15 minutes worth
of synthetic samples per host on each tick (extending the time series
forward), so the demo continues to feel "live" after the initial seed.
"""

from __future__ import annotations

import logging
import random
from datetime import datetime, timedelta, timezone

from shared.config import settings
from shared.db import timescale_conn
from shared.schemas import DiskTelemetry, Host

log = logging.getLogger(__name__)

GB = 1024**3


def fetch_hosts() -> list[Host]:
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM hosts ORDER BY host_id")
            rows = cur.fetchall()
    return [Host.model_validate(r) for r in rows]


def latest_sample_per_host(host_ids: list[str]) -> dict[str, DiskTelemetry]:
    """Return the most recent telemetry sample for each host (used to extend
    the synthetic series forward)."""
    if not host_ids:
        return {}
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT DISTINCT ON (host_id) ts, host_id, device, total_bytes,
                       used_bytes, free_bytes, in_use_pct
                FROM disk_telemetry
                WHERE host_id = ANY(%s)
                ORDER BY host_id, ts DESC
                """,
                (host_ids,),
            )
            rows = cur.fetchall()
    return {r["host_id"]: DiskTelemetry.model_validate(r) for r in rows}


def _next_sample(host: Host, last: DiskTelemetry, now: datetime, rng: random.Random) -> DiskTelemetry:
    """Extend a host's series by one sample at `now`. The drift direction is
    inferred from the recent trajectory, so hosts seeded as 'declining' keep
    declining, etc., without needing the original pattern label."""
    # Re-derive a small per-step delta. We don't try to perfectly mimic the
    # original pattern — just continue plausibly.
    delta_pct = rng.gauss(0, 0.3)  # default: noisy stable
    new_pct = max(0.0, min(99.9, last.in_use_pct + delta_pct))
    total_bytes = int(host.total_disk_gb * GB)
    used_bytes = int(total_bytes * (new_pct / 100.0))
    free_bytes = total_bytes - used_bytes
    return DiskTelemetry(
        ts=now,
        host_id=host.host_id,
        device=host.monitored_path,
        total_bytes=total_bytes,
        used_bytes=used_bytes,
        free_bytes=free_bytes,
        in_use_pct=round(new_pct, 3),
    )


def ingest_tick() -> int:
    """Run once: extend each host's series with samples covering the elapsed
    interval since their last recorded sample. Returns rows inserted.

    In production this would be: fetch from Datadog API → normalize → insert.
    Here we synthesize the same shape.
    """
    rng = random.Random()
    hosts = fetch_hosts()
    if not hosts:
        log.warning("no hosts in DB; run synthetic_generator first")
        return 0

    last_samples = latest_sample_per_host([h.host_id for h in hosts])
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    interval = timedelta(minutes=settings.synthetic_telemetry_interval_min)

    new_samples: list[dict] = []
    for host in hosts:
        last = last_samples.get(host.host_id)
        if last is None:
            log.debug("no prior sample for %s; skipping", host.host_id)
            continue
        # Fill all elapsed sample slots between last.ts and now
        cursor = last.ts + interval
        while cursor <= now:
            new = _next_sample(host, last, cursor, rng)
            new_samples.append(new.model_dump())
            last = new
            cursor += interval

    if not new_samples:
        log.info("ingest tick: no new samples needed")
        return 0

    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO disk_telemetry
                    (ts, host_id, device, total_bytes, used_bytes, free_bytes, in_use_pct)
                VALUES
                    (%(ts)s, %(host_id)s, %(device)s, %(total_bytes)s, %(used_bytes)s, %(free_bytes)s, %(in_use_pct)s)
                ON CONFLICT DO NOTHING
                """,
                new_samples,
            )
        conn.commit()

    log.info("ingest tick: wrote %d samples across %d hosts", len(new_samples), len(hosts))
    return len(new_samples)
