# Docker Host Setup with Pi-hole macvlan Network

## Update & Tools
```bash
sudo apt update && sudo apt upgrade -y
sudo apt install iputils-ping dnsutils nano -y
```

## Assumptions

```
Docker host:  10.2.2.205
Pi-hole host: 10.2.2.200
VLAN IP:      10.2.2.203
```

---

## 1. Configure Host Network (Netplan)

Edit `/etc/netplan/01-enp3s0.yaml`:

```yaml
network:
  version: 2
  renderer: networkd
  ethernets:
    enp3s0:
      dhcp4: false
      addresses: [10.2.2.205/24]
      routes:
        - to: default
          via: 10.2.2.1
      nameservers:
        addresses: [9.9.9.9]
```

Apply and lock down permissions:

```bash
sudo chmod 600 /etc/netplan/01-enp3s0.yaml
sudo chown root:root /etc/netplan/01-enp3s0.yaml
```

```bash
sudo netplan apply
```

---

## 2. Install docker
```bash
for pkg in docker.io docker-doc docker-compose docker-compose-v2 podman-docker containerd runc; do sudo apt-get remove $pkg; done
```

```bash
# Add Docker's official GPG key:
sudo apt-get update
sudo apt-get install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

# Add the repository to Apt sources:
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
sudo apt-get update
```

```bash
sudo apt-get install docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin -y
```

```bash
sudo systemctl status docker
```

```bash
sudo usermod -aG docker $USER
```

```bash
newgrp docker
```

```bash
sudo mkdir -p /opt/docker
sudo chown -R paul:paul /opt/docker
sudo mkdir -p /data
sudo chown -R paul:paul /data
```

---

## 3. Create macvlan Shim Service

Create `/etc/systemd/system/macvlan0.service`:

```ini
[Unit]
Description=Create macvlan0 shim on enp3s0
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
RemainAfterExit=yes

# Clean up if present
ExecStartPre=/bin/sh -c '/usr/sbin/ip link del macvlan0 2>/dev/null || true'

# Ensure parent exists and is up
ExecStartPre=/bin/sh -c 'for i in 1 2 3 4 5; do /usr/sbin/ip link show enp3s0 >/dev/null 2>&1 && /usr/sbin/ip link set enp3s0 up && exit 0; sleep 1; done; exit 1'

# Create shim
ExecStart=/usr/sbin/ip link add macvlan0 link enp3s0 type macvlan mode bridge
ExecStart=/usr/sbin/ip addr add 10.2.2.203/24 dev macvlan0
ExecStart=/usr/sbin/ip link set macvlan0 up

# Route host→Pi-hole via shim (idempotent)
ExecStartPost=/bin/sh -c '/usr/sbin/ip route replace 10.2.2.200/32 dev macvlan0'

# Cleanup on stop
ExecStop=/bin/sh -c '/usr/sbin/ip route del 10.2.2.200/32 dev macvlan0 2>/dev/null || true'
ExecStop=/usr/sbin/ip link del macvlan0

[Install]
WantedBy=multi-user.target
```

Enable and start the service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now macvlan0.service
```

This automatically creates the shim (`macvlan0`) at boot and ensures the host uses it to reach the Pi-hole container.

---

## 4. Verification

Confirm shim and routing:

```bash
ip addr show macvlan0
ip route get 10.2.2.200
```

Expected output should show:

```
10.2.2.200 dev macvlan0 src 10.2.2.203
```

Test host → container communication:

```bash
ping -I macvlan0 10.2.2.200 -c3
nslookup microsoft.com 10.2.2.200
```

If DNS queries fail, check Pi-hole inside Docker:

```bash
docker exec pihole ss -ulpnt | grep ':53'
docker logs pihole --tail=100
```

---

## 5. Summary

| Component    | IP Address   | Description                  |
| ------------ | ------------ | ---------------------------- |
| Docker host  | `10.2.2.205` | Main Ubuntu host             |
| Pi-hole host | `10.2.2.200` | Container on macvlan network |
| VLAN (shim)  | `10.2.2.203` | Host macvlan interface       |

The macvlan shim allows the host (`10.2.2.205`) to communicate directly with containers on the same subnet (`10.2.2.200`), which would otherwise be isolated by Linux’s macvlan driver.
