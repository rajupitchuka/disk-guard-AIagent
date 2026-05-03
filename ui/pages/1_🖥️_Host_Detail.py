"""Host Detail — the operator's main demo surface, structured as a 4-stage
flow that mirrors the architecture's data path:

  1. 🔍 Monitor     — see what's happening (telemetry + Fill-Disk simulator)
  2. 🔮 Predict     — run ML (Prophet + XGBoost) to project + classify
  3. 🧠 Reasoning   — run the LLM agent to interpret + recommend (no action)
  4. ✅ Resolve     — commit the action based on the Decision Engine score

Each stage shows progress with a numbered badge. The Reasoning stage stops
short of writing anything — operators see the recommendation BEFORE clicking
Resolve, which then either auto-remediates, routes to OpsGPT chat, or files
a ticket depending on the Decision Engine's confidence score.
"""

from __future__ import annotations

import os
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")
os.environ.setdefault("OMP_NUM_THREADS", "1")

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from ui.lib.actions import (
    clear_disk,
    fill_disk,
    run_ml,
    run_reasoning_only,
    run_resolve_action,
)
from ui.lib.data import (
    fetch_agent_runs,
    fetch_host_predictions,
    fetch_host_telemetry,
    fetch_hosts,
    fetch_latest_predictions,
    invalidate_caches,
)
from ui.lib.styles import DECISION_COLORS, STATUS_COLORS

st.set_page_config(page_title="OpsGPT — Host Detail", page_icon="🖥️", layout="wide")


