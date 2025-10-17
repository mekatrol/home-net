#!/bin/bash
set -euo pipefail

CONFIG_FILE="/etc/nginx/sites-available/reverse_proxy"
ENABLED_CONFIG="/etc/nginx/sites-enabled/reverse_proxy"
INPUT_FILE="reverse_proxy_list.txt"

# Check if input file exists
[[ -f "$INPUT_FILE" ]] || { echo "Error: $INPUT_FILE not found"; exit 1; }

# Create the Nginx configuration file
cat >"$CONFIG_FILE" <<'NGINX'
# Nginx reverse proxy configuration

# Redirect all HTTP to HTTPS for any host
#server {
#    listen 80 default_server;
#    server_name _;
#    return 301 https://$host$request_uri;
#}

# Common upgrade handling
map $http_upgrade $connection_upgrade {
    default upgrade;
    ""      close;
}
NGINX

# Generate per-host reverse proxy servers
while IFS=' ' read -r HOSTNAME IP_ADDRESS PROTOCOL_SCHEME PORT || [[ -n "${HOSTNAME:-}" ]]; do
    # Skip blanks/comments
    [[ -z "${HOSTNAME:-}" || "${HOSTNAME:0:1}" == "#" ]] && continue

    # default PORT by scheme if missing
    case "${PROTOCOL_SCHEME:-}" in
        http|ws)  PORT="${PORT:-80}"  ;;
        https|wss) PORT="${PORT:-443}" ;;
        *) echo "Error: unknown PROTOCOL_SCHEME '$PROTOCOL_SCHEME' for $HOSTNAME" >&2; exit 1 ;;
    esac

    if [[ -n "${HOSTNAME:-}" && -n "${IP_ADDRESS:-}" && -n "${PROTOCOL_SCHEME:-}" && -n "${PORT:-}" ]]; then
        cat >>"$CONFIG_FILE" <<NGINX

# http://$HOSTNAME/.well-known/acme-challenge/* --> http://$HOSTNAME/.well-known/acme-challenge/*
# http://$HOSTNAME/*                            --> http://$IP_ADDRESS
server {
    listen 80;
    server_name $HOSTNAME;
    root /var/www/html;

    location ^~ /.well-known/acme-challenge/ {
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        index index.html;
    }
}
NGINX
    fi
done <"$INPUT_FILE"

# Enable the configuration
ln -sf "$CONFIG_FILE" "$ENABLED_CONFIG"
