# Disk Guard AI Agent — Demo Video Script

A detailed shotlist for recording a 3–4 minute demo video for
LinkedIn / YouTube / conference submissions. The script is designed
so you can record in **one or two takes** without heavy editing.

## Equipment & setup

- **Recording tool:** Loom (easiest — installs as a Chrome
  extension, recommended for first attempt) or QuickTime Screen
  Recording (built into macOS, free)
- **Audio:** Built-in MacBook mic is acceptable; a USB headset
  (Logitech H390 or similar, ~USD 30) sounds noticeably better
- **Resolution:** Record at 1920×1080 (1080p) — Loom and QuickTime
  default to this
- **Browser zoom:** Set browser to **125%** before starting so UI
  text is readable when the video is compressed
- **Hide notifications:** Enable Do Not Disturb on macOS, close
  Slack/email
- **Tabs:** Have only the Streamlit app tab open; close all others
  to avoid distraction

## Pre-recording checklist

```bash
# Reset to a clean demo state
cd /Users/naga/Documents/IT-Projects/opsgpt-disk-prediction-poc
./scripts/demo_reset.sh

# Confirm Streamlit is running
open http://localhost:8501

# Confirm OrbStack is running
docker compose ps   # all containers should be 'healthy'

# Confirm API key is in .env
grep ANTHROPIC_API_KEY .env  # should NOT show 'sk-ant-...' placeholder
```

Open Streamlit at `http://localhost:8501`, navigate to **Host
Detail → demo-app-01**. This is your starting frame.

## Total runtime: 3 min 30 sec (~210 sec)

| Time     | Section                                   | Duration |
|----------|-------------------------------------------|----------|
| 0:00     | Hook                                      | 15 sec   |
| 0:15     | Problem framing                           | 25 sec   |
| 0:40     | The architecture in one sentence          | 20 sec   |
| 1:00     | Demo Stage 1: Monitor + Fill              | 30 sec   |
| 1:30     | Demo Stage 2: Run ML Prediction           | 25 sec   |
| 1:55     | Demo Stage 3: Run LLM Reasoning           | 35 sec   |
| 2:30     | Demo Stage 4: Resolve + the smart refusal | 35 sec   |
| 3:05     | Audit trail + ServiceNow ticket           | 15 sec   |
| 3:20     | Call to action                            | 10 sec   |

---

## Section-by-section script

### [0:00 – 0:15] Hook

**On screen:** Browser at the Fleet Overview page (or fade in from
black to the dashboard).

**Say:**

> *"Most disk-fill incidents in enterprise IT shouldn't ever cause
> outages. They do, because monitoring tools wait for thresholds to
> breach before they alert anyone. By then it's often too late."*

**Action:** As you say "outages," briefly highlight the red
"Anomalous" hosts on the fleet scatter chart with the cursor.

---

### [0:15 – 0:40] Problem framing

**On screen:** Stay on Fleet Overview; let the metrics row stand
visible.

**Say:**

> *"Across enterprise IT estates, storage-related events account
> for around 10 to 15 percent of infrastructure incidents.
> Industry surveys put enterprise hourly downtime cost above three
> hundred thousand US dollars. For a typical 3,000-server estate,
> disk-fill alone consumes about one engineering full-time
> equivalent per year and millions in associated outage cost."*

**Action:** Keep the cursor still and let the viewer absorb the
fleet metrics and scatter plot.

---

### [0:40 – 1:00] The architecture in one sentence

**On screen:** Optional — if you have the architecture diagram open
in another tab, switch to it briefly. Otherwise stay on the fleet
view.

**Say:**

> *"Disk Guard flips the model. Instead of waiting for thresholds,
> it continuously forecasts disk saturation, classifies anomalous
> growth, and uses an LLM agent — grounded in past-incident
> records — to decide what action to take, with full governance
> on top. Let me show you."*

**Action:** Click on `demo-app-01` (or your chosen demo host) to
navigate to Host Detail.

---

### [1:00 – 1:30] Stage 1: Monitor + Fill

**On screen:** Host Detail page. Stage 1 (Monitor) is at the top.

**Say:**

> *"This is one Linux container in our test fleet. The chart shows
> seven days of disk-usage telemetry. Right now the host is in a
> healthy state. Let me simulate what happens when something goes
> wrong — say a logger bug starts writing 60 gigabytes of stack
> traces."*

**Action:**
1. Click the "🪣 Fill Disk simulator" expander
2. Drag the size slider to **60 GB**, backfill to **60 minutes**
3. Click **💾 Fill**
4. Wait 1–2 seconds for the success message
5. Scroll back up — the chart now shows the spike

**Say (during the fill):**

> *"And there it is. The disk just jumped from 32 percent used to
> 92 percent in seconds."*

---

### [1:30 – 1:55] Stage 2: Run ML Prediction

**On screen:** Stage 2 section. Metrics will be from the previous
prediction.

**Say:**

> *"Now let's see what the ML engine thinks. This runs Prophet for
> the time-series forecast and an XGBoost classifier for anomaly
> detection."*

**Action:**
1. Click **🔮 Run ML Prediction**
2. Wait ~3 seconds for the spinner
3. Let the metrics update

**Say (after the metrics update):**

