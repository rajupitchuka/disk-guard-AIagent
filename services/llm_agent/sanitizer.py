"""Data Sanitizer — strips PII, credentials, and other sensitive content from
text before it reaches the LLM (or leaves the network boundary).

This is a regex-based first line of defense; production deployments should
layer this with content-aware DLP. The patterns here cover the high-value
targets that show up in IT-Ops telemetry and runbook excerpts: API keys,
auth tokens, passwords in command-line args, IP/MAC addresses, email,
filesystem-credential paths, URLs with embedded credentials.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Order matters: more specific patterns first so a generic substring rule
# doesn't pre-empt a structured one.
PATTERNS: list[tuple[str, re.Pattern]] = [
    # Long bearer-style tokens / API keys
    ("AWS_ACCESS_KEY", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("AWS_SECRET", re.compile(r"\b(?:[A-Za-z0-9/+=]{40})\b(?=[^A-Za-z0-9/+=]|$)")),
    ("GHP_TOKEN", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("GHO_TOKEN", re.compile(r"\bgho_[A-Za-z0-9]{36}\b")),
    ("ANTHROPIC_KEY", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{20,}\b")),
    ("OPENAI_KEY", re.compile(r"\bsk-[A-Za-z0-9]{20,}\b")),
    ("GENERIC_BEARER", re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._\-]{20,}\b")),
    ("BASIC_AUTH", re.compile(r"(?i)\bBasic\s+[A-Za-z0-9+/=]{20,}\b")),
    # Embedded credentials in URLs: https://user:pass@host
    ("URL_CRED", re.compile(r"\b[a-z]+://[^\s/:@]+:[^\s/@]+@")),
    # Password-like flags
    ("PASSWORD_FLAG", re.compile(r"(?i)(?:--?password|--?pass|-p)[ =]\S+")),
    # Private keys
    ("PRIVATE_KEY", re.compile(r"-----BEGIN [A-Z ]+PRIVATE KEY-----[\s\S]+?-----END [A-Z ]+PRIVATE KEY-----")),
    # Email
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    # IPv4
    ("IPV4", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\b")),
    # MAC
    ("MAC", re.compile(r"\b(?:[0-9A-Fa-f]{2}[:\-]){5}[0-9A-Fa-f]{2}\b")),
]


@dataclass
class SanitizationResult:
    sanitized: str
    redactions: dict[str, int]  # category -> count

    @property
    def total_redactions(self) -> int:
        return sum(self.redactions.values())


def sanitize(text: str) -> SanitizationResult:
    """Replace each match with a category-tagged placeholder. Counts per
    category so callers can audit / surface to the UI."""
    counts: dict[str, int] = {}
    out = text
    for name, pattern in PATTERNS:
        def _repl(_m: re.Match[str], _n: str = name) -> str:
            counts[_n] = counts.get(_n, 0) + 1
            return f"[REDACTED:{_n}]"
        out = pattern.sub(_repl, out)
    return SanitizationResult(sanitized=out, redactions=counts)


def sanitize_dict(d: dict, fields: list[str] | None = None) -> tuple[dict, dict[str, int]]:
    """Sanitize selected string fields in a dict. If `fields` is None,
    every string value is sanitized. Returns the new dict + total counts."""
    counts: dict[str, int] = {}
    out: dict = {}
    for k, v in d.items():
        if isinstance(v, str) and (fields is None or k in fields):
            r = sanitize(v)
            out[k] = r.sanitized
            for cat, n in r.redactions.items():
                counts[cat] = counts.get(cat, 0) + n
        else:
            out[k] = v
    return out, counts
