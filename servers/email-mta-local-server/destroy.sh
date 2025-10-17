#!/bin/bash

# Name of the container
CONTAINER_NAME="mail-server"

# Name of the image
IMAGE_NAME="mail-server"

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
if docker images -q "$IMAGE_NAME" | grep -q "\w"; then
    echo "Removing image '$IMAGE_NAME'..."
    docker rmi "$IMAGE_NAME"
else
    echo "Image '$IMAGE_NAME' does not exist."
fi
