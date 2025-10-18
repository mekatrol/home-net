#!/bin/sh
set -e

# Usage:
# DOMAIN=test.com SUBDOMAIN=sub SMTP_HOST=smtp.$DOMAIN FROM=proxy@$DOMAIN TO=certs@$DOMAIN TYPE="renew" ./renew_certs.sh

: "${DOMAIN:?DOMAIN not set}"
: "${SUBDOMAIN:?SUBDOMAIN not set}"

TYPE="${TYPE:-renew}"

# Capture stdout+stderr without exiting on failure
set +e
case "$TYPE" in
  create)
    CERTBOT_OUTPUT="$(
      certbot certonly \
        --non-interactive \
        --webroot \
        --webroot-path=/var/www/html \
        --email "admin@$DOMAIN" \
        --agree-tos \
        --no-eff-email \
        --cert-name "$SUBDOMAIN.$DOMAIN-rsa" \
        -d "$SUBDOMAIN.$DOMAIN" \
        --key-type rsa 2>&1
    )"; CERTBOT_STATUS=$?
    ;;
  renew)
    CERTBOT_OUTPUT="$(
      certbot renew \
        --non-interactive \
        --no-random-sleep-on-renew \
        --cert-name "$SUBDOMAIN.$DOMAIN-rsa" \
        --deploy-hook "nginx -s reload" 2>&1
    )"; CERTBOT_STATUS=$?
    ;;
  dryrun)
    CERTBOT_OUTPUT="$(
      certbot renew \
        --dry-run \
        --non-interactive \
        --no-random-sleep-on-renew \
        --cert-name "$SUBDOMAIN.$DOMAIN-rsa" \
        --deploy-hook "nginx -s reload" 2>&1
    )"; CERTBOT_STATUS=$?
    ;;
  *)
    echo "Invalid TYPE: $TYPE (expected 'create' | 'renew' | 'dryrun')" >&2
    exit 1
    ;;
esac
set -e

SMTP_HOST="${SMTP_HOST:-smtp.example.com}"
SMTP_PORT="${SMTP_PORT:-25}"
FROM="${FROM:-cronicle@example.com}"
TO="${TO:-test@example.com}"
SUBJECT="${SUBJECT:-$SUBDOMAIN.$DOMAIN certificate $TYPE}"
DATE_HDR="$(date -R || date)"

MSG_FILE="$(mktemp)"
{
  printf 'From: %s\n' "$FROM"
  printf 'To: %s\n' "$TO"
  printf 'Subject: %s\n' "$SUBJECT"
  printf 'Date: %s\n' "$DATE_HDR"
  printf 'Content-Type: text/plain; charset=UTF-8\n'
  printf '\n'
  printf '%s\n' "$CERTBOT_OUTPUT"
  printf '\nCertbot exit code: %s\n' "$CERTBOT_STATUS"
} > "$MSG_FILE"

curl --url "smtp://${SMTP_HOST}:${SMTP_PORT}" \
     --mail-from "$FROM" \
     --mail-rcpt "$TO" \
     --upload-file "$MSG_FILE" \
     --verbose

rm -f "$MSG_FILE"
echo "Email sent to $TO via $SMTP_HOST:$SMTP_PORT (no TLS). certbot exit code: $CERTBOT_STATUS"
