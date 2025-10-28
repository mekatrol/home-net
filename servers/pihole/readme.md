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

## VLAN

```bash
# The network interface card used for the network
NETWORK_PARENT="enp3s0"

# Static IP address for the vlan on host
HOST_VLAN_IP_ADDR="10.2.2.203"

# Name of host vlan
HOST_VLAN_NAME="macvlan0"

# ensure macvlan shim exists and is configured
if ! ip link show "$HOST_VLAN_NAME" >/dev/null 2>&1; then
  sudo ip link add "$HOST_VLAN_NAME" link "$NETWORK_PARENT" type macvlan mode bridge
fi

# ensure correct IP on the shim
if ! ip -o -4 addr show dev "$HOST_VLAN_NAME" | grep -q "\b$HOST_VLAN_IP_ADDR/24\b"; then
  sudo ip addr flush dev "$HOST_VLAN_NAME"
  sudo ip addr add "$HOST_VLAN_IP_ADDR/24" dev "$HOST_VLAN_NAME"
fi

# ensure it is up
sudo ip link set "$HOST_VLAN_NAME" up
ip link show macvlan0
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

# Make plain host→container traffic pick macvlan0
[Route]
Destination=10.2.2.200/32
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
```

```bash
ping -I macvlan0 10.2.2.200
```
```bash
nslookup microsoft.com 10.2.2.200
```
