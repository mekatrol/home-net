#!/bin/bash
set -euo pipefail

# e.g. to run this script:
# SSH_USER_NAME="ssh" SSH_USER_PASSWORD="pwd" HOSTNAME="ai.lan" DNSHOST="9.9.9.9" TIMEZONE="Australia/Sydney" ./create.sh

require_env() {
    local name="$1"
    if [ -z "${!name:-}" ]; then
        echo "Error: $name must be defined!"
        exit 1
    fi
}

require_env SSH_USER_NAME
require_env SSH_USER_PASSWORD
require_env HOSTNAME
require_env TIMEZONE
require_env DNSHOST

# The name of the image that will be created with 'docker build'
IMAGE_NAME="ai"
IMAGE_TAG="latest"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"

# The name of the container that will be created with docker run
CONTAINER_NAME="ai"

# The name of the network the nginx server will use
NETWORK_NAME="docker-network"

# The driver method used when creating the network if it does not already exist
NETWORK_DRIVER="ipvlan"

# The network interface card used for the network
NETWORK_PARENT="eth0"

# The network subnet
NETWORK_SUBNET="172.16.3.0/24"

# The network gateway
NETWORK_GATEWAY="172.16.3.1"

# Static IP address for the server host
CONTAINER_IP_ADDR="172.16.3.100"

# Check if the network exists
if ! docker network inspect "$NETWORK_NAME" >/dev/null 2>&1; then
    echo "Network '$NETWORK_NAME' does not exist. Creating it..."
    docker network create --driver="$NETWORK_DRIVER" --subnet="$NETWORK_SUBNET" --gateway="$NETWORK_GATEWAY" -o parent="$NETWORK_PARENT" "$NETWORK_NAME"
else
    echo "Network '$NETWORK_NAME' already exists."
fi

echo "Building image '$IMAGE_REF'..."
docker build --pull -t "$IMAGE_REF" \
    --build-arg SSH_USER_NAME="$SSH_USER_NAME" \
    --build-arg TIMEZONE="$TIMEZONE" \
    .

# Remove old container if exists
if docker ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
    echo "Removing existing container '$CONTAINER_NAME'..."
    if docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        docker stop "$CONTAINER_NAME"
    fi
    docker rm "$CONTAINER_NAME"
fi

docker run \
    -itd --init \
    --network="$NETWORK_NAME" \
    --restart=unless-stopped \
    --name="$CONTAINER_NAME" \
    --ip="$CONTAINER_IP_ADDR" \
    --hostname="$HOSTNAME" \
    --dns "$DNSHOST" \
    -v "$PWD/secrets:/run/secrets:ro" \
    -v "$PWD/logs:/var/log/home-monitor" \
    -e SSH_USER_NAME="$SSH_USER_NAME" \
    -e SSH_USER_PASSWORD="$SSH_USER_PASSWORD" \
    "$IMAGE_REF"

printf 'Logs:      docker logs %q --tail=200\n' "$CONTAINER_NAME"