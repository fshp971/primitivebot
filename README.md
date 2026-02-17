# Telegram-Gemini Task Queue Bot

This project implements a Telegram Bot that serves as an interface for `gemini-cli`, allowing users to queue and execute tasks in specific project directories. It features a robust concurrency model where tasks for different projects run in parallel, while tasks within the same project are executed sequentially to ensure safety.

## Key Features

1.  **Per-Project Concurrency:** 
    -   Each project folder has its own independent task queue and worker thread.
    -   Tasks submitted to "Project A" and "Project B" run simultaneously without blocking each other.
2.  **Sequential Execution:** 
    -   Tasks within a single project (e.g., "Project A") are executed one by one in the order they were received.
    -   This prevents race conditions and conflicts when modifying files within the same project.
3.  **Context Switching:** 
    -   Users can seamlessly switch between projects using `/cd` or the menu.
    -   Switching context does not interrupt running tasks in other projects.
4.  **Persistent Architecture:**
    -   Runs as a long-polling daemon inside a Docker container, avoiding serverless timeouts.

## Architecture

*   **`bot.py`**: The main application logic. It manages a dynamic set of `queue.Queue` objects and worker threads—one pair for each active project.
*   **`Dockerfile`**: Defines the container environment, including Python 3.10, Node.js (for `gemini-cli`), and system dependencies.
*   **`requirements.txt`**: Python dependencies (`pyTelegramBotAPI`, `python-dotenv`).

## Project Organization

```text
/
├── bot.py                  # Main application logic
├── Dockerfile              # Container definition
├── requirements.txt        # Python dependencies
├── README.md               # Documentation
└── tests/                  # Unit tests
    └── test_bot.py         # Tests for bot.py
```

## Deployment Guide

### Prerequisites
*   **Docker** installed on your host machine.
*   A **Telegram Bot Token** (obtained from @BotFather).
*   **SSH Keys** (optional but recommended) on your host machine for git operations inside the container.

### 1. Configuration (`.env`)

Create a `.env` file on your host machine to store your secrets.

```ini
# .env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
# Optional: defaults to /workspace inside the container
WORKSPACE_DIR=/workspace 
```

### 2. Directory Structure

We recommend the following structure on your host machine:

```text
/home/user/my-bot-deployment/
├── .env                # Your configuration file
├── projects/           # Folder containing all your project subfolders
│   ├── project-a/
│   └── project-b/
└── ...
```

### 3. Docker Run Command

Use the following command to start the bot. This mounts your configuration, project files, and SSH keys into the container.

```bash
docker run -d \
  --name gemini-bot \
  --restart unless-stopped \
  \
  # 1. Mount the .env file
  --env-file /home/user/my-bot-deployment/.env \
  \
  # 2. Mount your Projects folder to /workspace
  #    The bot will look for folders INSIDE /workspace
  -v /home/user/my-bot-deployment/projects:/workspace \
  \
  # 3. Inject SSH Keys (Read-only recommended)
  #    This maps your host's ~/.ssh to the container root's .ssh
  -v $HOME/.ssh:/root/.ssh:ro \
  \
  your-image-name
```

**Note on SSH Keys:**
Mounting `$HOME/.ssh` allows the `gemini-cli` inside the container to authenticate with GitHub/GitLab using your host's credentials. Ensure your `known_hosts` file is populated to avoid interactive prompts.

### 4. Usage

1.  **Start the Bot:** Send `/start` or `/projects` to list available project folders in your mounted `projects/` directory.
2.  **Select a Project:** Click on a project name to switch your context.
3.  **Execute Tasks:** Send any text message (e.g., "Refactor the login function").
    -   The task will be queued for the *currently selected* project.
    -   If the project is busy, it waits its turn.
    -   If the project is idle, it starts immediately, potentially running in parallel with other projects.
4.  **Create Projects:** Use `/create <project_name>` to create a new folder in the workspace.

## Development

### Running Tests
The project includes a comprehensive test suite in `tests/test_bot.py`.

```bash
# Run tests from the project root
PYTHONPATH=. python3 -m unittest discover tests
```

### Local Setup (Non-Docker)
1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    npm install -g gemini-cli
    ```
2.  Set environment variables:
    ```bash
    export TELEGRAM_BOT_TOKEN="your_token"
    export WORKSPACE_DIR="/path/to/projects"
    ```
3.  Run the bot:
    ```bash
    python bot.py
    ```