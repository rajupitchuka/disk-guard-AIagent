"""Audit Trail — every agent_runs row, filterable, with the LLM's reasoning
and the tool calls expanded inline. This is the page InnoVista judges look
at to confirm that every action was logged and explainable.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pandas as pd
import streamlit as st

from ui.lib.data import fetch_agent_runs, invalidate_caches
from ui.lib.styles import DECISION_COLORS, VERDICT_BADGES, action_summary

st.set_page_config(page_title="OpsGPT — Audit", page_icon="📋", layout="wide")

st.title("📋 Audit Trail")
st.caption(
    "Every agent invocation is recorded with full context: ML prediction, "
    "RAG documents retrieved, LLM reasoning, decision-engine score, "
    "remediation outcome. This is the demo's compliance story."
)

if st.button("🔄 Refresh"):
    invalidate_caches()
    st.rerun()

runs = fetch_agent_runs(limit=200)
if runs.empty:
    st.info("No agent runs yet. Open Host Detail and click **Run LLM Reasoning** to create one.")
    st.stop()


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
with st.expander("Filters", expanded=False):
    c1, c2, c3 = st.columns(3)
    decision_filter = c1.multiselect(
        "Decision",
        sorted(runs["decision"].dropna().unique().tolist()),
    )
    verdict_filter = c2.multiselect(
        "Verdict",
        sorted(runs["verdict"].dropna().unique().tolist()),
    )
    host_filter = c3.multiselect(
        "Host",
        sorted(runs["host_id"].unique().tolist()),
    )

filtered = runs.copy()
if decision_filter:
    filtered = filtered[filtered["decision"].isin(decision_filter)]
if verdict_filter:
    filtered = filtered[filtered["verdict"].isin(verdict_filter)]
if host_filter:
    filtered = filtered[filtered["host_id"].isin(host_filter)]


# ---------------------------------------------------------------------------
# Summary metrics
# ---------------------------------------------------------------------------
m1, m2, m3, m4, m5 = st.columns(5)
m1.metric("Total runs", len(filtered))
m2.metric("Auto-remediated", int((filtered["decision"] == "auto_remediate").sum()))
m3.metric("OpsGPT chat (pending)", int((filtered["decision"] == "opsgpt_chat").sum()))
m4.metric("Tickets created",
          int(filtered["servicenow_ticket_id"].fillna("").astype(bool).sum())
          if "servicenow_ticket_id" in filtered.columns else 0)
m5.metric("Total GB freed",
          f"{filtered['bytes_freed'].fillna(0).sum() / (1024**3):.2f}")

st.markdown("---")


# ---------------------------------------------------------------------------
# Row-per-run with expander for full detail
# ---------------------------------------------------------------------------
for _, run in filtered.iterrows():
    decision = run.get("decision") or "—"
    verdict = run.get("verdict") or "—"
    decision_color = DECISION_COLORS.get(decision, "#9ca3af")
    verdict_label = VERDICT_BADGES.get(verdict, verdict)

    started = run["started_at"]
    score = run.get("confidence_score")
    files = run.get("files_deleted") or 0
    gb_freed = (run.get("bytes_freed") or 0) / (1024**3)

    ticket_id = run.get("servicenow_ticket_id")
    ticket_part = f" · 📨 {ticket_id}" if ticket_id else ""
    header = (
        f"**{run['host_id']}** · {started.strftime('%Y-%m-%d %H:%M:%S')} · "
        f"`{decision}` (conf {score:.3f}) · {verdict_label} · "
        f"{files} files / {gb_freed:.2f} GB freed{ticket_part}"
    ) if pd.notna(score) else (
        f"**{run['host_id']}** · {started.strftime('%Y-%m-%d %H:%M:%S')} · {verdict_label}{ticket_part}"
    )

    with st.expander(header, expanded=False):
        # Plain-language summary first — disambiguates auto_remediate +
        # escalated_anomaly (system auto-acted but by filing a ticket, not
        # by deleting files).
        summary = action_summary(
            decision=decision if decision != "—" else None,
            verdict=verdict if verdict != "—" else None,
            files=int(files),
            gb_freed=gb_freed,
            ticket_id=ticket_id,
        )
        st.markdown(f"**Action taken:** {summary}")

        c1, c2 = st.columns([2, 1])
        with c1:
            st.markdown("**LLM reasoning**")
            st.info(run.get("llm_reasoning") or "(empty)")

            tool_calls = run.get("tool_calls")
            if tool_calls:
                # tool_calls is a JSON list of dicts
                if isinstance(tool_calls, str):
                    tool_calls = json.loads(tool_calls)
                st.markdown("**Tool calls**")
                for tc in tool_calls:
                    st.markdown(
                        f"- `{tc.get('tool')}({json.dumps(tc.get('args', {}))})` → "
                        f"_{tc.get('output_summary')}_"
                    )

        with c2:
            st.markdown("**Run metadata**")
            st.write({
                "run_id": run["run_id"],
                "prediction_id": run.get("prediction_id"),
                "started_at": str(run["started_at"]),
                "finished_at": str(run.get("finished_at")) if run.get("finished_at") else None,
                "decision": decision,
                "verdict": verdict,
                "confidence_score": float(score) if pd.notna(score) else None,
                "files_deleted": int(files),
                "bytes_freed_gb": round(gb_freed, 2),
                "rag_doc_ids": run.get("rag_context_ids") or [],
            })
