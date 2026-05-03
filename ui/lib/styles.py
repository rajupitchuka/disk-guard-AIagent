"""Shared styling helpers for consistent badges + colors across pages."""

from __future__ import annotations

STATUS_COLORS = {
    "healthy": "#10b981",       # green
    "predictive": "#f59e0b",    # amber
    "anomalous": "#ef4444",     # red
    "critical": "#dc2626",      # dark red
    "no_prediction": "#9ca3af", # gray
}

STATUS_LABELS = {
    "healthy": "✅ Healthy",
    "predictive": "⏳ Predictive",
    "anomalous": "⚠️ Anomaly",
    "critical": "🚨 Critical",
    "no_prediction": "❔ No data",
}

DECISION_COLORS = {
    "auto_remediate": "#10b981",
    "opsgpt_chat": "#f59e0b",
    "ticket_only": "#3b82f6",
}

VERDICT_BADGES = {
    "cleaned": "🧹 Cleaned",
    "escalated_anomaly": "🚨 Escalated",
    "no_action_needed": "💤 No action",
}

SEVERITY_COLORS = {
    "P1": "#dc2626",  # dark red
    "P2": "#ef4444",  # red
    "P3": "#f59e0b",  # amber
    "P4": "#3b82f6",  # blue (informational)
}

TICKET_STATUS_COLORS = {
    "new": "#ef4444",
    "assigned": "#f59e0b",
    "in_progress": "#3b82f6",
    "resolved": "#10b981",
    "closed": "#6b7280",
}


def status_badge_html(status: str) -> str:
    color = STATUS_COLORS.get(status, "#9ca3af")
    label = STATUS_LABELS.get(status, status)
    return (
        f"<span style='background:{color}; color:white; padding:2px 8px; "
        f"border-radius:6px; font-size:0.85em; font-weight:600;'>{label}</span>"
    )


def action_summary(
    decision: str | None,
    verdict: str | None,
    files: int = 0,
    gb_freed: float = 0.0,
    ticket_id: str | None = None,
) -> str:
    """One-sentence plain-language explanation of what the agent actually
    did, since (decision, verdict) pairs aren't always self-explanatory —
    notably 'auto_remediate' + 'escalated_anomaly' (system auto-acted but
    by filing a ticket, NOT by cleaning files)."""
    decision = decision or ""
    verdict = verdict or ""
    ticket_str = f" Ticket: `{ticket_id}`." if ticket_id else ""

    if decision == "auto_remediate":
        if verdict == "cleaned":
            return (
                f"🧹 Auto-remediated by running the cleanup playbook — "
                f"{files} files deleted, {gb_freed:.2f} GB freed."
            )
        if verdict == "escalated_anomaly":
            return (
                "🚨 Auto-remediated by **filing a ServiceNow ticket** — "
                "playbook NOT run because the LLM flagged anomalous growth. "
                "Cleaning would have masked the upstream incident."
                + ticket_str
            )
        return "💤 Auto-remediated to no-op — the LLM saw no actionable signal."

    if decision == "opsgpt_chat":
        return "🤖 Routed to OpsGPT chat — pending human approval."

    if decision == "ticket_only":
        return (
            "📨 Routed to ticket-only path — confidence below the auto-remediate "
            "threshold." + ticket_str
        )

    return "—"
