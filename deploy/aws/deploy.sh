#!/bin/bash
# Deploy the AI Tuition Assistant to an AWS EC2 instance with docker compose.
#
# Run in AWS CloudShell (the AWS CLI is pre-installed and logged in):
#   git clone https://github.com/mozankaya/se4458-ai-tuition-assistant.git
#   cd se4458-ai-tuition-assistant && bash deploy/aws/deploy.sh
#
# Creates in the default VPC:
#   - security group "tuition-sg": TCP 8000 (Kong gateway) and 8001 (MCP server) only;
#     PostgreSQL and the Tuition API are not reachable from the internet
#   - EC2 instance "tuition-vm" (Ubuntu 24.04) whose user data runs deploy/gcp/vm-startup.sh:
#     installs Docker and runs PostgreSQL, Tuition API, MCP server and Kong with docker compose
#
# Delete everything afterwards (commands are printed at the end).
set -euo pipefail

export AWS_DEFAULT_REGION="${AWS_REGION:-${AWS_DEFAULT_REGION:-eu-central-1}}"
NAME="tuition-vm"
SG_NAME="tuition-sg"
# Free plan eligible types (accounts created after 15 July 2025): t3.micro, t3.small, t4g.micro,
# t4g.small, c7i-flex.large, m7i-flex.large. c7i-flex.large has 2 vCPU and 4 GB RAM.
INSTANCE_TYPE="${INSTANCE_TYPE:-c7i-flex.large}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
STARTUP="$SCRIPT_DIR/../gcp/vm-startup.sh"

echo "==> Region: $AWS_DEFAULT_REGION, instance type: $INSTANCE_TYPE"
aws sts get-caller-identity --query Account --output text >/dev/null

AMI="$(aws ssm get-parameter \
    --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id \
    --query Parameter.Value --output text)"
VPC="$(aws ec2 describe-vpcs --filters Name=isDefault,Values=true --query 'Vpcs[0].VpcId' --output text)"
if [ "$VPC" = "None" ]; then
    echo "No default VPC in $AWS_DEFAULT_REGION. Create one with: aws ec2 create-default-vpc" >&2
    exit 1
fi
echo "==> Ubuntu image: $AMI, VPC: $VPC"

echo "==> Security group (gateway 8000, MCP 8001)"
SG="$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$SG_NAME" "Name=vpc-id,Values=$VPC" \
    --query 'SecurityGroups[0].GroupId' --output text)"
if [ "$SG" = "None" ]; then
    SG="$(aws ec2 create-security-group --group-name "$SG_NAME" --vpc-id "$VPC" \
        --description "AI Tuition Assistant: Kong gateway and MCP server" --query GroupId --output text)"
    aws ec2 authorize-security-group-ingress --group-id "$SG" \
        --ip-permissions 'IpProtocol=tcp,FromPort=8000,ToPort=8001,IpRanges=[{CidrIp=0.0.0.0/0,Description=gateway-and-mcp}]' \
        >/dev/null
fi

echo "==> EC2 instance"
ID="$(aws ec2 describe-instances \
    --filters "Name=tag:Name,Values=$NAME" "Name=instance-state-name,Values=pending,running,stopping,stopped" \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)"
if [ "$ID" = "None" ]; then
    # The demo password is generated here so it can be shown to you; other secrets stay on the VM.
    DEMO_PASSWORD="demo-$(openssl rand -hex 4)"
    USER_DATA="$(mktemp)"
    { echo '#!/bin/bash'; echo "export SEED_DEMO_PASSWORD=$DEMO_PASSWORD"; tail -n +2 "$STARTUP"; } > "$USER_DATA"
    ID="$(aws ec2 run-instances --image-id "$AMI" --instance-type "$INSTANCE_TYPE" \
        --security-group-ids "$SG" --user-data "file://$USER_DATA" \
        --block-device-mappings 'DeviceName=/dev/sda1,Ebs={VolumeSize=20,VolumeType=gp3}' \
        --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
        --query 'Instances[0].InstanceId' --output text)"
    rm -f "$USER_DATA"
    echo "    created $ID"
else
    DEMO_PASSWORD="(set when the instance was first created)"
    echo "    using existing $ID"
fi
aws ec2 wait instance-running --instance-ids "$ID"
IP="$(aws ec2 describe-instances --instance-ids "$ID" \
    --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)"
echo "==> Public IP: $IP"

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
    Demo password:   $DEMO_PASSWORD   (users student1..student4)

    Point the local agent at the cloud by setting in .env:
      GATEWAY_BASE_URL=http://$IP:8000
      MCP_SERVER_URL=http://$IP:8001/mcp

    Delete everything afterwards:
      aws ec2 terminate-instances --instance-ids $ID
      aws ec2 wait instance-terminated --instance-ids $ID
      aws ec2 delete-security-group --group-id $SG
EOF
