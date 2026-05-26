#!/bin/bash
set -e

echo "=== Syncing project files to remote server ==="
rsync -avz --delete \
  --exclude '.git/' \
  --exclude '.venv/' \
  --exclude '**/__pycache__/' \
  --exclude '.pytest_cache/' \
  --exclude 'build/' \
  --exclude 'dist/' \
  --exclude '*.egg-info/' \
  --exclude '.env' \
  --exclude 'file:test_saas_memdb' \
  ./ zakup:/opt/belzakupki

echo "=== Running remote deployment ==="
ssh zakup "cd /opt/belzakupki && \
  echo 'Initializing .env file if it does not exist...' && \
  [ ! -f .env ] && cp .env.example .env || true && \
  echo 'Building containers...' && \
  docker compose -f docker-compose.prod.yml build && \
  echo 'Starting database and redis...' && \
  docker compose -f docker-compose.prod.yml up -d db redis && \
  echo 'Running migrations...' && \
  docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head && \
  echo 'Starting web app and worker...' && \
  docker compose -f docker-compose.prod.yml up -d api worker caddy && \
  echo 'Cleaning up old unused Docker resources...' && \
  docker system prune -f"

echo "=== Deployment finished successfully! ==="
