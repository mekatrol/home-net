#!/bin/sh
set -eu
while true; do
  export DOMAIN=test.com
  for s in sub1 sub2 sub3; do
      SUBDOMAIN="$s" SMTP_HOST="smtp.$DOMAIN" FROM="proxy@$DOMAIN" TO="certs@$DOMAIN" TYPE=renew /scripts/renew_cert.sh
  done
  sleep 7d
done