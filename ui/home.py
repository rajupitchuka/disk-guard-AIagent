"""OpsGPT Streamlit UI — Fleet Overview (entry page).

Run with: streamlit run ui/home.py
"""

from __future__ import annotations

import os
# Prophet (cmdstanpy) and sentence-transformers (torch) both load OpenMP on
# macOS Apple Silicon, and the runtime can segfault on duplicate-library
# detection. Setting these BEFORE any imports keeps the demo stable.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import sys
from pathlib import Path

# Make `shared`, `services`, and `data` importable when streamlit invokes this
# file directly (without the project root on sys.path).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.express as px
import streamlit as st

from ui.lib.data import (
    fetch_agent_runs,
    fetch_tickets,
    fleet_overview,
    invalidate_caches,
)
from ui.lib.styles import STATUS_COLORS, STATUS_LABELS

st.set_page_config(
    page_title="OpsGPT — Fleet",
    page_icon="🛰️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("OpsGPT POC")
    st.caption("Predictive disk-management • InnoVista 2026")
    st.markdown("---")
    if st.button("🔄 Refresh data", use_container_width=True):
        invalidate_caches()
        st.rerun()
    st.markdown("---")
    st.markdown(
        "**Pages**\n\n"
        "🛰️ Fleet Overview (here)\n\n"
        "🖥️ Host Detail\n\n"
        "🤖 OpsGPT\n\n"
        "📋 Audit Trail\n\n"
        "📨 Tickets"
    )


# ---------------------------------------------------------------------------
# Header + metrics
# ---------------------------------------------------------------------------
st.title("🛰️ Fleet Overview")
st.caption(
    "OpsGPT POC — predictive disk-management across the demo fleet. "
    "Tile color reflects the latest status; click 'Open' to drill in."
)

df = fleet_overview()
if df.empty:
    st.warning("No hosts in the database. Run the seed scripts first.")
    st.stop()

total = len(df)
triggered = int(df["triggered_agent"].fillna(False).sum())
anomalous = int((df["anomaly_score"].fillna(0) >= 0.6).sum())
breach_in_7d = int(((df["forecast_7d_pct"].fillna(0) >= 90)).sum())
demo_count = int(df["is_demo_host"].sum())

tickets_open = 0
tickets_p1p2 = 0
try:
    _t = fetch_tickets(limit=500)
    if not _t.empty:
        tickets_open = int((~_t["status"].isin(["resolved", "closed"])).sum())
        tickets_p1p2 = int(_t["severity"].isin(["P1", "P2"]).sum())
except Exception:
    pass

c1, c2, c3, c4, c5, c6 = st.columns(6)
c1.metric("Total hosts", f"{total}")
c2.metric("Real demo containers", f"{demo_count}")
c3.metric("Triggered (need agent)", f"{triggered}")
c4.metric("Anomalous", f"{anomalous}")
c5.metric("Breach ≤ 7d", f"{breach_in_7d}")
c6.metric("Open tickets", f"{tickets_open}",
          delta=f"{tickets_p1p2} P1+P2" if tickets_p1p2 else None,
          delta_color="inverse")

st.markdown("---")


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
with st.expander("Filters", expanded=False):
    col1, col2, col3, col4 = st.columns(4)
    role_filter = col1.multiselect("Role", sorted(df["role"].unique().tolist()))
    env_filter = col2.multiselect("Environment", sorted(df["environment"].unique().tolist()))
    status_filter = col3.multiselect("Status", list(STATUS_COLORS.keys()))
    show_demo_only = col4.checkbox("Demo containers only", value=False)

filtered = df.copy()
if role_filter:
    filtered = filtered[filtered["role"].isin(role_filter)]
if env_filter:
    filtered = filtered[filtered["environment"].isin(env_filter)]
if status_filter:
    filtered = filtered[filtered["status"].isin(status_filter)]
if show_demo_only:
    filtered = filtered[filtered["is_demo_host"]]


# ---------------------------------------------------------------------------
# Fleet scatter — anomaly score vs forecast, colored by status
# ---------------------------------------------------------------------------
st.subheader("Fleet status — anomaly vs forecast")
chart_df = filtered.dropna(subset=["anomaly_score", "forecast_7d_pct"]).copy()
if chart_df.empty:
    st.info("No predictions yet — run the ML cycle first.")
else:
    fig = px.scatter(
        chart_df,
        x="anomaly_score",
        y="forecast_7d_pct",
        color="status",
        color_discrete_map=STATUS_COLORS,
        size=chart_df["total_disk_gb"].fillna(100).clip(lower=50),
        hover_name="host_id",
        hover_data={
            "hostname": True, "role": True, "environment": True,
            "in_use_pct": ":.1f", "hours_to_90pct": ":.1f",
            "anomaly_score": ":.3f", "forecast_7d_pct": ":.1f",
            "total_disk_gb": False, "status": False,
        },
        labels={
            "anomaly_score": "XGBoost anomaly score",
            "forecast_7d_pct": "Prophet 7-day forecast (%)",
        },
        height=420,
    )
    fig.add_hline(y=90, line_dash="dash", line_color="#ef4444",
                  annotation_text="90% breach line", annotation_position="top right")
    fig.add_vline(x=0.6, line_dash="dash", line_color="#f59e0b",
                  annotation_text="anomaly threshold", annotation_position="top right")
    fig.update_layout(margin=dict(t=20, l=20, r=20, b=40))
    st.plotly_chart(fig, use_container_width=True)


# ---------------------------------------------------------------------------
# Demo hosts highlighted card row
# ---------------------------------------------------------------------------
st.subheader("Real demo containers")
demo_df = filtered[filtered["is_demo_host"]].sort_values("host_id")
if demo_df.empty:
    st.info("No demo containers match the current filters.")
else:
    cols = st.columns(len(demo_df))
    for col, (_, host) in zip(cols, demo_df.iterrows()):
        with col:
            status = host["status"]
            label = STATUS_LABELS.get(status, status)
            color = STATUS_COLORS.get(status, "#9ca3af")
            st.markdown(
                f"""
                <div style="
                    background: white; border: 2px solid {color};
                    border-radius: 12px; padding: 14px; text-align: center;
                    box-shadow: 0 1px 3px rgba(0,0,0,0.08);">
                    <div style="font-weight:700; font-size:1.05em;">{host['host_id']}</div>
                    <div style="font-size:0.85em; color:#6b7280;">{host['role']} · {host['environment']}</div>
                    <div style="font-size:1.6em; margin:8px 0; font-weight:600; color:{color};">
                        {host['in_use_pct']:.1f}%
                    </div>
                    <div style="font-size:0.85em;">{label}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )
            if st.button(f"Open {host['host_id']}", key=f"open_{host['host_id']}", use_container_width=True):
                st.session_state["selected_host"] = host["host_id"]
                st.switch_page("pages/1_🖥️_Host_Detail.py")


# ---------------------------------------------------------------------------
# Full fleet table — sortable, selectable
# ---------------------------------------------------------------------------
st.subheader("All hosts")
display = filtered[[
    "host_id", "hostname", "role", "environment", "os", "is_demo_host",
    "in_use_pct", "anomaly_score", "forecast_7d_pct", "hours_to_90pct",
    "triggered_agent", "status",
]].rename(columns={
    "in_use_pct": "in_use_%",
    "anomaly_score": "anomaly",
    "forecast_7d_pct": "forecast_7d_%",
    "hours_to_90pct": "h_to_90",
    "triggered_agent": "triggered",
    "is_demo_host": "is_demo",
})

selection = st.dataframe(
    display,
    use_container_width=True,
    hide_index=True,
    selection_mode="single-row",
    on_select="rerun",
    column_config={
        "in_use_%": st.column_config.NumberColumn(format="%.1f"),
        "anomaly": st.column_config.NumberColumn(format="%.3f"),
        "forecast_7d_%": st.column_config.NumberColumn(format="%.1f"),
        "h_to_90": st.column_config.NumberColumn(format="%.1f"),
        "triggered": st.column_config.CheckboxColumn(),
        "is_demo": st.column_config.CheckboxColumn(),
    },
    height=400,
)
if selection and selection.selection.rows:
    idx = selection.selection.rows[0]
    chosen_host = display.iloc[idx]["host_id"]
    st.session_state["selected_host"] = chosen_host
    st.switch_page("pages/1_🖥️_Host_Detail.py")


# ---------------------------------------------------------------------------
# Recent agent runs strip
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Recent agent activity")
runs = fetch_agent_runs(limit=10)
if runs.empty:
    st.caption("No agent runs yet. Run the LLM agent on a triggered host to see activity.")
else:
    display_runs = runs[[
        "started_at", "host_id", "decision", "verdict",
        "confidence_score", "files_deleted", "bytes_freed",
    ]].copy()
    display_runs["bytes_freed_gb"] = (display_runs["bytes_freed"] / (1024**3)).round(2)
    display_runs = display_runs.drop(columns=["bytes_freed"])
    st.dataframe(display_runs, use_container_width=True, hide_index=True)
