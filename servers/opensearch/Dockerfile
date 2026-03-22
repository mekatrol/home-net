FROM n8nio/n8n:latest
USER root

ARG SSH_USER_NAME
ARG SSH_USER_PASSWORD
ARG HOSTNAME
ARG TIMEZONE
ARG CERTNAME

RUN apk update && apk add --no-cache \
  nginx openssh tzdata curl cronie \
  iputils bind-tools net-snmp-tools mosquitto-clients \
  certbot certbot-nginx sudo gettext

ENV TZ=${TIMEZONE}
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ >/etc/timezone

ENV N8N_SECURE_COOKIE=true
ENV N8N_HOST=${HOSTNAME}
ENV N8N_PORT=5678
ENV N8N_PROTOCOL=http
ENV N8N_PUBLIC_URL=https://${HOSTNAME}
ENV N8N_PROXY_HOPS=1

RUN mkdir -p /var/run/sshd && \
  adduser -D -s /bin/ash "$SSH_USER_NAME" && \
  echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd && \
  adduser "$SSH_USER_NAME" wheel && \
  echo "%wheel ALL=(ALL) NOPASSWD:ALL" > /etc/sudoers.d/wheel && \
  chmod 440 /etc/sudoers.d/wheel && \
  sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
  sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' /etc/ssh/sshd_config

RUN mkdir -p /home/node/.n8n && chown -R node:node /home/node/.n8n

ENV HOSTNAME=${HOSTNAME} CERTNAME=${CERTNAME}

# write template, not the final conf
RUN mkdir -p /etc/nginx/http.d && \
  rm -f /etc/nginx/http.d/default.conf /etc/nginx/conf.d/default.conf || true && \
  cat >/etc/nginx/http.d/n8n.conf.template <<'NGINXCONF'
upstream n8n_upstream { server 127.0.0.1:5678; }

# Lets encrypt ACME challenge
server {
  listen 80;
  server_name ${HOSTNAME};
  location ^~ /.well-known/acme-challenge/ {
    root /var/www/html;
    default_type text/plain;
    try_files $uri =404;
  }
  
  # Redirect everything else to HTTPS
  location / { return 301 https://$host$request_uri; }
}

# HTTPS
server {
  listen 443 ssl http2;
  server_name ${HOSTNAME};

  ssl_certificate     /etc/letsencrypt/live/${CERTNAME}/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/${CERTNAME}/privkey.pem;

  # optional: include /etc/letsencrypt/options-ssl-nginx.conf;

  client_max_body_size 50m;

  location / {
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto https;
    proxy_set_header X-Forwarded-Port 443;
    proxy_set_header X-Forwarded-Host $host;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection upgrade;
    proxy_pass http://n8n_upstream;
    proxy_read_timeout 600s;
    proxy_send_timeout 600s;
    proxy_buffering off;
  }
}
NGINXCONF

# Create Let's Encrypt ACME challenge
RUN mkdir -p /var/www/html/.well-known/acme-challenge && \
  sh -lc 'echo ok > /var/www/html/.well-known/acme-challenge/ping'

# Set up the cron job to renew certificates once per week
# Use to generate in first instance:
#   certbot certonly --webroot --webroot-path=/var/www/html --email admin@test.com --agree-tos --cert-name mail.test.com-rsa -d mail.test.com --key-type rsa
# Set cron job permissions 0644 = Owner = read/write | Group = read | Others = read
RUN mkdir -p /var/log/cron /etc/cron.d && \
  printf 'SHELL=/bin/sh\nPATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n' \
  > /etc/cron.d/certbot-renewal && \
  printf '5 3 * * * root sleep $((RANDOM%%1800)); /usr/bin/certbot renew --quiet --post-hook "nginx -s reload" >> /var/log/cron/certbot.log 2>&1\n' \
  >> /etc/cron.d/certbot-renewal && \
  chmod 0644 /etc/cron.d/certbot-renewal

# start script: sshd + nginx + n8n (as node)
RUN cat >/usr/local/bin/start.sh <<'SH'
#!/bin/sh
set -e
export TZ="${TZ}"
export HOME=/home/node
export N8N_ENFORCE_SETTINGS_FILE_PERMISSIONS=true

# ensure data dir owned by node
mkdir -p /home/node/.n8n
chown -R node:node /home/node/.n8n

# render nginx conf from template
envsubst '$HOSTNAME $CERTNAME' \
  </etc/nginx/http.d/n8n.conf.template >/etc/nginx/http.d/n8n.conf

# sshd
ssh-keygen -A
/usr/sbin/sshd

# If we have not yet fetched the certs, create self signed versions now so that nginx does not fail to load
if [ ! -f "/etc/letsencrypt/live/${CERTNAME}/fullchain.pem" ] || [ ! -f "/etc/letsencrypt/live/${CERTNAME}/privkey.pem" ]; then
  echo "No existing certs found for ${CERTNAME}, generating temporary self-signed cert"
  mkdir -p /etc/letsencrypt/live/${CERTNAME}
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -subj "/CN=localhost" \
    -keyout /etc/letsencrypt/live/${CERTNAME}/privkey.pem \
    -out /etc/letsencrypt/live/${CERTNAME}/fullchain.pem
fi

# nginx
nginx -t
nginx -g 'daemon off;' &

# start cron
crond -n -s &

# run n8n as node
exec su -s /bin/sh -c "n8n start" node
SH
RUN chmod +x /usr/local/bin/start.sh

HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD node -e "require('http').request({host:'127.0.0.1',port:5678,path:'/'},r=>process.exit(r.statusCode===200?0:1)).on('error',()=>process.exit(1)).end()"

EXPOSE 22 80 443
ENTRYPOINT ["/usr/local/bin/start.sh"]
