# Watchdog set up

## Overview

The monitor runs in a Docker container (`ai`) on the host machine and watches
a set of remote Raspberry Pi devices. It detects silence (missed MQTT pings)
and reboots unresponsive devices over SSH.

Two things must be in place on each monitored Pi:

- **Watchdog SSH access** — allows the monitor container to SSH in and trigger
  a reboot when the device goes silent. A restricted user (`watchdog`) and a
  command dispatcher enforce that only permitted operations are possible, even
  if the private key were stolen.

- **MQTT ping service** — a lightweight Python service (`ping`) that publishes
  a heartbeat to a configured MQTT topic at a regular interval. The watchdog
  container watches for this heartbeat; if it goes missing long enough, the
  device is rebooted.

Both are deployed in a single idempotent script.

---

## Prerequisites

### 1. Generate the watchdog SSH key pair

Run once on the machine hosting the Docker container, from the `servers/ai/` directory:

```bash
ssh-keygen -t ed25519 -f ./secrets/watchdog_key -N "" -C "home-monitor-watchdog"
```

This creates:
- `./secrets/watchdog_key` — private key (mounted into the container at `/run/secrets/watchdog_key`)
- `./secrets/watchdog_key.pub` — public key (deployed to each monitored Pi by the script)

> **Note:** Never commit `secrets/` to git.

---

## Deploy to a monitored Pi

Run from the `servers/ai/` directory:

```bash
./scripts/deploy.sh pi@<hostname-or-ip>
# or with an SSH key:
./scripts/deploy.sh pi@<hostname-or-ip> ~/.ssh/id_rsa
```

The script prompts for MQTT broker details (broker address, topic, interval,
credentials) and then connects to the remote Pi over SSH — **one password
prompt** for the entire process.

### What the script does

**Watchdog SSH access:**

1. Creates the `watchdog` OS user on the remote Pi
2. Installs `remote/watchdog-dispatch` at `/usr/local/bin/watchdog-dispatch` —
   the security boundary that validates every incoming SSH command against an
   explicit allowlist (`reboot`, `upgrade`) before acting. Even if the private
   key is stolen, an attacker can only trigger commands on the allowlist.
3. Configures `/etc/sudoers.d/watchdog` so the `watchdog` user can only run
   the specific binaries called from the dispatcher (`/sbin/reboot`, `/usr/bin/apt`)
4. Installs `secrets/watchdog_key.pub` into `/home/watchdog/.ssh/authorized_keys`
   with a `command=` restriction that forces every SSH connection through the
   dispatcher, regardless of what the client requests
5. Verifies the dispatcher is working by confirming it rejects an unknown command

**MQTT ping service:**

6. Installs `python3-venv` and `python3-pip` via apt
7. Copies `deploy/main.py` and `deploy/requirements.txt` to `/opt/ping/`
8. Writes `/etc/ping/config.yaml` with the MQTT broker, topic, interval and
   credentials you entered at the prompt
9. Creates the `ping-svc` system user (no login shell, no home directory) and
   the log directory `/var/log/ping/`
10. Creates a Python venv at `/opt/ping/.venv` and installs pip dependencies
11. Installs `deploy/ping.service` as a systemd unit and enables it to start on boot
12. Starts (or restarts) the service and prints its status

The script is **idempotent** — safe to re-run after changing config, rotating
the SSH key, or updating the ping service code.

---

## Deploy the monitor container

Place your real config at `./secrets/config.yaml` — see `app/config.example.yaml`
for the format. Each device entry's `mqtt_topic` must match the topic you
configured when running `deploy.sh` on that Pi.

```bash
SSH_USER_NAME="ssh" SSH_USER_PASSWORD="changeme" HOSTNAME="ai.lan" DNSHOST="9.9.9.9" TIMEZONE="Australia/Sydney" ./create.sh
```

---

## Adding allowed commands to the dispatcher

Edit `remote/watchdog-dispatch` and add new entries to the `case` block, then
re-run `./scripts/deploy.sh` on each affected Pi to push the update.

---

## Logs

On the monitored Pi:
```bash
journalctl -u ping -f
tail -f /var/log/ping/ping.log
```

In the monitor container:
```bash
docker logs ai --tail=200 -f
```
