#!/bin/bash
# Remove the watchdog service from all monitored devices.
#
# This is the TEMPLATE — do not put real credentials here.
# Copy this file to secrets/remove-all.sh and fill in the real device list.
#
# Usage:
#   ./secrets/remove-all.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REMOVE_SH="$SCRIPT_DIR/scripts/remove.sh"

remove() {
    local target="$1"   # user@host

    echo ""
    echo "========================================"
    echo "Removing from $target"
    echo "========================================"

    local ssh_pass
    read -rsp "  SSH password for $target: " ssh_pass
    echo ""

    SSH_PASS="$ssh_pass" "$REMOVE_SH" "$target"
}

# remove <user@host>
remove "pi@device1.lan"
remove "pi@device2.lan"
