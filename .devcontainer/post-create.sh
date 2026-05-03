#!/usr/bin/env bash
# Run once when the Codespaces container is first created.
# Sets up the Python venv and installs dependencies.

set -euo pipefail

echo "==> Setting up Disk Guard AI Agent dev container..."

cd /workspaces/opsgpt-disk-prediction-poc

# Native dependency: libomp (XGBoost on Linux uses libgomp; pre-installed
# on Bookworm, but ensure it's present)
sudo apt-get update -qq
sudo apt-get install -y -qq libgomp1 build-essential

# Python venv
echo "==> Creating Python virtual environment..."
python3 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip

echo "==> Installing project dependencies (this takes 3-5 minutes)..."
pip install --quiet -e ".[dev]"

# Pre-pull Docker images so 'docker compose up' is instant later
echo "==> Pre-pulling Docker images (background)..."
docker pull timescale/timescaledb:2.17.2-pg17 &
docker pull pgvector/pgvector:pg17 &
docker pull redis:7.4-alpine &
wait

echo ""
echo "==> Setup complete. Next: run .devcontainer/post-start.sh (auto-runs on container start)"
echo "==> Or manually: docker compose up -d && python data/synthetic_generator.py --hosts 50 --days 7"
