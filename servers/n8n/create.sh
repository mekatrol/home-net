#!/usr/bin/env bash
set -euo pipefail

# Required env (examples):
# SSH_USER_NAME="ssh" SSH_USER_PASSWORD="pwd" HOSTNAME="n8n.example.com" \
# TIMEZONE="Australia/Sydney" CERTNAME="n8n.example.com-rsa" ./create.sh

# Validate required vars
req=(SSH_USER_NAME SSH_USER_PASSWORD HOSTNAME TIMEZONE CERTNAME)
for v in "${req[@]}"; do
  [[ -z "${!v:-}" ]] && { echo "Error: $v must be defined"; exit 1; }
done

# The name of the image that will be created with 'docker build'
IMAGE_NAME="${IMAGE_NAME:-n8n}"

# The name of the container that will be created with docker run
CONTAINER_NAME="${CONTAINER_NAME:-n8n}"

# The name of the network the nginx server will use
NETWORK_NAME="${NETWORK_NAME:-docker-network}"

# The driver method used when creating the network if it does not already exist
NETWORK_DRIVER="${NETWORK_DRIVER:-ipvlan}"

# The network interface card used for the network
NETWORK_PARENT="${NETWORK_PARENT:-br0}"

# The network subnet
NETWORK_SUBNET="${NETWORK_SUBNET:-10.2.2.0/24}"

# The network gateway
NETWORK_GATEWAY="${NETWORK_GATEWAY:-10.2.2.1}"

# Static IP address for the server host
CONTAINER_IP_ADDR="${CONTAINER_IP_ADDR:-10.2.2.236}"

# Let’s Encrypt bind-mount (host:container)
LETS_ENCRYPT_VOLUME="${LETS_ENCRYPT_VOLUME:-/mnt/apps/data/etc-letsencrypt:/etc/letsencrypt}"

# n8n runtime
N8N_PORT_HOST="${N8N_PORT_HOST:-5678}"
N8N_PORT_CONT="${N8N_PORT_CONT:-5678}"
N8N_ENCRYPTION_KEY="${N8N_ENCRYPTION_KEY:-$(openssl rand -hex 32)}"
N8N_BASIC_AUTH_ACTIVE="${N8N_BASIC_AUTH_ACTIVE:-true}"
N8N_BASIC_AUTH_USER="${N8N_BASIC_AUTH_USER:-admin}"
N8N_BASIC_AUTH_PASSWORD="${N8N_BASIC_AUTH_PASSWORD:-change_me}"
N8N_PROTOCOL="${N8N_PROTOCOL:-http}"   # set to https if you terminate TLS in-container
WEBHOOK_URL="${WEBHOOK_URL:-$N8N_PROTOCOL://$HOSTNAME/}"

# Data volume for n8n home
DATA_VOL="${DATA_VOL:-n8n_data}"

# Checks
command -v docker >/dev/null || { echo "docker not found"; exit 1; }

# Network
if ! docker network ls --format '{{.Name}}' | grep -qx "$NETWORK_NAME"; then
  echo "Creating network $NETWORK_NAME ($NETWORK_DRIVER, parent=$NETWORK_PARENT)..."
  docker network create \
    --driver "$NETWORK_DRIVER" \
    --subnet "$NETWORK_SUBNET" \
    --gateway "$NETWORK_GATEWAY" \
    -o parent="$NETWORK_PARENT" \
    "$NETWORK_NAME"
else
  echo "Network '$NETWORK_NAME' exists."
fi

# Volumes
docker volume inspect "$DATA_VOL" >/dev/null 2>&1 || docker volume create "$DATA_VOL"

# Build image
# Expects a Dockerfile in cwd that extends n8nio/n8n and adds SSH user.
# Build args passed through for your Dockerfile.
if ! docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -qx "$IMAGE_NAME:latest"; then
  echo "Building image '$IMAGE_NAME:latest'..."
  docker build -t "$IMAGE_NAME:latest" \
    --build-arg SSH_USER_NAME="$SSH_USER_NAME" \
    --build-arg SSH_USER_PASSWORD="$SSH_USER_PASSWORD" \
    --build-arg HOSTNAME="$HOSTNAME" \
    --build-arg TIMEZONE="$TIMEZONE" \
    --build-arg CERTNAME="$CERTNAME" \
    .
else
  echo "Image '$IMAGE_NAME:latest' exists."
fi

# ---- Stop/remove existing ----
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Container '$CONTAINER_NAME' exists. Recreating..."
  docker rm -f "$CONTAINER_NAME" >/dev/null || true
fi

# ---- Run ----
run_args=(
  -d
  --restart always
  --name "$CONTAINER_NAME"
  --hostname "$HOSTNAME"
  --network "$NETWORK_NAME"
  --ip "$CONTAINER_IP_ADDR"
  -p "$N8N_PORT_HOST:$N8N_PORT_CONT"
  -e TZ="$TIMEZONE"
  -e N8N_HOST="$HOSTNAME"
  -e WEBHOOK_URL="$WEBHOOK_URL"
  -e N8N_ENCRYPTION_KEY="$N8N_ENCRYPTION_KEY"
  -e N8N_BASIC_AUTH_ACTIVE="$N8N_BASIC_AUTH_ACTIVE"
  -e N8N_BASIC_AUTH_USER="$N8N_BASIC_AUTH_USER"
  -e N8N_BASIC_AUTH_PASSWORD="$N8N_BASIC_AUTH_PASSWORD"
  -v "$DATA_VOL:/home/node/.n8n"
  --health-cmd "node -e \"require('http').request({host:'127.0.0.1',port:$N8N_PORT_CONT,path:'/'},r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1)).end()\""
  --health-interval 30s
  --health-timeout 5s
  --health-retries 3
)

# Extra ports for SSH/Nginx
run_args+=(-p 22:22 -p 80:80 -p 8443:8443)

# Let’s Encrypt mount
if [[ -n "${LETS_ENCRYPT_VOLUME:-}" ]]; then
  run_args+=(-v "$LETS_ENCRYPT_VOLUME")
fi

echo "Starting container..."
docker run "${run_args[@]}" "$IMAGE_NAME:latest"

echo "Done."
echo "UI:        $N8N_PROTOCOL://$HOSTNAME/  (mapped $N8N_PORT_HOST->$N8N_PORT_CONT)"
echo "Data vol:  $DATA_VOL  -> /home/node/.n8n"
echo "Network:   $NETWORK_NAME  IP: $CONTAINER_IP_ADDR"
printf 'Logs:      docker logs %q --tail=200\n' "$CONTAINER_NAME"