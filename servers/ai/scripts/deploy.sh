#!/bin/bash
# Deploy the watchdog WebSocket client service to a remote Pi.
#
# What this script does (all steps are idempotent):
#
#   Watchdog user setup:
#     1. Creates the 'watchdog' OS user
#     2. Configures sudoers so watchdog can only run reboot and apt-get
#
#   Watchdog WebSocket client service:
#     3.  Installs Python dependencies (python3-venv, python3-pip via apt)
#     4.  Copies service files to /opt/watchdog
#     5.  Writes /etc/watchdog/config.yaml with the server URL, device name, and token
#     6.  Creates the log directory /var/log/watchdog owned by watchdog
#     7.  Sets up a Python venv and installs pip dependencies
#     8.  Installs and enables the systemd watchdog.service
#     9.  Starts (or restarts) the service and shows its status
#
# Usage:
#   ./scripts/deploy.sh <user@host> [ssh-key-path]
#
# Examples:
#   ./scripts/deploy.sh pi@ntp.lan
#   ./scripts/deploy.sh pi@ntp.lan ~/.ssh/id_rsa
#
# Environment variables (bypass interactive prompts for automation):
#   WS_URL          wss://ai.lan:8765
#   WS_DEVICE_NAME  device slug (must match server config)
#   WS_TOKEN        shared auth token
#   HEARTBEAT       heartbeat interval in seconds (default: 30)
#   SSH_PASS        SSH password (uses sshpass)

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
REMOTE_DIR="$REPO_DIR/remote"

step() {
    echo ""
    echo "==> $*"
}

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------

if [ ! -f "$REMOTE_DIR/main.py" ]; then
    echo "Error: $REMOTE_DIR/main.py not found." >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# Config — use env vars if set, otherwise prompt interactively
# ---------------------------------------------------------------------------

if [ -z "${WS_URL:-}" ]; then
    read -rp "  WebSocket server URL [wss://ai.lan:8765]: " WS_URL
    WS_URL="${WS_URL:-wss://ai.lan:8765}"
fi

if [ -z "${WS_DEVICE_NAME:-}" ]; then
    read -rp "  Device name (slug, e.g. pi-nas): " WS_DEVICE_NAME
    while [ -z "$WS_DEVICE_NAME" ]; do
        read -rp "  Device name (required): " WS_DEVICE_NAME
    done
fi

if [ -z "${WS_TOKEN:-}" ]; then
    read -rsp "  Auth token (must match server config): " WS_TOKEN
    echo ""
    while [ -z "$WS_TOKEN" ]; do
        read -rsp "  Auth token (required): " WS_TOKEN
        echo ""
    done
fi

if [ -z "${HEARTBEAT:-}" ]; then
    read -rp "  Heartbeat interval in seconds [30]: " HEARTBEAT
    HEARTBEAT="${HEARTBEAT:-30}"
fi

echo "Deploying to $TARGET (device_name: $WS_DEVICE_NAME, server: $WS_URL)"

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
if [ -n "${SSH_PASS:-}" ]; then
    SSH_CMD=(sshpass -p "$SSH_PASS" ssh)
else
    SSH_CMD=(ssh)
fi
"${SSH_CMD[@]}" "${SSH_OPTS[@]}" -O check "$TARGET" 2>/dev/null || "${SSH_CMD[@]}" "${SSH_OPTS[@]}" -MNf "$TARGET"

cleanup() {
    ssh "${SSH_OPTS[@]}" "$TARGET" "sudo rm -f /etc/sudoers.d/99-deploy-temp" 2>/dev/null || true
    ssh "${SSH_OPTS[@]}" -O exit "$TARGET" 2>/dev/null || true
}
trap cleanup EXIT

if [ -n "${SSH_PASS:-}" ]; then
    step "Granting temporary passwordless sudo"
    REMOTE_USER="${TARGET%%@*}"
    printf '%s\n' "$SSH_PASS" | \
        ssh "${SSH_OPTS[@]}" "$TARGET" \
        "sudo -S bash -c 'printf \"%s ALL=(ALL) NOPASSWD: ALL\n\" \"$REMOTE_USER\" > /etc/sudoers.d/99-deploy-temp && chmod 440 /etc/sudoers.d/99-deploy-temp'"
fi

ssh_run() {
    ssh "${SSH_OPTS[@]}" "$TARGET" "$@"
}

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

