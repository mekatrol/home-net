#!/bin/bash
# Deploy the watchdog WebSocket client to all monitored devices.
#
# This is the TEMPLATE — do not put real credentials here.
# Copy this file to secrets/deploy-all.sh and fill in the real values there.
#
# Usage:
#   ./secrets/deploy-all.sh
#
# Requires sshpass:
#   sudo apt-get install -y sshpass

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_SH="$SCRIPT_DIR/scripts/deploy.sh"

# Shared config — same token across all devices (must match server config)
WS_SERVER_URL="wss://ai.lan:8765"
WS_TOKEN="change-me-to-something-secret"

deploy() {
    local target="$1"         # user@host
    local device_name="$2"    # slug matching server config device_name
    local heartbeat="${3:-30}" # heartbeat interval in seconds

    echo ""
    echo "========================================"
    echo "Deploying to $target ($device_name)"
    echo "========================================"

    local ssh_pass
    read -rsp "  SSH password for $target: " ssh_pass
    echo ""

    SSH_PASS="$ssh_pass" \
    WS_URL="$WS_SERVER_URL" \
    WS_DEVICE_NAME="$device_name" \
    WS_TOKEN="$WS_TOKEN" \
    HEARTBEAT="$heartbeat" \
    "$DEPLOY_SH" "$target"
}

# deploy <user@host> <device-name> [heartbeat-interval]
deploy "pi@device1.lan"  "device1"  "30"
deploy "pi@device2.lan"  "device2"  "30"
