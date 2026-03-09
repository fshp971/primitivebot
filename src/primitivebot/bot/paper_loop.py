import os
import asyncio
import logging
import zipfile
import shutil
from typing import Optional, Callable, Awaitable
from primitivebot.ai.cli import AICLITool

logger = logging.getLogger(__name__)

class PaperWritingLoop:
    def __init__(self, ai_tool: AICLITool, workspace_dir: str):
        self.ai_tool = ai_tool
        self.workspace_dir = workspace_dir
        self.tasks_dir = os.path.join(workspace_dir, 'paper_tasks')
        os.makedirs(self.tasks_dir, exist_ok=True)

    async def run(self, task_id: str, zip_path: str, rounds_n: int,
                  status_callback: Callable[[str], Awaitable[None]],
                  status_dict: Optional[dict] = None) -> str:
        """
        Runs the paper writing loop for N rounds.
        Returns the path to the final zip file.
        """
        project_dir = os.path.join(self.tasks_dir, task_id)
        if os.path.exists(project_dir):
            shutil.rmtree(project_dir)
        os.makedirs(project_dir)

        input_dir = os.path.join(project_dir, 'input')
        os.makedirs(input_dir)

        try:
            # 1. Unzip
            await status_callback(f"📦 Extracting input materials for {task_id}...")
            if status_dict is not None:
                status_dict['phase'] = "Extracting"

            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(input_dir)

            # Validate inputs
            writing_goal_path = os.path.join(input_dir, 'writing_goal.md')
            reviewing_goal_path = os.path.join(input_dir, 'reviewing_goal.md')

            if not os.path.exists(writing_goal_path) or not os.path.exists(reviewing_goal_path):
                raise ValueError("Input zip must contain writing_goal.md and reviewing_goal.md")

            with open(writing_goal_path, 'r') as f:
                writing_goal = f.read()
            with open(reviewing_goal_path, 'r') as f:
                reviewing_goal = f.read()

            current_source_dir = input_dir
            last_review = ""
            last_pdf = ""

            for i in range(1, rounds_n + 1):
                if status_dict is not None:
                    status_dict['round'] = i
                    status_dict['total_rounds'] = rounds_n

                round_dir = os.path.join(project_dir, f'round_{i}')
                source_dir = os.path.join(round_dir, 'source')
                os.makedirs(source_dir)

                # Copy previous source/input to current source
                for item in os.listdir(current_source_dir):
                    s = os.path.join(current_source_dir, item)
                    d = os.path.join(source_dir, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d, dirs_exist_ok=True)
                    else:
                        shutil.copy2(s, d)

                # A. Writer Bot Phase
                msg = f"📝 Round {i}/{rounds_n}: Writer Bot is drafting..."
                await status_callback(msg)
                if status_dict is not None:
                    status_dict['phase'] = "Writing"

                writer_prompt = f"""
You are a professional academic writer. Your goal is to write/refine a high-quality LaTeX paper.

# Writing Goal
{writing_goal}

# Previous Feedback
{last_review if last_review else "This is the first round. Start drafting based on the goal."}

# Instructions
1. Review the current source files in the directory.
2. Update the LaTeX source files (.tex, .bib, etc.) to address the goals and feedback.
3. Ensure the paper is complete and follows the required format.
4. After updating the files, you MUST compile the PDF using `pdflatex` and `bibtex`.
5. Name the final compiled PDF as `paper.pdf` in the current directory.
6. Provide a brief summary of your changes.

Use your tools to modify files and run shell commands.
"""
                stdout, stderr, rc = await self.ai_tool.call(writer_prompt, source_dir)
                if rc != 0:
                    logger.error(f"Writer Bot failed in round {i}: {stderr}")
                    await status_callback(f"⚠️ Writer Bot encountered an error in round {i}. Attempting to continue...")

                paper_pdf = os.path.join(source_dir, 'paper.pdf')
                round_pdf = os.path.join(round_dir, 'paper.pdf')
                if os.path.exists(paper_pdf):
                    shutil.copy2(paper_pdf, round_pdf)
                    last_pdf = round_pdf
                else:
                    await status_callback(f"❌ Round {i}: Writer failed to produce paper.pdf.")
                    # We might want to stop here or try to recover.
                    # For now, let's just log and continue if possible, or raise error.
                    if i == 1:
                         raise RuntimeError(f"Writer failed to produce PDF in the first round.")

                # B. Reviewer Bot Phase
                msg = f"🧐 Round {i}/{rounds_n}: Reviewer Bot is evaluating..."
                await status_callback(msg)
                if status_dict is not None:
                    status_dict['phase'] = "Reviewing"

                reviewer_prompt = f"""
You are an expert peer reviewer for a top-tier academic conference.

# Reviewing Goal & Criteria
{reviewing_goal}

# Paper to Review
Please read the compiled PDF `paper.pdf` and the LaTeX source in the current directory.

# Instructions
1. Critically evaluate the paper based on the criteria.
2. Provide a detailed review report, including strengths, weaknesses, and specific suggestions for improvement.
3. Your output should be a markdown review report. Save it as `review.md` in the current directory.
"""
                stdout, stderr, rc = await self.ai_tool.call(reviewer_prompt, source_dir)
                review_md = os.path.join(source_dir, 'review.md')
                round_review = os.path.join(round_dir, 'review.md')

                if os.path.exists(review_md):
                    shutil.copy2(review_md, round_review)
                    with open(review_md, 'r') as f:
                        last_review = f.read()
                else:
                    last_review = "Reviewer failed to generate review.md."
                    with open(round_review, 'w') as f:
                        f.write(last_review)

                current_source_dir = source_dir

            # 4. Finalization
            await status_callback(f"📦 Finalizing and packaging all rounds...")
            if status_dict is not None:
                status_dict['phase'] = "Finalizing"
            
            return self._create_final_zip(project_dir, task_id)

        except asyncio.CancelledError:
            logger.info(f"Paper task {task_id} was cancelled. Packaging current results...")
            await status_callback(f"🛑 Paper writing task {task_id} cancelled. Packaging current results...")
            zip_path = self._create_final_zip(project_dir, task_id)
            raise # Still re-raise to indicate cancellation but the zip is created

    def _create_final_zip(self, project_dir: str, task_id: str) -> str:
        final_zip_name = f"{task_id}_final.zip"
        final_zip_path = os.path.join(self.tasks_dir, final_zip_name)

        with zipfile.ZipFile(final_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(project_dir):
                for file in files:
                    file_path = os.path.join(root, file)
                    arcname = os.path.relpath(file_path, project_dir)
                    zipf.write(file_path, arcname)
        return final_zip_path
