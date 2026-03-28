FROM ubuntu:latest

# Set environment variables:
#  * avoid interactive prompts during installation
#  * force Python to write output immediately instead of buffering it
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Expected arguments
ARG SSH_USER_NAME
ARG TIMEZONE

RUN if [ -z "$SSH_USER_NAME" ]; then \
    echo "Error: SSH_USER_NAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$TIMEZONE" ]; then \
    echo "Error: TIMEZONE must be defined!" && exit 1; \
    fi

# Base packages
RUN apt-get update && apt-get install -y \
    sudo nano tzdata openssh-server openssh-client supervisor python3 python3-pip python3-venv \
    iputils-ping dnsutils ca-certificates openssl && \
    rm -rf /var/lib/apt/lists/*

ENV SSH_USER_NAME=${SSH_USER_NAME}

# Create the SSH user
RUN useradd -m -U -s /bin/bash $SSH_USER_NAME

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Ensure ownership first
RUN chown -R ${SSH_USER_NAME}:${SSH_USER_NAME} /home/${SSH_USER_NAME}

# Set timezone
RUN ln -fs /usr/share/zoneinfo/$TIMEZONE /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Configure sshd
RUN sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config

# Log directory — mounted as a volume at runtime so logs persist across rebuilds
RUN mkdir -p /var/log/home-monitor && chown ${SSH_USER_NAME}:${SSH_USER_NAME} /var/log/home-monitor

# TLS cert directory — persists self-signed cert across restarts
RUN mkdir -p /var/lib/watchdog-server

# Install app into its own venv
COPY app/ /opt/monitor/
RUN python3 -m venv /opt/monitor/.venv && \
    /opt/monitor/.venv/bin/pip install --no-cache-dir -r /opt/monitor/requirements.txt

# Create container startup script
RUN cat > /start.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER_NAME:?SSH_USER_NAME env not set}"
: "${SSH_USER_PASSWORD:?SSH_USER_PASSWORD env not set}"

# Set password at runtime (not build time)
echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

service ssh start

# Fix log directory ownership — the volume mount overwrites build-time chown
chown ${SSH_USER_NAME}:${SSH_USER_NAME} /var/log/home-monitor

# Generate self-signed TLS cert for WebSocket server if not already present
if [ ! -f /var/lib/watchdog-server/server.crt ]; then
    openssl req -x509 -newkey rsa:2048 \
        -keyout /var/lib/watchdog-server/server.key \
        -out /var/lib/watchdog-server/server.crt \
        -days 3650 -nodes -subj "/CN=watchdog-server"
    chown ${SSH_USER_NAME}:${SSH_USER_NAME} /var/lib/watchdog-server/server.crt /var/lib/watchdog-server/server.key
    echo "TLS certificate generated."
fi

cat > /etc/supervisor/conf.d/home-monitor.conf <<EOF
[unix_http_server]
file=/var/run/supervisor.sock

[supervisorctl]
serverurl=unix:///var/run/supervisor.sock

[rpcinterface:supervisor]
supervisor.rpcinterface_factory = supervisor.rpcinterface:make_main_rpcinterface

[supervisord]
nodaemon=true
user=root

[program:home-monitor]
command=/opt/monitor/.venv/bin/python /opt/monitor/main.py
directory=/opt/monitor
user=${SSH_USER_NAME}
environment=HOME="/home/${SSH_USER_NAME}",USER="${SSH_USER_NAME}",LOGNAME="${SSH_USER_NAME}",SHELL="/bin/bash"
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
EOF

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/home-monitor.conf
SH

RUN chmod +x /start.sh

# Run container start up script
CMD ["/bin/bash", "/start.sh"]
