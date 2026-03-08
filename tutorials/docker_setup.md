# Tutorial: How to Setup a Docker Container to Run the Bot

This tutorial will guide you through the process of setting up and running the `primitivebot` using Docker. This ensures a consistent environment for the bot and its dependencies.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) installed on your machine.
- A Telegram Bot Token (obtained from [@BotFather](https://t.me/BotFather)).
- A GitHub Personal Access Token (PAT) for repository access (if needed).

## Step 1: Prepare Your Project Directory

Ensure you have the `primitivebot` source code on your host machine.

```bash
git clone <repository_url> primitivebot
cd primitivebot
```

## Step 2: Create a Workspace Directory

Create a directory on your host machine to store your project data and workspace files. This directory will be mounted into the Docker container.

```bash
mkdir ./workspace
```

## Step 3: Configure Environment Variables

The bot requires certain environment variables to function correctly. You can create a `.env` file in the root of the project:

```bash
# .env file
TELEGRAM_BOT_TOKEN=your_telegram_bot_token
GITHUB_PAT=your_github_personal_access_token
WORKSPACE_DIR=/workspace
```

## Step 4: Build the Docker Image

Use the provided `Dockerfile` to build the Docker image.

```bash
docker build -t primitivebot .
```

## Step 5: Run the Docker Container

Run the container, mounting the host workspace directory and passing the environment variables.

```bash
docker run -d
  --name primitivebot
  --env-file .env
  -v $(pwd)/workspace:/workspace
  primitivebot
```

### Explanation of flags:
- `-d`: Run the container in detached mode (background).
- `--name primitivebot`: Assign a name to the container.
- `--env-file .env`: Load environment variables from the `.env` file.
- `-v $(pwd)/workspace:/workspace`: Mount the local `workspace` directory to `/workspace` inside the container. This ensures your project files persist even if the container is stopped or removed.

## Step 6: Verify the Bot is Running

Check the container logs to ensure the bot has started successfully:

```bash
docker logs -f primitivebot
```

You should see output indicating that the bot daemon has started.

## Customizing Configuration

If you want to use a custom configuration file (e.g., to set a whitelist or model version), you can modify `src/config.yaml` before building the image, or mount a custom config file into the container.

To use a custom config file at runtime:
```bash
docker run -d
  --name primitivebot
  --env-file .env
  -v $(pwd)/workspace:/workspace
  -v $(pwd)/my_config.yaml:/app/src/config.yaml
  primitivebot
```
