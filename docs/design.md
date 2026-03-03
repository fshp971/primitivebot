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

### 1. Telegram Interface
- **Bot Engine**: Uses `pyTelegramBotAPI` for long-polling.
- **Command Handlers**: Manages project selection, creation, and status monitoring.
- **Message Receiver**: Any non-command text is treated as a task for the current project.

### 2. State Management
- `project_queues`: A dictionary mapping project paths to lists of tasks.
- `active_workers`: A dictionary mapping project paths to `threading.Thread` instances.
- `running_tasks`: A dictionary mapping task IDs to their `subprocess.Popen` objects.
- `user_project_state`: Tracks the current working directory for each chat.

### 3. Worker Threads (`project_worker`)
- Each project receives a single dedicated worker thread.
- The worker waits for tasks using a `threading.Condition` variable.
- When a task is available, it is popped and executed via `process_task`.
- If no tasks are received for a specified period (e.g., 5 minutes), the thread terminates to save resources.

### 4. Task Execution (`process_task`)
- **Context Injection**: Reads `AGENT.md` (if it exists) and prepends its content to the user's prompt.
- **Subprocess Management**: Runs `gemini --yolo -m <model> --prompt -` using `subprocess.Popen`.
- **Safety**: Uses `os.setsid()` and `os.killpg()` for task termination (stopping the entire process group).
- **Timeouts**: Implements `timeout` for `communicate()` to prevent hung tasks.

### 5. Initialization (`initialize_bot`)
- Runs once at startup.
- Executes `gemini` with `INIT.md` to set up the global environment (e.g., git config).

## Reproducibility Checklist for AI Tools
- [ ] Implement a per-directory task queue.
- [ ] Use threading for parallel project processing.
- [ ] Use subprocess with input redirection for CLI interaction.
- [ ] Implement SIGTERM-based task cancellation.
- [ ] Support prompt augmentation with file-based rules (`AGENT.md`).
