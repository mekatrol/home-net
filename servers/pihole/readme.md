# Set up docker host 

## Assumptions

```
Docker host: 10.2.2.205
pihole host: 10.2.2.200
VLAN IP:     10.2.2.203
```
## /etc/netplan/01-enp3s0.yaml

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

```bash
sudo netplan apply
```

## Other config
```bash
sudo tee /etc/systemd/network/10-macvlan0.netdev >/dev/null <<'EOF'
[NetDev]
Name=macvlan0
Kind=macvlan
[MACVLAN]
Mode=bridge
EOF
```

```bash
sudo tee /etc/systemd/network/10-macvlan0.network >/dev/null <<'EOF'
[Match]
Name=macvlan0

[Network]
Address=10.2.2.203/24
EOF
```

```bash
sudo tee /etc/systemd/network/11-enp3s0.network >/dev/null <<'EOF'
[Match]
Name=enp3s0

[Network]
LinkLocalAddressing=no
[MACVLAN]
MACVLAN=macvlan0
EOF
```

```bash
sudo tee /etc/systemd/network/11-enp3s0.network >/dev/null <<'EOF'
[Match]
Name=enp3s0

[Network]
LinkLocalAddressing=no
[MACVLAN]
MACVLAN=macvlan0
EOF
```

```bash
sudo systemctl restart systemd-networkd
```

```bash
ip addr show macvlan0
ping -I macvlan0 10.2.2.200
nslookup microsoft.com 10.2.2.200
```
