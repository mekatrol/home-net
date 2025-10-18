#!/bin/bash
set -euo pipefail

# e.g. to run this script:
# SSH_USER_NAME="ssh" SSH_USER_PASSWORD="pwd" CRONICLE_ADMIN_USER="admin" CRONICLE_ADMIN_PASS="pwd" HOSTNAME="scheduler.lan" TIMEZONE="Australia/Sydney" ./create.sh

if [ -z "$SSH_USER_NAME" ]; then
    echo "Error: SSH_USER_NAME must be defined!"
    exit 1
fi

if [ -z "$SSH_USER_PASSWORD" ]; then
    echo "Error: SSH_USER_PASSWORD must be defined!"
    exit 1
fi

if [ -z "$CRONICLE_ADMIN_USER" ]; then
    echo "Error: CRONICLE_ADMIN_USER must be defined!"
    exit 1
fi

if [ -z "$CRONICLE_ADMIN_PASS" ]; then
    echo "Error: CRONICLE_ADMIN_PASS must be defined!"
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

# The name of the image that will be created with 'docker build'
IMAGE_NAME="scheduler"

# The name of the container that will be created with docker run
CONTAINER_NAME="scheduler"

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
CONTAINER_IP_ADDR="10.2.2.238"

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
        --build-arg CRONICLE_ADMIN_USER="$CRONICLE_ADMIN_USER" \
        --build-arg CRONICLE_ADMIN_PASS="$CRONICLE_ADMIN_PASS" \
        --build-arg HOSTNAME="$HOSTNAME" \
        --build-arg TIMEZONE="$TIMEZONE" \
        .
else
    echo "Image '$IMAGE_NAME' already exists."
fi

docker run \
    -itd --network="$NETWORK_NAME" \
    --restart=always \
    --ip="$CONTAINER_IP_ADDR" \
    -p 443:443 \
    -p 80:80 \
    -p 22:22 \
    --name="$CONTAINER_NAME" \
    --hostname="$HOSTNAME" \
    --volume="$LETS_ENCRYPT_VOLUME" \
    "$IMAGE_NAME"

printf 'Logs:         docker logs %q --tail=200\n' "$CONTAINER_NAME"
printf 'Certs-dryrun: sudo certbot certonly --staging --dry-run --webroot --webroot-path=/var/www/html --email admin@%s --agree-tos --cert-name %s-rsa -d %s --key-type rsa\n' "$HOSTNAME" "$HOSTNAME" "$HOSTNAME"
printf 'Certs-init:   certbot certonly --webroot --webroot-path=/var/www/html --email admin@%s --agree-tos --cert-name %s-rsa -d %s --key-type rsa\n' "$HOSTNAME" "$HOSTNAME" "$HOSTNAME"
printf 'Certs-sched:  certbot renew --quiet && nginx -s reload\n'

