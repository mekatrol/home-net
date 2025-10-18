#!/bin/bash
# configure_reverse_proxy.sh
#
# Purpose:
#   Generate an Nginx configuration that:
#     - Listens on :443 at the STREAM (TCP) layer and SNI-routes TLS blindly
#       to backend servers. Default backend port is 443, but you can override
#       it per-host (e.g. 8443).
#     - Listens on :80 at the HTTP layer and proxies clear-text HTTP to
#       the backend :80, preserving the Host header. ACME path stays local.
#
# Input file format (space-separated):
#   HOSTNAME  BACKEND_IP  https  [BACKEND_PORT_FOR_TLS]
# Examples:
#   internal.example.com  10.0.0.2  https
#   app.example.com       10.0.0.3  https 8443  # 443 -> 8443 upstream
#
# Notes:
#   - This script targets Ubuntu/Debian nginx layout.
#   - It loads the dynamic stream module exactly once when needed.
#   - It ensures a single top-level:  stream { include /etc/nginx/stream.d/*.conf; }
#   - It writes:
#       /etc/nginx/conf.d/reverse_proxy.conf          (HTTP :80 proxy blocks)
#       /etc/nginx/stream.d/reverse_proxy_stream.conf (STREAM :443 SNI map)
#   - It validates config at the end with `nginx -t`. Reload is NOT done here.
#   - Run this at container start so missing certs/volumes never break image build.

set -euo pipefail

INPUT_FILE="reverse_proxy_list.txt"

HTTP_CONF="/etc/nginx/conf.d/reverse_proxy.conf"
STREAM_CONF="/etc/nginx/stream.d/reverse_proxy_stream.conf"
NGINX_CONF="/etc/nginx/nginx.conf"

# --------------------------------------------------------------------------- #
# 0) Ensure directories and ACME webroot exist
# --------------------------------------------------------------------------- #
mkdir -p /etc/nginx/conf.d \
         /etc/nginx/stream.d \
         /etc/nginx/modules-enabled \
         /var/www/html/.well-known/acme-challenge

echo ok > /var/www/html/.well-known/acme-challenge/ping

# --------------------------------------------------------------------------- #
# 1) Ensure the stream module is present and loaded exactly once
#    - If nginx was built with --with-stream=dynamic, we need a loader.
#    - If stream is built-in (no =dynamic), no loader file is needed.
#    - Never create duplicate load_module lines.
# --------------------------------------------------------------------------- #
if nginx -V 2>&1 | grep -q -- '--with-stream=dynamic'; then
  # Any existing loader anywhere in /etc/nginx?
  if ! grep -RslqE '^[[:space:]]*load_module .*ngx_stream_module\.so;[[:space:]]*$' /etc/nginx 2>/dev/null; then
    apt-get update && apt-get install -y libnginx-mod-stream
    MOD="$(dpkg -L libnginx-mod-stream | grep '/ngx_stream_module\.so$')"
    printf 'load_module %s;\n' "$MOD" > /etc/nginx/modules-enabled/50-stream.conf
    # Ensure nginx.conf includes modules-enabled/*
    grep -q '^include /etc/nginx/modules-enabled/\*.conf;' "$NGINX_CONF" \
      || sed -i '1i include /etc/nginx/modules-enabled/*.conf;' "$NGINX_CONF"
  fi
else
  # Built-in or no stream support: remove any stale loader to avoid dlopen errors
  grep -RslE '^[[:space:]]*load_module .*ngx_stream_module\.so;[[:space:]]*$' /etc/nginx 2>/dev/null | xargs -r rm -f
fi

