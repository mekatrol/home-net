# Configuring cloud MTA to use on-premises MTA

# On a new digital ocean Ubuntu droplet

## Update packages

```bash
apt update && apt upgrade -y
```

## Set host name to fqdns

Update the following files to FQDN hostname and then reboot

* `nano /etc/hostname`
* `nano /etc/hosts`

Reboot server

`sudo reboot`

## Set up SSH

### Add ssh user

```bash
# Change `user` to actual new user name
export SSH_USER=user

# Create user home and copy SSH key
mkdir -p /home/$SSH_USER/.ssh
cp /root/.ssh/authorized_keys /home/$SSH_USER/.ssh/

# Add user
useradd -d /home/$SSH_USER $SSH_USER -s /bin/bash

# user to SUDOers group
usermod -aG sudo $SSH_USER

# Set ownership to new user
chown -R $SSH_USER:$SSH_USER /home/$SSH_USER/

# Set permissions
chmod 700 /home/$SSH_USER/.ssh
chmod 600 /home/$SSH_USER/.ssh/authorized_keys

# Now set the users password
passwd $SSH_USER
```

### Sign in as user via SSH

> Make sure you can sign in over SSH as the user and do a `sudo su` successfully.

### Disable root login via ssh

Sign in as the new user

```bash
sudo nano /etc/ssh/sshd_config
```

Set PermitRootLogin to no
```ini
PermitRootLogin no
```

Save, exit and reboot machine

```bash
sudo reboot
```

## Set up certificates using certmon, we'll use nginx to allow Lets Encrypt to validate we own the DNS record.

Install needed packages (nginx and certbot)
```bash
sudo apt install nginx certbot python3-certbot-nginx -y
```

Configure NGINX for verifying hostname ownership

```bash
# Set owner for nginx to www-data
sudo chown -R www-data:www-data /var/lib/nginx

# Configure acme challenge
cat <<EOF | sudo tee /etc/nginx/sites-available/$HOSTNAME > /dev/null
server {
    listen 80;
    listen [::]:80;
    server_name $HOSTNAME;
    root /var/www/html;

    location / {
        index index.html;
    }

    location ~ /.well-known/acme-challenge {
        allow all;
    }
}
EOF

# Create index.html
cat <<EOF | sudo tee /var/www/html/index.html > /dev/null
<!DOCTYPE html>
<html lang="en">

<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>$HOSTNAME</title>
</head>
<body>
    <p>active</p>
    <span>$(date '+%Y-%m-%d %H:%M:%S')</span>
</body>
</html>
EOF

# Enable site
sudo ln -s /etc/nginx/sites-available/$HOSTNAME /etc/nginx/sites-enabled/$HOSTNAME

# Restart NGINX
sudo service nginx restart
```

Run certbot for the first time
```bash
sudo certbot certonly --webroot --webroot-path=/var/www/html --email admin@$HOSTNAME --agree-tos --no-eff-email --cert-name $HOSTNAME-rsa -d $HOSTNAME --key-type rsa
```

## Install and configure postfix

### Install

```bash
# Install
sudo apt install postfix -y
```

> When prompted select `Internet Site` and set your mail server host name (it will default to machine host name).

```bash
# Backup configuration files
sudo cp /etc/postfix/main.cf /etc/postfix/main.cf.bak
sudo cp /etc/postfix/master.cf /etc/postfix/master.cf.bak
```

As a quick check start the postfix service, view logs, then stop the service. You should successfully see log entries with no errors.
```bash
sudo service postfix start
sudo tail -n 100 /var/log/mail.log
```

### Accept relaying from internal on-premises server

In /etc/postfix/main.cf add internal on-premises server IP to end of mynetworks 

```bash
sudo nano /etc/postfix/main.cf

mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 **ADD HERE**

# e.g.

mynetworks = 127.0.0.0/8 [::ffff:127.0.0.0]/104 [::1]/128 58.165.151.139/32
```

In /etc/postfix/main.cf remove the blank entry (two consecutive commas without a value) 

```bash
sudo nano /etc/postfix/main.cf

mydestination = $myhostname, smtp.<domain>.com, localhost.<domain>.com, , localhost
```

### Accept all users for configured domains and forward to upstream server for those domains
```bash
export DOMAIN1=@domain1.com
export DOMAIN2=@domain2.com
export UPSTREAM_SMTP=smtp.upstream.com

cat <<EOF | sudo tee /etc/postfix/transport > /dev/null
$DOMAIN1    smtp:[$UPSTREAM_SMTP]
$DOMAIN2    smtp:[$UPSTREAM_SMTP]
EOF

# Compile transports into db file
sudo postmap /etc/postfix/transport

# The domains that this SMTP server can relay
sudo postconf -e "relay_domains = $DOMAIN1, $DOMAIN2"

# No alias maps (accept all recipients)
sudo postconf -e "virtual_alias_maps = "

# Configure certificate
sudo postconf -e "smtpd_tls_cert_file = /etc/letsencrypt/live/$HOSTNAME-rsa/fullchain.pem" 
sudo postconf -e "smtpd_tls_key_file = /etc/letsencrypt/live/$HOSTNAME-rsa/privkey.pem" 

# Any recipient domains that are not one of the relay_domains will use any configured relayhost to send mail
# If no relayhost is configured then the recipient domains SMTP server is used
sudo postconf -e "relayhost = "
sudo postconf -e "transport_maps = hash:/etc/postfix/transport"

sudo service postfix restart
```

