# Unify server

Taken from [Unifi Controller Self Hosted in Docker - MongoDB](https://www.youtube.com/watch?v=9x1mJC7sCv4)

## Change credentials
Inside `init-mongo.js` and `docker-compose.yaml` change credentials to preferred value (don't leave as default as the credentials are on public internet for everyone to see).

## Create volumes

```bash
mkdir -p /data/unify/config /data/unify/data
cp ./init-mongo.js /data/unify
```

## Create network
```bash
docker network create proxy
```

## Start containers
```bash
docker compose up -d
```

## Check logs
```bash
docker container logs unifi-db
docker container logs unifi-network-application
```

## Upload backup
Navigate to home page https://unify.lan:8443 and select upload backup at bottom of page.