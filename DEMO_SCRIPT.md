# OpsGPT POC — Demo Walkthrough

A 5-minute live demo script for InnoVista 2026 (or internal review).
Each section maps to a moment in the architecture diagram so the audience
can see ML → LLM → Decision → Remediation → Audit unfold in real time.

## Pre-demo checklist (run once, ~30 seconds)

```bash
cd opsgpt-disk-prediction-poc
./scripts/demo_reset.sh                 # clean slate; preserves the 50-host fleet seed
streamlit run ui/home.py                # http://localhost:8501
```

You should see: 53 hosts seeded · 0 agent runs · 0 tickets · 8 triggered.

---

## Act 1 — The Fleet (30 seconds)

> "OpsGPT monitors 3,000 production servers. Here's a demo slice — 53 hosts,
> 3 of them real Linux containers running on this laptop, 50 simulated to
> illustrate scale."

**Show:** Fleet Overview page.

- **Top metrics row**: total hosts, real containers, triggered, anomalous,
  breach predictions, open tickets.
- **Anomaly-vs-forecast scatter**: red dots above the 90% line are the
  hosts the system has flagged.
- **Demo container cards**: `demo-web-01`, `demo-app-01`, `demo-db-01` —
  each a real Docker container with its own filesystem.

> "The colored dots aren't decorative — XGBoost on the X axis flags
> anomalous growth, Prophet on the Y axis projects 7-day fill. The agent
> only fires for hosts that cross either threshold."

---

## Act 2 — Predictive cleanup (the boring win, ~120 seconds)

> "Most of what saves engineering hours is preventing routine fires. The
> Host Detail page walks through the architecture in four stages —
> Monitor, Predict, Reason, Resolve — so you can see each layer engage
> in sequence."

**Click** demo-web-01 → Host Detail. Each stage has a numbered badge that
turns green when complete; the page guides you through them top to bottom.

### 🔍 Stage 1 — Monitor

> "Live disk-usage telemetry from this real Linux container. Time series
> over the last 7 days, with a 90% threshold line."

**Open** the "Fill Disk simulator" expander.
Set size to **35 GB**, Backfill **60 min**, click **💾 Fill**.

> "I just wrote 35 GB of synthetic data into the container's `/var/log`.
> The container's reporting agent picked it up; the chart should update on
> next refresh."

### 🔮 Stage 2 — Predict

**Click** 🔮 **Run ML Prediction**.

> "Prophet fits a per-host forecast at 1/3/7/14 days; XGBoost scores
> the trajectory's anomaly probability. **Anomaly: 0.003** — XGBoost
> knows this is rotation, not a runaway. **Forecast 7d: 100%** — we
> *are* going to breach. **Hours-to-90: ~35**. Triggered: yes."

### 🧠 Stage 3 — Reasoning

**Click** 🧠 **Run Reasoning**.

> "This invokes the LangGraph reasoning subgraph: fetch host context,
> sanitize for PII/creds, retrieve matching runbooks from pgvector via
> cosine similarity, send sanitized context to Claude, get back a
> structured JSON recommendation. **Crucially — no action is taken yet.**
> The operator sees what the system *wants* to do before committing."

The recommendation panel appears. Read it aloud:

> "*Anomaly score is negligible (0.003), ruling out an upstream incident.
> Forecast projects ... within the preemptive window. The file listing
> contains four rotated, gzip-compressed access logs ... safe to clean.*"

> "Decision Engine combines four signals into the confidence score:
> LLM self-confidence (40% weight), ML alignment with the recommendation
> (30%), RAG grounding (15%), environment risk (15%). **Score 0.86 —
> above the auto-remediate threshold.**"

### ✅ Stage 4 — Resolve

**Click** ✅ **Resolve**.

> "Now we commit. The Resolve subgraph picks up the reasoning state and
> applies the routing: 0.86 is above 0.85, so it ran the web playbook.
> **17 files deleted, 16.8 GB freed.** Audit row written. No ticket —
> the action *is* the resolution."

**Switch to** 📋 **Audit Trail** → expand the latest row.

> "Every step logged: LLM rationale, tool calls, RAG document IDs,
> Decision Engine breakdown, files deleted, GB freed. Compliance-ready."

---

