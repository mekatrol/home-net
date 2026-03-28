#!/bin/bash
# Deploy the MQTT ping service and watchdog SSH access to a remote Pi.
#
# What this script does (all steps are idempotent):
#
#   Watchdog SSH access (enables the monitor container to reboot this device):
#     1. Creates the 'watchdog' OS user with a locked-down shell
#     2. Installs watchdog-dispatch — the SSH command allowlist enforcer
#     3. Configures sudoers so watchdog can only run permitted binaries
#     4. Installs the watchdog public key, restricted to the dispatcher
#     5. Verifies the dispatcher rejects unknown commands
#
#   MQTT ping service (lets the watchdog detect if this device goes silent):
#     6.  Installs Python dependencies (python3-venv, python3-pip via apt)
#     7.  Copies the ping service files to /opt/ping
#     8.  Writes /etc/ping/config.yaml with the MQTT broker and topic you specify
#     9.  Creates the 'ping-svc' system user and log directory
#     10. Sets up a Python venv and installs pip dependencies
#     11. Installs and enables the systemd ping.service
#     12. Starts (or restarts) the service and shows its status
#
# Usage:
#   ./scripts/deploy.sh <user@host> [ssh-key-path]
#
# Examples:
#   ./scripts/deploy.sh pi@ntp.lan
#   ./scripts/deploy.sh pi@ntp.lan ~/.ssh/id_rsa
#
# Prerequisites:
#   - secrets/watchdog_key.pub  (generate with: ssh-keygen -t ed25519 -f secrets/watchdog_key -N "")
#   - remote/watchdog-dispatch  (already in repo)

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
REPO_DIR="$SCRIPT_DIR/.."
SECRETS_DIR="$REPO_DIR/secrets"
DEPLOY_DIR="$REPO_DIR/deploy"
PUBKEY_FILE="$SECRETS_DIR/watchdog_key.pub"
WATCHDOG_KEY="$SECRETS_DIR/watchdog_key"
DISPATCH_FILE="$REPO_DIR/remote/watchdog-dispatch"

step() {
    echo ""
    echo "==> $*"
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ ! -f "$PUBKEY_FILE" ]; then
    echo "Error: $PUBKEY_FILE not found." >&2
    echo "Generate a key pair first:" >&2
    echo "  ssh-keygen -t ed25519 -f $SECRETS_DIR/watchdog_key -N \"\" -C home-monitor-watchdog" >&2
    exit 1
fi

if [ ! -f "$DISPATCH_FILE" ]; then
    echo "Error: $DISPATCH_FILE not found." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Prompt for MQTT config
# ---------------------------------------------------------------------------

echo "MQTT ping configuration for $TARGET"
read -rp "  Broker hostname/IP [mqtt.lan]: " MQTT_BROKER
MQTT_BROKER="${MQTT_BROKER:-mqtt.lan}"

read -rp "  Port [1883]: " MQTT_PORT
MQTT_PORT="${MQTT_PORT:-1883}"

read -rp "  Topic (e.g. ntp/ping): " MQTT_TOPIC
while [ -z "$MQTT_TOPIC" ]; do
    read -rp "  Topic (required): " MQTT_TOPIC
done

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

# ---------------------------------------------------------------------------
# SSH connection — one password prompt for the entire script
# ---------------------------------------------------------------------------

CONTROL_SOCKET="/tmp/deploy-$$"

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

step "Opening SSH connection to $TARGET"
ssh "${SSH_OPTS[@]}" -O check "$TARGET" 2>/dev/null || ssh "${SSH_OPTS[@]}" -MNf "$TARGET"

cleanup() {
    ssh "${SSH_OPTS[@]}" -O exit "$TARGET" 2>/dev/null || true
}
trap cleanup EXIT

ssh_run() {
    ssh "${SSH_OPTS[@]}" "$TARGET" "$@"
}

# Copy a local file to a remote path via /tmp (avoids needing write perms on dst dir)
scp_file() {
    local src="$1" dst="$2"
    local tmp="/tmp/deploy-$(basename "$src")"
    scp "${SSH_OPTS[@]}" "$src" "$TARGET:$tmp"
    ssh_run "sudo mv $tmp $dst"
}

# ---------------------------------------------------------------------------
# 1. Create watchdog user
# ---------------------------------------------------------------------------

step "Creating watchdog user (if not exists)"
if ! ssh_run "id watchdog" &>/dev/null; then
    ssh_run "sudo useradd -m -s /bin/bash watchdog"
    echo "    User 'watchdog' created."
else
    echo "    User 'watchdog' already exists."
fi
ssh_run "sudo mkdir -p /home/watchdog/.ssh"
ssh_run "sudo chmod 700 /home/watchdog/.ssh"
ssh_run "sudo chown -R watchdog:watchdog /home/watchdog/.ssh"

# ---------------------------------------------------------------------------
# 2. Install watchdog-dispatch
# ---------------------------------------------------------------------------

