#!/bin/bash
# Startup script for the Google Cloud VM (runs as root on every boot).
# Installs Docker, fetches the repository, creates /opt/tuition/.env with random secrets
# (only on the first boot) and starts PostgreSQL, Tuition API, MCP server and Kong with docker compose.
set -euo pipefail

REPO_URL="https://github.com/mozankaya/se4458-ai-tuition-assistant.git"
APP_DIR=/opt/tuition
LOG=/var/log/tuition-startup.log
exec >>"$LOG" 2>&1
echo "=== startup $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="

if ! command -v docker >/dev/null 2>&1; then
    apt-get update -y
    apt-get install -y ca-certificates curl git
    curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

if [ -d "$APP_DIR/.git" ]; then
    git -C "$APP_DIR" pull --ff-only
else
    git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"

# Secrets are generated on the VM and never leave it (read them with: sudo cat /opt/tuition/.env).
if [ ! -f .env ]; then
    cp .env.example .env
    sed -i \
        -e "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$(openssl rand -hex 16)/" \
        -e "s/^JWT_SECRET=.*/JWT_SECRET=$(openssl rand -hex 32)/" \
        -e "s/^SEED_DEMO_PASSWORD=.*/SEED_DEMO_PASSWORD=demo-$(openssl rand -hex 4)/" \
        .env
    # Keep DATABASE_URL consistent with the generated password (used only by host-side tools).
    PG_PASSWORD=$(grep '^POSTGRES_PASSWORD=' .env | cut -d= -f2)
    sed -i -e "s#://tuition:change-me@#://tuition:${PG_PASSWORD}@#g" .env
    chmod 600 .env
fi

# The test database is not needed in the cloud.
docker compose up -d --build db api mcp gateway
echo "=== stack started ==="
docker compose ps
