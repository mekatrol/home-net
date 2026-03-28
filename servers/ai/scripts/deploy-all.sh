#!/bin/bash
# Deploy the ping service and watchdog SSH access to all monitored devices.
#
# This is the TEMPLATE — do not put real credentials here.
# Copy this file to secrets/deploy-all.sh and fill in the real values there.
#
# Usage:
#   ./secrets/deploy-all.sh
#
# Requires sshpass for non-interactive SSH:
#   sudo apt-get install -y sshpass

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
DEPLOY_SH="$SCRIPT_DIR/scripts/deploy.sh"

deploy() {
    local target="$1"        # user@host
    local ssh_pass="$2"      # SSH password for initial connection
    local mqtt_topic="$3"    # MQTT topic this device publishes pings on
    local mqtt_broker="${4:-mqtt.lan}"
    local mqtt_port="${5:-1883}"
    local mqtt_user="${6:-}"
    local mqtt_pass="${7:-}"
    local ping_interval="${8:-60}"

    echo ""
    echo "========================================"
    echo "Deploying to $target"
    echo "========================================"

    SSH_PASS="$ssh_pass" \
    MQTT_BROKER="$mqtt_broker" \
    MQTT_PORT="$mqtt_port" \
    MQTT_TOPIC="$mqtt_topic" \
    PING_INTERVAL="$ping_interval" \
    MQTT_USER="$mqtt_user" \
    MQTT_PASS="$mqtt_pass" \
    "$DEPLOY_SH" "$target"
}

# deploy <user@host> <ssh-password> <mqtt-topic> [broker] [port] [mqtt-user] [mqtt-pass] [interval]
deploy "pi@device1.lan"  "ssh-password-here"  "device1/ping"  "mqtt.lan"  "1883"  "watchdog"  "mqtt-password-here"  "60"
deploy "pi@device2.lan"  "ssh-password-here"  "device2/ping"  "mqtt.lan"  "1883"  "watchdog"  "mqtt-password-here"  "60"
