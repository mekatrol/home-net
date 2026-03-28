#!/bin/bash
# Deploy the MQTT ping service to a remote device.
#
# Usage:
#   ./scripts/deploy-ping.sh <user@host> [ssh-key-path]
#
# Examples:
#   ./scripts/deploy-ping.sh pi@ntp.lan
#   ./scripts/deploy-ping.sh pi@ntp.lan ~/.ssh/id_rsa
#
# The script is idempotent — safe to re-run after config changes.
# After deploying, edit /etc/ping/config.yaml on the device to set the
# correct mqtt topic and credentials, then: sudo systemctl restart ping

set -euo pipefail

# ---------------------------------------------------------------------------
# Args
# ---------------------------------------------------------------------------

if [ $# -lt 1 ]; then
    echo "Usage: $0 <user@host> [ssh-key-path]" >&2
    exit 1
fi

TARGET="$1"
SSH_KEY="${2:-}"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_DIR="$SCRIPT_DIR/../deploy"

step() {
    echo ""
    echo "==> $*"
}

# ---------------------------------------------------------------------------
# Prompt for MQTT config
# ---------------------------------------------------------------------------

echo "MQTT configuration for $TARGET"
read -rp "  Broker hostname/IP [mqtt.lan]: " MQTT_BROKER
MQTT_BROKER="${MQTT_BROKER:-mqtt.lan}"

read -rp "  Port [1883]: " MQTT_PORT
MQTT_PORT="${MQTT_PORT:-1883}"

read -rp "  Topic [ntp/ping]: " MQTT_TOPIC
MQTT_TOPIC="${MQTT_TOPIC:-ntp/ping}"

read -rp "  Ping interval in seconds [10]: " PING_INTERVAL
PING_INTERVAL="${PING_INTERVAL:-10}"

read -rp "  MQTT username [watchdog]: " MQTT_USER
MQTT_USER="${MQTT_USER:-watchdog}"
if [ -n "$MQTT_USER" ]; then
    read -rsp "  MQTT password: " MQTT_PASS
    echo ""
else
    MQTT_PASS=""
fi

CONTROL_SOCKET="/tmp/deploy-ping-$$"

SSH_OPTS=(
    -o StrictHostKeyChecking=no
    -o ConnectTimeout=10
    -o ControlMaster=auto
    -o ControlPath="$CONTROL_SOCKET"
    -o ControlPersist=60
)
if [ -n "$SSH_KEY" ]; then
    SSH_OPTS+=(-i "$SSH_KEY")
fi

# Open the master connection once (prompts for password here if needed)
step "Opening SSH connection to $TARGET"
ssh "${SSH_OPTS[@]}" -O check "$TARGET" 2>/dev/null || ssh "${SSH_OPTS[@]}" -MNf "$TARGET"

cleanup() {
    ssh "${SSH_OPTS[@]}" -O exit "$TARGET" 2>/dev/null || true
}
trap cleanup EXIT

ssh_run() {
    ssh "${SSH_OPTS[@]}" "$TARGET" "$@"
}

# Copy src to dst on the remote, via /tmp to avoid permission issues
scp_file() {
    local src="$1" dst="$2"
    local tmp="/tmp/deploy-$(basename "$src")"
    scp "${SSH_OPTS[@]}" "$src" "$TARGET:$tmp"
    ssh_run "sudo mv $tmp $dst"
}

# ---------------------------------------------------------------------------
# 1. Copy files
# ---------------------------------------------------------------------------

step "Copying ping service files to /opt/ping"
ssh_run "sudo mkdir -p /opt/ping"
scp_file "$DEPLOY_DIR/main.py"          /opt/ping/main.py
scp_file "$DEPLOY_DIR/requirements.txt" /opt/ping/requirements.txt

# ---------------------------------------------------------------------------
# 2. Write config from prompted values
# ---------------------------------------------------------------------------

step "Writing /etc/ping/config.yaml"
ssh_run "sudo mkdir -p /etc/ping"
ssh_run "sudo tee /etc/ping/config.yaml > /dev/null" <<EOF
mqtt:
  broker: "${MQTT_BROKER}"
  port: ${MQTT_PORT}
  username: "${MQTT_USER}"
  password: "${MQTT_PASS}"

ping:
  topic: "${MQTT_TOPIC}"
  interval: ${PING_INTERVAL}
EOF
ssh_run "sudo chown root:ping-svc /etc/ping/config.yaml"
ssh_run "sudo chmod 640 /etc/ping/config.yaml"

# ---------------------------------------------------------------------------
# 3. Create service user (idempotent)
# ---------------------------------------------------------------------------

step "Creating service user 'ping-svc' (if not exists)"
if ! ssh_run "id ping-svc" &>/dev/null; then
    ssh_run "sudo useradd --system --no-create-home --shell /usr/sbin/nologin ping-svc"
    echo "    User 'ping-svc' created."
else
    echo "    User 'ping-svc' already exists."
fi
ssh_run "sudo mkdir -p /var/log/ping && sudo chown ping-svc:ping-svc /var/log/ping"

# ---------------------------------------------------------------------------
# 4. Set up Python venv and install dependencies
# ---------------------------------------------------------------------------

step "Installing Python dependencies"
ssh_run "sudo apt-get install -y -q python3-pip python3-venv"

step "Setting up Python venv at /opt/ping/.venv"
ssh_run "sudo chown -R ping-svc:ping-svc /opt/ping"
ssh_run "sudo -u ping-svc python3 -m venv /opt/ping/.venv"
ssh_run "sudo -u ping-svc /opt/ping/.venv/bin/pip install --quiet --no-cache-dir -r /opt/ping/requirements.txt"

# ---------------------------------------------------------------------------
# 5. Install systemd service
# ---------------------------------------------------------------------------

step "Installing systemd service"
scp_file "$DEPLOY_DIR/ping.service" /tmp/ping.service
ssh_run "sudo mv /tmp/ping.service /etc/systemd/system/ping.service"
ssh_run "sudo systemctl daemon-reload"

# ---------------------------------------------------------------------------
# 6. Enable service (idempotent — enable is a no-op if already enabled)
# ---------------------------------------------------------------------------

step "Enabling ping service"
ssh_run "sudo systemctl enable ping"

# ---------------------------------------------------------------------------
# 7. Start / restart service
# ---------------------------------------------------------------------------

step "Restarting ping service"
ssh_run "sudo systemctl restart ping"

sleep 2
echo ""
echo "==> Service status:"
ssh_run "sudo systemctl status ping --no-pager --lines=10" || true

echo ""
echo "Done."
echo "  Journal logs: ssh ${TARGET} journalctl -u ping -f"
echo "  Log file:     ssh ${TARGET} tail -f /var/log/ping/ping.log"
