"""Per-role cleanup playbooks. Each playbook returns a list of *candidate*
deletion patterns; the executor walks the host's monitored path, matches
files, applies safety guards, and deletes the survivors.

Playbooks are role-specific because the right cleanup differs by what the
host writes to its monitored path. The runbook RAG corpus encodes the same
domain knowledge for the LLM; this module encodes it for the executor.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CleanupRule:
    """A single rule: pattern + minimum age. Files matching the glob and
    older than min_age_days are candidates for deletion."""
    glob: str
    min_age_days: float
    description: str


@dataclass(frozen=True)
class Playbook:
    role: str
    rules: tuple[CleanupRule, ...]


# Web servers: nginx/apache rotated logs
WEB_PLAYBOOK = Playbook(
    role="web",
    rules=(
        CleanupRule(
            glob="*.log.[0-9]*",
            min_age_days=14,
            description="rotated nginx/apache logs (.log.1, .log.2, etc.)",
        ),
        CleanupRule(
            glob="*.log.gz",
            min_age_days=21,
            description="gzipped rotated logs",
        ),
        CleanupRule(
            glob="*-archive-*.log*",
            min_age_days=14,
            description="explicitly-archived web logs",
        ),
    ),
)


APP_PLAYBOOK = Playbook(
    role="app",
    rules=(
        CleanupRule(
            glob="*-archive-*.log*",
            min_age_days=30,
            description="application archive files",
        ),
        CleanupRule(
            glob="*.log.gz",
            min_age_days=21,
            description="gzipped application logs",
        ),
        CleanupRule(
            glob="*.log.[0-9]*",
            min_age_days=14,
            description="rotated application logs",
        ),
        CleanupRule(
            glob="junk-*.bin",
            min_age_days=0,
            description="demo 'fill disk' artifacts (POC only)",
        ),
    ),
)


DB_PLAYBOOK = Playbook(
    role="db",
    rules=(
        CleanupRule(
            glob="postgresql-*.log",
            min_age_days=30,
            description="old postgresql query logs",
        ),
        CleanupRule(
            glob="postgresql-*.log.gz",
            min_age_days=30,
            description="gzipped postgresql logs",
        ),
        # Notably absent: pg_wal/* — never auto-clean WAL
        CleanupRule(
            glob="junk-*.bin",
            min_age_days=0,
            description="demo 'fill disk' artifacts (POC only)",
        ),
    ),
)


PLAYBOOKS: dict[str, Playbook] = {
    "web": WEB_PLAYBOOK,
    "app": APP_PLAYBOOK,
    "db": DB_PLAYBOOK,
}


def get_playbook(role: str) -> Playbook:
    if role in PLAYBOOKS:
        return PLAYBOOKS[role]
    # Fall back to app playbook as a sane default for unknown roles
    return APP_PLAYBOOK
