FROM ubuntu:latest

# Set environment variables to avoid interactive prompts during installation
ENV DEBIAN_FRONTEND=noninteractive

# Expected arguments
ARG DB_NAME
ARG POSTGRES_PASSWORD
ARG DB_ADMIN_NAME
ARG DB_ADMIN_PASSWORD
ARG DB_READER_NAME
ARG DB_READER_PASSWORD
ARG SSH_USER_NAME
ARG SSH_USER_PASSWORD
ARG HOSTNAME
ARG MAIL_DOMAIN
ARG REQUIRE_STARTTLS
ARG TIMEZONE
ARG ADDITIONAL_MY_NETWORKS
ARG RELAY_HOST
ARG RELAY_HOST_PORT=25

# Configuration file directory
ARG CONFIG_DIR="/home/${SSH_USER_NAME}"

# Validate arguments have been set
RUN if [ -z "$DB_NAME" ]; then \
    echo "Error: DB_NAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$POSTGRES_PASSWORD" ]; then \
    echo "Error: POSTGRES_PASSWORD must be defined!" && exit 1; \
    fi

RUN if [ -z "$DB_ADMIN_NAME" ]; then \
    echo "Error: DB_ADMIN_NAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$DB_ADMIN_PASSWORD" ]; then \
    echo "Error: DB_ADMIN_PASSWORD must be defined!" && exit 1; \
    fi

RUN if [ -z "$DB_READER_NAME" ]; then \
    echo "Error: DB_READER_NAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$DB_READER_PASSWORD" ]; then \
    echo "Error: DB_READER_PASSWORD must be defined!" && exit 1; \
    fi

RUN if [ -z "$SSH_USER_NAME" ]; then \
    echo "Error: SSH_USER_NAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$SSH_USER_PASSWORD" ]; then \
    echo "Error: SSH_USER_PASSWORD must be defined!" && exit 1; \
    fi

RUN if [ -z "$HOSTNAME" ]; then \
    echo "Error: HOSTNAME must be defined!" && exit 1; \
    fi

RUN if [ -z "$MAIL_DOMAIN" ]; then \
    echo "Error: MAIL_DOMAIN must be defined!" && exit 1; \
    fi

RUN if [ -z "$REQUIRE_STARTTLS" ]; then \
    echo "Error: REQUIRE_STARTTLS must be defined!" && exit 1; \
    fi

RUN if [ -z "$TIMEZONE" ]; then \
    echo "Error: TIMEZONE must be defined!" && exit 1; \
    fi

RUN if [ -z "$ADDITIONAL_MY_NETWORKS" ]; then \
    echo "Error: ADDITIONAL_MY_NETWORKS must be defined!" && exit 1; \
    fi

# Install packages
RUN apt update && DEBIAN_FRONTEND=noninteractive apt install -y \
    sudo \
    syslog-ng \
    telnet \
    nano \
    tzdata \
    openssh-server \
    nginx \
    postfix postfix-pgsql \
    dovecot-core dovecot-imapd dovecot-pop3d dovecot-pgsql \
    postgresql postgresql-contrib 

