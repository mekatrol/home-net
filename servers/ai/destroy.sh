#!/bin/bash
set -euo pipefail

# Name of the container
CONTAINER_NAME="ai"

# Name of the image
IMAGE_NAME="ai"
IMAGE_TAG="latest"
IMAGE_REF="${IMAGE_NAME}:${IMAGE_TAG}"

# Check if the container exists
if docker ps -a --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
    echo "Container '$CONTAINER_NAME' exists."

    # Stop the container if it is running
    if docker ps --format '{{.Names}}' | grep -q "^$CONTAINER_NAME$"; then
        echo "Stopping container '$CONTAINER_NAME'..."
        docker stop "$CONTAINER_NAME"
    fi

    # Remove the container
    echo "Removing container '$CONTAINER_NAME'..."
    docker rm "$CONTAINER_NAME"
else
    echo "Container '$CONTAINER_NAME' does not exist."
fi

# Check if the image exists and remove it
if docker image inspect "$IMAGE_REF" >/dev/null 2>&1; then
    echo "Removing image '$IMAGE_REF'..."
    docker rmi "$IMAGE_REF"
else
    echo "Image '$IMAGE_REF' does not exist."
fi