#!/bin/bash
set -euo pipefail

# e.g. to run this script:
# SSH_USER_NAME="ssh" SSH_USER_PASSWORD="pwd" HOSTNAME="secretsanta.example.com" TIMEZONE="Australia/Sydney" CERTNAME="secretsanta.example.com-rsa" ./create.sh

if [ -z "$SSH_USER_NAME" ]; then
    echo "Error: SSH_USER_NAME must be defined!"
    exit 1
fi

if [ -z "$SSH_USER_PASSWORD" ]; then
    echo "Error: SSH_USER_PASSWORD must be defined!"
    exit 1
fi

if [ -z "$HOSTNAME" ]; then
    echo "Error: HOSTNAME must be defined!"
    exit 1
fi

if [ -z "$TIMEZONE" ]; then
    echo "Error: TIMEZONE must be defined!"
    exit 1
fi

if [ -z "$CERTNAME" ]; then
    echo "Error: CERTNAME must be defined!"
    exit 1
fi

# The name of the image that will be created with 'docker build'
IMAGE_NAME="secretsanta"

# The name of the container that will be created with docker run
CONTAINER_NAME="secretsanta"

# The name of the network the nginx server will use
NETWORK_NAME="docker-network"

# The driver method used when creating the network if it does not already exist
NETWORK_DRIVER="ipvlan"

# The network interface card used for the network
NETWORK_PARENT="eth0"

# The network subnet
NETWORK_SUBNET="10.2.2.0/24"

# The network gateway
NETWORK_GATEWAY="10.2.2.1"

# Static IP address for the server host
CONTAINER_IP_ADDR="10.2.2.235"

# The lets encrypt volume
LETS_ENCRYPT_VOLUME="/data/etc-letsencrypt:/etc/letsencrypt"

# Check if the network exists
if ! docker network ls --format '{{.Name}}' | grep -q "^$NETWORK_NAME$"; then
    echo "Network '$NETWORK_NAME' does not exist. Creating it..."
    docker network create --driver="$NETWORK_DRIVER" --subnet="$NETWORK_SUBNET" --gateway="$NETWORK_GATEWAY" -o parent="$NETWORK_PARENT" "$NETWORK_NAME"
else
    echo "Network '$NETWORK_NAME' already exists."
fi

if ! docker image ls --format '{{.Tag}}' | grep -q "^$IMAGE_NAME$"; then
    echo "Image '$IMAGE_NAME' does not exist. Creating it..."
    docker build -t "$IMAGE_NAME" \
        --build-arg SSH_USER_NAME="$SSH_USER_NAME" \
        --build-arg SSH_USER_PASSWORD="$SSH_USER_PASSWORD" \
        --build-arg HOSTNAME="$HOSTNAME" \
        --build-arg TIMEZONE="$TIMEZONE" \
        --build-arg CERTNAME="$CERTNAME" \
        .
else
    echo "Image '$IMAGE_NAME' already exists."
fi

docker run \
    -itd --network="$NETWORK_NAME" \
    --ip="$CONTAINER_IP_ADDR" \
    -p 8443:8443 \
    -p 80:80 \
    -p 22:22 \
    --name="$CONTAINER_NAME" \
    --hostname="$HOSTNAME" \
    --volume="$LETS_ENCRYPT_VOLUME" \
    "$IMAGE_NAME"

# Check env values set
echo 'docker inspect secretsanta --format '{{json .Config.Env}}' | jq -r '.[]' | grep ASPNETCORE_'

# E.g. running locally

echo 'export ASPNETCORE_URLS="https://0.0.0.0:8443"'
echo 'export ASPNETCORE_Kestrel__Certificates__Default__Path="/etc/letsencrypt/live/secretsanta.example.com-rsa/fullchain.pem"'
echo 'export ASPNETCORE_Kestrel__Certificates__Default__KeyPath="/etc/letsencrypt/live/secretsanta.example.com-rsa/privkey.pem"'
echo 'cd /opt/secretsanta/published'
echo 'sudo -E dotnet ./SecretSanta.Api.dll'
echo 'pgrep -a dotnet'
echo 'ps -o pid,cmd -C dotnet'
echo 'curl -vkI https://localhost:8443/ || true'
echo 'tail -n 200 /var/log/secretsanta.log | grep -E "Now listening on|Application started|Kestrel"'
