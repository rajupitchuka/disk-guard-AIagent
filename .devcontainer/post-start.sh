#!/usr/bin/env bash
# Run every time the Codespaces container starts. Idempotent.
# Boots the data + AI stack, seeds the demo data, runs one ML cycle,
# and prints next-step instructions.

set -euo pipefail

echo "==> Starting Disk Guard AI Agent stack..."
cd /workspaces/opsgpt-disk-prediction-poc

# Bring up the docker-compose stack (TimescaleDB, pgvector, Redis,
# 3 demo containers)
docker compose up -d

# Wait for DBs to be healthy (max 60 s)
echo "==> Waiting for databases to become healthy..."
for i in {1..30}; do
    if docker compose ps --format json | python3 -c "
import json, sys
running = [json.loads(l) for l in sys.stdin if l.strip()]
healthy = sum(1 for c in running if c.get('Health') == 'healthy')
sys.exit(0 if healthy >= 3 else 1)
" 2>/dev/null; then
        echo "  ✓ all databases healthy"
        break
    fi
    sleep 2
done

# shellcheck disable=SC1091
source .venv/bin/activate

# Check if the fleet is already seeded; if not, seed it
HOST_COUNT=$(docker exec opsgpt_timescaledb psql -U opsgpt -d opsgpt_telemetry -tAc "SELECT COUNT(*) FROM hosts" 2>/dev/null || echo "0")
HOST_COUNT=${HOST_COUNT// /}  # trim whitespace

if [[ "$HOST_COUNT" -lt 50 ]]; then
    echo "==> Fleet not seeded (have $HOST_COUNT hosts). Seeding now..."
    PYTHONPATH=. python data/synthetic_generator.py --hosts 50 --days 7 --interval-min 5
    PYTHONPATH=. python data/seed_demo_hosts.py --days 7 --interval-min 5
    PYTHONPATH=. python data/seed_runbooks.py
    PYTHONPATH=. python -m services.ml_engine --train
    PYTHONPATH=. python -m services.ml_engine --once
else
    echo "==> Fleet already seeded ($HOST_COUNT hosts), skipping seed step"
fi

# Set ANTHROPIC_API_KEY hint if not configured
if [[ -f .env ]] && grep -q "ANTHROPIC_API_KEY=sk-ant-" .env; then
    echo "==> ANTHROPIC_API_KEY found in .env"
else
    echo ""
    echo "  ⚠️  ANTHROPIC_API_KEY is not set in .env"
    echo "     The Streamlit UI will work but the LLM agent (Stage 3) will fail."
    echo "     Get a key at console.anthropic.com and add it to .env:"
    echo "       cp .env.example .env && nano .env"
fi

echo ""
echo "============================================================"
echo " Disk Guard AI Agent is ready."
echo ""
echo " Open the Streamlit UI: http://localhost:8501"
echo " (Codespaces will pop a port-forwarding notification)"
echo ""
echo " Quick demo:"
echo "   1. Click on demo-app-01 from the Fleet Overview"
echo "   2. Stage 1: Fill the disk"
echo "   3. Stage 2: Run ML Prediction"
echo "   4. Stage 3: Run Reasoning  (requires ANTHROPIC_API_KEY)"
echo "   5. Stage 4: Resolve"
echo ""
echo " Reset for a fresh demo: ./scripts/demo_reset.sh"
echo "============================================================"

# Auto-launch Streamlit in background on container start
nohup bash -c '
    cd /workspaces/opsgpt-disk-prediction-poc
    source .venv/bin/activate
    KMP_DUPLICATE_LIB_OK=TRUE OMP_NUM_THREADS=1 \
        streamlit run ui/home.py \
        --server.headless true \
        --server.port 8501 \
        --server.address 0.0.0.0 \
        > /tmp/streamlit.log 2>&1
' > /dev/null 2>&1 &

echo "  Streamlit launching in background..."
echo "  Check logs: tail -f /tmp/streamlit.log"
