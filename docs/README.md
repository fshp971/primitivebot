# PrimitiveBot Documentation

PrimitiveBot is a Telegram Bot that acts as an interface for `gemini-cli`. It allows users to manage projects and execute AI tasks concurrently within a specified workspace.

## Table of Contents
1. [Overview](#overview)
2. [Design & Architecture](#design--architecture)
3. [Concurrency Model](#concurrency-model)
4. [Usage Guide](#usage-guide)
5. [Reproducing PrimitiveBot](#reproducing-primitivebot)
6. [Configuration](#configuration)

---

## Overview
PrimitiveBot enables developers to interact with their codebases through a Telegram interface. By bridging the gap between a chat platform and the `gemini-cli`, it allows for remote code editing, refactoring, and general AI assistance on any project hosted within its workspace.

## Design & Architecture
The system is built using Python and is organized into a modular structure under `src/primitivebot`. It uses the `pyTelegramBotAPI` for Telegram communication and an agnostic AI CLI tool interface for executing tasks.

### Key Components:
- **TelegramBot**: A class that encapsulates the Telegram interface, task dispatching, and worker thread management. It is initialized with configuration parameters and an AI tool calling class.
- **AICLITool**: A model-agnostic class that handles calling the underlying AI CLI tool (e.g., `gemini-cli`). It abstracts the command-line arguments and execution logic.
- **Task Dispatcher**: Receives messages and routes them to the appropriate project queue within the `TelegramBot` class.
- **Worker Threads**: Each project has its own dedicated worker thread managed by the `TelegramBot` to ensure sequential execution within a project but parallel execution across different projects.
- **Gemini CLI Integration**: Tasks are executed by calling the `gemini` command through the `AICLITool` interface.
- **Agentic Paper Writing Loop**: A specialized workflow for iterative paper drafting and peer review. See [Paper Writing Loop Design](paper_writing_loop.md) for details.

## Concurrency Model
PrimitiveBot implements a **Per-Project Concurrency** model:

1. **Isolation**: Every project directory in the `/workspace` is treated as an independent execution unit.
2. **Worker threads**: When a task is received for a project, a dedicated worker thread is spawned (if not already running) for that project.
3. **Queues**: Each project has its own task queue. Tasks for the same project are executed one-by-one to prevent race conditions (e.g., two AI tasks trying to edit the same file simultaneously).
4. **Parallelism**: Multiple worker threads can run tasks for different projects at the same time.

## Usage Guide

### Commands
- `/start` or `/projects`: Displays a list of available projects in the workspace.
- `/cd`: Switch the current working directory.
- `/create <name>`: Create a new project folder in the workspace.
- `/status`: Show the current running tasks and the length of the queues.
- `/stop <task_id>`: Terminate a running task or remove it from the queue.

### Task Execution
To run a task, simply select a project and send a message. The bot will:
1. Append any rules from `AGENT.md` (if present in the project or root).
2. Queue the task.
3. Execute it using `gemini-cli` when its turn comes.
4. Return the output and any errors to the user.

## Reproducing PrimitiveBot
To reproduce the functionality of this repository, an AI coding tool should follow these steps:

1. **Environment Setup**:
   - Provide a Python environment with `pyTelegramBotAPI`, `python-dotenv`, and `PyYAML`.
   - Ensure `gemini-cli` is installed and accessible via the `gemini` command.
   - Set up a workspace directory for project folders.

2. **Core Logic Implementation**:
   - Implement a mechanism to track the "current project" for each user.
   - Create a mapping of project paths to `threading.Thread` and task queues.
   - Ensure that `subprocess.Popen` is used with `os.setsid` to allow for process group termination.
   - Implement `AGENT.md` and `INIT.md` handling for context and initialization.

3. **Safety & Security**:
   - Restrict file operations to the workspace directory.
   - Use environment variables for sensitive tokens like `TELEGRAM_BOT_TOKEN`.

## Configuration
The bot can be configured via `src/config.yaml` or environment variables:
- `TELEGRAM_BOT_TOKEN`: Your bot token from @BotFather.
- `WORKSPACE_DIR`: Root directory for projects.
- `BOT_CONFIG`: Path to the YAML configuration file.

Example `config.yaml`:
```yaml
task_timeout_second: 600
status_desc_length: 30
model_version: "auto"
```
