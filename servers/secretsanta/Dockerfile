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
    sudo syslog-ng nano tzdata cron openssh-server curl git jq nginx certbot python3-certbot-nginx

# Node.js 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get update && apt-get install -y nodejs

# .NET 8 SDK
RUN wget https://packages.microsoft.com/config/ubuntu/24.04/packages-microsoft-prod.deb -O /tmp/packages-microsoft-prod.deb \
    && dpkg -i /tmp/packages-microsoft-prod.deb \
    && rm /tmp/packages-microsoft-prod.deb \
    && apt-get update && apt-get install -y dotnet-sdk-8.0

RUN rm -rf /var/lib/apt/lists/*

# Clone repo
WORKDIR /opt
RUN git clone https://github.com/mekatrol/secretsanta.git

# Build API
WORKDIR /opt/secretsanta
RUN dotnet restore
RUN dotnet build -c Release

# Build SPA
WORKDIR /opt/secretsanta/SecretSanta.Spa
RUN npm i -g npm@latest && \
    npm install --save-dev @vitejs/plugin-basic-ssl@^2 && \
    if [ -f package-lock.json ]; then npm ci --no-audit --no-fund; else npm install --no-audit --no-fund; fi && \
    npm run build

# Publish backend
WORKDIR /opt/secretsanta
RUN dotnet publish -c Release -o /opt/secretsanta/published

# Copy origins settings
COPY origins.txt /opt/origins.txt

# Update CORS settings
# Convert lines -> JSON array, ignoring blanks and comments
RUN ORIGINS_JSON="$(jq -R -s '[split("\n")[] | gsub("^\\s+|\\s+$";"") | select(length>0 and (test("^#")|not))]' /opt/origins.txt)" \
    && jq --argjson origins "$ORIGINS_JSON" \
    '.Cors = (.Cors // {}) | .Cors.AllowedOrigins = $origins' \
    /opt/secretsanta/published/appsettings.json \
    > /tmp/appsettings.json \
    && mv /tmp/appsettings.json /opt/secretsanta/published/appsettings.json

# The ports to expose:
#    80 - used by nginx for lets encrypt
#   443 - used by nginx
#  8443 - secretsanta site
EXPOSE 443 80 8443

# Set up the cron job to renew certificates once per week
# Use to generate in first instance:
#   certbot certonly --webroot --webroot-path=/var/www/html --email admin@test.com --agree-tos --cert-name secretsanta.test.com-rsa -d secretsanta.test.com --key-type rsa
RUN echo "5 0 */7 * * root certbot renew --quiet && nginx -s reload" > /etc/cron.d/certbot-renewal

# Create a directory to store cron logs
RUN mkdir -p /var/log/cron

# Set cron job permissions, Owner = read/write | Group = read | Others = read
RUN chmod 0644 /etc/cron.d/certbot-renewal

# Create the SSH user and set a password
RUN useradd -m -s /bin/bash $SSH_USER_NAME && echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Create SSH run file directory
RUN mkdir /var/run/sshd 

# Exclude core messages in docker cotnainer
RUN sed -i 's/system()/system(exclude-kmsg(yes))/g' /etc/syslog-ng/syslog-ng.conf

# Tell ASP.NET to use certs and listen on all interfaces 443
ENV ASPNETCORE_URLS="https://0.0.0.0:8443"
ENV ASPNETCORE_Kestrel__Certificates__Default__Path="/etc/letsencrypt/live/$CERTNAME/fullchain.pem"
ENV ASPNETCORE_Kestrel__Certificates__Default__KeyPath="/etc/letsencrypt/live/$CERTNAME/privkey.pem"

# Back to root directory
WORKDIR /

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

WORKDIR /opt/secretsanta/published

# Create container startup script
RUN cat > /start.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

service syslog-ng start
service cron start
service ssh start

# start app in background, log to file
nohup dotnet /opt/secretsanta/published/SecretSanta.Api.dll >>/var/log/secretsanta.log 2>&1 &

# keep PID 1 as nginx
exec nginx -g 'daemon off;'
SH
RUN chmod +x /start.sh

# Run container start up script
CMD ["/bin/bash", "/start.sh"]
