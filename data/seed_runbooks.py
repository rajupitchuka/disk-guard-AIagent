"""Seed the pgvector RAG corpus with synthetic runbooks + past-incident
records. The LLM agent retrieves relevant docs at reasoning time so its
decisions are grounded in playbook content rather than only its training
knowledge.

In production this would mirror the customer's actual ServiceNow KB +
runbook repository. For the POC we generate plausible content covering:
  - Linux disk-fill remediation (web/app/db roles)
  - Windows disk-fill remediation
  - Anomalous-growth incident reports (don't blindly clean)
  - Log rotation policies + retention requirements
  - Known-good cleanup procedures

Embeddings via sentence-transformers (all-MiniLM-L6-v2, 384-dim, local).
"""

from __future__ import annotations

import argparse
import logging
import uuid
from typing import Iterable

from pgvector.psycopg import register_vector
from sentence_transformers import SentenceTransformer

from shared.config import settings
from shared.db import pgvector_conn
from shared.logging_setup import setup_logging

log = logging.getLogger(__name__)


RUNBOOKS: list[dict] = [
    # ---- Linux: routine cleanup ---------------------------------------
    {
        "source": "runbook",
        "title": "Linux web server: /var/log cleanup",
        "metadata": {"role": "web", "os": "linux"},
        "content": (
            "When a Linux web server's /var/log directory exceeds 80% of disk capacity, "
            "the standard remediation is: (1) compress rotated nginx and apache access "
            "logs older than 7 days using gzip; (2) delete .log.1, .log.2 ... .log.N "
            "rotated files older than 14 days; (3) remove journalctl entries older than "
            "30 days via 'journalctl --vacuum-time=30d'. NEVER delete the active *.log "
            "files (e.g., access.log, error.log) — they are open file handles and only "
            "logrotate is allowed to manage them. Verify the cleanup freed enough space "
            "to bring usage below 70% before declaring resolution."
        ),
    },
    {
        "source": "runbook",
        "title": "Linux app server: /var/log/app archives cleanup",
        "metadata": {"role": "app", "os": "linux"},
        "content": (
            "Application servers writing to /var/log/app typically accumulate dated "
            "archive files (e.g., app-2025-03-archive.log, app-2025-Q1.log.gz). "
            "Standard cleanup: remove archive files (any file matching *-archive*.log* "
            "or dated quarter/month patterns) older than 30 days. Files matching "
            "*.log.gz can be removed if older than 21 days. The active app.log must "
            "never be touched. After cleanup, restart the application's logging "
            "subsystem only if specifically instructed by the on-call engineer."
        ),
    },
    {
        "source": "runbook",
        "title": "Linux database server: WAL and old query logs",
        "metadata": {"role": "db", "os": "linux"},
        "content": (
            "Database servers (PostgreSQL or similar) writing to /var/log/postgresql "
            "should NOT be cleaned without checking active connections first. Old "
            "postgresql-*.log files can be removed if older than 30 days AND there is "
            "no active replication slot referencing them. WAL files in pg_wal must "
            "NEVER be deleted manually — only PostgreSQL itself is allowed to recycle "
            "them. If pg_wal is consuming excessive space, this is an INCIDENT not a "
            "cleanup task — escalate to DBA team."
        ),
    },
    # ---- Windows ------------------------------------------------------
    {
        "source": "runbook",
        "title": "Windows server: C:\\Logs cleanup",
        "metadata": {"role": "any", "os": "windows"},
        "content": (
            "Windows servers store application and IIS logs under C:\\Logs and "
            "C:\\inetpub\\logs\\LogFiles. Safe targets for cleanup are: rotated files "
            "with .1, .2, .gz, or dated suffixes older than 14 days. The active .log "
            "files held open by the IIS process are locked by the OS and attempts to "
            "delete them fail; this is expected behavior. Use Get-Process to confirm "
            "no service holds an exclusive lock before attempting removal. After "
            "cleanup, run 'Get-EventLog' to verify no clear-log warnings were emitted."
        ),
    },
    # ---- Anomaly response ---------------------------------------------
    {
        "source": "runbook",
        "title": "Anomalous log growth: do not auto-clean",
        "metadata": {"category": "anomaly", "severity": "high"},
        "content": (
            "When monitoring detects that a single log file is growing far above its "
            "historical baseline (>3x the typical rate, or growing >1 GB/hour when "
            "normal rate is sub-100 MB/hour), DO NOT run routine cleanup. Such growth "
            "almost always indicates an upstream incident: a misconfigured logger, a "
            "tight retry loop, an exception storm, or a runaway process. Cleaning the "
            "logs masks the symptom and the disk fills up again within hours. The "
            "correct response is: (1) capture the file's tail for analysis, (2) open "
            "a high-priority incident in ServiceNow, (3) page the application team "
            "owning the service. Only proceed with cleanup if the application team "
            "explicitly approves it."
        ),
    },
    {
        "source": "past_incident",
        "title": "INC-2024-0817: app-prod-us-east0042 anomalous growth — debug logger left enabled after deploy",
        "metadata": {"category": "anomaly", "severity": "P2"},
        "content": (
            "On 2024-08-17 monitoring flagged a 12x growth-rate anomaly on "
            "app-prod-us-east0042's /var/log/app directory. Initial response was to "
            "cleanup the directory which restored disk to 35% used. Within 4 hours "
            "the disk filled again to 95%. Root cause: a deploy 6 hours earlier had "
            "left DEBUG logging enabled in a production code path generating ~800 MB "
            "of stack traces per hour. Lesson learned: when anomaly detector flags "
            "a host, cleanup is the WRONG response — escalate to the app team to "
            "investigate the upstream cause first."
        ),
    },
    # ---- Generic policy -----------------------------------------------
    {
        "source": "kb_article",
        "title": "Disk cleanup safety policy (TCS infra)",
        "metadata": {"policy_id": "DCS-001"},
        "content": (
            "Per TCS infrastructure policy, automated disk cleanup must observe these "
            "absolute rules: (1) NEVER delete files modified within the last 24 hours "
            "without explicit human approval; (2) NEVER delete files matching "
            "*.pid, *.sock, *.lock, or any active socket/lock files; (3) cleanup may "
            "free no more than 50 GB or 100 files in a single run without escalation; "
            "(4) every action must be logged with: file path, size, age, deletion "
            "reason; (5) if in doubt, escalate to the on-call engineer rather than "
            "delete. Violation of these rules is a P1 process violation and triggers "
            "automatic suspension of the automation."
        ),
    },
    {
        "source": "kb_article",
        "title": "Log retention requirements by environment",
        "metadata": {"policy_id": "LR-002"},
        "content": (
            "Production hosts must retain logs for 90 days (compliance requirement). "
            "Staging hosts retain for 30 days. Dev hosts retain for 7 days. These "
            "minimums apply REGARDLESS of disk pressure — if a production host has "
            "logs younger than 90 days, those logs are protected from automated "
            "cleanup. The disk-cleanup agent must verify the file's age against the "
            "host's environment tag before proposing deletion. A production host "
            "running out of disk with only protected logs to delete is an incident "
            "that requires either capacity expansion or an explicit retention waiver."
        ),
    },
    {
        "source": "runbook",
        "title": "Capacity expansion: when not to clean",
        "metadata": {"category": "capacity"},
        "content": (
            "If a host is running near capacity but its logs are all within retention "
            "policy, the right answer is capacity expansion — NOT cleanup. Indicators: "
            "(1) the host has been steadily growing for weeks, not suddenly jumping; "
            "(2) the largest files are all < retention age; (3) the workload is "
            "expected to continue. In this case, file an INFRA-CAPACITY ticket "
            "requesting volume expansion. Aggressive cleanup of within-retention logs "
            "to buy time is technically a compliance violation."
        ),
    },
    {
        "source": "runbook",
        "title": "Demo host fleet: standard log layouts",
        "metadata": {"environment": "demo"},
        "content": (
            "Demo and reference hosts in this fleet are configured with role-specific "
            "monitored paths: web servers monitor /var/log (nginx, apache, system "
            "logs); app servers monitor /var/log/app (application logs and rotated "
            "archives); db servers monitor /var/log/postgresql (database logs). "
            "Cleanup follows the role-specific runbook for that path."
        ),
    },
]