> *"Anomaly score 0.997 — XGBoost recognized this as out-of-pattern
> growth, not normal log accumulation. Forecast says 100 percent
> in less than a day. The 'Triggered?' flag is yes — meaning the
> system thinks the LLM agent should look at this."*

---

### [1:55 – 2:30] Stage 3: Run LLM Reasoning

**On screen:** Stage 3 section.

**Say:**

> *"Stage 3 is the LangGraph agent — Claude reasoning over the
> situation, grounded in past-incident records retrieved from
> pgvector. Notice this stage stops short of any action. The
> operator sees what the system wants to do before committing."*

**Action:** Click **🧠 Run Reasoning**. Wait ~10 seconds for the
LLM call.

**Say (while waiting, fill the silence):**

> *"While that's running, here's what's happening underneath: the
> agent gathered the host context, retrieved the four most relevant
> runbook documents, sanitized for PII and credentials, and sent a
> structured prompt to Claude."*

**When the rationale appears:**

> *"And here's the recommendation — escalate anomaly. Read this:
> 'Anomaly score 0.997 combined with a single massive file
> exhibiting explosive growth is a textbook upstream incident
> signature. INC-2024-0817 demonstrates that cleanup of anomalous
> growth merely delays the inevitable disk fill.' The agent just
> retrieved a real past-incident record from RAG and pattern-matched
> our current scenario against it."*

**Action:** Briefly point cursor at the "Decision route:
auto_remediate" and "Confidence score: 0.89" fields.

---

### [2:30 – 3:05] Stage 4: Resolve — the smart refusal

**On screen:** Stage 4 section.

**Say:**

> *"Stage 4 commits the action. The Decision Engine score is 0.89,
> above the auto-remediate threshold of 0.85. So the system has
> permission to act on its own. But here's the safety rule: when
> the LLM says 'this is anomalous, escalate,' the executor never
> cleans files — even at high confidence. Watch."*

**Action:** Click **✅ Resolve**. Wait ~3 seconds.

**Say (when result appears):**

> *"Look at the result. The system went to ServiceNow and filed a
> P2 ticket assigned to the application support team. No files
> were deleted. The reasoning is in the ticket description for the
> on-call engineer. This is the right answer — cleaning would have
> masked the upstream bug, and the disk would refill in minutes.
> The system caught what a threshold-based monitor and a static
> automation script would have missed."*

---

### [3:05 – 3:20] Audit trail + ServiceNow ticket

**On screen:** Click the green "📨 Open the ticket →" link, navigate
to the Tickets page.

**Say:**

> *"Every action is logged. Here's the auto-created ServiceNow
> ticket — severity, assignment group, full agent reasoning
> attached. This is the compliance story for IT-operations governance.
> Every decision is auditable, every recommendation is
> grounded, every action has a reason."*

---

### [3:20 – 3:30] Call to action

**On screen:** Switch to the GitHub repo URL (or stay on Streamlit;
either works).

**Say:**

> *"The full source code, architecture, and whitepaper are public
> on GitHub at github dot com slash rajupitchuka slash
> disk-guard-AI-agent. I built this as a proof of concept — feedback
> and contributions welcome. Thanks for watching."*

**End frame:** Display the GitHub URL on screen for 3 seconds, then
fade to black.

---

## Post-recording

1. **Trim & cut:** In Loom or QuickTime, trim the dead air at the
   start and end. Keep takes natural — small "uhms" are human and
   help the video pass AI-detection on platforms that scrutinize.
2. **Subtitles:** Loom auto-generates captions; review them for
   technical-term mistakes ("XGBoost" often misheard as
   "X-G-Boost" or "exboost"). Spend 5 minutes correcting.
3. **Export:** 1080p, MP4. Loom handles upload directly to YouTube
   if you connect it.
4. **YouTube:**
   - Upload as **Unlisted** initially while you review
   - **Title:** Disk Guard AI Agent — Predictive disk failure
     prevention with ML + LLM (3-min demo)
   - **Description:** Brief paragraph + GitHub link + arXiv link
     (once available) + paper link
5. **Make Public** when you're ready for the LinkedIn post

## Optional: a 60-second GIF version

LinkedIn posts with embedded GIFs (under 30MB) get higher
engagement than video links. To create a short GIF version:

1. Record only Stage 2 → Stage 4 (the most visually interesting
   minute)
2. Use QuickTime → File → Export → 720p
3. Convert to GIF with `ffmpeg`:

```bash
brew install ffmpeg

ffmpeg -i input.mov -vf "fps=15,scale=1024:-1:flags=lanczos" \
       -loop 0 demo.gif
```

Aim for under 25 MB. If too large, drop fps to 12 or scale to 800.

## Tips for sounding natural (not AI-generated)

- **Don't read this script verbatim.** Read it 2–3 times to absorb
  the structure, then talk through it from memory. Your delivery
  will be more natural and trustworthy.
- **Vary pace.** Slow down on numbers (0.997, three hundred
  thousand) so they land. Speed up on transitions.
- **Pause occasionally.** A 1-second silence after a key claim
  feels confident.
- **Don't sound like a sales pitch.** This is your engineering
  work — speak the way you would to a colleague at the next desk.

## Tips for re-recording

If you mess up partway, **don't restart from zero**. Just pause,
back up two sentences, and continue. Edit the rough cut in Loom
or iMovie. The first attempt is rarely the keeper; expect 2–3
takes for the tricky middle sections.
