"""LLM agent tools — operations on the real demo host containers.

Two principles:
  1. Tools called during REASONING are read-only: list_files, get_file_info,
     search_runbooks. The LLM uses these to gather evidence before deciding.
  2. WRITE actions (delete, gzip, etc.) are NOT exposed to the LLM directly.
     They go through the Remediation Engine after the Decision Engine routes
     the run with sufficient confidence. The agent's output is a
     *recommendation*; execution is gated.

This split mirrors the architecture diagram: the LLM Agent (Zone 2) reasons,
the Remediation Engine (Zone 3) executes — and the Decision Engine sits
between them.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field

from .rag import RetrievedDoc, format_for_prompt, search as rag_search

log = logging.getLogger(__name__)


def _docker_bin() -> str:
    which = shutil.which("docker")
    if which:
        return which
    return "/Applications/OrbStack.app/Contents/MacOS/xbin/docker"


def _exec(container: str, cmd: list[str], timeout: int = 30) -> str:
    """Run cmd inside container, return stdout. Raises on non-zero exit."""
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
class FileInfo:
    path: str
    size_bytes: int
    age_days: float
    is_active_log: bool  # heuristic: matches active-log naming + recent mtime


@dataclass
class ToolCall:
    """One tool invocation, recorded for the audit trail."""
    tool: str
    args: dict
    output_summary: str
    error: str | None = None


# ---------------------------------------------------------------------------
# list_files: enumerate the host's monitored path with metadata
# ---------------------------------------------------------------------------

def list_files(host_id: str, monitored_path: str, max_files: int = 50) -> tuple[list[FileInfo], ToolCall]:
    """Walk the monitored path inside the container and return file metadata
    sorted by size (largest first). Excludes the seed-baseline file."""
    cmd = [
        "sh", "-c",
        # printf format: size_bytes<TAB>mtime_epoch<TAB>path
        f"find {monitored_path} -type f -not -name '_seed_baseline.bin' "
        f"-printf '%s\\t%T@\\t%p\\n' | sort -rn | head -{max_files}",
    ]
    try:
        stdout = _exec(host_id, cmd)
    except subprocess.CalledProcessError as e:
        err = e.stderr or str(e)
        return [], ToolCall(
            tool="list_files",
            args={"host_id": host_id, "path": monitored_path},
            output_summary=f"error: {err[:200]}",
            error=err,
        )

    import time as _time
    now = _time.time()
    files: list[FileInfo] = []
    for line in stdout.splitlines():
        parts = line.split("\t", 2)
        if len(parts) < 3:
            continue
        size_str, mtime_str, path = parts
        try:
            size = int(size_str)
            mtime = float(mtime_str)
        except ValueError:
            continue
        age_days = max(0.0, (now - mtime) / 86400)
        # Heuristic: active log = name has *.log (no rotation suffix) AND mtime within 1 day
        name = path.rsplit("/", 1)[-1]
        active_name = (
            name.endswith(".log")
            and not any(seg in name for seg in (".log.1", ".log.2", "archive", "-old"))
        )
        is_active = active_name and age_days < 1.0
        files.append(FileInfo(path=path, size_bytes=size, age_days=age_days, is_active_log=is_active))

    summary = f"{len(files)} files; largest = {files[0].size_bytes:,} bytes" if files else "no files"
    return files, ToolCall(
        tool="list_files",
        args={"host_id": host_id, "path": monitored_path},
        output_summary=summary,
    )


# ---------------------------------------------------------------------------
# search_runbooks: RAG retrieval against pgvector
# ---------------------------------------------------------------------------

def search_runbooks(query: str, top_k: int = 4) -> tuple[list[RetrievedDoc], ToolCall]:
    docs = rag_search(query, top_k=top_k)
    summary = f"{len(docs)} docs retrieved; top: {docs[0].title!r} ({docs[0].similarity:.2f})" if docs else "no docs"
    return docs, ToolCall(
        tool="search_runbooks",
        args={"query": query, "top_k": top_k},
        output_summary=summary,
    )


# ---------------------------------------------------------------------------
# Render helpers for prompt context
# ---------------------------------------------------------------------------

def format_file_listing(files: list[FileInfo]) -> str:
    if not files:
        return "(no files in monitored path)"
    lines = ["size_bytes\tage_days\tis_active\tpath"]
    for f in files[:30]:  # cap context
        active = "yes" if f.is_active_log else "no"
        lines.append(f"{f.size_bytes}\t{f.age_days:.1f}\t{active}\t{f.path}")
    if len(files) > 30:
        lines.append(f"... and {len(files) - 30} more (truncated)")
    return "\n".join(lines)


def format_runbook_context(docs: list[RetrievedDoc]) -> str:
    return format_for_prompt(docs)
