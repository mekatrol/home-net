# Watchdog set up

## Generate SSH key pair

Run this once on the machine hosting the Docker container:

```bash
ssh-keygen -t ed25519 -f ./secrets/watchdog_key -N "" -C "home-monitor-watchdog"
```

This creates:
- `./secrets/watchdog_key` — private key (mounted into the container at `/run/secrets/watchdog_key`)
- `./secrets/watchdog_key.pub` — public key (copied to each monitored Pi)

> **Note:** Never commit `secrets/` to git.

## Set up each monitored Pi

### 1. Create the watchdog user

```bash
sudo useradd -m -s /bin/bash watchdog
sudo mkdir -p /home/watchdog/.ssh
sudo chown -R watchdog:watchdog /home/watchdog/.ssh
sudo chmod 700 /home/watchdog/.ssh
```

### 2. Install the command dispatcher

The dispatcher is the security boundary on the Pi. It validates every incoming
SSH command against an explicit allowlist before acting. Even if the monitor
container is compromised and the private key stolen, an attacker can only trigger
commands the Pi explicitly permits.

```bash
# Copy from this repo to the Pi (run from the repo root on the Pi, or scp it across first)
scp remote/watchdog-dispatch pi@<pi-hostname-or-ip>:/tmp/watchdog-dispatch
ssh -t pi@<pi-hostname-or-ip> "sudo mv /tmp/watchdog-dispatch /usr/local/bin/watchdog-dispatch && sudo chown root:root /usr/local/bin/watchdog-dispatch && sudo chmod 755 /usr/local/bin/watchdog-dispatch"
```

To add new allowed commands in future, edit the `case` block in that script.

### 3. Allow only the dispatcher via sudo

```bash
sudo tee /etc/sudoers.d/watchdog <<'EOF'
watchdog ALL=(ALL) NOPASSWD: /sbin/reboot, /usr/bin/apt, /usr/bin/apt-get
EOF
sudo chmod 440 /etc/sudoers.d/watchdog
```

Only the specific binaries called from `watchdog-dispatch` need to be listed here.

### 4. Authorize the public key — restricted to the dispatcher

The `command=` option forces every SSH connection using this key through the
dispatcher, regardless of what the client requests:

```bash
mkdir ./secrets
nano ./secrets/watchdog_key.pub
```

> Paste the contents of ./secrets/watchdog_key.pub

```bash
PUBKEY=$(cat ./secrets/watchdog_key.pub)
sudo tee /home/watchdog/.ssh/authorized_keys <<EOF
command="/usr/local/bin/watchdog-dispatch",no-port-forwarding,no-X11-forwarding,no-agent-forwarding,no-pty $PUBKEY
EOF
sudo chmod 600 /home/watchdog/.ssh/authorized_keys
sudo chown watchdog:watchdog /home/watchdog/.ssh/authorized_keys
```

### 5. Test the connection

```bash
# Should trigger a reboot
ssh -i ./secrets/watchdog_key watchdog@<pi-hostname-or-ip> reboot

# Should be rejected by the dispatcher
ssh -i ./secrets/watchdog_key watchdog@<pi-hostname-or-ip> "rm -rf /"
```

## Deploy the container

Place your real config at `./secrets/config.yaml` — see `app/config.yaml.example` for the format.

```bash
SSH_USER_NAME="watchdog" SSH_USER_PASSWORD="pwd" HOSTNAME="ai.lan" DNSHOST="9.9.9.9" TIMEZONE="Australia/Sydney" ./create.sh
```
