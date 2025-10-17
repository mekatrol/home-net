#!/bin/bash

# e.g. to run this script:
# DB_NAME="maildb" \
# POSTGRES_PASSWORD="postgress_pwd" \
# DB_ADMIN_NAME="db_admin" \
# DB_ADMIN_PASSWORD="admin_pwd" \
# DB_READER_NAME="db_reader" \
# DB_READER_PASSWORD="reader_pwd" \
# SSH_USER_NAME="ssh" \
# SSH_USER_PASSWORD="pwd" \
# HOSTNAME="mail.test.com" \
# MAIL_DOMAIN="test.com" \
# REQUIRE_STARTTLS="false" \
# TIMEZONE="Australia/Sydney" \
# ADDITIONAL_MY_NETWORKS="192.168.0.0/24" \
# RELAY_HOST="192.168.10.1" \
# ./create.sh

# Check required arguments
if [ -z "$DB_NAME" ]; then
    echo "Error: DB_NAME must be defined!"
    exit 1
fi

if [ -z "$POSTGRES_PASSWORD" ]; then
    echo "Error: POSTGRES_PASSWORD must be defined!"
    exit 1
fi

if [ -z "$DB_ADMIN_NAME" ]; then
    echo "Error: DB_ADMIN_NAME must be defined!"
    exit 1
fi

if [ -z "$DB_ADMIN_PASSWORD" ]; then
    echo "Error: DB_ADMIN_PASSWORD must be defined!"
    exit 1
fi

if [ -z "$DB_READER_NAME" ]; then
    echo "Error: DB_READER_NAME must be defined!"
    exit 1
fi

if [ -z "$DB_READER_PASSWORD" ]; then
    echo "Error: DB_READER_PASSWORD must be defined!"
    exit 1
fi

if [ -z "$HOSTNAME" ]; then
    echo "Error: HOSTNAME must be defined!"
    exit 1
fi

if [ -z "$MAIL_DOMAIN" ]; then
    echo "Error: MAIL_DOMAIN must be defined!"
    exit 1
fi

if [ -z "$REQUIRE_STARTTLS" ]; then
    echo "Error: REQUIRE_STARTTLS must be defined!"
    exit 1
fi

if [ -z "$TIMEZONE" ]; then
    echo "Error: TIMEZONE must be defined!"
    exit 1
fi

if [ -z "$SSH_USER_NAME" ]; then
    echo "Error: SSH_USER_NAME must be defined!"
    exit 1
fi

if [ -z "$SSH_USER_PASSWORD" ]; then
    echo "Error: SSH_USER_PASSWORD must be defined!"
    exit 1
fi

if [ -z "$ADDITIONAL_MY_NETWORKS" ]; then
    echo "Error: ADDITIONAL_MY_NETWORKS must be defined!"
    exit 1
fi

# The name of the image that will be created with 'docker build'
IMAGE_NAME="mail-server"

# The name of the container that will be created with docker run
CONTAINER_NAME="mail-server"

# The name of the network the mail server will use
NETWORK_NAME="docker-network"

# The driver method used when creting the network if it does not already exist
NETWORK_DRIVER="ipvlan"

# The network interface card used for the network
NETWORK_PARENT="enp1s0"

# The network subnet
NETWORK_SUBNET="172.16.3.0/24"

# The network gateway
NETWORK_GATEWAY="172.16.3.1"

# Static IP address for the mail server host
CONTAINER_IP_ADDR="172.16.3.210"

# Mail server host name
CONTAINER_HOST_NAME="$HOSTNAME"

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
        --build-arg ADDITIONAL_MY_NETWORKS="$ADDITIONAL_MY_NETWORKS" \
        --build-arg RELAY_HOST="$RELAY_HOST" \
        --build-arg DB_NAME="$DB_NAME" \
        --build-arg POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
        --build-arg DB_ADMIN_NAME="$DB_ADMIN_NAME" \
        --build-arg DB_ADMIN_PASSWORD="$DB_ADMIN_PASSWORD" \
        --build-arg DB_READER_NAME="$DB_READER_NAME" \
        --build-arg DB_READER_PASSWORD="$DB_READER_PASSWORD" \
        --build-arg SSH_USER_NAME="$SSH_USER_NAME" \
        --build-arg SSH_USER_PASSWORD="$SSH_USER_PASSWORD" \
        --build-arg HOSTNAME="$HOSTNAME" \
        --build-arg MAIL_DOMAIN="$MAIL_DOMAIN" \
        --build-arg REQUIRE_STARTTLS="$REQUIRE_STARTTLS" \
        --build-arg TIMEZONE="$TIMEZONE" \
        .
else
    echo "Image '$IMAGE_NAME' already exists."
fi

docker run \
    -itd --network="$NETWORK_NAME" \
    --ip="$CONTAINER_IP_ADDR" \
    --name="$CONTAINER_NAME" \
    --hostname="$CONTAINER_HOST_NAME" \
    --volume="$LETS_ENCRYPT_VOLUME" \
    "$IMAGE_NAME"

printf 'Logs:      docker logs %q --tail=200\n' "$CONTAINER_NAME"