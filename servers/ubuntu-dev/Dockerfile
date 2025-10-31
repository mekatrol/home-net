FROM ubuntu:latest

# Set environment variables:
#  * avoid interactive prompts during installation
#  * force Python to write output immediately instead of buffering it
ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1

# Expected arguments
ARG SSH_USER_NAME
ARG SSH_USER_PASSWORD
ARG HOSTNAME
ARG TIMEZONE

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

# Base packages
RUN apt-get update && apt-get install -y \
    sudo syslog-ng-core syslog-ng-scl nano tzdata openssh-server git supervisor python3-venv iputils-ping dnsutils && \
    rm -rf /var/lib/apt/lists/*

ENV HOSTNAME=${HOSTNAME} SSH_USER_NAME=${SSH_USER_NAME}

# Create the SSH user and set a password
RUN useradd -m -U -s /bin/bash $SSH_USER_NAME && echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Create SSH run file directory
RUN mkdir -p /var/run/sshd /home/$SSH_USER_NAME/repos 

# Clone repo and take ownership for SSH user
RUN git clone https://github.com/mekatrol/home-monitor.git /home/$SSH_USER_NAME/repos/home-monitor && chown -R $SSH_USER_NAME:$SSH_USER_NAME /home/$SSH_USER_NAME/repos 

# Configure GIT
RUN git config --global user.name "Mekatrol" && \
    git config --global user.email git@mekatrol.com && \
    git config --global --add safe.directory /home/$SSH_USER_NAME/repos/home-monitor

# App user and dir
RUN useradd --system --no-create-home --shell /usr/sbin/nologin monitoruser \
    && mkdir -p /app
WORKDIR /app

# Create monitor user
RUN cp /home/$SSH_USER_NAME/repos/home-monitor/requirements.txt /app/ && \
    cp /home/$SSH_USER_NAME/repos/home-monitor/monitor/monitor.py /app/ && \
    python3 -m venv .venv && \
    ./.venv/bin/pip install --upgrade pip && \
    ./.venv/bin/pip install -r requirements.txt && \
    chown -R monitoruser:monitoruser /app 

# Supervisor program config
RUN tee /etc/supervisor/conf.d/monitor.conf >/dev/null <<'EOF'
[program:monitor]
command=/app/.venv/bin/python /app/monitor.py
directory=/app
user=monitoruser
autostart=true
autorestart=true
stdout_logfile=/app/monitor.out.log
stderr_logfile=/app/monitor.err.log
stopsignal=TERM
EOF

# Exclude core messages in docker cotnainer
RUN sed -i 's/system()/system(exclude-kmsg(yes))/g' /etc/syslog-ng/syslog-ng.conf

# Set timezone
RUN  ln -fs /usr/share/zoneinfo/$TIMEZONE /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Create container startup script
RUN cat > /start.sh <<'SH'
#!/usr/bin/env bash
set -euo pipefail

: "${SSH_USER_NAME:?SSH_USER_NAME env not set}"

service syslog-ng start
service ssh start

supervisord -n &
sleep 1

supervisorctl reread
supervisorctl update
supervisorctl status monitor

sudo -u "$SSH_USER_NAME" bash -lc 'cd ~/repos/home-monitor && git pull || true'

exec tail -f /var/log/syslog
SH
RUN chmod +x /start.sh

# Run container start up script
CMD ["/bin/bash", "/start.sh"]
