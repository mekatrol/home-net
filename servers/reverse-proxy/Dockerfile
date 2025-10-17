FROM ubuntu:latest

# Set environment variables to avoid interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

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

# Install packages
RUN apt update && DEBIAN_FRONTEND=noninteractive apt install -y \
    sudo \
    syslog-ng \
    nano \
    tzdata \
    openssh-server \
    curl \
    nginx-core \
    libnginx-mod-stream && \
    rm -rf /var/lib/apt/lists/*

# Include modules-enabled at top if missing in file
RUN grep -q '^include /etc/nginx/modules-enabled/\*.conf;' /etc/nginx/nginx.conf \
    || sed -i '1i include /etc/nginx/modules-enabled/*.conf;' /etc/nginx/nginx.conf

# The ports to expose:
#    80 - for lets encrypt to prove domain ownership in .well-known/acme-challenge
#   443 - NGINX https
EXPOSE 80 443

# Create the SSH user and set a password
RUN useradd -m -s /bin/bash $SSH_USER_NAME && echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Create SSH run file directory
RUN mkdir /var/run/sshd 

# Exclude core messages in docker cotnainer
RUN sudo sed -i 's/system()/system(exclude-kmsg(yes))/g' /etc/syslog-ng/syslog-ng.conf

# Set owner for nginx to www-data
RUN chown -R www-data:www-data /var/lib/nginx

# Delete the NGINX default redirect
RUN rm -f /etc/nginx/sites-enabled/default

# Copy the reverse proxy definition file (strip Windows carriage returns if they exist)
COPY reverse_proxy_list.txt /reverse_proxy_list.txt
RUN sed -i 's/\r$//' /reverse_proxy_list.txt

# Copy the reverse proxy configure shell script
COPY configure_reverse_proxy.sh /configure_reverse_proxy.sh

# Make shell script executable
RUN chmod +x /configure_reverse_proxy.sh

# Set timezone
RUN  ln -fs /usr/share/zoneinfo/$TIMEZONE /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Create container startup script
RUN cat > /start.sh <<'SH' && chmod +x /start.sh
#!/bin/bash
set -e
service syslog-ng start
ssh-keygen -A
service ssh start
/configure_reverse_proxy.sh
nginx -t
exec nginx -g 'daemon off;'
tail -f /var/log/nginx/access.log
SH

# Run container start up script
CMD ["/bin/bash", "/start.sh"]