RUN rm -rf /var/lib/apt/lists/*

# The ports to expose:
#    80 - for lets encrypt to prove domain ownership in .well-known/acme-challenge
#   443 - NGINX https
#    22 - SSH
#    25 - SMTP
#   587 - SMTP AUTH
#   993 - POP3
EXPOSE 80 443 22 25 587 993

# Create the SSH user and set a password
RUN useradd -m -s /bin/bash $SSH_USER_NAME && echo "$SSH_USER_NAME:$SSH_USER_PASSWORD" | chpasswd

# Add the SSH user to the sudo group
RUN usermod -aG sudo $SSH_USER_NAME

# Create SSH run file directory
RUN mkdir /var/run/sshd 

# Exclude core messages in docker cotnainer
RUN sudo sed -i 's/system()/system(exclude-kmsg(yes))/g' /etc/syslog-ng/syslog-ng.conf

# Create mailreader group
RUN sudo groupadd $DB_READER_NAME

# Create mailreader user
RUN sudo useradd -g $DB_READER_NAME -d /home/mail -s /sbin/nologin $DB_READER_NAME

# Create users mail directory root and change owner to mail reader account
RUN sudo mkdir /home/mail
RUN sudo chown $DB_READER_NAME:$DB_READER_NAME /home/mail

# Set up PostgreSQL
RUN service postgresql start && \
    export DB_READER_GROUP_ID=$(getent group $DB_READER_NAME | cut -d: -f3) && \
    sudo -u postgres psql -c "ALTER USER postgres PASSWORD '$POSTGRES_PASSWORD';"  && \
    sudo -u postgres psql -c "CREATE DATABASE $DB_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "CREATE USER $DB_ADMIN_NAME WITH PASSWORD '$DB_ADMIN_PASSWORD';"  && \
    sudo -u postgres psql -d $DB_NAME -c "CREATE USER $DB_READER_NAME WITH PASSWORD '$DB_READER_PASSWORD';"  && \
    sudo -u postgres psql -d $DB_NAME -c "CREATE TABLE users (email VARCHAR PRIMARY KEY, password VARCHAR, realname VARCHAR, maildir VARCHAR NOT NULL, created TIMESTAMP WITH TIME ZONE DEFAULT now());"  && \    
    sudo -u postgres psql -d $DB_NAME -c "CREATE TABLE transports (domain VARCHAR PRIMARY KEY, gid INTEGER NOT NULL, transport VARCHAR NOT NULL);"  && \    
    sudo -u postgres psql -d $DB_NAME -c "CREATE TABLE aliases (alias VARCHAR PRIMARY KEY, email VARCHAR NOT NULL);"  && \    
    sudo -u postgres psql -d $DB_NAME -c "GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_ADMIN_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT SELECT ON users TO $DB_ADMIN_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT UPDATE ON users TO $DB_ADMIN_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT SELECT ON aliases TO $DB_ADMIN_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT UPDATE ON aliases TO $DB_ADMIN_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT SELECT ON transports TO $DB_READER_NAME;" && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT UPDATE ON transports TO $DB_READER_NAME;" && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT SELECT ON users TO $DB_READER_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT SELECT ON aliases TO $DB_READER_NAME;"  && \
    sudo -u postgres psql -d $DB_NAME -c "GRANT SELECT ON transports TO $DB_READER_NAME;" && \
    if [ -n "$RELAY_HOST" ]; then sudo -u postgres psql -d $DB_NAME -c "INSERT INTO transports (domain, gid, transport) VALUES ('*', $DB_READER_GROUP_ID, 'relay:[$RELAY_HOST]:25') ON CONFLICT (domain) DO NOTHING;"; fi

# Copy the users definition file
COPY users.csv $CONFIG_DIR/users.csv 

# Copy the user add shell script
COPY add_users.sh $CONFIG_DIR/add_users.sh

# Change ownership
RUN sudo chown $SSH_USER_NAME:$SSH_USER_NAME $CONFIG_DIR/add_users.sh && sudo chown $SSH_USER_NAME:$SSH_USER_NAME $CONFIG_DIR/users.csv

# Set the DB name in the add users script
RUN sudo sed -i "s/DB_NAME=\"maildb\"/DB_NAME=$DB_NAME/" $CONFIG_DIR/add_users.sh

# Set the group ID in the add users script
RUN sudo sed -i "s/GROUP_ID=\"1002\"/GROUP_ID=\"$(id -g $DB_READER_NAME)\"/" $CONFIG_DIR/add_users.sh

# Make executable
RUN chmod +x $CONFIG_DIR/add_users.sh

# Configure SQL for reading users
RUN cat <<EOF > /etc/postfix/users.cf
user=$DB_READER_NAME
password=$DB_READER_PASSWORD
dbname=$DB_NAME
table=users
select_field=maildir
where_field=email
hosts=localhost
EOF

# Configure SQL for reading aliases
RUN cat <<EOF > /etc/postfix/aliases.cf
user=$DB_READER_NAME
password=$DB_READER_PASSWORD
dbname=$DB_NAME
table=aliases
select_field=email
where_field=alias
hosts=localhost
EOF

# Configure SQL for reading transports
RUN cat <<EOF > /etc/postfix/transports.cf
user=$DB_READER_NAME
password=$DB_READER_PASSWORD
dbname=$DB_NAME
table=transports
select_field=transport
where_field=domain
hosts=localhost
EOF

RUN sudo cp /etc/postfix/master.cf /etc/postfix/master.cf.bak

RUN sed -i '/^#submission inet n[[:space:]]\+-[[:space:]]\+y[[:space:]]\+-[[:space:]]\+-[[:space:]]\+smtpd/,/^#/c\
    submission inet n       -       y       -       -       smtpd\n\
    -o syslog_name=postfix/submission\n\
    -o smtpd_tls_wrappermode=no\n\
    -o smtpd_tls_security_level=encrypt\n\
    -o smtpd_sasl_auth_enable=yes\n\
    -o smtpd_sasl_type=dovecot\n\
    -o smtpd_sasl_path=private/auth' /etc/postfix/master.cf

RUN sed -i '0,/^#  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject/s/^#  -o smtpd_recipient_restrictions=permit_sasl_authenticated,reject/  -o smtpd_recipient_restrictions=permit_sasl_authenticated,defer/' /etc/postfix/master.cf

RUN sed -i '0,/^#  -o smtpd_relay_restrictions=/s/^#  -o smtpd_relay_restrictions=/  -o smtpd_relay_restrictions=permit_sasl_authenticated,reject_unauth_destination/' /etc/postfix/master.cf

RUN sed -i '0,/^#\s*-o milter_macro_daemon_name=ORIGINATING/ s//  -o milter_macro_daemon_name=ORIGINATING/' /etc/postfix/master.cf

RUN sed -i '/cleanup   unix  n       -       y       -       0       cleanup/c\
    cleanup   unix  n       -       y       -       0       cleanup\n\
    -o header_checks=regexp:/etc/postfix/header_checks' /etc/postfix/master.cf

# Careful of the single and double quoted strings in postconf settings (that is deliberate)
RUN sudo postconf -e "myhostname = $HOSTNAME" && \
    sudo postconf -e "mydomain = $MAIL_DOMAIN" && \
    sudo postconf -e 'myorigin = $mydomain'  && \
    sudo postconf -e 'inet_interfaces = all'  && \
    sudo postconf -e 'inet_protocols = ipv4'  && \
    sudo postconf -e 'mailbox_size_limit = 0'  && \
    sudo postconf -e 'message_size_limit = 10240000'  && \
    sudo postconf -e "smtpd_tls_cert_file = /etc/letsencrypt/live/$HOSTNAME-rsa/fullchain.pem" && \
    sudo postconf -e "smtpd_tls_key_file = /etc/letsencrypt/live/$HOSTNAME-rsa/privkey.pem" && \
    sudo postconf -e "mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 $ADDITIONAL_MY_NETWORKS" && \
    sudo postconf -e "relay_domains = $MAIL_DOMAIN" && \
    sudo postconf -e 'mydestination = $myhostname, localhost.$mydomain, $mydomain' && \
    sudo postconf -e 'disable_dns_lookups = yes'

# Allow connections from trusted networks and authenticated users only (https://www.postfix.org/SMTPD_ACCESS_README.html)
RUN sudo postconf -e 'smtpd_client_restrictions = permit_mynetworks, permit_sasl_authenticated, reject'

# Don't talk to mail systems that don't know their own hostname.
# With Postfix < 2.3, specify reject_unknown_hostname.
# RUN sudo postconf -e 'smtpd_helo_restrictions = reject_unknown_helo_hostname'

# Don't accept mail from domains that don't exist.
# RUN sudo postconf -e 'smtpd_sender_restrictions = reject_unknown_sender_domain'

# Force encrypt (client must use STARTLS)
RUN if [ "$REQUIRE_STARTTLS" = "true" ]; then sudo postconf -e 'smtpd_tls_security_level = encrypt'; fi

# Disable local mail delivery on mailserver, we are using virtual mailboxes
RUN sudo postconf -e 'local_recipient_maps = '

# Set the owner of all mailboxes to 
RUN sudo postconf -e "virtual_uid_maps = static:$(id -u $DB_READER_NAME)"
RUN sudo postconf -e "virtual_gid_maps = static:$(id -g $DB_READER_NAME)"

# Set virtual mailbox bas address
RUN sudo postconf -e 'virtual_mailbox_base = /home/mail/'

# Configre how to map to virtual mailboxes
RUN sudo postconf -e 'virtual_mailbox_maps = pgsql:/etc/postfix/users.cf'

# Configure how to map to aliases
RUN sudo postconf -e 'virtual_alias_maps = pgsql:/etc/postfix/aliases.cf'

# Configure how to map to transports
RUN sudo postconf -e 'transport_maps = pgsql:/etc/postfix/transports.cf'

# Clean specified headers
RUN echo "/^Received:.*with ESMTPSA/ IGNORE\n/^Return-Receipt-To:/ IGNORE\n/^Disposition-Notification-To:/ IGNORE" > /etc/postfix/header_checks  
RUN sudo postmap /etc/postfix/header_checks

# Configure Dovecot master.cf
RUN sudo cp /etc/dovecot/conf.d/10-master.conf /etc/dovecot/conf.d/10-master.conf.bak
RUN sed -i '/unix_listener auth-userdb {/,/}/c\
    unix_listener auth-userdb {\n\
    path = /var/spool/postfix/private/auth\n\
    mode = 0600\n\
    user = postfix\n\
    group = postfix\n\
    }' /etc/dovecot/conf.d/10-master.conf

# Configure Dovecot SSL
RUN sudo cp /etc/dovecot/conf.d/10-ssl.conf /etc/dovecot/conf.d/10-ssl.conf.bak
RUN sudo sed -i 's/^ssl = yes/ssl = required/' /etc/dovecot/conf.d/10-ssl.conf
RUN sudo sed -i "s/^ssl_cert = <\/etc\/dovecot\/private\/dovecot.pem/ssl_cert = <\/etc\/letsencrypt\/live\/$HOSTNAME-rsa\/fullchain.pem/" /etc/dovecot/conf.d/10-ssl.conf
RUN sudo sed -i "s/^ssl_key = <\/etc\/dovecot\/private\/dovecot.key/ssl_key = <\/etc\/letsencrypt\/live\/$HOSTNAME-rsa\/privkey.pem/" /etc/dovecot/conf.d/10-ssl.conf
RUN sudo sed -i 's/^#ssl_min_protocol = TLSv1.2/ssl_min_protocol = TLSv1.2/' /etc/dovecot/conf.d/10-ssl.conf
RUN sudo sed -i 's/^#ssl_prefer_server_ciphers = no/ssl_prefer_server_ciphers = yes/' /etc/dovecot/conf.d/10-ssl.conf

# Configure Dovecot auth for plain and login
RUN sudo sed -i 's/^auth_mechanisms = plain/auth_mechanisms = plain login/' /etc/dovecot/conf.d/10-auth.conf

# Configure Dovecot auth for SQL
RUN sudo sed -i 's/^!include auth-system.conf.ext/#!include auth-system.conf.ext/' /etc/dovecot/conf.d/10-auth.conf
RUN sudo sed -i 's/^#!include auth-sql.conf.ext/!include auth-sql.conf.ext/' /etc/dovecot/conf.d/10-auth.conf

# We want to prefetch user information when querying password
# See: https://doc.dovecot.org/2.3/configuration_manual/authentication/prefetch_userdb/#authentication-prefetch-userdb
RUN sudo sed -i '/^userdb[[:space:]]*{/,/^}/ {/^\s*driver = sql/s/driver = sql/driver = prefetch/}' /etc/dovecot/conf.d/auth-sql.conf.ext
RUN sudo sed -i '/^userdb[[:space:]]*{/,/^}/ {/^\s*args = \/etc\/dovecot\/dovecot-sql.conf.ext/s/^/# /}' /etc/dovecot/conf.d/auth-sql.conf.ext

# Set IDs of mail read group and account
RUN sudo sed -i "s/^#mail_uid =/mail_uid = $DB_READER_NAME/" /etc/dovecot/conf.d/10-mail.conf
RUN sudo sed -i "s/^#mail_gid =/mail_gid = $DB_READER_NAME/" /etc/dovecot/conf.d/10-mail.conf

# Debugging Dovecot (un comment these to see debug info in dovecot logging)
# RUN sudo sed -i 's/^#auth_verbose = no/auth_verbose = yes/' /etc/dovecot/conf.d/10-logging.conf
# RUN sudo sed -i 's/^#auth_verbose_passwords = no/auth_verbose_passwords = yes/' /etc/dovecot/conf.d/10-logging.conf
# RUN sudo sed -i 's/^#auth_debug = no/auth_debug = yes/' /etc/dovecot/conf.d/10-logging.conf
# RUN sudo sed -i 's/^#auth_debug_passwords = no/auth_debug_passwords = yes/' /etc/dovecot/conf.d/10-logging.conf
# RUN sudo sed -i 's/^#mail_debug = no/mail_debug = yes/' /etc/dovecot/conf.d/10-logging.conf
# RUN sudo sed -i 's/^#verbose_ssl = no/verbose_ssl = yes/' /etc/dovecot/conf.d/10-logging.conf

# Configure Dovecot to use PostgreSQL for virtual users 
RUN echo "driver = pgsql" > /etc/dovecot/dovecot-sql.conf.ext \
    && echo "connect = host=localhost dbname=$DB_NAME user=$DB_READER_NAME password=$DB_READER_PASSWORD" >> /etc/dovecot/dovecot-sql.conf.ext \
    && echo "default_pass_scheme = BLF-CRYPT" >> /etc/dovecot/dovecot-sql.conf.ext \
    && echo "password_query = SELECT email as user, password, 'maildir:/home/mail/'||maildir as userdb_mail FROM users WHERE email = '%u'" >> /etc/dovecot/dovecot-sql.conf.ext

# Create directories for Postfix and Dovecot
RUN mkdir -p /var/mail/vhosts && chown -R dovecot:dovecot /var/mail/vhosts

# Set owner for nginx to www-data
RUN chown -R www-data:www-data /var/lib/nginx

# Add site config for lets encrypt to verify domain ownership
RUN echo "server {\n"                                \
    "    listen 80;\n"                               \
    "    listen [::]:80;\n"                          \
    "    server_name $HOSTNAME;\n"                   \
    "    root /var/www/html;\n"                      \
    "\n"                                             \
    "    location / {\n"                             \
    "        index index.html;\n"                    \
    "    }\n"                                        \
    "\n"                                             \
    "    location ~ /.well-known/acme-challenge {\n" \
    "        allow all;\n"                           \
    "    }\n"                                        \
    "}\n"                                            > /etc/nginx/sites-available/$HOSTNAME                              

# Create index.html just for testing site up and running
RUN echo "<!DOCTYPE html>\n"                                                           \
    "<html lang=""en"">\n"                                                             \
    "\n"                                                                               \
    "<head>\n"                                                                         \
    "    <meta charset=""UTF-8"">\n"                                                   \
    "    <meta name=""viewport"" content=""width=device-width, initial-scale=1.0"">\n" \
    "    <title>$MAIL_DOMAIN</title>\n"                                                \
    "</head>\n"                                                                        \
    "\n"                                                                               \
    "<body>\n"                                                                         \
    "    <p>active</p>\n"                                                              \
    "    <span>$(date '+%Y-%m-%d %H:%M:%S')</span>\n"                                  \
    "</body>\n"                                                                        \
    "\n"                                                                               \
    "</html>\n"                                                                        > /var/www/html/index.html

# Make site active
RUN ln -s /etc/nginx/sites-available/$HOSTNAME /etc/nginx/sites-enabled/$HOSTNAME

# Ensure lets encrypt ACME ping file exists
RUN mkdir -p /var/www/html/.well-known/acme-challenge && echo ok > /var/www/html/.well-known/acme-challenge/ping

# Set timezone
RUN  ln -fs /usr/share/zoneinfo/$TIMEZONE /etc/localtime && \
    dpkg-reconfigure -f noninteractive tzdata

# Create container startup script
RUN echo "#!/bin/bash\n\
    sudo service syslog-ng start\n\
    sudo service ssh start\n\
    sudo service postgresql start\n\
    sudo service postfix start\n\
    sudo service dovecot start\n\
    sudo nginx -g 'daemon off;'\n\
    tail -f /var/log/mail.log" > /start.sh && chmod +x /start.sh

# Run container start up script
CMD ["/bin/bash", "/start.sh"]
