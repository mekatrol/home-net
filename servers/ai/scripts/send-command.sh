#!/bin/bash
# Send a command to a monitored device via the watchdog WebSocket server.
#
# Usage:
#   ./scripts/send-command.sh --list
#   ./scripts/send-command.sh <device-name> <command>
#
# Commands: reboot, upgrade, upgrade_reboot
#
# Examples:
#   ./scripts/send-command.sh --list
#   ./scripts/send-command.sh pi-nas upgrade_reboot
#   ./scripts/send-command.sh ntp-server reboot

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Prefer the watchdog client venv (installed by deploy.sh); fall back to system python3
if [ -x "/opt/watchdog/.venv/bin/python3" ]; then
    PYTHON="/opt/watchdog/.venv/bin/python3"
else
    PYTHON="$(which python3)"
fi

"$PYTHON" "$SCRIPT_DIR/send-command.py" "$@"
