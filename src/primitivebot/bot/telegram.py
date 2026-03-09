import asyncio
import os
import signal
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode
from primitivebot.ai.cli import AICLITool
from primitivebot.bot.paper_loop import PaperWritingLoop

logger = logging.getLogger(__name__)

@dataclass
class TelegramBotParams:
    """Hyperparameters for starting and running the TelegramBot."""
    token: str
    workspace_dir: str = '/workspace'
    task_timeout_second: int = 600
    status_desc_length: int = 30
    whitelist: List[int] = field(default_factory=list)
    # any other IM specific parameters

class TelegramBot:
    """Refactored TelegramBot class using python-telegram-bot asyncio version."""

    def __init__(self, params: TelegramBotParams, ai_tool: AICLITool):
        self.params = params
        self.ai_tool = ai_tool

        # Internal state
        self.application = ApplicationBuilder().token(self.params.token).build()
        self.project_queues: Dict[str, asyncio.Queue] = {}
        self.active_workers: Dict[str, asyncio.Task] = {}
        self.running_tasks: Dict[int, Dict[str, Any]] = {}
        self.tasks_by_id: Dict[int, Dict[str, Any]] = {}
        self.worker_lock = asyncio.Lock()
        self.task_id_counter = 1
        self.user_project_state: Dict[int, str] = {}
        self.paper_loop = PaperWritingLoop(self.ai_tool, self.params.workspace_dir)
        self.last_zip_paths: Dict[int, str] = {}

        # Register handlers
        self._register_handlers()

    def _is_allowed(self, user_id: int) -> bool:
        if not self.params.whitelist:
            return True
        return user_id in self.params.whitelist

    def _register_handlers(self):
        # Whitelist filter
        async def check_whitelist(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
            user = update.effective_user
            if not user or not self._is_allowed(user.id):
                if update.message:
                    logger.warning(f"Unauthorized access attempt by user {user.id} ({user.username if user else 'N/A'})")
                    await update.message.reply_text("🚫 You are not authorized to use this bot.")
                elif update.callback_query:
                    logger.warning(f"Unauthorized callback attempt by user {user.id} ({user.username if user else 'N/A'})")
                    await update.callback_query.answer("🚫 Unauthorized", show_alert=True)
                return False
            return True

        # Use a wrapper for authorized handlers
        def authorized_handler(handler_func):
            async def wrapped(update: Update, context: ContextTypes.DEFAULT_TYPE):
                if await check_whitelist(update, context):
                    return await handler_func(update, context)
            return wrapped

        self.application.add_handler(CommandHandler(["cd", "projects", "start"], authorized_handler(self.list_projects)))
        self.application.add_handler(CallbackQueryHandler(authorized_handler(self.handle_project_selection), pattern="^proj_"))
        self.application.add_handler(CommandHandler("create", authorized_handler(self.create_project)))
        self.application.add_handler(CommandHandler("status", authorized_handler(self.show_status)))
        self.application.add_handler(CommandHandler(["stop", "cancel"], authorized_handler(self.stop_tasks)))
        self.application.add_handler(CommandHandler("clean", authorized_handler(self.clean_task)))
        self.application.add_handler(CommandHandler("clean_all_papers", authorized_handler(self.clean_all_papers)))
        self.application.add_handler(CommandHandler("write_paper", authorized_handler(self.write_paper)))
        self.application.add_handler(MessageHandler(filters.Document.ZIP, authorized_handler(self.handle_document)))
        self.application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), authorized_handler(self.handle_task)))

    async def next_task_id(self) -> int:
        async with self.worker_lock:
            tid = self.task_id_counter
            self.task_id_counter += 1
            return tid

    def get_project_dirs(self) -> List[str]:
        if not os.path.exists(self.params.workspace_dir):
            return []
        try:
            return [d for d in os.listdir(self.params.workspace_dir) if os.path.isdir(os.path.join(self.params.workspace_dir, d))]
        except OSError as e:
            logger.error(f"Error accessing base directory: {e}")
            return []

    async def ensure_worker_running(self, project_path: str):
        async with self.worker_lock:
            if project_path not in self.active_workers or self.active_workers[project_path].done():
                t = asyncio.create_task(self.project_worker(project_path))
                self.active_workers[project_path] = t
                logger.info(f"Started worker for {project_path}")

    # --- Handlers implementation ---

    async def list_projects(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        dirs = self.get_project_dirs()
        if not dirs:
            await update.message.reply_text("Workspace is empty. Please create project folders in the mounted host directory.")
            return

        keyboard = []
        for d in dirs:
            keyboard.append([InlineKeyboardButton(d, callback_data=f"proj_{d}")])
        keyboard.append([InlineKeyboardButton("🏠 Root Directory", callback_data="proj_ROOT")])

        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("📁 Select a project directory:", reply_markup=reply_markup)

    async def handle_project_selection(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        project_name = query.data.replace('proj_', '')
        chat_id = query.message.chat_id

        if project_name == "ROOT":
            self.user_project_state[chat_id] = self.params.workspace_dir
            display_name = f"Root Directory {self.params.workspace_dir}"
        else:
            self.user_project_state[chat_id] = os.path.join(self.params.workspace_dir, project_name)
            display_name = project_name

        await query.answer("Switched successfully")
        await query.edit_message_text(f"✅ Current working directory switched to: {display_name}\nSubsequent tasks will execute in this folder.")

    async def create_project(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                await update.message.reply_text("Usage: /create <project_name>")
                return

            project_name = context.args[0]
            if not all(c.isalnum() or c in ('_', '-') for c in project_name):
                 await update.message.reply_text("Invalid project name. Use alphanumeric characters, underscores, or hyphens.")
                 return

            project_path = os.path.join(self.params.workspace_dir, project_name)
            if os.path.exists(project_path):
                await update.message.reply_text(f"⚠️ Project '{project_name}' already exists.")
                return

            os.makedirs(project_path)
            await update.message.reply_text(f"✅ Project '{project_name}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating project: {e}")
            await update.message.reply_text(f"❌ Failed to create project: {e}")

    async def show_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        async with self.worker_lock:
            active_projects = [p for p, q in self.project_queues.items() if not q.empty()]
            if not self.running_tasks and not active_projects:
                await update.message.reply_text("📭 No tasks running or queued.")
                return

            status_msg = "📊 **System Status**\n\n"
            if self.running_tasks:
                status_msg += "🏃 **Running Tasks:**\n"
                for tid, info in self.running_tasks.items():
                    project_name = os.path.basename(info['task']['cwd']) or "Root"
                    task_text = info['task']['text']
                    task_preview = (task_text[:self.params.status_desc_length] + '...') if len(task_text) > self.params.status_desc_length else task_text
                    elapsed = int(time.time() - info['start_time'])
                    status_msg += f"- `[{tid}]` `{project_name}`: {task_preview} ({elapsed}s)\n"
                status_msg += "\n"

            has_queued = False
            for path, q in self.project_queues.items():
                if not q.empty():
                    if not has_queued:
                        status_msg += "⏳ **Queued Tasks:**\n"
                        has_queued = True
                    project_name = os.path.basename(path) or "Root"
                    status_msg += f"📂 `{project_name}`:\n"
                    status_msg += f"  - (Queue size: {q.qsize()})\n"

            await update.message.reply_text(status_msg, parse_mode=ParseMode.MARKDOWN)

    async def stop_tasks(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                await update.message.reply_text("Usage: /stop {task_id}\nUse /status to see the task_id.")
                return
            task_id = int(context.args[0])
            await self.perform_stop_by_id(task_id, update.effective_chat.id)
        except ValueError:
            await update.message.reply_text("Invalid task ID. Please provide a numeric task_id.")
        except Exception as e:
            logger.error(f"Error in stop_tasks: {e}")
            await update.message.reply_text(f"❌ Error: {e}")

    async def perform_stop_by_id(self, task_id, chat_id):
        async with self.worker_lock:
            task = self.tasks_by_id.get(task_id)
            if not task:
                await self.application.bot.send_message(chat_id, f"❌ Task `{task_id}` does not exist.")
                return

            if task_id in self.running_tasks:
                info = self.running_tasks[task_id]
                info['stopped'] = True
                pass

            if task['status'] == 'queued':
                 task['status'] = 'cancelled'
                 await self.application.bot.send_message(chat_id, f"🛑 Task `{task_id}` marked as cancelled.")
                 return

            status = task.get('status', 'unknown')
            await self.application.bot.send_message(chat_id, f"ℹ️ Task `{task_id}` is not currently queued (Status: {status}).")

    async def clean_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            if not context.args:
                await update.message.reply_text("Usage: /clean <task_id>")
                return

            task_id = context.args[0]
            project_dir = os.path.join(self.paper_loop.tasks_dir, task_id)
            if os.path.exists(project_dir):
                import shutil
                shutil.rmtree(project_dir)
                await update.message.reply_text(f"✅ Cleaned task {task_id}")
            else:
                await update.message.reply_text(f"❌ Task {task_id} not found.")
        except Exception as e:
            logger.error(f"Error in clean_task: {e}")
            await update.message.reply_text(f"❌ Failed to clean task: {e}")

    async def clean_all_papers(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            import shutil
            if os.path.exists(self.paper_loop.tasks_dir):
                for item in os.listdir(self.paper_loop.tasks_dir):
                    item_path = os.path.join(self.paper_loop.tasks_dir, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                await update.message.reply_text("✅ Cleaned all paper tasks.")
            else:
                await update.message.reply_text("📁 No paper tasks directory found.")
        except Exception as e:
            logger.error(f"Error in clean_all_papers: {e}")
            await update.message.reply_text(f"❌ Failed to clean all paper tasks: {e}")

    async def handle_document(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        doc = update.message.document
        if not doc.file_name.endswith('.zip'):
            await update.message.reply_text("⚠️ Please upload a .zip file for the paper writing task.")
            return

        try:
            file = await context.bot.get_file(doc.file_id)

            temp_zip_path = os.path.join(self.params.workspace_dir, f"paper_input_{chat_id}.zip")
            await file.download_to_drive(temp_zip_path)

            self.last_zip_paths[chat_id] = temp_zip_path
            await update.message.reply_text("✅ Zip file received. Use `/write_paper <rounds_n>` to start the loop.")
        except Exception as e:
            logger.error(f"Error handling document: {e}")
            await update.message.reply_text(f"❌ Failed to receive file: {e}")

    async def write_paper(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        zip_path = self.last_zip_paths.get(chat_id)
        if not zip_path or not os.path.exists(zip_path):
            await update.message.reply_text("⚠️ No zip file found. Please upload a .zip file first.")
            return

        rounds_n = 3 # Default
        if context.args:
            try:
                rounds_n = int(context.args[0])
            except ValueError:
                await update.message.reply_text("Usage: /write_paper <rounds_n>")
                return

        tid = await self.next_task_id()
        task_id = f"paper_task_{tid}"

        # We run this as a task in the background
        asyncio.create_task(self.run_paper_loop_task(chat_id, task_id, zip_path, rounds_n))
        await update.message.reply_text(f"🚀 Started Paper Writing Loop (ID: {task_id}) for {rounds_n} rounds.")

    async def run_paper_loop_task(self, chat_id, task_id, zip_path, rounds_n):
        async def status_update(msg):
            await self.application.bot.send_message(chat_id, msg)

        try:
            final_zip_path = await self.paper_loop.run(task_id, zip_path, rounds_n, status_update)

            with open(final_zip_path, 'rb') as f:
                await self.application.bot.send_document(chat_id, f, caption=f"🏁 Paper writing task {task_id} completed!")

            # Cleanup temp zip
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if chat_id in self.last_zip_paths:
                del self.last_zip_paths[chat_id]

        except Exception as e:
            logger.error(f"Error in run_paper_loop_task: {e}")
            await self.application.bot.send_message(chat_id, f"❌ Paper loop failed: {e}")

    async def handle_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        current_dir = self.user_project_state.get(chat_id, self.params.workspace_dir)

        tid = await self.next_task_id()
        task = {
            'id': tid,
            'chat_id': chat_id,
            'text': update.message.text,
            'cwd': current_dir,
            'status': 'queued'
        }

        async with self.worker_lock:
            if current_dir not in self.project_queues:
                self.project_queues[current_dir] = asyncio.Queue()
            await self.project_queues[current_dir].put(task)
            self.tasks_by_id[tid] = task
            q_size = self.project_queues[current_dir].qsize()

        await self.ensure_worker_running(current_dir)
        await update.message.reply_text(f"📝 Task queued (ID: {tid}) for {os.path.basename(current_dir)}\n{q_size - 1} tasks ahead in this folder.")

    async def process_task(self, task):
        chat_id = task['chat_id']
        task_text = task['text']
        work_dir = task['cwd']

        if task.get('status') == 'cancelled':
            logger.info(f"Skipping cancelled task {task['id']}")
            return

        try:
            await self.application.bot.send_message(chat_id, f"⚙️ Executing...\nDirectory: {os.path.basename(work_dir)}")

            agent_rules_path = os.path.join(self.params.workspace_dir, 'AGENT.md')
            if os.path.exists(agent_rules_path) and os.path.isfile(agent_rules_path):
                try:
                    with open(agent_rules_path, 'r') as f:
                        agent_rules = f.read()
                    task_text = f"--- Agent Rules ---\n{agent_rules}\n--- End Rules ---\n\n{task_text}"
                    logger.info(f"Loaded AGENT.md for task in {work_dir}")
                except Exception as e:
                    logger.error(f"Failed to read AGENT.md: {e}")
                    await self.application.bot.send_message(chat_id, f"⚠️ Warning: Found AGENT.md but failed to read it: {e}")

            async with self.worker_lock:
                self.running_tasks[task['id']] = {
                    'task': task,
                    'start_time': time.time(),
                    'stopped': False
                }

            stdout, stderr, return_code = await self.ai_tool.call(task_text, work_dir)

            async with self.worker_lock:
                was_stopped = False
                if task['id'] in self.running_tasks:
                    was_stopped = self.running_tasks[task['id']].get('stopped', False)
                    del self.running_tasks[task['id']]
                task['status'] = 'completed' if not was_stopped else 'stopped'

            if was_stopped:
                return

            reply = f"✅ Task Completed (ID: {task['id']})\n\n[Output]:\n{stdout}"
            if stderr:
                reply += f"\n\n[Error/Warning]:\n{stderr}"
            if return_code != 0 and not stderr:
                reply += f"\n\n[Return Code]: {return_code}"

            if len(reply) > 4000:
                reply = reply[:4000] + "...\n[Output Truncated]"

            await self.application.bot.send_message(chat_id, reply)

        except Exception as e:
            logger.error(f"Worker exception: {e}")
            try:
                await self.application.bot.send_message(chat_id, f"❌ Internal Worker Error: {e}")
            except:
                pass

    async def project_worker(self, project_path):
        queue = self.project_queues[project_path]
        while True:
            try:
                # Wait for a task from the queue
                # Use a timeout to stop the worker if idle
                task = await asyncio.wait_for(queue.get(), timeout=300)
                task['status'] = 'running'
                await self.process_task(task)
                queue.task_done()
            except asyncio.TimeoutError:
                async with self.worker_lock:
                    if project_path in self.active_workers:
                        del self.active_workers[project_path]
                    logger.info(f"Stopping worker for {project_path} (idle)")
                    return
            except Exception as e:
                logger.error(f"Error in project_worker for {project_path}: {e}")
                await asyncio.sleep(1)

    async def initialize_bot(self):
        init_file = os.path.join(self.params.workspace_dir, 'INIT.md')
        if os.path.exists(init_file):
            logger.info(f"Initializing bot with {init_file}...")
            stdout, stderr, return_code = await self.ai_tool.call(f"Initialize according to @{init_file}", self.params.workspace_dir)
            if return_code == 0:
                logger.info("Bot initialization successful.")
                if stdout:
                    logger.info(f"Initialization Output: {stdout}")
            else:
                logger.error(f"Bot initialization failed with exit code {return_code}")
                if stderr:
                    logger.error(f"Initialization Error: {stderr}")
        else:
            logger.info(f"No initialization file found at {init_file}. Skipping initialization.")

    async def start(self):
        logger.info("🤖 Bot Daemon Starting...")
        await self.initialize_bot()
        logger.info("🤖 Bot Daemon Started...")
        async with self.application:
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling()

            # Keep the loop running until signaled
            stop_event = asyncio.Event()

            # Simple way to handle signals in this context
            loop = asyncio.get_running_loop()
            for sig in (signal.SIGINT, signal.SIGTERM):
                try:
                    loop.add_signal_handler(sig, stop_event.set)
                except NotImplementedError:
                    # Signal handlers not supported on some platforms (like Windows)
                    pass

            await stop_event.wait()

            await self.application.updater.stop()
            await self.application.stop()
            await self.application.shutdown()
