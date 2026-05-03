# Demo host — a tiny Linux container that simulates one production server.
# Each container runs an in-process telemetry agent that:
#   - Self-registers in the `hosts` table on startup
#   - Reports disk usage every REPORT_INTERVAL_SEC to TimescaleDB
# The "monitored path" inside this container has a configured virtual size
# (VIRTUAL_TOTAL_GB), so the UI's "Fill disk" button can write actual files
# into that path and the reported in_use_pct moves accordingly.

FROM python:3.12-slim

# Tools the LLM agent will exec in the container during remediation
RUN apt-get update && apt-get install -y --no-install-recommends \
    coreutils findutils gzip \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent.py ./agent.py

# The path each demo host monitors. Override per-container via env.
ENV MONITORED_PATH=/var/log
ENV REPORT_INTERVAL_SEC=60

CMD ["python", "/app/agent.py"]
