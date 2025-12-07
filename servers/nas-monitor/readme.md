
### Copy files to remote server
```bash
ssh pi@monitor.lan "mkdir -p /home/pi/nas"
scp -r ./home-net/servers/nas-monitor/nas* pi@monitor.lan:/home/pi/nas/ 
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