def _embed_batch(model: SentenceTransformer, texts: list[str]) -> list[list[float]]:
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embeddings.tolist()


def seed(model_name: str | None = None, batch_size: int = 32) -> int:
    name = model_name or settings.embedding_model
    log.info("loading embedding model %s", name)
    model = SentenceTransformer(name)

    texts = [r["content"] for r in RUNBOOKS]
    titles = [r["title"] for r in RUNBOOKS]
    log.info("embedding %d documents", len(texts))
    vectors = _embed_batch(model, texts)

    rows = [
        {
            "doc_id": f"doc-{uuid.uuid4().hex[:12]}",
            "source": r["source"],
            "title": r["title"],
            "content": r["content"],
            "metadata": __import__("json").dumps(r["metadata"]),
            "embedding": vec,
        }
        for r, vec in zip(RUNBOOKS, vectors)
    ]

    with pgvector_conn() as conn:
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("DELETE FROM knowledge_docs")  # idempotent reseed
            cur.executemany(
                """
                INSERT INTO knowledge_docs
                    (doc_id, source, title, content, metadata, embedding)
                VALUES
                    (%(doc_id)s, %(source)s, %(title)s, %(content)s,
                     %(metadata)s::jsonb, %(embedding)s)
                """,
                rows,
            )
        conn.commit()

    log.info("seeded %d runbooks/incidents into pgvector", len(rows))
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(prog="opsgpt-seed-runbooks")
    parser.add_argument("--model", help="Override embedding model")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    setup_logging(level=logging.DEBUG if args.verbose else logging.INFO)
    seed(model_name=args.model)


if __name__ == "__main__":
    main()
