# OpenSearch configuration

## See

[OpenSearch - Docker](https://docs.opensearch.org/latest/install-and-configure/install-opensearch/docker/)

## Download images

```bash
docker pull opensearchproject/opensearch:3
docker pull opensearchproject/opensearch-dashboards:3
```

## Setup containers

### Setup search

```bash
docker run -d \
  --name opensearch \
  -p 9200:9200 \
  -p 9600:9600 \
  -e "discovery.type=single-node" \
  -e "OPENSEARCH_INITIAL_ADMIN_PASSWORD=NotRealPassword123" \
  opensearchproject/opensearch:latest
```

### Test search

```bash
curl https://localhost:9200 -ku admin:NotRealPassword123
```