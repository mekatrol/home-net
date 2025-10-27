#!/bin/bash
set -euo pipefail

# e.g. to run this script:
# HOSTNAME="pihole.example.com" WEBPASSWORD="changeme" TIMEZONE="Australia/Sydney" ./create.sh

if [ -z "$HOSTNAME" ]; then
    echo "Error: HOSTNAME must be defined!"
    exit 1
fi

if [ -z "$WEBPASSWORD" ]; then
    echo "Error: WEBPASSWORD must be defined!"
    exit 1
fi

if [ -z "$TIMEZONE" ]; then
    echo "Error: TIMEZONE must be defined!"
    exit 1
fi

# The name of the image that will be created with 'docker build'
IMAGE_NAME="pihole"

# The name of the container that will be created with docker run
CONTAINER_NAME="pihole"

# The name of the network the nginx server will use
NETWORK_NAME="docker-network"

# The driver method used when creating the network if it does not already exist
NETWORK_DRIVER="ipvlan"

# The network interface card used for the network
NETWORK_PARENT="enp3s0"

# The network subnet
NETWORK_SUBNET="10.2.2.0/24"

# The network gateway
NETWORK_GATEWAY="10.2.2.1"

# Static IP address for the server host
CONTAINER_IP_ADDR="10.2.2.200"

# PIHOLE volumes
PIHOLE_VOLUME="/data/pihole-data:/etc/pihole"
DNSMASQ_VOLUME="/data/pihole-dnsmasq.d:/etc/dnsmasq.d"

# Make sure empty volumes exist
rm -rf /data/pihole-data /data/pihole-dnsmasq.d
mkdir -p /data/pihole-data /data/pihole-dnsmasq.d

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
        --build-arg HOSTNAME="$HOSTNAME" \
        --build-arg TIMEZONE="$TIMEZONE" \
        .
else
    echo "Image '$IMAGE_NAME' already exists."
fi

docker run \
    -itd \
    --restart=always \
    --ip="$CONTAINER_IP_ADDR" \
    -e WEBPASSWORD="$WEBPASSWORD" \
    -e DNSMASQ_LISTENING=all \
    -e PIHOLE_DNS_1=9.9.9.9 \
    -e FTLCONF_LOCAL_IPV4="$CONTAINER_IP_ADDR" \
    -e TZ="$TIMEZONE" \
    --name="$CONTAINER_NAME" \
    --hostname="$HOSTNAME" \
    --network="$NETWORK_NAME" \
    --volume="$PIHOLE_VOLUME" \
    --volume="$DNSMASQ_VOLUME" \
    "$IMAGE_NAME"

# Set web UI password
docker exec -it "$CONTAINER_NAME" pihole setpassword "$WEBPASSWORD"

# 1) Normalize and clean, sort by hostname
tr -d '\r' < localdns.txt \
  | awk 'NF && $1 !~ /^#/' \
  | sort -k2,2 > localdns_sorted.txt

# 2) Build TOML array
arr=$(
  awk '{printf "\"%s %s\",", $1, $2}' localdns_sorted.txt \
  | sed 's/,$//'
)

# 3) Apply (no reload)
docker exec pihole sh -lc "pihole-FTL --config dns.hosts '[$arr]'"

# Restart to make sure list is loaded
docker restart pihole

# Sleep for 5 seconds while restarting
sleep 5

# Print local DNS entries
docker exec -it "$CONTAINER_NAME" cat /etc/pihole/hosts/custom.list

printf '\n'
printf '\n'
printf '\n'
printf 'Logs:      docker logs %q --tail=200\n' "$CONTAINER_NAME"
printf 'Logs:      docker exec -it %q cat /etc/pihole/hosts/custom.list\n' "$CONTAINER_NAME"
