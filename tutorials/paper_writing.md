# Tutorial: How to Use the Paper Writing Feature

This tutorial will show you how to use the autonomous paper writing functionality in `primitivebot`.

## Overview

The `primitivebot` includes a specialized agentic workflow that automates the iterative process of drafting and reviewing academic papers. It uses two specialized AI roles—a **Writer** and a **Reviewer**—to refine a paper over multiple rounds.

## Step 1: Prepare Your Project Files

The paper writing loop expects a single `.zip` file containing the following:

### Mandatory Files:
- `writing_goal.md`: Contains the title, core idea, high-level organization, and conference template requirements.
- `reviewing_goal.md`: Contains the target conference, reviewing criteria, and scoring guidelines.

### Supplemental Materials (Recommended):
- LaTeX templates (`.cls`, `.tex` files).
- Preliminary results (`.csv`, `.png`, etc.).
- Relevant experimental code.

Ensure all files are in the root of the `.zip` archive.

## Step 2: Upload Your Project to the Bot

1. Open your Telegram bot.
2. Upload the `.zip` file you prepared in Step 1.
3. The bot will respond: "✅ Zip file received. Use `/write_paper <rounds_n>` to start the loop."

## Step 3: Start the Writing Loop

Run the writing loop command followed by the number of rounds (iterations) you want to perform (default is 3):

```bash
/write_paper 5
```

The bot will create a project folder and start the process:
- **Writer Bot Phase**: Generates a complete LaTeX source set and compiles it into a PDF (`round_i.pdf`).
- **Reviewer Bot Phase**: Critically evaluates the paper based on the criteria in `reviewing_goal.md` and generates a report (`review_i.md`).

## Step 4: Monitor Progress

Use the following command to check the current round and progress:

```bash
/status
```

The bot will send periodic updates about the completion of each round.

## Step 5: Stop or Cancel

If you want to terminate the loop early, use:

```bash
/stop <task_id>
```

Replace `<task_id>` with the ID provided by the `/status` command.

## Step 6: Download the Final Results

Once all rounds are completed, the bot will automatically:
1. Collect all original materials, LaTeX source files, compiled PDFs, and review reports for all rounds.
2. Compress them into a single `.zip` file.
3. Send the final `.zip` file to you via Telegram.

## Step 7: Clean Up

To keep your workspace clean, you can use the following commands:
- `/clean <task_id>`: Deletes the project folder for a specific task.
- `/clean_all_papers`: Removes all paper writing task folders from the workspace.
