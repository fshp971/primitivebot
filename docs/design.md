# PrimitiveBot Design Document

PrimitiveBot is designed for asynchronous, concurrent execution of AI tasks within a workspace containing multiple project directories.

## Architecture Diagram (Simplified)
```text
[Telegram] <-> [Telegram Interface (bot.py)]
                    |
              [Task Dispatcher]
                    |
      ------------------------------
      |              |             |
 [Queue Project A] [Queue Project B] [Queue Project C]
      |              |             |
[Worker Thread A] [Worker Thread B] [Worker Thread C]
      |              |             |
 [gemini-cli]     [gemini-cli]     [gemini-cli]
```

## Core Components

### 1. TelegramBot Class
The `TelegramBot` class encapsulates the Telegram interface and task management logic. It is initialized with `TelegramBotParams` and an `AICLITool` instance.
- **Bot Engine**: Uses `pyTelegramBotAPI` for long-polling.
- **Command Handlers**: Manages project selection, creation, and status monitoring.
- **Message Receiver**: Any non-command text is treated as a task for the current project.
- **State Management**:
  - `project_queues`: A dictionary mapping project paths to lists of tasks.
  - `active_workers`: A dictionary mapping project paths to `threading.Thread` instances.
  - `running_tasks`: A dictionary mapping task IDs to their status and start time.
  - `user_project_state`: Tracks the current working directory for each chat.

### 2. AICLITool Class
The `AICLITool` class is an "ai-cli-tool-agnostic" interface for calling AI command-line tools. It is initialized with `AICLIToolParams`.
- **Method `.call(prompt, cwd)`**: Feeds the prompt into the CLI tool, processes the output, and returns results.
- **Subprocess Management**: Handles `subprocess.Popen` calls, timeouts, and error reporting.
- **Abstraction**: Encapsulates the specific command and arguments (e.g., `gemini --yolo -m <model> --prompt -`), allowing the `TelegramBot` to remain agnostic of the underlying AI tool.

### 3. Worker Threads (`project_worker`)
Managed by the `TelegramBot` class, each project receives a single dedicated worker thread.
- The worker waits for tasks using a `threading.Condition` variable.
- When a task is available, it is popped and executed via `process_task` by calling `AICLITool.call()`.
- If no tasks are received for a specified period (e.g., 5 minutes), the thread terminates to save resources.

### 5. Initialization (`initialize_bot`)
- Runs once at startup.
- Executes `gemini` with `INIT.md` to set up the global environment (e.g., git config).

## Reproducibility Checklist for AI Tools
- [ ] Implement a per-directory task queue.
- [ ] Use threading for parallel project processing.
- [ ] Use subprocess with input redirection for CLI interaction.
- [ ] Implement SIGTERM-based task cancellation.
- [ ] Support prompt augmentation with file-based rules (`AGENT.md`).
