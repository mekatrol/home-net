#!/bin/bash
# Deploy the ping service and watchdog SSH access to all monitored devices.
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

deploy() {
    local target="$1"        # user@host
    local mqtt_topic="$2"    # MQTT topic this device publishes pings on
    local mqtt_broker="${3:-mqtt.lan}"
    local mqtt_port="${4:-1883}"
    local mqtt_user="${5:-}"
    local mqtt_pass="${6:-}"
    local ping_interval="${7:-60}"

    echo ""
    echo "========================================"
    echo "Deploying to $target"
    echo "========================================"

    local ssh_pass
    read -rsp "  SSH password for $target: " ssh_pass
    echo ""

    SSH_PASS="$ssh_pass" \
    MQTT_BROKER="$mqtt_broker" \
    MQTT_PORT="$mqtt_port" \
    MQTT_TOPIC="$mqtt_topic" \
    PING_INTERVAL="$ping_interval" \
    MQTT_USER="$mqtt_user" \
    MQTT_PASS="$mqtt_pass" \
    "$DEPLOY_SH" "$target"
}

# deploy <user@host> <mqtt-topic> [broker] [port] [mqtt-user] [mqtt-pass] [interval]
deploy "pi@device1.lan"  "device1/ping"  "mqtt.lan"  "1883"  "watchdog"  "mqtt-password-here"  "60"
deploy "pi@device2.lan"  "device2/ping"  "mqtt.lan"  "1883"  "watchdog"  "mqtt-password-here"  "60"
