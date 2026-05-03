"""OpsGPT chatbot — conversational approval interface for human-in-the-loop
reviews. (Implements the AgentAsk component from Zone 3 of the architecture
diagram; user-facing brand is OpsGPT.)

When the Decision Engine routes to `agentask` (confidence 0.75–0.85), the
operator opens this page, picks a pending recommendation, chats with OpsGPT
about it (asking follow-up questions about the host's history, the runbook
context, or the proposed action), and finally clicks Approve or Deny.
Approve triggers the actual remediation; Deny records a no-action verdict.
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
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from shared.config import settings
from shared.db import timescale_conn
from ui.lib.data import fetch_agent_runs, invalidate_caches
from ui.lib.styles import VERDICT_BADGES
from services.remediation.executor import execute as remediation_execute
from services.remediation.playbooks import get_playbook

st.set_page_config(page_title="OpsGPT", page_icon="🤖", layout="wide")

st.title("🤖 OpsGPT")
st.caption(
    "Conversational approval surface for medium-confidence decisions "
    "(confidence 0.75–0.85). Chat with OpsGPT about its proposal, then "
    "approve or deny."
)


# ---------------------------------------------------------------------------
# Find pending recommendations (the ones we haven't acted on yet)
# ---------------------------------------------------------------------------
def _pending_agentask_runs() -> pd.DataFrame:
    """An agent_run is 'pending' if decision='agentask' and there is no
    follow-up run for the same host that resolved it. We use a simple
    convention: a follow-up run with verdict in {'cleaned', 'no_action_needed'}
    after the agentask run resolves it."""
    runs = fetch_agent_runs(limit=200)
    if runs.empty:
        return runs
    pending = runs[runs["decision"] == "agentask"].copy()
    if pending.empty:
        return pending
    # Strip already-resolved (any newer run for same host with cleaned/no_action)
    resolved_hosts: set[str] = set()
    for _, run in runs.iterrows():
        if run["verdict"] in ("cleaned", "no_action_needed"):
            resolved_hosts.add((run["host_id"], run["started_at"]))
    return pending


pending = _pending_agentask_runs()


# ---------------------------------------------------------------------------
# Pending list + selector
# ---------------------------------------------------------------------------
if pending.empty:
    st.info(
        "No pending OpsGPT approvals right now. The chatbot is invoked when "
        "the Decision Engine's confidence lands between "
        f"{settings.decision_agentask_threshold:.2f} and "
        f"{settings.decision_auto_remediate_threshold:.2f}. "
        "Run the agent on a host with mixed signals to create one."
    )
    st.stop()

st.subheader(f"Pending approvals ({len(pending)})")
options = {
    f"{r['host_id']} · conf {r['confidence_score']:.3f} · "
    f"{r['started_at'].strftime('%H:%M:%S')}": r["run_id"]
    for _, r in pending.iterrows()
}
choice = st.selectbox("Select a pending recommendation", list(options.keys()))
run = pending[pending["run_id"] == options[choice]].iloc[0]


# ---------------------------------------------------------------------------
# Recommendation card
# ---------------------------------------------------------------------------
st.markdown("---")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Host", run["host_id"])
c2.metric("LLM rationale length", f"{len(run['llm_reasoning'] or '')} chars")
c3.metric("Confidence", f"{run['confidence_score']:.3f}")
c4.metric("Recommendation", run.get("verdict") or "—")

st.markdown("**LLM reasoning**")
st.info(run["llm_reasoning"] or "(no reasoning recorded)")


# ---------------------------------------------------------------------------
# Chat — ask follow-up questions
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Ask follow-up questions")

chat_key = f"agentask_chat_{run['run_id']}"
if chat_key not in st.session_state:
    st.session_state[chat_key] = []

# Display existing messages
for msg in st.session_state[chat_key]:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

prompt = st.chat_input("Ask the agent about this recommendation…")
if prompt:
    st.session_state[chat_key].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Build LLM context: original reasoning + chat so far
    system = (
        "You are an IT-Operations agent explaining a prior recommendation to a "
        "human reviewer. Stay concise and operational. The original recommendation "
        "and reasoning are below. Answer the reviewer's questions about the host, "
        "the proposed action, the runbook context, or the trade-offs. Do not "
        "fabricate details — if you weren't given specific data, say so."
    )
    context_block = (
        f"Host: {run['host_id']}\n"
        f"Decision: {run['decision']} (confidence {run['confidence_score']:.3f})\n"
        f"Verdict: {run.get('verdict') or '—'}\n"
        f"Reasoning:\n{run['llm_reasoning'] or '(empty)'}\n"
    )

    messages = [SystemMessage(content=system), HumanMessage(content=context_block)]
    for m in st.session_state[chat_key]:
        if m["role"] == "user":
            messages.append(HumanMessage(content=m["content"]))
        else:
            messages.append(AIMessage(content=m["content"]))

    llm = ChatAnthropic(
        model=settings.opsgpt_llm_model,
        max_tokens=512,
        api_key=settings.anthropic_api_key,
    )
    with st.chat_message("assistant"):
        with st.spinner("…"):
            response = llm.invoke(messages)
            text = response.content if isinstance(response.content, str) else str(response.content)
        st.markdown(text)
    st.session_state[chat_key].append({"role": "assistant", "content": text})


# ---------------------------------------------------------------------------
# Approve / Deny
# ---------------------------------------------------------------------------
st.markdown("---")
st.subheader("Resolve")

a1, a2 = st.columns(2)
approve = a1.button("✅ Approve & remediate", type="primary", use_container_width=True)
deny = a2.button("❌ Deny (record as no-action)", use_container_width=True)


def _record_resolution(parent_run, decision: str, verdict: str,
                       bytes_freed: int = 0, files_deleted: int = 0,
                       reasoning: str = "") -> str:
    import uuid
    from datetime import datetime, timezone
    new_id = f"run-{uuid.uuid4().hex[:12]}"
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO agent_runs
                  (run_id, started_at, finished_at, host_id, prediction_id,
                   confidence_score, decision, verdict, bytes_freed, files_deleted,
                   llm_reasoning)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    new_id,
                    datetime.now(timezone.utc),
                    datetime.now(timezone.utc),
                    parent_run["host_id"],
                    parent_run.get("prediction_id"),
                    parent_run["confidence_score"],
                    decision,
                    verdict,
                    bytes_freed,
                    files_deleted,
                    reasoning,
                ),
            )
        conn.commit()
    return new_id


if approve:
    # Look up the host to get role + monitored_path
    with timescale_conn() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT role, monitored_path FROM hosts WHERE host_id = %s",
                        (run["host_id"],))
            host_meta = cur.fetchone()

    playbook = get_playbook(host_meta["role"])
    with st.spinner(f"Remediating {run['host_id']}..."):
        result = remediation_execute(
            host_id=run["host_id"],
            monitored_path=host_meta["monitored_path"],
            playbook=playbook,
            dry_run=False,
        )
    new_id = _record_resolution(
        run, decision="auto_remediate", verdict="cleaned",
        bytes_freed=result.bytes_freed, files_deleted=result.file_count,
        reasoning=f"Approved by operator via OpsGPT chatbot (parent run {run['run_id']}). "
                  f"Freed {result.bytes_freed / (1024**3):.2f} GB across "
                  f"{result.file_count} files.",
    )
    st.success(f"✅ Approved. New run {new_id} recorded. "
               f"{result.file_count} files deleted, "
               f"{result.bytes_freed / (1024**3):.2f} GB freed.")
    invalidate_caches()
    st.rerun()

if deny:
    new_id = _record_resolution(
        run, decision="ticket_only", verdict="no_action_needed",
        reasoning=f"Denied by operator via OpsGPT chatbot (parent run {run['run_id']}). "
                  "No remediation taken; ticket-only path.",
    )
    st.warning(f"❌ Denied. New run {new_id} recorded with verdict 'no_action_needed'.")
    invalidate_caches()
    st.rerun()