# ---------------------------------------------------------------------------
# 2. Configure sudoers for watchdog
# ---------------------------------------------------------------------------

step "Configuring sudoers for watchdog"
ssh_run "sudo tee /etc/sudoers.d/watchdog > /dev/null" <<'EOF'
watchdog ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/bin/apt-get
EOF
ssh_run "sudo chmod 440 /etc/sudoers.d/watchdog"

# ---------------------------------------------------------------------------
# 3. Install Python system dependencies
# ---------------------------------------------------------------------------

step "Installing Python system dependencies"
ssh_run "sudo apt-get update -q"
ssh_run "sudo apt-get install -y -q python3-pip python3-venv"

# ---------------------------------------------------------------------------
# 4. Copy watchdog service files
# ---------------------------------------------------------------------------

step "Copying watchdog service files to /opt/watchdog"
ssh_run "sudo mkdir -p /opt/watchdog"
scp_file "$REMOTE_DIR/main.py"          /opt/watchdog/main.py
scp_file "$REMOTE_DIR/requirements.txt" /opt/watchdog/requirements.txt

# ---------------------------------------------------------------------------
# 5. Write config
# ---------------------------------------------------------------------------

step "Writing /etc/watchdog/config.yaml"
ssh_run "sudo mkdir -p /etc/watchdog"
ssh_run "sudo tee /etc/watchdog/config.yaml > /dev/null" <<EOF
server:
  url: "${WS_URL}"
  device_name: "${WS_DEVICE_NAME}"
  token: "${WS_TOKEN}"

heartbeat_interval: ${HEARTBEAT}
EOF
ssh_run "sudo chown root:watchdog /etc/watchdog/config.yaml"
ssh_run "sudo chmod 640 /etc/watchdog/config.yaml"

# ---------------------------------------------------------------------------
# 6. Create log directory
# ---------------------------------------------------------------------------

step "Creating log directory /var/log/watchdog"
ssh_run "sudo mkdir -p /var/log/watchdog"
ssh_run "sudo chown watchdog:watchdog /var/log/watchdog"

# ---------------------------------------------------------------------------
# 7. Set up Python venv
# ---------------------------------------------------------------------------

step "Setting up Python venv at /opt/watchdog/.venv"
ssh_run "sudo chown -R watchdog:watchdog /opt/watchdog"
ssh_run "sudo -u watchdog python3 -m venv /opt/watchdog/.venv"
ssh_run "sudo -u watchdog /opt/watchdog/.venv/bin/pip install --quiet --no-cache-dir -r /opt/watchdog/requirements.txt"

# ---------------------------------------------------------------------------
# 8 & 9. Install systemd service (skipped in containers without systemd)
# ---------------------------------------------------------------------------

HAS_SYSTEMD=$(ssh_run "ps -p 1 -o comm=" 2>/dev/null | grep -q systemd && echo yes || echo no)

if [ "$HAS_SYSTEMD" = "yes" ]; then
    step "Installing systemd service"
    scp_file "$REMOTE_DIR/watchdog.service" /etc/systemd/system/watchdog.service
    ssh_run "sudo systemctl daemon-reload"

    step "Enabling and starting watchdog service"
    ssh_run "sudo systemctl enable watchdog"
    ssh_run "sudo systemctl restart watchdog"

    sleep 2
    echo ""
    echo "==> Service status:"
    ssh_run "sudo systemctl status watchdog --no-pager --lines=10" || true

    echo ""
    echo "Done."
    echo "  Journal logs: ssh ${TARGET} journalctl -u watchdog -f"
    echo "  Log file:     ssh ${TARGET} tail -f /var/log/watchdog/watchdog.log"
else
    echo ""
    echo "  No systemd detected (container) — skipping auto-start configuration."
    echo "  Starting watchdog now..."
    ssh_run "sudo -u watchdog bash -c 'nohup /opt/watchdog/.venv/bin/python /opt/watchdog/main.py >> /var/log/watchdog/watchdog.log 2>&1 &'"
    echo ""
    echo "Done."
    echo "  To start on boot, add this to your container boot script:"
    echo "    [ -f /opt/watchdog/.venv/bin/python ] && sudo -u watchdog bash -c 'nohup /opt/watchdog/.venv/bin/python /opt/watchdog/main.py >> /var/log/watchdog/watchdog.log 2>&1 &'"
    echo ""
    echo "  Log file: ssh ${TARGET} tail -f /var/log/watchdog/watchdog.log"
fi