step "Installing watchdog-dispatch"
scp_file "$DISPATCH_FILE" /usr/local/bin/watchdog-dispatch
ssh_run "sudo chown root:root /usr/local/bin/watchdog-dispatch"
ssh_run "sudo chmod 755 /usr/local/bin/watchdog-dispatch"

# ---------------------------------------------------------------------------
# 3. Configure sudoers
# ---------------------------------------------------------------------------

step "Configuring sudoers for watchdog"
ssh_run "sudo tee /etc/sudoers.d/watchdog > /dev/null" <<'EOF'
watchdog ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/bin/apt, /usr/bin/apt-get
EOF
ssh_run "sudo chmod 440 /etc/sudoers.d/watchdog"

# ---------------------------------------------------------------------------
# 4. Authorize public key (restricted to dispatcher)
# ---------------------------------------------------------------------------

step "Authorizing watchdog_key.pub on remote"
PUBKEY=$(cat "$PUBKEY_FILE")
ssh_run "sudo tee /home/watchdog/.ssh/authorized_keys > /dev/null" <<EOF
command="/usr/local/bin/watchdog-dispatch",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $PUBKEY
EOF
ssh_run "sudo chmod 600 /home/watchdog/.ssh/authorized_keys"
ssh_run "sudo chown watchdog:watchdog /home/watchdog/.ssh/authorized_keys"

# ---------------------------------------------------------------------------
# 5. Test dispatcher
# ---------------------------------------------------------------------------

step "Testing watchdog SSH connection"
if [ -f "$WATCHDOG_KEY" ]; then
    if ssh -i "$WATCHDOG_KEY" -o StrictHostKeyChecking=no -l watchdog "${TARGET#*@}" "unknown-command" 2>&1 | grep -q "not permitted"; then
        echo "    Dispatcher is working — unknown commands are rejected."
    else
        echo "    Warning: could not verify dispatcher rejects unknown commands."
    fi
else
    echo "    Skipping test — private key not found at $WATCHDOG_KEY"
fi

# ---------------------------------------------------------------------------
# 6. Install Python system dependencies
# ---------------------------------------------------------------------------

step "Installing Python system dependencies"
ssh_run "sudo apt-get install -y -q python3-pip python3-venv"

# ---------------------------------------------------------------------------
# 7. Copy ping service files
# ---------------------------------------------------------------------------

step "Copying ping service files to /opt/ping"
ssh_run "sudo mkdir -p /opt/ping"
scp_file "$DEPLOY_DIR/main.py"          /opt/ping/main.py
scp_file "$DEPLOY_DIR/requirements.txt" /opt/ping/requirements.txt

# ---------------------------------------------------------------------------
# 8. Write MQTT config
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

# ---------------------------------------------------------------------------
# 9. Create ping-svc user and log directory
# ---------------------------------------------------------------------------

step "Creating service user 'ping-svc' (if not exists)"
if ! ssh_run "id ping-svc" &>/dev/null; then
    ssh_run "sudo useradd --system --no-create-home --shell /usr/sbin/nologin ping-svc"
    echo "    User 'ping-svc' created."
else
    echo "    User 'ping-svc' already exists."
fi
ssh_run "sudo mkdir -p /var/log/ping"
ssh_run "sudo chown root:ping-svc /etc/ping/config.yaml"
ssh_run "sudo chmod 640 /etc/ping/config.yaml"
ssh_run "sudo chown ping-svc:ping-svc /var/log/ping"

# ---------------------------------------------------------------------------
# 10. Set up Python venv
# ---------------------------------------------------------------------------

step "Setting up Python venv at /opt/ping/.venv"
ssh_run "sudo chown -R ping-svc:ping-svc /opt/ping"
ssh_run "sudo -u ping-svc python3 -m venv /opt/ping/.venv"
ssh_run "sudo -u ping-svc /opt/ping/.venv/bin/pip install --quiet --no-cache-dir -r /opt/ping/requirements.txt"

# ---------------------------------------------------------------------------
# 11. Install systemd service
# ---------------------------------------------------------------------------

step "Installing systemd service"
scp_file "$DEPLOY_DIR/ping.service" /etc/systemd/system/ping.service
ssh_run "sudo systemctl daemon-reload"

# ---------------------------------------------------------------------------
# 12. Enable and restart service
# ---------------------------------------------------------------------------

step "Enabling and restarting ping service"
ssh_run "sudo systemctl enable ping"
ssh_run "sudo systemctl restart ping"

sleep 2
echo ""
echo "==> Service status:"
ssh_run "sudo systemctl status ping --no-pager --lines=10" || true

echo ""
echo "Done."
echo "  Journal logs: ssh ${TARGET} journalctl -u ping -f"
echo "  Log file:     ssh ${TARGET} tail -f /var/log/ping/ping.log"
echo "  Test reboot:  ssh -i ${WATCHDOG_KEY} watchdog@${TARGET#*@} reboot"