### Test SMTP

Check virtual transport working
```bash
postmap -q $DOMAIN1 /etc/postfix/transport
postmap -q $DOMAIN2 /etc/postfix/transport
```

On another machine start telnet

`telnet`

Send an email to each domain using the following template (not the blank line before dot is needed to signal end of message)

```bash
OPEN smtp.upstream.com 25

EHLO dummydomain.com

MAIL FROM:<user@dummydomain.com>
RCPT TO:<user@domain1.com> NOTIFY=success,failure
DATA
Subject: Test using telnet
From:'John Doe'<john.doe@dummydomain.com>
To:'Jane Doe'<jane.doe@domain1.com>

.

QUIT
```

## Configure SPF, DKIM and DMARC

### SPF

Set SPF record

```bash
v=spf1 ip4:YOUR.MAIL.SERVER.IP -all
```

e.g: if domain is test.com and IP address of SMTP server is 58.165.151.139 then:

<pre>
Type   Name       Value  
TXT    test.com   v=spf1 ip4:58.165.151.139 -all  
</pre>

### DKIM

```bash
sudo apt install opendkim opendkim-tools -y
```

Make keys for domain (eg for test.com) - can be done for each domain (changing $MAIL_DOMAIN):

```bash
export MAIL_DOMAIN=test.com
sudo mkdir -p /etc/opendkim/keys/$MAIL_DOMAIN
cd /etc/opendkim/keys/$MAIL_DOMAIN
sudo opendkim-genkey -s default -d $MAIL_DOMAIN
sudo chown opendkim:opendkim default.private
```
Set DKIM record

e.g: if domain is test.com and IP address of SMTP server is 58.165.151.139 then (where p=) which can be obtained from default.txt

Make sure:

* No newlines  
* No quotes (")  
* No semicolons at the end  
* No extra whitespace  

<pre>
Type   Name                 Value  
TXT    default._domainkey   starts with v=DKIM1; k=rsa; p=... 
</pre>

Configure OpenDKIM

```bash
sudo nano /etc/opendkim.conf
```

Add contents to end of file:
```bash
Selector                default
Socket                  inet:12301@localhost
Canonicalization        relaxed/simple
Mode                    sv
SubDomains              no
# Servers to trust
ExternalIgnoreList      /etc/opendkim/TrustedHosts
InternalHosts           /etc/opendkim/TrustedHosts
KeyTable                /etc/opendkim/KeyTable
SigningTable            /etc/opendkim/SigningTable
AutoRestart             yes
```

```bash
sudo nano /etc/opendkim/KeyTable
```

Enter contents (add each domain on a new line):
```bash
default._domainkey.test.com test.com:default:/etc/opendkim/keys/test.com/default.private
```

```bash
sudo nano /etc/opendkim/SigningTable
```

Enter contents (add each domain on a new line):
```bash
test.com default._domainkey.test.com
```

```bash
sudo nano /etc/opendkim/TrustedHosts
```

NOTES: 
> enter the IP address of servers who can send (relay) through this SMTP server  
> i.e. add any IP addresses for on-premises servers  

Enter:  
```bash
127.0.0.1
localhost
58.165.151.139
```

```bash
sudo nano /etc/postfix/main.cf
```

Add:
```bash
# DKIM
milter_default_action = accept
milter_protocol = 2
smtpd_milters = inet:localhost:12301
non_smtpd_milters = inet:localhost:12301
```

Restart services:
```bash
sudo service opendkim restart
sudo service postfix restart
```

### DMARC

Set DMARC record

e.g: if domain is test.com and IP address of SMTP server is 58.165.151.139 then:

<pre>
Type   Name       Value  
TXT    _dmarc     v=DMARC1; p=quarantine; rua=mailto:postmaster@test.com 
</pre>

### Verify

1. Send an email to a Gmail account.
2. Click on the message
3. Select show original (ellipses on right hand side)
4. Verify SPF, DKIM and DMARC have all passed.

Also:

```bash
dig TXT test.com
dig TXT default._domainkey.test.com
dig TXT _dmarc.test.com
```

Test SMTP client:

```c#
using System.Net.Mail;
using System.Net;

namespace SendMail
{
    internal class Program
    {
        static void Main()
        {
            using var smtpClient = new SmtpClient("smtp.test.com")
            {
                Port = 587,
                Credentials = new NetworkCredential("email@smtp.test.com", "email_password"),
                EnableSsl = true
            };

            smtpClient.Send("email@test.com", "recipient@test.com", "authenticated!", "email body");
        }
    }
}
```