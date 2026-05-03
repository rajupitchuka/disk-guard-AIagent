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
    "agentask": "#f59e0b",
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
