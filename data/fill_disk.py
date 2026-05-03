"""'Fill disk' helper — writes sparse files into a demo host's monitored path
to artificially increase its in_use_pct. Used by the Day 4 UI's button and
also runnable from the CLI for manual demos.

Sparse files (fallocate -l) take effectively zero real disk and respond
instantly. Each call adds N bytes of "junk" so the live agent's next sample
shows the higher percentage.

For demo responsiveness, `--with-backfill MIN` also inserts N backdated
samples at the new percentage so Prophet/XGBoost respond immediately rather
than after several agent cycles.
"""

from __future__ import annotations

import argparse
import logging
import shutil
import subprocess
import time
import uuid
from datetime import datetime, timedelta, timezone

from data.seed_demo_hosts import DEMO_HOSTS
from shared.db import timescale_conn
from shared.logging_setup import setup_logging

log = logging.getLogger(__name__)

GB = 1024**3


def _docker_bin() -> str:
    which = shutil.which("docker")
    if which:
        return which
    return "/Applications/OrbStack.app/Contents/MacOS/xbin/docker"


def host_metadata(host_id: str) -> tuple[str, float]:
    """Return (monitored_path, total_disk_gb) for a demo host."""
    for host, _pat in DEMO_HOSTS:
        if host.host_id == host_id:
            return host.monitored_path, host.total_disk_gb
    raise ValueError(f"unknown demo host: {host_id} (try one of {[h.host_id for h, _ in DEMO_HOSTS]})")


def fill(
    host_id: str,
    gb: float,
    label: str | None = None,
    backfill_minutes: int = 0,
) -> dict:
    """Write `gb` of sparse junk into the host's monitored path.

    If backfill_minutes > 0, also inserts that many backdated samples into
    disk_telemetry at the new (post-fill) percentage so ML responds without
    waiting for live agent cycles. Use this for demo flow.
    """
    monitored, total_gb = host_metadata(host_id)
    if gb <= 0:
        raise ValueError("gb must be positive")
    if gb > total_gb * 0.95:
        raise ValueError(f"requested {gb}GB is too close to total {total_gb}GB; capped at 95%")

    bytes_to_add = int(gb * GB)
    label = label or uuid.uuid4().hex[:8]
    path_in_container = f"{monitored}/junk-{label}.bin"

    docker = _docker_bin()
    started = time.time()
    subprocess.run(
        [docker, "exec", host_id, "fallocate", "-l", str(bytes_to_add), path_in_container],
        check=True,
        capture_output=True,
    )
    elapsed = time.time() - started

    log.info(
        "filled %s with %.2f GB at %s (in %.2fs)",
        host_id, gb, path_in_container, elapsed,
    )

    backfilled = 0
    if backfill_minutes > 0:
        backfilled = _backfill_samples(host_id, monitored, total_gb, backfill_minutes)
        log.info("inserted %d backdated samples for %s", backfilled, host_id)

    return {
        "host_id": host_id,
        "path": path_in_container,
        "bytes_added": bytes_to_add,
        "label": label,
        "samples_backfilled": backfilled,
    }


def _backfill_samples(host_id: str, monitored: str, total_gb: float, minutes: int) -> int:
    """Insert N backdated samples reflecting the new disk state, one per
    minute up to 'now'. Avoids collisions with samples already in the DB by
    using ON CONFLICT DO NOTHING."""
    total_bytes = int(total_gb * GB)
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    rows = []

    # Read current actual usage from the container so the backfill matches
    # what the live agent would have reported.
    docker = _docker_bin()
    result = subprocess.run(
        [docker, "exec", host_id, "sh", "-c", f"du -sb {monitored} | cut -f1"],
        check=True,
        capture_output=True,
        text=True,
    )
    used_bytes = int(result.stdout.strip())
    used_bytes = min(used_bytes, total_bytes - 1)
    free_bytes = total_bytes - used_bytes
    in_use_pct = round(100.0 * used_bytes / total_bytes, 3)

    for i in range(minutes):
        ts = now - timedelta(minutes=minutes - 1 - i)
        rows.append({
            "ts": ts,
            "host_id": host_id,
            "device": monitored,
            "total_bytes": total_bytes,
            "used_bytes": used_bytes,
            "free_bytes": free_bytes,
            "in_use_pct": in_use_pct,
        })

    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO disk_telemetry
                    (ts, host_id, device, total_bytes, used_bytes, free_bytes, in_use_pct)
                VALUES (%(ts)s, %(host_id)s, %(device)s, %(total_bytes)s,
                        %(used_bytes)s, %(free_bytes)s, %(in_use_pct)s)
                ON CONFLICT DO NOTHING
                """,
                rows,
            )
        conn.commit()
    return len(rows)


def clear(host_id: str, label: str | None = None) -> dict:
    """Remove junk files. If `label` is None, removes all junk-*.bin files."""
    monitored, _ = host_metadata(host_id)
    docker = _docker_bin()
    pattern = f"{monitored}/junk-{label}.bin" if label else f"{monitored}/junk-*.bin"
    # Use sh -c so the wildcard expands inside the container
    result = subprocess.run(
        [docker, "exec", host_id, "sh", "-c", f"rm -f {pattern} && echo cleared"],
        check=True,
        capture_output=True,
        text=True,
    )
    log.info("cleared junk on %s: %s", host_id, result.stdout.strip())
    return {"host_id": host_id, "pattern": pattern}


def main() -> None:
    parser = argparse.ArgumentParser(prog="opsgpt-fill-disk")
    parser.add_argument("host_id", help="One of demo-web-01, demo-app-01, demo-db-01")
    sub = parser.add_subparsers(dest="cmd", required=True)
    fill_p = sub.add_parser("fill", help="Add junk files to fill the monitored path")
    fill_p.add_argument("--gb", type=float, required=True)
    fill_p.add_argument("--label", help="Label suffix (default: random)")
    fill_p.add_argument(
        "--with-backfill",
        type=int,
        default=0,
        metavar="MIN",
        help="Insert N backdated samples at new pct so ML responds immediately.",
    )
    clear_p = sub.add_parser("clear", help="Remove junk files")
    clear_p.add_argument("--label", help="Specific label to clear (default: all)")
    args = parser.parse_args()

    setup_logging()

    if args.cmd == "fill":
        fill(args.host_id, args.gb, args.label, backfill_minutes=args.with_backfill)
    else:
        clear(args.host_id, args.label)


if __name__ == "__main__":
    main()