# ---------------------------------------------------------------------------
# Stage helpers — visual progress badges
# ---------------------------------------------------------------------------
def _stage_header(num: int, icon: str, name: str, status: str = "pending") -> None:
    """status: pending | active | done"""
    palette = {
        "pending": "#9ca3af",
        "active":  "#3b82f6",
        "done":    "#10b981",
    }
    color = palette.get(status, "#9ca3af")
    st.markdown(
        f"""
        <div style="display:flex;align-items:center;gap:12px;margin-top:24px;margin-bottom:8px;">
          <div style="background:{color};color:white;border-radius:50%;width:36px;height:36px;
                      display:flex;align-items:center;justify-content:center;font-weight:700;font-size:1.1em;">
            {num}
          </div>
          <div style="font-size:1.5em;font-weight:600;">{icon} {name}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Host selector
# ---------------------------------------------------------------------------
hosts_df = fetch_hosts()
if hosts_df.empty:
    st.warning("No hosts in the database. Seed first.")
    st.stop()

host_ids = hosts_df["host_id"].tolist()
default_host = st.session_state.get("selected_host", host_ids[0])
if default_host not in host_ids:
    default_host = host_ids[0]

st.title("🖥️ Host Detail")
selected = st.selectbox(
    "Host",
    host_ids,
    index=host_ids.index(default_host),
    format_func=lambda h: f"{h} · {hosts_df.loc[hosts_df.host_id == h, 'role'].values[0]} · "
                          f"{hosts_df.loc[hosts_df.host_id == h, 'environment'].values[0]}",
)
if selected != st.session_state.get("selected_host"):
    # New host selected → drop any prior reasoning state
    st.session_state.pop("reasoning_state", None)
st.session_state["selected_host"] = selected
host = hosts_df[hosts_df.host_id == selected].iloc[0]
is_demo = bool(host.get("is_demo_host", False))


# ---------------------------------------------------------------------------
# Header strip — host meta
# ---------------------------------------------------------------------------
c1, c2, c3, c4 = st.columns(4)
c1.metric("Hostname", host["hostname"])
c2.metric("Role / Env", f"{host['role']} · {host['environment']}")
c3.metric("Total disk", f"{host['total_disk_gb']:.0f} GB")
c4.metric("Monitored path", host["monitored_path"])

if not is_demo:
    st.warning(
        "This host is part of the simulated 50-host fleet — Fill Disk and "
        "Resolve actions only apply to the real demo containers "
        "(`demo-web-01`, `demo-app-01`, `demo-db-01`). Predict + Reasoning "
        "still work for analysis."
    )


# ---------------------------------------------------------------------------
# STAGE 1 — MONITOR
# ---------------------------------------------------------------------------
_stage_header(1, "🔍", "Monitor", "active")
st.caption(
    "Live disk-usage trajectory from Datadog telemetry (synthetic for the demo). "
    "Use the Fill Disk simulator to inject load and watch the system react."
)

range_options = {"24 hours": 24, "3 days": 72, "7 days": 168}
range_choice = st.radio("Range", list(range_options.keys()), index=2, horizontal=True,
                         key="monitor_range")
hours_back = range_options[range_choice]

telemetry = fetch_host_telemetry(selected, hours=hours_back)
if telemetry.empty:
    st.info("No telemetry yet.")
else:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=telemetry["ts"], y=telemetry["in_use_pct"],
        mode="lines", line=dict(color="#3b82f6", width=2),
        name="in_use %",
    ))
    fig.add_hline(y=90, line_dash="dash", line_color="#ef4444", annotation_text="90% threshold")
    fig.update_layout(
        height=320, margin=dict(t=20, l=20, r=20, b=20),
        yaxis_title="in_use %", xaxis_title="time",
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True)

with st.expander("🪣 Fill Disk simulator (writes real files into the demo container)", expanded=False):
    st.caption(
        "Sparse files via fallocate — instant. Backfill inserts that many "
        "backdated 1-min samples at the new percentage so the ML cycle "
        "responds immediately."
    )
    f1, f2, f3 = st.columns([2, 2, 1])
    fill_gb = f1.slider("Size (GB)", min_value=1.0, max_value=80.0, value=30.0, step=1.0, key="fill_gb")
    backfill = f2.slider("Backfill (min)", min_value=0, max_value=180, value=60, step=15, key="fill_backfill")
    with f3:
        st.write("")
        st.write("")
        fill_clicked = st.button("💾 Fill", type="primary", disabled=not is_demo, use_container_width=True)
        clear_clicked = st.button("🧹 Clear", disabled=not is_demo, use_container_width=True)


# ---------------------------------------------------------------------------
# STAGE 2 — PREDICT
# ---------------------------------------------------------------------------
preds = fetch_latest_predictions()
my_pred_row = preds[preds.host_id == selected]
has_prediction = not my_pred_row.empty
my_pred = my_pred_row.iloc[0] if has_prediction else None

_stage_header(2, "🔮", "Predict", "done" if has_prediction else "pending")
st.caption(
    "Prophet fits per-host (1/3/7/14 day forecasts) and XGBoost classifies "
    "the trajectory as anomalous or normal."
)

if has_prediction:
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("Anomaly score", f"{my_pred['anomaly_score']:.3f}",
              help="XGBoost — > 0.6 means out-of-pattern growth")
    p2.metric("Forecast 1d", f"{my_pred['forecast_1d_pct']:.1f}%" if pd.notna(my_pred['forecast_1d_pct']) else "n/a")
    p3.metric("Forecast 7d", f"{my_pred['forecast_7d_pct']:.1f}%" if pd.notna(my_pred['forecast_7d_pct']) else "n/a")
    p4.metric("Hours to 90%", f"{my_pred['hours_to_90pct']:.1f}" if pd.notna(my_pred['hours_to_90pct']) else "n/a")
    p5.metric("Triggered?", "✅ YES" if my_pred['triggered_agent'] else "—",
              help="True if forecast crosses 90% within 7d OR anomaly score >= 0.6")
else:
    st.info("No ML prediction yet for this host — click **Run ML Prediction** below.")

ml_clicked = st.button("🔮 Run ML Prediction", type="primary", key="predict_btn",
                       use_container_width=False)


# ---------------------------------------------------------------------------
# STAGE 3 — REASONING
# ---------------------------------------------------------------------------
reasoning_done = "reasoning_state" in st.session_state and \
                 st.session_state.get("reasoning_state", {}).get("host_id") == selected

_stage_header(3, "🧠", "Reasoning", "done" if reasoning_done else "pending")
st.caption(
    "LangGraph agent: fetches host context, sanitizes PII, retrieves "
    "matching runbooks via RAG, calls Claude for structured reasoning, "
    "then computes a Decision Engine confidence score. Stops here — no "
    "action committed yet."
)

reasoning_clicked = st.button(
    "🧠 Run Reasoning",
    type="primary",
    key="reasoning_btn",
    disabled=not has_prediction,
    help="Requires a prediction first" if not has_prediction else None,
    use_container_width=False,
)

if reasoning_done:
    r = st.session_state["reasoning_state"]
    rec = r.get("llm_recommendation", "—")
    self_conf = r.get("llm_self_confidence", 0.0)
    decision = r.get("decision")
    rec_palette = {
        "clean": "#10b981",
        "no_action": "#3b82f6",
        "escalate_anomaly": "#ef4444",
    }
    rec_color = rec_palette.get(rec, "#9ca3af")

    rc1, rc2, rc3, rc4 = st.columns(4)
    rc1.metric("LLM recommendation", rec)
    rc2.metric("LLM self-confidence", f"{self_conf:.2f}")
    rc3.metric("Decision route", decision.decision if decision else "—",
               help="From the Decision Engine — auto_remediate / agentask / ticket_only")
    rc4.metric("Confidence score", f"{decision.confidence_score:.3f}" if decision else "—")

    st.markdown(
        f"<div style='background:{rec_color};color:white;padding:8px 14px;"
        f"border-radius:8px;display:inline-block;font-weight:600;margin-top:4px;'>"
        f"Recommendation: {rec.replace('_', ' ').upper()}</div>",
        unsafe_allow_html=True,
    )

    st.markdown("**Root-cause reasoning + recommendation**")
    st.info(r.get("llm_rationale", ""))

    evidence = r.get("llm_key_evidence") or []
    if evidence:
        st.markdown("**Key evidence cited**")
        for e in evidence:
            st.markdown(f"- {e}")

    if decision:
        with st.expander("Decision Engine score breakdown", expanded=False):
            for line in decision.rationale:
                st.text(line)


# ---------------------------------------------------------------------------
# STAGE 4 — RESOLVE
# ---------------------------------------------------------------------------
resolved_done = "resolve_result" in st.session_state and \
                st.session_state.get("resolve_result_host") == selected

_stage_header(4, "✅", "Resolve", "done" if resolved_done else "pending")
st.caption(
    "Apply the Decision Engine's routing: > 0.85 auto-remediates (runs the "
    "playbook), 0.75–0.85 routes to OpsGPT chat for operator approval, "
    "below 0.75 files a ServiceNow ticket only."
)

resolve_clicked = st.button(
    "✅ Resolve",
    type="primary",
    key="resolve_btn",
    disabled=not reasoning_done,
    help="Requires reasoning to complete first" if not reasoning_done else None,
    use_container_width=False,
)

if resolved_done:
    rr = st.session_state["resolve_result"]
    decision = rr.get("decision")
    files = rr.get("files_deleted", 0)
    gb_freed = rr.get("bytes_freed", 0) / (1024**3)
    color = DECISION_COLORS.get(decision, "#9ca3af")
    st.markdown(
        f"<div style='background:{color};color:white;padding:10px 16px;"
        f"border-radius:8px;display:inline-block;font-weight:600;margin-top:4px;'>"
        f"Action: {decision}</div>",
        unsafe_allow_html=True,
    )
    if files:
        st.success(f"🧹 Cleaned {files} files · {gb_freed:.2f} GB freed")
        st.page_link("pages/3_📋_Audit_Trail.py", label="📋 View this run in the Audit Trail →")
    elif decision == "agentask":
        st.warning(
            "📨 Routed to OpsGPT chat — pending operator approval. Open the "
            "chatbot, ask follow-up questions if you want, then approve or deny."
        )
        st.page_link("pages/2_🤖_OpsGPT.py", label="🤖 Open OpsGPT chat →")
    elif decision == "ticket_only":
        st.info("📨 ServiceNow ticket created — see Tickets page.")
        st.page_link("pages/4_📨_Tickets.py", label="📨 Open Tickets →")
    else:
        st.info("No action taken (escalation path or no safe candidates).")
        st.page_link("pages/3_📋_Audit_Trail.py", label="📋 View this run in the Audit Trail →")


# ---------------------------------------------------------------------------
# Action handlers (state-changing)
# ---------------------------------------------------------------------------
def _show(result, title: str):
    box = st.success if result.ok else st.error
    box(f"{title}: {result.message}")
    if result.detail and not result.ok:
        with st.expander("Details", expanded=False):
            st.json(result.detail)


if fill_clicked:
    with st.spinner(f"Filling {selected} with {fill_gb} GB..."):
        r = fill_disk(selected, fill_gb, with_backfill_min=backfill)
    _show(r, "Fill")
    invalidate_caches()
    # Filling invalidates downstream stages
    st.session_state.pop("reasoning_state", None)
    st.session_state.pop("resolve_result", None)
    st.rerun()

if clear_clicked:
    with st.spinner(f"Clearing junk on {selected}..."):
        r = clear_disk(selected)
    _show(r, "Clear")
    invalidate_caches()
    st.session_state.pop("reasoning_state", None)
    st.session_state.pop("resolve_result", None)
    st.rerun()

if ml_clicked:
    with st.spinner("Running Prophet + XGBoost..."):
        r = run_ml(selected)
    _show(r, "Predict")
    invalidate_caches()
    # New prediction invalidates reasoning + resolve
    st.session_state.pop("reasoning_state", None)
    st.session_state.pop("resolve_result", None)
    st.rerun()

if reasoning_clicked:
    with st.spinner("Running LangGraph reasoning subgraph (calls Claude)..."):
        r = run_reasoning_only(selected)
    if r.ok:
        st.session_state["reasoning_state"] = r.detail["state"]
        st.session_state.pop("resolve_result", None)
        st.success(r.message)
    else:
        st.error(r.message)
    st.rerun()

if resolve_clicked:
    state = st.session_state.get("reasoning_state")
    if state is None:
        st.error("No reasoning state — run Reasoning first.")
    else:
        with st.spinner("Running LangGraph resolve subgraph..."):
            r = run_resolve_action(state)
        if r.ok:
            st.session_state["resolve_result"] = r.detail
            st.session_state["resolve_result_host"] = selected
            # Reasoning state is now consumed
            st.session_state.pop("reasoning_state", None)
            st.success(r.message)
        else:
            st.error(r.message)
        invalidate_caches()
        st.rerun()


# ---------------------------------------------------------------------------
# Recent agent runs for this host
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Recent agent runs for this host")
runs = fetch_agent_runs(host_id=selected, limit=20)
if runs.empty:
    st.caption("No agent runs yet for this host.")
else:
    table = runs[[
        "started_at", "decision", "verdict", "confidence_score",
        "files_deleted", "bytes_freed", "servicenow_ticket_id",
    ]].copy()
    table["bytes_freed_gb"] = (table["bytes_freed"] / (1024**3)).round(2)
    table = table.drop(columns=["bytes_freed"])
    st.dataframe(table, use_container_width=True, hide_index=True)
