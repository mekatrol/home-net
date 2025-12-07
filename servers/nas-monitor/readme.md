# UPS Montioring

## Monitor set up

### Copy files to remote server 
> assumes is being executed from repo 'home-net' root directory  

```bash
ssh pi@monitor.lan "mkdir -p /home/pi/nas"
scp -r ./servers/nas-monitor/nas* pi@monitor.lan:/home/pi/nas/ 
scp -r ./servers/nas-monitor/ups* pi@monitor.lan:/home/pi/nas/ 
```

### Run on remote server
```bash
sudo mv ~/nas/nas-monitor.service /etc/systemd/system/nas-monitor.service
```

### Edit config
> make any needed changes
```bash
nano ~/nas/nas-monitor.conf
```

### Generate SSH keys
> change user 'admin' to your user  
> change password 'PasswordGoesHere' to your password  
```bash
ssh-keygen -t ed25519
ssh-copy-id admin@nas.lan
```

### Create .venv
```bash
sudo apt update
sudo apt install python3.13-venv -y
cd ~/nas
python3 -m venv .venv
cd ~/
```

### Enable and start service
```bash
sudo systemctl daemon-reload
sudo systemctl enable nas-monitor.service
sudo systemctl start nas-monitor.service
```

### Check logs:
```bash
journalctl -u nas-monitor.service -f
tail -f /var/log/nas-monitor.log
```

## UPS intrface set up

### Check for USB

```bash
lsusb
```

> You should see something like  
`Bus 001 Device 004: ID 0001:0000 Fry's Electronics MEC0003`

### Install python USB
```bash
sudo apt install python3-usb
```

### Run script
```bash
sudo python3 ups_monitor.py
```