# --------------------------------------------------------------------------- #
# 2) Guarantee a single top-level `stream { include /etc/nginx/stream.d/*.conf; }`
#    Remove any existing stream blocks (anywhere), then insert one at top level.
# --------------------------------------------------------------------------- #
# Strip all existing stream blocks robustly (brace depth tracking)
awk '
/^[[:space:]]*stream[[:space:]]*{/ {
  depth=1
  while (getline > 0) {
    if ($0 ~ /{/) depth++
    if ($0 ~ /}/) { depth--; if (depth==0) break }
  }
  next
}
{ print }
' "$NGINX_CONF" > "${NGINX_CONF}.nostream"

# Insert a single top-level stream include before the http block if present, else append
awk '
/^[[:space:]]*http[[:space:]]*{/ && !ins {
  print "stream {\n    include /etc/nginx/stream.d/*.conf;\n}\n"
  ins=1
}
{ print }
END {
  if (!ins) print "stream {\n    include /etc/nginx/stream.d/*.conf;\n}\n"
}
' "${NGINX_CONF}.nostream" > "${NGINX_CONF}.new"

mv "${NGINX_CONF}.new" "$NGINX_CONF"
rm -f "${NGINX_CONF}.nostream"

# --------------------------------------------------------------------------- #
# 3) Build config from input
#    - STREAM map lines: "    host ip:port;"
#    - HTTP blocks: per host proxy on :80 -> backend :80 with Host preserved
# --------------------------------------------------------------------------- #
MAP_ENTRIES=""
HTTP_BLOCKS=""

# Read: HOST IP SCHEME [TLS_BACKEND_PORT]
while IFS=' ' read -r HOST IP SCHEME TLS_BACKEND_PORT || [[ -n "${HOST:-}" ]]; do
  # Skip blanks and comments
  [[ -z "${HOST:-}" || "${HOST:0:1}" == "#" ]] && continue

  # Only https scheme is supported in this upstream-only mode
  if [[ "${SCHEME:-}" != "https" ]]; then
    echo "Error: only 'https' is supported for TLS passthrough. Offending line: $HOST $IP $SCHEME" >&2
    exit 1
  fi

  # Default backend TLS port is 443; allow override (e.g. 8443)
  PORT="${TLS_BACKEND_PORT:-443}"

  # STREAM: SNI -> IP:PORT
  MAP_ENTRIES+=$(printf ' %s %s:%s;\n' "$HOST" "$IP" "$PORT")

  # HTTP: :80 reverse proxy to backend :80, keep ACME local
  HTTP_BLOCKS+=$(cat <<HTTP

# $HOST : HTTP layer :80 -> http://$IP:80
server {
    listen 80;
    server_name $HOST;
    root /var/www/html;

    # Keep ACME on the proxy host if you use http-01 challenges
    location ^~ /.well-known/acme-challenge/ {
        default_type text/plain;
        try_files \$uri =404;
    }

    location / {
        proxy_pass http://$IP:80;
        proxy_http_version 1.1;

        # Preserve original request info
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto http;

        # WebSocket/HTTP/2 upgrade safety
        proxy_set_header Upgrade \$http_upgrade;
        proxy_set_header Connection \$connection_upgrade;

        # Sensible timeouts
        proxy_connect_timeout 5s;
        proxy_read_timeout 60s;
        proxy_send_timeout 60s;

        proxy_redirect off;
    }
}
HTTP
)
done < "$INPUT_FILE"

# --------------------------------------------------------------------------- #
# 4) Write HTTP config (all :80 servers) and STREAM config (single :443 listener)
# --------------------------------------------------------------------------- #
cat > "$HTTP_CONF" <<HTTP
# Generated by configure_reverse_proxy.sh
# HTTP layer: per-host :80 proxy to backend :80
map \$http_upgrade \$connection_upgrade { default upgrade; "" close; }
$HTTP_BLOCKS
HTTP

cat > "$STREAM_CONF" <<STREAM
# Generated by configure_reverse_proxy.sh
# TLS passthrough by SNI on :443
map \$ssl_preread_server_name \$sni_backend {
${MAP_ENTRIES} default 0.0.0.0:443;
}

server {
    listen 443;
    proxy_pass \$sni_backend;
    ssl_preread on;

    # Optional hardening/timeouts:
    # proxy_connect_timeout 5s;
    # proxy_timeout 60s;
}
STREAM

# --------------------------------------------------------------------------- #
# 5) Validate config. Reload is left to the caller (e.g. entrypoint).
# --------------------------------------------------------------------------- #
nginx -t
