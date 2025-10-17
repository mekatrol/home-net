#!/bin/sh
set -e

# Usage:
# SMTP_HOST=smtp.example.com FROM=cronicle@example.com TO=you@example.com ./send-test-email-plain.sh

SMTP_HOST="${SMTP_HOST:-smtp.example.com}"
SMTP_PORT="${SMTP_PORT:-25}"
FROM="${FROM:-cronicle@example.com}"
TO="${TO:-test@example.com}"
SUBJECT="${SUBJECT:-Cronicle Test Email}"
BODY="${BODY:-Test message from Cronicle scheduler.}"

MSG_FILE=$(mktemp)
{
  echo "From: ${FROM}"
  echo "To: ${TO}"
  echo "Subject: ${SUBJECT}"
  echo
  echo "${BODY}"
} > "$MSG_FILE"

curl --url "smtp://${SMTP_HOST}:${SMTP_PORT}" \
     --mail-from "$FROM" \
     --mail-rcpt "$TO" \
     --upload-file "$MSG_FILE" \
     --verbose

rm -f "$MSG_FILE"
echo "Email sent to $TO via $SMTP_HOST:$SMTP_PORT (no TLS)"
