# arXiv Abstract Submission Text

Paste the text below into the arXiv submission form's **Abstract**
field. It is a tightened version of the paper abstract that fits
within arXiv's 1920-character limit (this version is ~1700
characters / ~240 words).

---

## Plain text version (for arXiv form)

Disk-fill incidents are among the most common production failures in enterprise IT. Threshold-based monitoring tools detect such conditions only when 85-90% utilization is breached, generating an alert that triggers manual or automated cleanup. For routine log accumulation this is sufficient; for anomalous fast-fill scenarios driven by misconfigured loggers, retry storms, or deploy regressions, the alert fires too late and the host saturates. Industry surveys put enterprise hourly outage cost above USD 300K, with storage-related events accounting for 10-15% of infrastructure incidents. At the scale of a typical 3,000-server estate, disk-fill alone consumes one engineering FTE per year and produces several million dollars per year in associated outage cost.

This paper presents Disk Guard AI Agent, a working proof of concept of a predictive multi-AI architecture that addresses this structurally. Rather than waiting for thresholds, the system continuously forecasts disk saturation using Prophet and classifies anomalous growth using XGBoost. When either signal crosses a trigger condition, a Claude-powered LangGraph agent grounded in retrieved past-incident records reasons about the situation and produces a structured recommendation. A Decision Engine routes the recommendation to one of three governance bands (auto-remediate, chatbot approval, or ServiceNow ticket only) based on a confidence score combining LLM self-confidence, ML signal alignment, RAG grounding, and environment risk.

The implementation runs end-to-end on a 53-host fleet with full ML cycles in approximately 8 seconds. Two reproducible scenarios demonstrate the system: a predictive cleanup of routine rotated logs, and a correctly-refused cleanup of an anomalous-growth event. The contribution is not a new ML algorithm but a working composition pattern that generalizes to other infrastructure-operations problems.

---

## Character count check

Paste the abstract text (without these instructions) into a
character counter. It should land between 1700-1900 characters.
arXiv's hard limit is 1920. If you find yourself trimming further,
remove sentences from the second paragraph first (the technical
detail) — keep the problem framing and the contribution statement.

## Tips

- Avoid LaTeX commands in the abstract field — arXiv displays it
  as plain text. Use "USD 300K" not "\$300K"; em-dashes can stay
  as `—` or be replaced with `--`.
- Don't reference figures or section numbers — the abstract is
  shown standalone.
- Don't include URLs in the abstract — those go in the Comments
  field.
