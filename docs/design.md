# PrimitiveBot Design Document

PrimitiveBot is designed for asynchronous, concurrent execution of AI tasks within a workspace containing multiple project directories using `asyncio`.

## Architecture Diagram (Simplified)
```text
[Telegram] <-> [Async Telegram Interface (bot.py)]
                    |
              [Task Dispatcher]
                    |
      ------------------------------
      |              |             |
 [Queue Project A] [Queue Project B] [Queue Project C]
      |              |             |
 [Worker Task A]   [Worker Task B]   [Worker Task C]
      |              |             |
 [gemini-cli]     [gemini-cli]     [gemini-cli]
```

## Core Components

### 1. TelegramBot Class
The `TelegramBot` class encapsulates the Telegram interface and task management logic using `asyncio`. It is initialized with `TelegramBotParams` and an `AICLITool` instance.
- **Bot Engine**: Uses `telebot.async_telebot.AsyncTeleBot` for non-blocking communication.
- **Command Handlers**: Asynchronous handlers for project selection, creation, and status monitoring.
- **Message Receiver**: Any non-command text is treated as a task for the current project.
- **State Management**:
  - `project_queues`: A dictionary mapping project paths to `asyncio.Queue` instances.
  - `active_workers`: A dictionary mapping project paths to `asyncio.Task` instances.
  - `running_tasks`: A dictionary mapping task IDs to their status and start time.
  - `user_project_state`: Tracks the current working directory for each chat.

### 2. AICLITool Class
The `AICLITool` class is an "ai-cli-tool-agnostic" interface for calling AI command-line tools asynchronously. It is initialized with `AICLIToolParams`.
- **Method `async .call(prompt, cwd)`**: Feeds the prompt into the CLI tool, processes the output, and returns results without blocking the event loop.
- **Subprocess Management**: Handles `asyncio.create_subprocess_exec` calls, timeouts, and error reporting.
- **Abstraction**: Encapsulates the specific command and arguments (e.g., `gemini --yolo -m <model> --prompt -`), allowing the `TelegramBot` to remain agnostic of the underlying AI tool.

### 3. Worker Tasks (`project_worker`)
Managed by the `TelegramBot` class, each project receives a single dedicated worker task.
- The worker waits for tasks using `await queue.get()`.
- When a task is available, it is processed via `process_task` by calling `await AICLITool.call()`.
- If no tasks are received for a specified period (e.g., 5 minutes), the task terminates to save resources.

### 5. Initialization (`initialize_bot`)
- Runs once at startup.
- Executes `gemini` with `INIT.md` to set up the global environment (e.g., git config).

## Reproducibility Checklist for AI Tools
- [ ] Implement a per-directory task queue using `asyncio.Queue`.
- [ ] Use `asyncio` for parallel project processing.
- [ ] Use `asyncio.create_subprocess_exec` with input redirection for CLI interaction.
- [ ] Implement task cancellation.
- [ ] Support prompt augmentation with file-based rules (`AGENT.md`).
