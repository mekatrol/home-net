#!/bin/bash
# Remove everything deployed by deploy.sh from a remote Pi.
#
# What this script removes:
#   Watchdog service:
#     1. Stops and disables the watchdog systemd service
#     2. Removes the service file and reloads systemd
#     3. Removes /opt/watchdog (app files and venv)
#     4. Removes /etc/watchdog (config)
#     5. Removes /var/log/watchdog (logs)
#
#   Watchdog user:
#     6. Removes /etc/sudoers.d/watchdog
#     7. Removes the watchdog user and home directory
#
# Usage:
#   ./scripts/remove.sh <user@host> [ssh-key-path]
#
# Examples:
#   ./scripts/remove.sh pi@ntp.lan
#   ./scripts/remove.sh pi@ntp.lan ~/.ssh/id_rsa

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

step() {
    echo ""
    echo "==> $*"
}

# ---------------------------------------------------------------------------
# SSH connection
# ---------------------------------------------------------------------------

CONTROL_SOCKET="/tmp/remove-$$"

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

# ---------------------------------------------------------------------------
# 1. Stop and disable watchdog service
# ---------------------------------------------------------------------------

step "Stopping and disabling watchdog service"
if ssh_run "systemctl is-active watchdog 2>/dev/null" &>/dev/null; then
    ssh_run "sudo systemctl stop watchdog"
    echo "    Service stopped."
else
    echo "    Service not running."
fi
if ssh_run "systemctl is-enabled watchdog 2>/dev/null" &>/dev/null; then
    ssh_run "sudo systemctl disable watchdog"
    echo "    Service disabled."
fi

# ---------------------------------------------------------------------------
# 2. Remove service file
# ---------------------------------------------------------------------------

step "Removing systemd service file"
ssh_run "sudo rm -f /etc/systemd/system/watchdog.service"
ssh_run "sudo systemctl daemon-reload"

# ---------------------------------------------------------------------------
# 3–5. Remove app files, config, and logs
# ---------------------------------------------------------------------------

step "Removing /opt/watchdog"
ssh_run "sudo rm -rf /opt/watchdog"

step "Removing /etc/watchdog"
ssh_run "sudo rm -rf /etc/watchdog"

step "Removing /var/log/watchdog"
ssh_run "sudo rm -rf /var/log/watchdog"

# ---------------------------------------------------------------------------
# 6. Remove sudoers entry
# ---------------------------------------------------------------------------

step "Removing sudoers entry for watchdog"
ssh_run "sudo rm -f /etc/sudoers.d/watchdog"

# ---------------------------------------------------------------------------
# 7. Remove watchdog user
# ---------------------------------------------------------------------------

step "Removing watchdog user"
if ssh_run "id watchdog" &>/dev/null; then
    ssh_run "sudo userdel -r watchdog"
    echo "    User 'watchdog' removed."
else
    echo "    User 'watchdog' does not exist."
fi

echo ""
echo "Done. $TARGET has been cleaned up."
