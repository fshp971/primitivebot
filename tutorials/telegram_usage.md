# Tutorial: How to Access and Use the Bot Through Telegram

This tutorial will show you how to set up and interact with the `primitivebot` using Telegram.

## Prerequisites

- A Telegram account.
- `primitivebot` instance running (locally or in Docker).
- Telegram Bot Token from [@BotFather](https://t.me/BotFather).

## Step 1: Initialize Your Bot

1. Open Telegram and search for [@BotFather](https://t.me/BotFather).
2. Create a new bot by sending `/newbot`.
3. Follow the instructions to give your bot a name and a username.
4. Note down the **HTTP API Token** provided.

## Step 2: Configure the Bot

Ensure the `TELEGRAM_BOT_TOKEN` environment variable is set in your bot's environment:

```bash
export TELEGRAM_BOT_TOKEN=your_token_here
```

To restrict who can use your bot, modify the `whitelist` in `src/config.yaml`:

```yaml
# src/config.yaml
whitelist:
  - 12345678 # Your Telegram User ID (integer)
```

## Step 3: Start Interacting with the Bot

Open Telegram and search for your bot's username. Click "Start" or send `/start`.

### Basic Commands

- `/start`: Initialize the bot and show basic information.
- `/projects`: List the directories available in the workspace.
- `/create <project_name>`: Create a new project directory in the workspace.
- `/status`: Show the status of currently running and queued tasks.
- `/stop <task_id>`: Cancel a running or queued task. Use `/status` to find the `task_id`.

## Step 4: Manage Your Workspace

The bot operates within a "Workspace Directory". You can switch between different sub-folders (projects) to organize your work.

1. Send `/projects` to see existing folders.
2. Use the inline keyboard to select a project.
3. Subsequent commands will execute within that selected directory.

## Step 5: Execute AI Tasks

You can send any text message (that's not a command) to the bot. The bot will treat it as a task and process it using the underlying AI agent.

Example:
- User: "List the files in this directory."
- Bot: (Executes the task and replies with the file list).

If an `AGENT.md` file exists in the workspace root, its contents will be prepended to your prompt as "Agent Rules" to provide context and instructions to the AI.

## Step 6: Using Files

- **Upload Zip**: You can upload a `.zip` file for specific tasks, such as the paper writing loop.
- **Download Zip**: Certain tasks will result in the bot sending a `.zip` file back to you with the results.
