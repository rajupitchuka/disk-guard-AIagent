"""Generate a clean architecture diagram PNG for README + LinkedIn.

Pure matplotlib (no external graphviz / mermaid dependency). Produces
assets/architecture.png at 1920x1280, suitable for LinkedIn posts and
README hero image.

Run:
    python scripts/generate_architecture_diagram.py
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch

OUT = Path(__file__).resolve().parent.parent / "assets" / "architecture.png"
OUT.parent.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Color palette — accessible, calm, professional.
# ---------------------------------------------------------------------------
ZONE_COLORS = {
    "data":       ("#dbeafe", "#1d4ed8"),  # blue-100, blue-700
    "agent":      ("#ede9fe", "#6d28d9"),  # violet-100, violet-700
    "governance": ("#fef3c7", "#b45309"),  # amber-100, amber-700
    "infra":      ("#e2e8f0", "#334155"),  # slate-200, slate-700
}
TEXT_DARK = "#0f172a"   # slate-900
TEXT_MUTED = "#475569"  # slate-600
ARROW_COLOR = "#64748b"


def zone(ax, x, y, w, h, name, fill, edge):
    """Background rectangle for a zone with a heading band."""
    bg = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.0,rounding_size=1.0",
        linewidth=2.0, edgecolor=edge, facecolor=fill, alpha=0.55,
        zorder=1,
    )
    ax.add_patch(bg)
    # heading band (top strip)
    ax.text(
        x + 1.2, y + h - 1.6, name,
        fontsize=12, fontweight="bold", color=edge, zorder=3,
    )


def box(ax, x, y, w, h, title, subtitle=None, accent="#1e293b"):
    """A component box with title + optional subtitle."""
    rect = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.0,rounding_size=0.6",
        linewidth=1.2, edgecolor=accent, facecolor="white",
        zorder=2,
    )
    ax.add_patch(rect)
    cy = y + h / 2 + (0.4 if subtitle else 0)
    ax.text(
        x + w / 2, cy, title,
        ha="center", va="center",
        fontsize=10, fontweight="bold", color=TEXT_DARK, zorder=3,
    )
    if subtitle:
        ax.text(
            x + w / 2, y + h / 2 - 0.85, subtitle,
            ha="center", va="center",
            fontsize=8.2, color=TEXT_MUTED, zorder=3, style="italic",
        )


def arrow(ax, x1, y1, x2, y2, label=None, color=ARROW_COLOR, ls="-",
          curvature=0.0, label_offset=(0, 0.6), label_color=None):
    """Curved arrow with optional label."""
    a = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=15,
        linewidth=1.5, color=color, linestyle=ls,
        connectionstyle=f"arc3,rad={curvature}",
        zorder=4,
    )
    ax.add_patch(a)
    if label:
        mx, my = (x1 + x2) / 2 + label_offset[0], (y1 + y2) / 2 + label_offset[1]
        ax.text(
            mx, my, label,
            ha="center", va="center", fontsize=8.5,
            color=label_color or TEXT_MUTED, style="italic",
            bbox=dict(facecolor="white", edgecolor="none", pad=2),
            zorder=5,
        )


def main() -> None:
    fig, ax = plt.subplots(figsize=(16, 10.5), dpi=120)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 70)
    ax.axis("off")
    ax.set_aspect("equal")

    # ---- Title -----------------------------------------------------------
    fig.suptitle(
        "Disk Guard AI Agent — Architecture",
        fontsize=24, fontweight="bold", color=TEXT_DARK, y=0.97,
    )
    fig.text(
        0.5, 0.93,
        "Predictive disk-failure detection · ML forecasting · LLM reasoning · Confidence-gated remediation",
        ha="center", fontsize=12, color=TEXT_MUTED, style="italic",
    )

    # ---- ZONE 1: Data Layer ---------------------------------------------
    z1_fill, z1_edge = ZONE_COLORS["data"]
    zone(ax, 5, 50, 90, 14, "ZONE 1 · DATA LAYER", z1_fill, z1_edge)

    box(ax, 8, 53, 16, 7, "Datadog Telemetry",
        "5-min cadence · 53 hosts", accent=z1_edge)
    box(ax, 28, 53, 16, 7, "Ingestion Service",
        "APScheduler · normalize · DB write", accent=z1_edge)
    box(ax, 48, 53, 18, 7, "TimescaleDB Hypertable",
        "30-day retention · in_use_pct", accent=z1_edge)
    box(ax, 70, 53, 22, 7, "ML Engine (every 15 min)",
        "Prophet forecast (1/3/7/14d) · XGBoost anomaly", accent=z1_edge)

    # Internal arrows in Zone 1
    arrow(ax, 24, 56.5, 28, 56.5, color=z1_edge)
    arrow(ax, 44, 56.5, 48, 56.5, color=z1_edge)
    arrow(ax, 66, 56.5, 70, 56.5, color=z1_edge)

    # ---- ZONE 2: AI Agent Layer -----------------------------------------
    z2_fill, z2_edge = ZONE_COLORS["agent"]
    zone(ax, 5, 32, 90, 14, "ZONE 2 · AI AGENT LAYER", z2_fill, z2_edge)

    box(ax, 8, 35, 16, 7, "Data Sanitizer",
        "PII + credentials regex", accent=z2_edge)
    box(ax, 28, 35, 22, 7, "LLM Agent (LangGraph)",
        "Claude Haiku 4.5 · structured JSON", accent=z2_edge)
    box(ax, 54, 35, 18, 7, "RAG Retrieval",
        "pgvector · cosine sim · runbooks", accent=z2_edge)
    box(ax, 76, 35, 16, 7, "Reasoning + Decision",
        "ServiceNow KB grounded", accent=z2_edge)

    arrow(ax, 24, 38.5, 28, 38.5, color=z2_edge)
    arrow(ax, 50, 38.5, 54, 38.5, color=z2_edge)
    arrow(ax, 72, 38.5, 76, 38.5, color=z2_edge)

    # Trigger: ML → Agent (only when forecast ≥ 90% in 7d, or anomaly)
    arrow(
        ax, 81, 53, 50, 42,
        label="trigger: forecast ≥ 90% in 7 d  OR  anomaly_score ≥ 0.6",
        color=z1_edge, ls="-", curvature=-0.15, label_offset=(2, 1.2),
        label_color=z1_edge,
    )

    # ---- ZONE 3: Governance Layer ---------------------------------------
    z3_fill, z3_edge = ZONE_COLORS["governance"]
    zone(ax, 5, 14, 90, 14, "ZONE 3 · GOVERNANCE LAYER", z3_fill, z3_edge)

    box(ax, 8, 17, 22, 7, "Decision Engine",
        "LLM 40% · ML 30% · RAG 15% · Env 15%", accent=z3_edge)
    box(ax, 36, 19.5, 17, 6, "Auto-remediate",
        "playbook · SSH/PowerShell", accent="#15803d")
    box(ax, 56, 19.5, 17, 6, "Chatbot Approval",
        "human-in-the-loop", accent="#b45309")
    box(ax, 76, 19.5, 16, 6, "ServiceNow Ticket",
        "P1 / P2 / P3 / P4", accent="#1d4ed8")

    arrow(ax, 30, 22, 36, 22.5, color=z3_edge)
    # Score-based fan-out from Decision Engine (labels under each route)
    ax.text(33, 25.5, "score → route", fontsize=8.4, color=TEXT_MUTED, style="italic")
    ax.text(44.5, 18.6, "≥ 0.85", fontsize=8.5, color="#15803d", fontweight="bold", ha="center")
    ax.text(64.5, 18.6, "0.75 – 0.85", fontsize=8.5, color="#b45309", fontweight="bold", ha="center")
    ax.text(84,   18.6, "< 0.75", fontsize=8.5, color="#1d4ed8", fontweight="bold", ha="center")

    # Agent → Decision Engine
    arrow(ax, 84, 35, 19, 24.5,
          label="reasoning + LLM rec",
          color=z2_edge, ls="-", curvature=-0.18, label_offset=(0, 1.0),
          label_color=z2_edge)

    # ---- ZONE 4: Infrastructure ----------------------------------------
    z4_fill, z4_edge = ZONE_COLORS["infra"]
    zone(ax, 5, 1, 90, 9, "ZONE 4 · INFRASTRUCTURE", z4_fill, z4_edge)

    box(ax, 12, 3, 22, 5, "pgvector",
        "RAG corpus · runbooks + past incidents", accent=z4_edge)
    box(ax, 40, 3, 22, 5, "Redis",
        "state · dedup · agent cache", accent=z4_edge)
    box(ax, 68, 3, 22, 5, "TimescaleDB",
        "telemetry hypertable · audit", accent=z4_edge)

    # Footer
    fig.text(
        0.5, 0.025,
        "Stack: Python · LangGraph · Claude API · Prophet · XGBoost · "
        "TimescaleDB · pgvector · Redis · Streamlit · Docker",
        ha="center", fontsize=9.5, color=TEXT_MUTED, style="italic",
    )

    plt.savefig(OUT, dpi=150, bbox_inches="tight",
                facecolor="white", edgecolor="none")
    print(f"✓ wrote {OUT} ({OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
