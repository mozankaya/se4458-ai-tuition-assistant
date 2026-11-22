#!/bin/bash
# Deploy the AI Tuition Assistant to a Google Cloud VM (Compute Engine) with docker compose.
#
# Run in Google Cloud Shell (gcloud is pre-installed and logged in):
#   git clone https://github.com/mozankaya/se4458-ai-tuition-assistant.git
#   cd se4458-ai-tuition-assistant && bash deploy/gcp/deploy.sh
#
# Creates:
#   - firewall rule "tuition-allow-public": TCP 8000 (Kong gateway) and 8001 (MCP server) only;
#     PostgreSQL and the Tuition API are not reachable from the internet
#   - VM "tuition-vm" (Debian 12, e2-medium) whose startup script installs Docker and runs
#     PostgreSQL, Tuition API, MCP server and Kong with docker compose
#
# Delete everything afterwards:
#   gcloud compute instances delete tuition-vm --zone "$ZONE" --quiet
#   gcloud compute firewall-rules delete tuition-allow-public --quiet
set -euo pipefail

ZONE="${ZONE:-europe-west1-b}"
VM="${VM:-tuition-vm}"
MACHINE_TYPE="${MACHINE_TYPE:-e2-medium}"
FIREWALL_RULE="tuition-allow-public"
TAG="tuition"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

PROJECT="$(gcloud config get-value project 2>/dev/null)"
if [ -z "$PROJECT" ]; then
    echo "No project selected. Run: gcloud config set project <PROJECT_ID>" >&2
    exit 1
fi
echo "==> Project: $PROJECT, zone: $ZONE, VM: $VM ($MACHINE_TYPE)"

echo "==> Enabling the Compute Engine API (first time may take a minute)"
gcloud services enable compute.googleapis.com

echo "==> Firewall rule (gateway 8000, MCP 8001)"
if ! gcloud compute firewall-rules describe "$FIREWALL_RULE" >/dev/null 2>&1; then
    gcloud compute firewall-rules create "$FIREWALL_RULE" \
        --direction=INGRESS --action=ALLOW --rules=tcp:8000,tcp:8001 \
        --source-ranges=0.0.0.0/0 --target-tags="$TAG" \
        --description="AI Tuition Assistant: Kong gateway and MCP server"
fi

echo "==> Virtual machine"
if ! gcloud compute instances describe "$VM" --zone "$ZONE" >/dev/null 2>&1; then
    gcloud compute instances create "$VM" \
        --zone "$ZONE" --machine-type "$MACHINE_TYPE" \
        --image-family debian-12 --image-project debian-cloud \
        --boot-disk-size 20GB --tags "$TAG" \
        --metadata-from-file startup-script="$SCRIPT_DIR/vm-startup.sh"
else
    # Re-run the startup script on an existing VM (pulls the latest code and restarts the stack).
    gcloud compute instances add-metadata "$VM" --zone "$ZONE" \
        --metadata-from-file startup-script="$SCRIPT_DIR/vm-startup.sh"
    gcloud compute ssh "$VM" --zone "$ZONE" --command "sudo google_metadata_script_runner startup"
fi

IP="$(gcloud compute instances describe "$VM" --zone "$ZONE" \
    --format='get(networkInterfaces[0].accessConfigs[0].natIP)')"
echo "==> External IP: $IP"

echo "==> Waiting for the stack (Docker install and image builds take about 5-10 minutes)"
for i in $(seq 1 60); do
    if curl -fs -m 5 "http://$IP:8000/api/v1/health" >/dev/null && curl -fs -m 5 "http://$IP:8001/health" >/dev/null; then
        echo "    ready"
        break
    fi
    echo "    not ready yet ($i/60)"
    sleep 15
done

cat <<EOF

==> Deployment finished
    Gateway (REST):  http://$IP:8000
    Swagger UI:      http://$IP:8000/docs
    MCP server:      http://$IP:8001/mcp

    Point the local agent at the cloud by setting in .env:
      GATEWAY_BASE_URL=http://$IP:8000
      MCP_SERVER_URL=http://$IP:8001/mcp

    Demo password on the VM:
      gcloud compute ssh $VM --zone $ZONE --command "sudo grep SEED_DEMO_PASSWORD /opt/tuition/.env"
    Startup log:
      gcloud compute ssh $VM --zone $ZONE --command "sudo tail -n 50 /var/log/tuition-startup.log"
EOF
