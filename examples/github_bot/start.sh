#!/bin/bash

# Configuration
BOT_IMAGE="primitivebot:latest"
BOT_NAME="gemini-github-bot"
ENV_FILE=".env"
HOME_DIR="$(pwd)/home"
PROJECTS_DIR="$(pwd)/projects"

# Ensure directories exist
mkdir -p "$HOME_DIR"
mkdir -p "$PROJECTS_DIR"

# Run the bot
docker run --rm -d \
  --name "$BOT_NAME" \
  --env-file "$ENV_FILE" \
  -v "$HOME_DIR":/root \
  -v "$PROJECTS_DIR":/workspace \
  "$BOT_IMAGE"

echo "Bot '$BOT_NAME' started with HOME mapped to $HOME_DIR and WORKSPACE mapped to $PROJECTS_DIR."
