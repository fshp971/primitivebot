# Agentic Paper Writing Loop Design

This document describes the design and implementation plan for the autonomous paper writing functionality within `primitivebot`.

## Overview
The Paper Writing Loop is an agentic workflow that automates the iterative process of drafting and reviewing academic papers. It utilizes two specialized AI roles—a **Writer** and a **Reviewer**—to refine a paper over multiple rounds (up to $N$ iterations).

## Architecture & Workflow

### 1. Task Organization
All paper writing tasks are stored in a dedicated workspace subdirectory:
- **Root Folder**: `/workspace/paper_tasks/`
- **Project Folder**: `/workspace/paper_tasks/<task_id>/`

Each task is isolated in its own sub-folder to ensure clean execution and easy cache management (e.g., `rm -rf /workspace/paper_tasks/<task_id>`).

### 2. Input Requirements
The system expects a `.zip` file containing:
- `writing_goal.md`: Title, core idea, high-level organization, and conference template requirements.
- `reviewing_goal.md`: Target conference, reviewing criteria, and scoring guidelines.
- **Supplemental Materials**: LaTeX templates (`.cls`, `.tex`), preliminary results (`.csv`, `.png`), and any relevant experimental code.

### 3. The Iterative Loop (N Rounds)
For each round $i$ from 1 to $N$:

#### A. Writer Bot Phase
- **Inputs**:
    - Original `writing_goal.md`.
    - Previous round's PDF: `round_{i-1}.pdf` (if $i > 1$).
    - Previous round's Review: `review_{i-1}.md` (if $i > 1$).
- **Objective**: Generate a complete LaTeX source set and a compiled PDF.
- **Commands**:
    - The writer uses `pdflatex` (and `bibtex` if necessary) to compile the source.
- **Outputs**:
    - LaTeX source files (`.tex`, `.bib`, figures).
    - Compiled PDF: `round_{i}.pdf`.

#### B. Reviewer Bot Phase
- **Inputs**:
    - Original `reviewing_goal.md`.
    - Current round's PDF: `round_{i}.pdf`.
- **Objective**: Critically evaluate the paper based on the conference-specific criteria.
- **Outputs**:
    - Review report: `review_{i}.md`.

### 4. Finalization & Delivery
After $N$ rounds or early termination:
1. All files (original inputs + generated source/PDFs/reviews for all rounds) are collected.
2. The collection is compressed into a single `.zip` file.
3. The final `.zip` is sent to the user via the Telegram interface.

## Implementation Details for AI Tools

### Directory Structure
```text
/workspace/paper_tasks/
└── <task_name>/
    ├── input/               # Extracted original materials
    ├── round_1/
    │   ├── source/          # .tex, .bib, images
    │   ├── paper.pdf        # Compiled PDF
    │   └── review.md        # Reviewer's feedback
    ├── ...
    └── round_N/
```

### Automation Logic
1. **Unzip**: Extract the user's uploaded zip into the project folder.
2. **Loop Controller**: A Python script (or `gemini-cli` agent) manages the state and triggers the bots.
3. **Environment**: The execution environment must have `texlive-full` (or a similar LaTeX distribution) installed to support `pdflatex`.
4. **Tooling**: Use `gemini-cli` for both bots, passing the appropriate context from previous rounds.

## User Guide

### Starting a Paper Task
1. Upload a `.zip` file containing your goals and templates to the Telegram bot.
2. Send a command like `/write_paper <rounds_n>`.
3. The bot will acknowledge and start the iterative process.

### Monitoring & Control
- Use `/status` to see the current round and progress.
- Use `/stop` to terminate the loop early.

### Cleanup
- To clean the cache for a specific project: `/clean <task_id>` (executes `rm -rf`).
- To clean all paper tasks: `/clean_all_papers` (executes `rm -rf /workspace/paper_tasks/*`).

## Reproducibility Checklist
- [ ] Setup `/workspace/paper_tasks` directory.
- [ ] Implement zip extraction and final packaging logic.
- [ ] Configure `gemini-cli` prompts for "Writer" (focus on LaTeX/Academic style) and "Reviewer" (focus on critical analysis).
- [ ] Ensure `pdflatex` availability in the execution environment.
- [ ] Implement the N-round state machine.
