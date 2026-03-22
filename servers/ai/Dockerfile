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
    sudo syslog-ng-core syslog-ng-scl nano tzdata openssh-server git supervisor python3-venv iputils-ping dnsutils && \
    rm -rf /var/lib/apt/lists/*

ENV SSH_USER_NAME=${SSH_USER_NAME}

# Create the SSH user
RUN useradd -m -U -s /bin/bash $SSH_USER_NAME

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Ensure ownership first
RUN chown -R ${SSH_USER_NAME}:${SSH_USER_NAME} /home/${SSH_USER_NAME}

# Exclude core messages in docker cotnainer
RUN sed -i 's/system()/system(exclude-kmsg(yes))/g' /etc/syslog-ng/syslog-ng.conf || true

# Reduce syslog-ng noise in container
RUN mkdir -p /usr/share/syslog-ng && \
    touch /usr/share/syslog-ng/smart-multi-line.fsm && \
    sed -i '1s/^@version: .*/@version: 4.3/' /etc/syslog-ng/syslog-ng.conf || true && \
    sed -i 's/^[[:space:]]*stats_freq([^)]*);/stats(freq(0));/' /etc/syslog-ng/syslog-ng.conf || true

# Set timezone
RUN  ln -fs /usr/share/zoneinfo/$TIMEZONE /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Configure sshd
RUN sed -i 's/^#\?PasswordAuthentication .*/PasswordAuthentication yes/' /etc/ssh/sshd_config && \
    sed -i 's/^#\?PermitRootLogin .*/PermitRootLogin no/' /etc/ssh/sshd_config

# Create container startup script
RUN cat > /start.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER_NAME:?SSH_USER_NAME env not set}"
: "${SSH_USER_PASSWORD:?SSH_USER_PASSWORD env not set}"

# Set password at runtime (not build time)
echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

service syslog-ng start
service ssh start

REPO_DIR="/home/${SSH_USER_NAME}/repos/home-monitor"
MONITOR_CMD="exec sleep infinity"

if [ -d "$REPO_DIR/.git" ]; then
    sudo -u "$SSH_USER_NAME" bash -c "cd \"$REPO_DIR\" && git pull" || true

    if [ -x "$REPO_DIR/start.sh" ]; then
        MONITOR_CMD="cd \"$REPO_DIR\" && exec ./start.sh"
    elif [ -f "$REPO_DIR/main.py" ]; then
        MONITOR_CMD="cd \"$REPO_DIR\" && exec python3 main.py"
    fi
fi

cat > /etc/supervisor/conf.d/monitor.conf <<EOF
[supervisord]
nodaemon=true
user=root

[program:monitor]
command=/bin/bash -c '$MONITOR_CMD'
directory=/home/${SSH_USER_NAME}
user=${SSH_USER_NAME}
environment=HOME="/home/${SSH_USER_NAME}",USER="${SSH_USER_NAME}",LOGNAME="${SSH_USER_NAME}",SHELL="/bin/bash"
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
EOF

exec /usr/bin/supervisord -c /etc/supervisor/conf.d/monitor.conf
SH

RUN chmod +x /start.sh

# Run container start up script
CMD ["/bin/bash", "/start.sh"]