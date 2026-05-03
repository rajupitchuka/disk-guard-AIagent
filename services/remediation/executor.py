"""Remediation executor — applies a Playbook against a host's monitored path
via `docker exec`. Returns a structured RemediationResult for the audit log.

Safety guards (absolute, applied regardless of LLM decision):
  - never delete files modified within MIN_FILE_AGE_HOURS (default 24h)
  - never delete files outside the host's monitored_path
  - cap per-run deletes at MAX_BYTES_PER_RUN_GB and MAX_FILES_PER_RUN
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Iterable

from .playbooks import CleanupRule, Playbook

log = logging.getLogger(__name__)

GB = 1024**3

MIN_FILE_AGE_HOURS = 24.0
MAX_BYTES_PER_RUN_GB = 80.0
MAX_FILES_PER_RUN = 200


def _docker_bin() -> str:
    which = shutil.which("docker")
    if which:
        return which
    return "/Applications/OrbStack.app/Contents/MacOS/xbin/docker"


def _exec(container: str, cmd: list[str], timeout: int = 60) -> str:
    docker = _docker_bin()
    result = subprocess.run(
        [docker, "exec", container, *cmd],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return result.stdout


@dataclass
class DeletionRecord:
    path: str
    size_bytes: int
    age_days: float
    matched_rule: str


@dataclass
class RemediationResult:
    host_id: str
    dry_run: bool
    files_deleted: list[DeletionRecord] = field(default_factory=list)
    files_skipped_age: list[str] = field(default_factory=list)  # too recent
    files_skipped_safety: list[str] = field(default_factory=list)  # hit a guard
    bytes_freed: int = 0
    error: str | None = None

    @property
    def file_count(self) -> int:
        return len(self.files_deleted)


def _candidates_for_rule(host_id: str, monitored_path: str, rule: CleanupRule) -> list[tuple[str, int, float]]:
    """Return [(path, size_bytes, age_days)] for files inside monitored_path
    matching rule.glob and older than rule.min_age_days. Uses `find` inside
    the container — this never returns the active /seed/junk-baseline file
    because it's not the right glob, and never returns files outside
    monitored_path because find is rooted there."""
    days = max(0, int(rule.min_age_days))
    cmd = [
        "sh", "-c",
        # -mtime +N matches files older than N days. -printf gives us size+mtime.
        f"find {monitored_path} -type f -name {_shell_quote(rule.glob)} "
        f"-mtime +{days - 1 if days > 0 else 0} "
        f"-printf '%s\\t%T@\\t%p\\n' 2>/dev/null || true",
    ]
    try:
        stdout = _exec(host_id, cmd)
    except subprocess.CalledProcessError as e:
        log.warning("find failed for %s rule=%s: %s", host_id, rule.glob, e.stderr)
        return []

    import time as _time
    now = _time.time()
    results: list[tuple[str, int, float]] = []
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) != 3:
            continue
        try:
            size = int(parts[0])
            mtime = float(parts[1])
        except ValueError:
            continue
        results.append((parts[2], size, max(0.0, (now - mtime) / 86400)))
    return results


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _is_path_under(child: str, parent: str) -> bool:
    """Refuse paths outside the monitored root, even if a rule's glob is
    weird or the LLM somehow proposes one. Belt-and-braces with find -path."""
    parent = parent.rstrip("/")
    return child == parent or child.startswith(parent + "/")


def execute(
    host_id: str,
    monitored_path: str,
    playbook: Playbook,
    dry_run: bool = True,
) -> RemediationResult:
    """Apply playbook to host. Dry-run reports candidates without deleting."""
    result = RemediationResult(host_id=host_id, dry_run=dry_run)

    candidates: list[tuple[str, int, float, CleanupRule]] = []
    seen: set[str] = set()
    for rule in playbook.rules:
        for path, size, age_days in _candidates_for_rule(host_id, monitored_path, rule):
            if path in seen:
                continue
            seen.add(path)
            candidates.append((path, size, age_days, rule))

    # Sort by age descending — delete oldest first (safer)
    candidates.sort(key=lambda x: x[2], reverse=True)

    for path, size, age_days, rule in candidates:
        # Safety: path must be inside monitored_path
        if not _is_path_under(path, monitored_path):
            result.files_skipped_safety.append(path)
            log.warning("path %s not under %s — skipping", path, monitored_path)
            continue
        # Safety: age must exceed minimum
        if age_days * 24 < MIN_FILE_AGE_HOURS:
            result.files_skipped_age.append(path)
            continue
        # Safety: per-run cap
        if (result.bytes_freed + size) / GB > MAX_BYTES_PER_RUN_GB:
            result.files_skipped_safety.append(f"{path} (per-run byte cap)")
            continue
        if result.file_count >= MAX_FILES_PER_RUN:
            result.files_skipped_safety.append(f"{path} (per-run file cap)")
            continue

        # Delete (or pretend to)
        if not dry_run:
            try:
                _exec(host_id, ["rm", "-f", path])
            except subprocess.CalledProcessError as e:
                log.error("delete failed for %s: %s", path, e.stderr)
                result.files_skipped_safety.append(f"{path} (delete error)")
                continue

        result.files_deleted.append(DeletionRecord(
            path=path,
            size_bytes=size,
            age_days=age_days,
            matched_rule=rule.description,
        ))
        result.bytes_freed += size

    return result
