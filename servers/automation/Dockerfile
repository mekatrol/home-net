FROM ubuntu:latest

# Set environment variables to avoid interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Expected arguments
ARG SSH_USER_NAME
ARG SSH_USER_PASSWORD
ARG HOSTNAME
ARG TIMEZONE
ARG CERTNAME

RUN if [ -z "$SSH_USER_NAME" ]; then \
    echo "Error: SSH_USER_NAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$SSH_USER_PASSWORD" ]; then \
    echo "Error: SSH_USER_PASSWORD must be defined!" && exit 1; \
    fi

RUN if [ -z "$HOSTNAME" ]; then \
    echo "Error: HOSTNAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$TIMEZONE" ]; then \
    echo "Error: TIMEZONE must be defined!" && exit 1; \
    fi

RUN if [ -z "$CERTNAME" ]; then \
    echo "Error: CERTNAME must be defined!" && exit 1; \
    fi

# Base packages
RUN apt-get update && apt-get install -y \
    sudo syslog-ng nano tzdata openssh-server curl git jq nginx certbot python3-certbot-nginx && \
    rm -rf /var/lib/apt/lists/*

# The ports to expose:
#    80 - used by nginx for lets encrypt
#   443 - used by nginx
#  8443 - secretsanta site
EXPOSE 443 80

# Create the SSH user and set a password
RUN useradd -m -s /bin/bash $SSH_USER_NAME && echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Create SSH run file directory
RUN mkdir /var/run/sshd 

# Exclude core messages in docker cotnainer
RUN sed -i 's/system()/system(exclude-kmsg(yes))/g' /etc/syslog-ng/syslog-ng.conf

# Delete the NGINX default redirect
RUN rm -f /etc/nginx/sites-enabled/default

# Copy the reverse proxy configure shell script
COPY configure_reverse_proxy.sh /configure_reverse_proxy.sh

# Make shell script executable
RUN chmod +x /configure_reverse_proxy.sh

# Copy the reverse proxy definition file (strip Windows carriage returns if they exist)
COPY reverse_proxy_list.txt /reverse_proxy_list.txt
RUN sed -i 's/\r$//' /reverse_proxy_list.txt

# Run the configuration script
RUN /configure_reverse_proxy.sh

# Create lets encrypt acme challenge
RUN mkdir -p /var/www/html/.well-known/acme-challenge && echo ok | sudo tee /var/www/html/.well-known/acme-challenge/ping >/dev/null

# Write site config correctly
RUN cat > /etc/nginx/sites-available/${HOSTNAME} <<EOF
server {
    listen 80;
    listen [::]:80;
    server_name ${HOSTNAME};
    root /var/www/html;

    location / { index index.html; }
    location /.well-known/acme-challenge/ { allow all; }
}
EOF

# Enable site and disable default
RUN rm -f /etc/nginx/sites-enabled/default && \
    ln -s /etc/nginx/sites-available/${HOSTNAME} /etc/nginx/sites-enabled/${HOSTNAME}

# Optional: test config during build (fails the build if bad)
RUN nginx -t

# Create index.html just for testing site up and running
RUN install -d -m 755 /var/www/html && \
    cat > /var/www/html/index.html <<'EOF'
<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8"><title>OK</title></head>
<body><p>active</p></body>
</html>
EOF

# Set timezone
RUN  ln -fs /usr/share/zoneinfo/$TIMEZONE /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Create container startup script
RUN cat > /start.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

service syslog-ng start
service ssh start

# If we have not yet fetched the certs, create self signed versions now so that nginx does not fail to load
if [ ! -f "/etc/letsencrypt/live/${CERTNAME}/fullchain.pem" ] || [ ! -f "/etc/letsencrypt/live/${CERTNAME}/privkey.pem" ]; then
  echo "No existing certs found for ${CERTNAME}, generating temporary self-signed cert"
  mkdir -p /etc/letsencrypt/live/${CERTNAME}
  openssl req -x509 -nodes -newkey rsa:2048 -days 1 \
    -subj "/CN=$HOSTNAME" \
    -keyout /etc/letsencrypt/live/${CERTNAME}/privkey.pem \
    -out /etc/letsencrypt/live/${CERTNAME}/fullchain.pem
fi

# nginx
nginx -t
# nginx -g 'daemon off;' &
exec nginx -g 'daemon off;'
SH
RUN chmod +x /start.sh

# Run container start up script
CMD ["/bin/bash", "/start.sh"]
