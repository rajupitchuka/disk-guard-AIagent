"""Generate supporting diagrams for the Disk Guard whitepaper.

Outputs:
  - assets/figure_traditional_flow.png    — the problem (reactive monitoring)
  - assets/figure_predictive_flow.png     — the solution (Disk Guard)
  - assets/figure_timeline_comparison.png — side-by-side reactive vs predictive
  - assets/figure_agent_state_machine.png — LangGraph state machine

All pure matplotlib, no external graph tooling required.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Rectangle

ASSETS = Path(__file__).resolve().parent.parent / "assets"
ASSETS.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Shared styling
# ---------------------------------------------------------------------------
TEXT_DARK = "#0f172a"
TEXT_MUTED = "#475569"
EDGE = "#1e293b"

PALETTE = {
    "monitor":    ("#dbeafe", "#1d4ed8"),  # blue
    "alert":      ("#fee2e2", "#b91c1c"),  # red
    "ticket":     ("#fef3c7", "#b45309"),  # amber
    "engineer":   ("#e2e8f0", "#334155"),  # slate
    "auto":       ("#dcfce7", "#15803d"),  # green
    "outcome_bad":  ("#fef2f2", "#b91c1c"),  # red
    "outcome_good": ("#ecfdf5", "#059669"),  # green
    "ml":         ("#dbeafe", "#1d4ed8"),
    "llm":        ("#ede9fe", "#6d28d9"),
    "decision":   ("#fef3c7", "#b45309"),
    "remed":      ("#e2e8f0", "#334155"),
}


def fancy_box(ax, x, y, w, h, fill, edge, title, subtitle=None):
    p = FancyBboxPatch(
        (x, y), w, h,
        boxstyle="round,pad=0.0,rounding_size=0.6",
        linewidth=1.4, edgecolor=edge, facecolor=fill, zorder=3,
    )
    ax.add_patch(p)
    cy = y + h / 2 + (0.45 if subtitle else 0)
    ax.text(x + w / 2, cy, title, ha="center", va="center",
            fontsize=10, fontweight="bold", color=TEXT_DARK, zorder=4)
    if subtitle:
        ax.text(x + w / 2, y + h / 2 - 0.85, subtitle, ha="center", va="center",
                fontsize=8.4, color=TEXT_MUTED, style="italic", zorder=4)


def arrow(ax, x1, y1, x2, y2, label=None, color="#64748b", ls="-",
          curvature=0.0, label_offset=(0, 0.7), label_color=None,
          mutation=15, lw=1.6):
    a = FancyArrowPatch(
        (x1, y1), (x2, y2),
        arrowstyle="-|>", mutation_scale=mutation,
        linewidth=lw, color=color, linestyle=ls,
        connectionstyle=f"arc3,rad={curvature}",
        zorder=4,
    )
    ax.add_patch(a)
    if label:
        mx, my = (x1 + x2) / 2 + label_offset[0], (y1 + y2) / 2 + label_offset[1]
        ax.text(
            mx, my, label,
            ha="center", va="center", fontsize=8.4,
            color=label_color or TEXT_MUTED, style="italic",
            bbox=dict(facecolor="white", edgecolor="none", pad=2),
            zorder=5,
        )


# ===========================================================================
# Figure 1 — Traditional reactive flow
# ===========================================================================
def fig_traditional_flow():
    fig, ax = plt.subplots(figsize=(14, 6), dpi=120)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 40)
    ax.axis("off")
    ax.set_aspect("equal")

    fig.suptitle(
        "Figure 1 — Traditional Reactive Disk Monitoring (Today's Practice)",
        fontsize=15, fontweight="bold", color=TEXT_DARK, y=0.97,
    )
    fig.text(0.5, 0.91,
             "Monitoring tool detects threshold breach → alert → ticket → manual or automated cleanup. "
             "All action happens AFTER the disk is already in trouble.",
             ha="center", fontsize=10, color=TEXT_MUTED, style="italic")

    # Main flow boxes
    f, e = PALETTE["monitor"]
    fancy_box(ax, 4, 18, 18, 8, f, e, "Server Telemetry",
              "Windows · Linux · /var/log · C:\\Logs")

    fancy_box(ax, 26, 18, 18, 8, f, e, "Monitoring Tool",
              "SCOM · Datadog · Nagios")

    f, e = PALETTE["alert"]
    fancy_box(ax, 48, 18, 18, 8, f, e, "Threshold Alert",
              "fires at 85% / 90% only")

    f, e = PALETTE["ticket"]
    fancy_box(ax, 70, 23, 12, 5, f, e, "Incident Ticket")

    f, e = PALETTE["engineer"]
    fancy_box(ax, 70, 16, 12, 5, f, e, "Auto-cleanup")

    f, e = PALETTE["outcome_bad"]
    fancy_box(ax, 87, 18, 11, 8, f, e, "OUTAGE",
              "if disk filled\nbefore threshold")

    # Arrows
    arrow(ax, 22, 22, 26, 22)
    arrow(ax, 44, 22, 48, 22)
    arrow(ax, 66, 23, 70, 25, label="P1 incident")
    arrow(ax, 66, 22, 70, 18, label="if instrumented")
    arrow(ax, 82, 25, 87, 23,
          label="anomalous fast-fill\n(missed by threshold)",
          color="#b91c1c", curvature=0.15, label_offset=(2.2, 1.2),
          label_color="#b91c1c", lw=2.0)
    arrow(ax, 82, 18, 87, 21,
          label="too late",
          color="#b91c1c", curvature=-0.15, label_offset=(0, -0.7),
          label_color="#b91c1c", lw=2.0)

    # Time annotation
    ax.annotate(
        "", xy=(78, 6), xytext=(8, 6),
        arrowprops=dict(arrowstyle="->", color="#94a3b8", lw=1.3),
    )
    ax.text(43, 4.4, "TIME", ha="center", fontsize=9, color=TEXT_MUTED,
            style="italic", fontweight="bold")
    ax.text(8, 8.5, "T₀\nDisk healthy", ha="left", fontsize=8.5,
            color=TEXT_MUTED, style="italic")
    ax.text(43, 8.5, "T+hours\nThreshold breached",
            ha="center", fontsize=8.5, color=TEXT_MUTED, style="italic")
    ax.text(78, 8.5, "T+min\nResponse begins", ha="center", fontsize=8.5,
            color=TEXT_MUTED, style="italic")

    plt.savefig(ASSETS / "figure_traditional_flow.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    print(f"  ✓ figure_traditional_flow.png")


# ===========================================================================
# Figure 2 — Disk Guard predictive flow (single-host view)
# ===========================================================================
def fig_predictive_flow():
    fig, ax = plt.subplots(figsize=(15, 7), dpi=120)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 50)
    ax.axis("off")
    ax.set_aspect("equal")

    fig.suptitle(
        "Figure 2 — Disk Guard Predictive Flow (Single-Host View)",
        fontsize=15, fontweight="bold", color=TEXT_DARK, y=0.97,
    )
    fig.text(0.5, 0.92,
             "Continuous telemetry · ML predicts trajectory · LLM reasons "
             "with RAG · Decision Engine routes by confidence. "
             "Action triggered BEFORE threshold is reached.",
             ha="center", fontsize=10.5, color=TEXT_MUTED, style="italic")

    # Main flow
    f, e = PALETTE["monitor"]
    fancy_box(ax, 3, 28, 16, 8, f, e, "Continuous Telemetry",
              "every 5 min · all hosts")

    f, e = PALETTE["ml"]
    fancy_box(ax, 22, 28, 19, 8, f, e, "ML Engine (every 15 min)",
              "Prophet forecast + XGBoost anomaly")

    f, e = PALETTE["llm"]
    fancy_box(ax, 44, 28, 22, 8, f, e, "LLM Agent (LangGraph)",
              "Claude · RAG · sanitizer · structured output")

    f, e = PALETTE["decision"]
    fancy_box(ax, 69, 28, 16, 8, f, e, "Decision Engine",
              "confidence score 0–1")

    # Trigger condition (label ABOVE the boxes so it doesn't collide with text)
    arrow(ax, 19, 32, 22, 32)
    arrow(ax, 41, 32, 44, 32,
          label="if forecast ≥ 90% in 7 d  OR  anomaly_score ≥ 0.6",
          color=PALETTE["ml"][1], label_offset=(0, 6),
          label_color=PALETTE["ml"][1])
    arrow(ax, 66, 32, 69, 32,
          label="reasoning + recommendation",
          color=PALETTE["llm"][1], label_offset=(0, 6),
          label_color=PALETTE["llm"][1])

    # Three routes (fan-out)
    f, e = PALETTE["auto"]
    fancy_box(ax, 88, 39, 11, 5, f, e, "Auto-remediate",
              "playbook")

    f, e = PALETTE["llm"]
    fancy_box(ax, 88, 30, 11, 5, f, e, "Chatbot",
              "human approval")

    f, e = ("#dbeafe", "#1d4ed8")
    fancy_box(ax, 88, 21, 11, 5, f, e, "ServiceNow",
              "P1–P4 ticket")

    arrow(ax, 85, 33, 88, 41, label="≥ 0.85", color="#15803d",
          label_color="#15803d", curvature=-0.18, label_offset=(2.5, 0.3))
    arrow(ax, 85, 32, 88, 32.5, label="0.75 – 0.85", color="#b45309",
          label_color="#b45309", label_offset=(0, 0.9))
    arrow(ax, 85, 31, 88, 23.5, label="< 0.75", color="#1d4ed8",
          label_color="#1d4ed8", curvature=0.18, label_offset=(2.5, -0.3))

    # Outcome
    f, e = PALETTE["outcome_good"]
    fancy_box(ax, 36, 5, 30, 7, f, e,
              "DISK STAYS HEALTHY",
              "Action taken hours/days BEFORE the breach")

    arrow(ax, 51, 28, 51, 12, color=PALETTE["outcome_good"][1],
          ls="--", lw=2.0)

    # Time arrow
    ax.text(50, 18.5, "Continuous loop — runs every 15 min for every host",
            ha="center", fontsize=9, color=TEXT_MUTED, style="italic",
            fontweight="bold")

    plt.savefig(ASSETS / "figure_predictive_flow.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    print(f"  ✓ figure_predictive_flow.png")


# ===========================================================================
# Figure 3 — Timeline comparison
# ===========================================================================
def fig_timeline_comparison():
    fig, ax = plt.subplots(figsize=(15, 8), dpi=120)
    ax.set_xlim(-2, 100)
    ax.set_ylim(0, 60)
    ax.axis("off")

    fig.suptitle(
        "Figure 3 — Reactive vs Predictive: Timeline Comparison",
        fontsize=15, fontweight="bold", color=TEXT_DARK, y=0.97,
    )
    fig.text(0.5, 0.92,
             "Same incident scenario: a logger bug starts filling /var/log "
             "at an unusually fast rate. How each approach handles it.",
             ha="center", fontsize=10.5, color=TEXT_MUTED, style="italic")

    # Two parallel timelines
    # Top: REACTIVE (traditional)
    ax.text(-1, 55, "TRADITIONAL (Reactive)", fontsize=12,
            fontweight="bold", color=PALETTE["alert"][1])
    # axis line
    ax.plot([0, 96], [48, 48], color="#94a3b8", lw=1.5)
    for x in [0, 24, 48, 72, 96]:
        ax.plot([x, x], [47, 49], color="#94a3b8", lw=1.5)

    ax.text(0, 41, "T₀\nbug starts",
            ha="center", va="top", fontsize=8.5, color=TEXT_MUTED)
    ax.text(24, 41, "T+6h\ndisk 70%\n(below threshold)",
            ha="center", va="top", fontsize=8.5, color=TEXT_MUTED)
    ax.text(48, 41, "T+8h\nALERT @ 90%",
            ha="center", va="top", fontsize=8.5,
            color=PALETTE["alert"][1], fontweight="bold")
    ax.text(72, 41, "T+8h:15\nticket assigned",
            ha="center", va="top", fontsize=8.5, color=TEXT_MUTED)
    ax.text(96, 41, "T+9h\nDISK FULL\nOUTAGE",
            ha="center", va="top", fontsize=8.5,
            color=PALETTE["alert"][1], fontweight="bold")

    # Markers
    for x, color in [(0, "#94a3b8"), (24, "#94a3b8"),
                     (48, PALETTE["alert"][1]),
                     (72, "#94a3b8"),
                     (96, PALETTE["alert"][1])]:
        ax.scatter([x], [48], s=80, color=color, zorder=5,
                   edgecolor="white", linewidth=1.5)

    # Outage region
    ax.fill_betweenx([46, 50], 90, 96, color=PALETTE["alert"][1], alpha=0.2)

    # Bottom: PREDICTIVE
    ax.text(-1, 33, "DISK GUARD (Predictive)", fontsize=12,
            fontweight="bold", color=PALETTE["outcome_good"][1])
    ax.plot([0, 96], [26, 26], color="#94a3b8", lw=1.5)
    for x in [0, 24, 48, 72, 96]:
        ax.plot([x, x], [25, 27], color="#94a3b8", lw=1.5)

    ax.text(0, 19, "T₀\nbug starts",
            ha="center", va="top", fontsize=8.5, color=TEXT_MUTED)
    ax.text(24, 19, "T+15min\nXGBoost flags\nanomaly_score=0.99",
            ha="center", va="top", fontsize=8.5,
            color=PALETTE["llm"][1], fontweight="bold")
    ax.text(48, 19, "T+20min\nLLM cites past\nincident, escalates",
            ha="center", va="top", fontsize=8.5,
            color=PALETTE["llm"][1], fontweight="bold")
    ax.text(72, 19, "T+25min\nP2 ticket filed\nApp team paged",
            ha="center", va="top", fontsize=8.5, color=TEXT_MUTED)
    ax.text(96, 19, "T+1h\nbug fixed\nNO OUTAGE",
            ha="center", va="top", fontsize=8.5,
            color=PALETTE["outcome_good"][1], fontweight="bold")

    for x, color in [(0, "#94a3b8"),
                     (24, PALETTE["llm"][1]),
                     (48, PALETTE["llm"][1]),
                     (72, "#94a3b8"),
                     (96, PALETTE["outcome_good"][1])]:
        ax.scatter([x], [26], s=80, color=color, zorder=5,
                   edgecolor="white", linewidth=1.5)

    ax.fill_betweenx([24, 28], 90, 96, color=PALETTE["outcome_good"][1],
                      alpha=0.2)

    # Outcome boxes
    f, e = PALETTE["outcome_bad"]
    fancy_box(ax, 28, 5, 30, 8, f, e,
              "Reactive: outage, customer impact",
              "rolling back, post-mortem, downtime")

    f, e = PALETTE["outcome_good"]
    fancy_box(ax, 62, 5, 32, 8, f, e,
              "Predictive: incident contained early",
              "no customer impact, root cause fixed")

    plt.savefig(ASSETS / "figure_timeline_comparison.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    print(f"  ✓ figure_timeline_comparison.png")


# ===========================================================================
# Figure 4 — LangGraph state machine
# ===========================================================================
def fig_agent_state_machine():
    fig, ax = plt.subplots(figsize=(16, 5), dpi=120)
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 30)
    ax.axis("off")
    ax.set_aspect("equal")

    fig.suptitle(
        "Figure 4 — LLM Agent State Machine (LangGraph)",
        fontsize=15, fontweight="bold", color=TEXT_DARK, y=0.95,
    )
    fig.text(0.5, 0.87,
             "Six-node directed graph. Reasoning subgraph (nodes 1–4) runs "
             "without side effects; Resolve subgraph (5–6) commits action.",
             ha="center", fontsize=10, color=TEXT_MUTED, style="italic")

    nodes = [
        (4,   "1. fetch_context",   "host meta\nML pred · file list", "#dbeafe", "#1d4ed8"),
        (20,  "2. sanitize",        "PII + creds regex", "#dbeafe", "#1d4ed8"),
        (36,  "3. reason",          "Claude · RAG · JSON output", "#ede9fe", "#6d28d9"),
        (52,  "4. decide",          "confidence score · route", "#ede9fe", "#6d28d9"),
        (68,  "5. execute_or_skip", "playbook (auto-rem only)", "#fef3c7", "#b45309"),
        (84,  "6. audit",           "agent_runs · ticket", "#fef3c7", "#b45309"),
    ]

    for x, title, sub, fill, edge in nodes:
        fancy_box(ax, x, 11, 13, 8, fill, edge, title, sub)

    # Edges
    for x_from in [4, 20, 36, 52, 68]:
        arrow(ax, x_from + 13, 15, x_from + 16, 15)

    # Subgraph annotations
    ax.add_patch(Rectangle(
        (3, 9), 51, 12, fill=False, edgecolor="#6d28d9", lw=1.6,
        linestyle="--", zorder=2,
    ))
    ax.text(28.5, 22, "Reasoning subgraph (no side effects)",
            ha="center", fontsize=9, color="#6d28d9", fontweight="bold",
            style="italic")

    ax.add_patch(Rectangle(
        (67, 9), 30, 12, fill=False, edgecolor="#b45309", lw=1.6,
        linestyle="--", zorder=2,
    ))
    ax.text(82, 22, "Resolve subgraph (commits action)",
            ha="center", fontsize=9, color="#b45309", fontweight="bold",
            style="italic")

    plt.savefig(ASSETS / "figure_agent_state_machine.png", dpi=150,
                bbox_inches="tight", facecolor="white")
    print(f"  ✓ figure_agent_state_machine.png")


def main() -> None:
    print(f"Generating diagrams to {ASSETS}/")
    fig_traditional_flow()
    fig_predictive_flow()
    fig_timeline_comparison()
    fig_agent_state_machine()
    print("done.")


if __name__ == "__main__":
    main()
