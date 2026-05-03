"""In-container telemetry agent.

Runs as PID 1 in each demo host container. Does two things:
  1. On startup, self-registers in the `hosts` table (idempotent).
  2. Forever: every REPORT_INTERVAL_SEC, sums files under MONITORED_PATH and
     writes a row to disk_telemetry showing the current usage as a fraction
     of the container's configured VIRTUAL_TOTAL_GB.

Why a virtual disk size: real container filesystems are shared with the
Docker host, so `df` would show the host's free space and "Fill disk" would
have to fill the entire OrbStack VM. By treating the monitored directory as
its own "virtual disk" of configured size, fills are local and predictable.
"""

from __future__ import annotations

import logging
import os
import signal
import sys
import time
from datetime import datetime, timezone

import psycopg

GB = 1024**3
log = logging.getLogger("demo-host-agent")


def env(name: str, default: str | None = None) -> str:
    val = os.environ.get(name, default)
    if val is None:
        raise RuntimeError(f"required env var {name} is unset")
    return val


def env_int(name: str, default: int) -> int:
    return int(os.environ.get(name, default))


def env_float(name: str, default: float) -> float:
    return float(os.environ.get(name, default))


def directory_size_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                continue
    return total


def connect(dsn: str) -> psycopg.Connection:
    """Retry until TimescaleDB is reachable. Containers may start before DB."""
    delay = 1.0
    for _ in range(30):
        try:
            return psycopg.connect(dsn, autocommit=True)
        except psycopg.OperationalError as e:
            log.warning("DB not ready (%s); retrying in %.1fs", e, delay)
            time.sleep(delay)
            delay = min(delay * 1.5, 10.0)
    raise RuntimeError("could not connect to TimescaleDB after 30 attempts")


def register_host(conn: psycopg.Connection) -> None:
    host_id = env("HOST_ID")
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO hosts (host_id, hostname, os, environment, region, role,
                               total_disk_gb, monitored_path)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (host_id) DO UPDATE SET
              hostname = EXCLUDED.hostname,
              os = EXCLUDED.os,
              environment = EXCLUDED.environment,
              region = EXCLUDED.region,
              role = EXCLUDED.role,
              total_disk_gb = EXCLUDED.total_disk_gb,
              monitored_path = EXCLUDED.monitored_path
            """,
            (
                host_id,
                env("HOSTNAME", host_id),
                env("OS_TYPE", "linux"),
                env("ENVIRONMENT", "prod"),
                env("REGION", "us-east-1"),
                env("ROLE", "app"),
                env_float("VIRTUAL_TOTAL_GB", 100.0),
                env("MONITORED_PATH", "/var/log"),
            ),
        )
    log.info("registered host %s", host_id)


def report_one_sample(conn: psycopg.Connection) -> dict:
    host_id = env("HOST_ID")
    monitored = env("MONITORED_PATH", "/var/log")
    total_gb = env_float("VIRTUAL_TOTAL_GB", 100.0)
    total_bytes = int(total_gb * GB)
    used_bytes = directory_size_bytes(monitored)
    used_bytes = min(used_bytes, total_bytes - 1)  # don't go negative-free
    free_bytes = total_bytes - used_bytes
    in_use_pct = round(100.0 * used_bytes / total_bytes, 3)
    ts = datetime.now(timezone.utc).replace(microsecond=0)

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO disk_telemetry
                (ts, host_id, device, total_bytes, used_bytes, free_bytes, in_use_pct)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (ts, host_id, monitored, total_bytes, used_bytes, free_bytes, in_use_pct),
        )
    return {"in_use_pct": in_use_pct, "used_bytes": used_bytes, "ts": ts.isoformat()}


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    interval = env_int("REPORT_INTERVAL_SEC", 60)
    dsn = env("TIMESCALE_DSN")

    log.info(
        "starting agent: host_id=%s monitored=%s virtual_size=%sGB interval=%ds",
        env("HOST_ID"), env("MONITORED_PATH", "/var/log"),
        env_float("VIRTUAL_TOTAL_GB", 100.0), interval,
    )

    stopping = False

    def _stop(signum, _frame):  # noqa: ARG001
        nonlocal stopping
        log.info("received signal %d; shutting down", signum)
        stopping = True

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    conn = connect(dsn)
    register_host(conn)
    # Immediate sample so the container shows up right after startup
    sample = report_one_sample(conn)
    log.info("first sample: %s", sample)

    while not stopping:
        for _ in range(interval):
            if stopping:
                break
            time.sleep(1)
        if stopping:
            break
        try:
            sample = report_one_sample(conn)
            log.info("reported in_use_pct=%.2f", sample["in_use_pct"])
        except Exception as e:  # noqa: BLE001
            log.exception("report failed: %s", e)
            try:
                conn.close()
            except Exception:
                pass
            conn = connect(dsn)

    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