## Act 3 — The smarter win: refusing to clean (~90 seconds)

> "Anyone can write a script that deletes files when the disk gets full.
> The interesting question is when *not* to."

**Switch to** 🖥️ **Host Detail** → select **demo-app-01**.
Walk through the same 4-stage flow:

- 🔍 **Monitor**: Fill 60 GB · Backfill 60 → 💾 **Fill**
- 🔮 **Predict**: Run ML — **anomaly 0.997**, XGBoost flagged the pattern
- 🧠 **Reasoning**: Run Reasoning — read the rationale aloud:

> "*Anomaly score of 0.997 combined with a single massive file ...
> exhibiting explosive growth is a textbook upstream incident signature.
> INC-2024-0817 demonstrates that cleanup of anomalous growth merely
> delays the inevitable...*"

> "Notice the past-incident reference — `INC-2024-0817`. The agent just
> retrieved an actual ServiceNow KB record from RAG, pattern-matched the
> current situation against it, and recommends **escalate_anomaly**, not
> clean."

- ✅ **Resolve**: Click Resolve.

> "Decision Engine routed `auto_remediate` (high confidence in the
> escalation) but the LLM said don't clean — so the executor correctly
> does nothing and a P2 ticket gets filed instead."

**Switch to** 📨 **Tickets**.

> "P2, assigned to App-Support-app — exactly where the runbook says
> anomalies belong. The full agent reasoning is in the ticket
> description, so the on-call engineer has the context immediately."

---

## Act 4 — Human-in-the-loop (60 seconds, optional)

> "Confidence above 0.85 auto-remediates. Below 0.75 just files a ticket.
> The middle band — 0.75 to 0.85 — sends to OpsGPT chat for human review."

**Switch to** 🤖 **OpsGPT** page.

If there's a pending agentask run: walk through it. Ask a follow-up
question in the chatbot ("why P2 not P3?") and watch Claude answer
grounded in the run's context. Click Approve or Deny.

If there are no pending agentask runs (common after a reset): explain
verbally — *"In production, ~15% of decisions land in this band. The
operator chats with the agent about the recommendation, then approves or
denies with one click."*

---

## Act 5 — Architecture wrap (30 seconds)

> "Behind every page is the architecture you saw at the start: TimescaleDB
> for telemetry, pgvector for RAG, Redis for state, Prophet + XGBoost for
> ML, Claude + LangGraph for the agent, Decision Engine for governance,
> ServiceNow for ticketing. Every box on the diagram is wired up; every
> action is auditable; every prediction is reproducible."

**Show:** sidebar with all 5 pages — Fleet Overview, Host Detail, OpsGPT
chat, Audit Trail, Tickets.

> "Three real Linux hosts to prove it works on real infrastructure;
> 50 simulated to prove it scales. Same code path for both."

---

## Backup material (if asked)

| Q | A |
|---|---|
| "How do you handle false positives?" | The Decision Engine has a hard rule: anomaly_score > 0.6 with `clean` recommendation is auto-suppressed. Plus the per-run safety guards (24h min age, 80GB cap, 200-file cap) prevent runaway cleanup. |
| "What if Claude is unavailable?" | The ML pipeline runs independently and continues to flag triggered hosts. Without the agent, those route to ticket_only by default — degraded but not broken. |
| "Why XGBoost not just thresholds?" | Threshold rules can't distinguish 'logs growing fast because of a deploy' from 'logs growing fast because of a bug'. The classifier sees 12 features (slope, acceleration, residuals, jumps) and learns the difference from past incidents. |
| "What's the cost per agent run?" | About $0.005 with Claude Haiku 4.5. A fleet of 3,000 with ~5% triggered per cycle and 15-min cycles is roughly $50/day — about 2 hours of an SRE's time. |
| "How do you keep up with new runbook content?" | The pgvector corpus is re-embedded on any schedule; a nightly job that pulls fresh ServiceNow KB articles and re-embeds them is straight-line work. |

## Reset between demos

```bash
./scripts/demo_reset.sh
```

This wipes runtime state but keeps the seeded fleet + RAG corpus + trained
model. Each demo starts from the same clean baseline.

For a deeper reset (re-seed simulated fleet + re-embed runbooks):

```bash
./scripts/demo_reset.sh --full
```
