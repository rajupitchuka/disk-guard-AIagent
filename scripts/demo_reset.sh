#!/usr/bin/env bash
# OpsGPT POC — fresh-demo reset.
#
# Wipes runtime state (predictions, agent runs, tickets, demo-host telemetry)
# but KEEPS the synthetic 50-host fleet seed + 7-day historical telemetry +
# the trained XGBoost model. Re-aligns the demo containers' disks to their
# baseline so the next demo starts in a known clean state.
#
# Usage:
#   ./scripts/demo_reset.sh          # reset to clean baseline
#   ./scripts/demo_reset.sh --full   # also re-seed simulated fleet + RAG corpus

set -euo pipefail

cd "$(dirname "$0")/.."

DOCKER_BIN="docker"
if ! command -v docker >/dev/null 2>&1; then
    DOCKER_BIN="/Applications/OrbStack.app/Contents/MacOS/xbin/docker"
fi

FULL=false
if [[ "${1:-}" == "--full" ]]; then
    FULL=true
fi

echo "==> [1/5] Verifying stack is up..."
$DOCKER_BIN compose ps --format json | python3 -c "
import json, sys
running = [json.loads(l) for l in sys.stdin if l.strip()]
needed = {'opsgpt_timescaledb', 'opsgpt_pgvector', 'opsgpt_redis',
          'demo-web-01', 'demo-app-01', 'demo-db-01'}
have = {c['Name'] for c in running if c.get('State') == 'running'}
missing = needed - have
if missing:
    print(f'  missing containers: {sorted(missing)}', file=sys.stderr)
    sys.exit(1)
print('  all containers running')
"

echo "==> [2/5] Wiping runtime state in TimescaleDB..."
$DOCKER_BIN exec opsgpt_timescaledb psql -U opsgpt -d opsgpt_telemetry -q -c "
TRUNCATE servicenow_tickets, agent_runs, ml_predictions CASCADE;
DELETE FROM disk_telemetry WHERE host_id LIKE 'demo-%';
" >/dev/null
echo "  wiped: tickets, agent_runs, ml_predictions, demo-host telemetry"

echo "==> [3/5] Clearing junk files in demo containers..."
for c in demo-web-01 demo-app-01 demo-db-01; do
    monitored=$($DOCKER_BIN exec "$c" printenv MONITORED_PATH || echo "/var/log")
    $DOCKER_BIN exec "$c" sh -c "rm -f $monitored/junk-*.bin $monitored/_seed_baseline.bin $monitored/_aged_baseline.bin $monitored/access.log.* $monitored/app-archive-*" >/dev/null 2>&1 || true
    echo "  cleaned $c:$monitored"
done

if [[ "$FULL" == true ]]; then
    echo "==> [4/5] FULL reset — wiping simulated fleet + RAG corpus..."
    $DOCKER_BIN exec opsgpt_timescaledb psql -U opsgpt -d opsgpt_telemetry -q -c "
    TRUNCATE disk_telemetry;
    DELETE FROM hosts WHERE host_id NOT LIKE 'demo-%';
    " >/dev/null
    $DOCKER_BIN exec opsgpt_pgvector psql -U opsgpt -d opsgpt_rag -q -c "TRUNCATE knowledge_docs;" >/dev/null
    echo "  wiped: simulated fleet + telemetry + RAG corpus"

    echo "==> Re-seeding everything..."
    PYTHONPATH=. python data/synthetic_generator.py --hosts 50 --days 7 --interval-min 5 2>&1 | tail -3
    PYTHONPATH=. python data/seed_runbooks.py 2>&1 | tail -3
    PYTHONPATH=. python -m services.ml_engine --train 2>&1 | tail -2
else
    echo "==> [4/5] Skipping full reset (use --full to re-seed simulated fleet too)"
fi

echo "==> [5/5] Re-seeding demo hosts (fresh history + disk alignment)..."
PYTHONPATH=. python data/seed_demo_hosts.py --days 7 --interval-min 5 2>&1 | tail -5

echo "==> Running ML cycle..."
PYTHONPATH=. python -m services.ml_engine --once 2>&1 | tail -2

echo ""
echo "============================================================"
echo " Demo reset complete. State summary:"
$DOCKER_BIN exec opsgpt_timescaledb psql -U opsgpt -d opsgpt_telemetry -tAc "
SELECT '  hosts:       ' || COUNT(*) FROM hosts UNION ALL
SELECT '  predictions: ' || COUNT(*) FROM ml_predictions UNION ALL
SELECT '  agent_runs:  ' || COUNT(*) FROM agent_runs UNION ALL
SELECT '  tickets:     ' || COUNT(*) FROM servicenow_tickets UNION ALL
SELECT '  triggered:   ' || COUNT(*) FROM (
  SELECT DISTINCT ON (host_id) host_id, triggered_agent
  FROM ml_predictions ORDER BY host_id, ts DESC
) p WHERE triggered_agent;
"
echo "============================================================"
echo "Next: open http://localhost:8501 and start the demo."
