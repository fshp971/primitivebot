# Telegram-Gemini Task Queue Bot

This project implements a Telegram Bot that serves as an interface for `gemini-cli`, allowing users to queue and execute tasks in a specific directory context. It uses a long-polling mechanism running within a single container to ensure stability and persistence, avoiding the limitations of serverless environments.

## Architecture

The project is built around the following core concepts:

1.  **Single-Container Long Polling:** The bot runs as a persistent process (daemon) inside a Docker container. This avoids timeouts associated with serverless functions and allows for long-running tasks.
2.  **In-Memory Task Queue:** A `queue.Queue` handles incoming tasks sequentially. This ensures that tasks are processed one by one, preventing race conditions on file operations within the same directory.
3.  **Directory-Based Context:** Users can switch their "working directory" using Telegram commands. The bot maintains a session state mapping each user to a specific directory in the mounted volume.
4.  **Context Injection:** If a `.gemini_context.txt` file exists in the current working directory, its content is automatically prepended to the user's prompt as a "System Context". This allows for project-specific instructions (e.g., "Use LaTeX for math", "Write Python code").

### Components

*   **`bot.py`**: The main entry point. It initializes the Telegram bot, handles commands (`/start`, `/cd`), manages the task queue, and runs a worker thread that executes `gemini-cli` as a subprocess.
*   **`Dockerfile`**: Defines the container environment, installing Python 3.10, Node.js (for `gemini-cli`), and necessary dependencies.
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

## Setup and Usage

### Prerequisites
*   Docker
*   A Telegram Bot Token (from @BotFather)

### Local Development
1.  Install dependencies:
    ```bash
    pip install -r requirements.txt
    npm install -g gemini-cli
    ```
2.  Set environment variables:
    ```bash
    export TELEGRAM_BOT_TOKEN="your_token_here"
    export WORKSPACE_DIR="/path/to/your/workspace"
    ```
3.  Run the bot:
    ```bash
    python bot.py
    ```

### Docker Deployment

1.  **Build the image:**
    ```bash
    docker build -t gemini-worker .
    ```

2.  **Run the container:**
    Mount your local workspace directory to `/workspace` inside the container.
    ```bash
    docker run -d \
      --name my-gemini-worker \
      --restart unless-stopped \
      -e TELEGRAM_BOT_TOKEN="your_token_here" \
      -v /path/to/host/projects:/workspace \
      gemini-worker
    ```

### Bot Commands
*   `/start`, `/cd`, `/projects`: List available project directories in the workspace and allow switching context.
*   **Text Message**: Any text message sent to the bot is treated as a task. It is queued and executed by `gemini-cli` in the currently selected directory.

## Testing

The project includes unit tests to verify the logic of the bot without requiring a real Telegram connection or `gemini-cli` installation.

### Organization of Unit Tests
Tests are located in `tests/test_bot.py`. They use `unittest` and `unittest.mock`.

*   **Mocking:** `telebot` is mocked at the module level to prevent network calls during import. `subprocess.run`, `os.listdir`, and file operations are also mocked.
*   **Coverage:**
    *   `test_list_projects`: Verifies directory listing and empty workspace handling.
    *   `test_handle_project_selection`: Verifies session state updates when a user selects a project.
    *   `test_handle_task`: Verifies that tasks are correctly added to the queue with the correct context.
    *   `test_process_task`: Verifies that the worker function constructs the correct `gemini-cli` command, including context injection if `.gemini_context.txt` is present.

### Running Tests
Execute the following command from the project root:
```bash
python3 -m unittest discover tests
```
