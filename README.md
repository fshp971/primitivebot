# Primitive Bot

this is simple app for primitives to operate gemini-cli through telegram. It implements a Telegram Bot that serves as an interface for `gemini-cli`, allowing users to queue and execute tasks in specific project directories. It features a robust concurrency model where tasks for different projects run in parallel, while tasks within the same project are executed sequentially to ensure safety.

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

## Quick Start with Bot Space

A "Bot Space" is a directory structure that organizes your bot's configuration, persistent home directory, and projects.

### 1. Prerequisites
*   **Docker** installed on your host machine.
*   A **Telegram Bot Token** (obtained from @BotFather).

### 2. Build the Docker Image
```bash
docker build -t primitivebot:latest .
```

### 3. Recommended Structure

```text
my-bot-space/
├── .env                # Telegram token and other secrets
├── start_bot.sh        # Script to launch the bot
├── home/               # Persisted as /root inside the container
│   ├── AGENT.md        # (Optional) Custom instructions for the agent
│   └── INIT.md         # (Optional) Initialization script for the bot
└── projects/           # Persisted as /workspace inside the container
    ├── my-app/
    └── another-repo/
```

### 4. Configuring your Bot

Create a `.env` file on your host machine to store your secrets.

```ini
# .env
TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
# Optional: defaults to /workspace inside the container
WORKSPACE_DIR=/workspace 
```
You can control your bot's behavior by placing two special files in the `home/` directory:

-   **`AGENT.md`**: These instructions are prepended to *every* task sent to the bot. Use it to define coding styles, security rules (like "never commit secrets"), or specific tool usage preferences.
-   **`INIT.md`**: This file is executed *once* when the bot starts up. Use it to configure global settings like `git config`, install common tools, or verify environment variables.

### 5. Using Examples

We provide a pre-configured example in the `examples/` directory:

-   [**`github_bot`**](./examples/github_bot): Optimized for working with GitHub, including PAT management and git configuration.

To use an example:
1. Copy the example's `home/` and `start.sh` to your bot space.
2. Create your `.env` file with `TELEGRAM_BOT_TOKEN`.
3. **(Optional) To use Gemini with a Google account login:**
   - Create a `.gemini` folder inside your `home/` directory.
   - Copy `oauth_creds.json`, `google_accounts.json` and `settings.json` from your local `~/.gemini/` folder to `home/.gemini/`.
4. Run `bash start.sh`.

### 6. Usage

1.  **Start the Bot:** Send `/start` or `/projects` to list available project folders in your mounted `projects/` directory.
2.  **Select a Project:** Click on a project name to switch your context.
3.  **Execute Tasks:** Send any text message (e.g., "Refactor the login function").
    -   The task will be queued for the *currently selected* project.
    -   If the project is busy, it waits its turn.
    -   If the project is idle, it starts immediately, potentially running in parallel with other projects.
4.  **Create Projects:** Use `/create <project_name>` to create a new folder in the workspace.
5.  **Check Status:** Use `/status` to see a list of currently running tasks and the number of tasks in each project's queue.

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
    npm install -g @google/gemini-cli
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
