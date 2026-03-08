import asyncio
import os
import signal
import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from telebot.async_telebot import AsyncTeleBot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
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
    """Refactored TelegramBot class using asyncio."""

    def __init__(self, params: TelegramBotParams, ai_tool: AICLITool):
        self.params = params
        self.ai_tool = ai_tool

        # Internal state
        self.bot = AsyncTeleBot(self.params.token)
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
        @self.bot.message_handler(func=lambda message: not self._is_allowed(message.from_user.id))
        async def unauthorized_message_handler(message):
            logger.warning(f"Unauthorized access attempt by user {message.from_user.id} ({message.from_user.username})")
            await self.bot.reply_to(message, "🚫 You are not authorized to use this bot.")

        @self.bot.callback_query_handler(func=lambda call: not self._is_allowed(call.from_user.id))
        async def unauthorized_callback_handler(call):
            logger.warning(f"Unauthorized callback attempt by user {call.from_user.id} ({call.from_user.username})")
            await self.bot.answer_callback_query(call.id, "🚫 Unauthorized", show_alert=True)

        @self.bot.message_handler(commands=['cd', 'projects', 'start'])
        async def list_projects_handler(message):
            await self.list_projects(message)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('proj_'))
        async def handle_project_selection_handler(call):
            await self.handle_project_selection(call)

        @self.bot.message_handler(commands=['create'])
        async def create_project_handler(message):
            await self.create_project(message)

        @self.bot.message_handler(commands=['status'])
        async def show_status_handler(message):
            await self.show_status(message)

        @self.bot.message_handler(commands=['stop', 'cancel'])
        async def stop_tasks_handler(message):
            await self.stop_tasks(message)

        @self.bot.message_handler(commands=['clean'])
        async def clean_task_handler(message):
            await self.clean_task(message)

        @self.bot.message_handler(commands=['clean_all_papers'])
        async def clean_all_papers_handler(message):
            await self.clean_all_papers(message)

        @self.bot.message_handler(commands=['write_paper'])
        async def write_paper_handler(message):
            await self.write_paper(message)

        @self.bot.message_handler(content_types=['document'])
        async def handle_document_handler(message):
            await self.handle_document(message)

        @self.bot.message_handler(func=lambda message: not message.text.startswith('/'))
        async def handle_task_handler(message):
            await self.handle_task(message)

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

    async def list_projects(self, message):
        dirs = self.get_project_dirs()
        if not dirs:
            await self.bot.reply_to(message, "Workspace is empty. Please create project folders in the mounted host directory.")
            return

        markup = InlineKeyboardMarkup()
        for d in dirs:
            markup.add(InlineKeyboardButton(d, callback_data=f"proj_{d}"))
        markup.add(InlineKeyboardButton("🏠 Root Directory", callback_data="proj_ROOT"))

        await self.bot.send_message(message.chat.id, "📁 Select a project directory:", reply_markup=markup)

    async def handle_project_selection(self, call):
        project_name = call.data.replace('proj_', '')
        chat_id = call.message.chat.id

        if project_name == "ROOT":
            self.user_project_state[chat_id] = self.params.workspace_dir
            display_name = f"Root Directory {self.params.workspace_dir}"
        else:
            self.user_project_state[chat_id] = os.path.join(self.params.workspace_dir, project_name)
            display_name = project_name

        await self.bot.answer_callback_query(call.id, "Switched successfully")
        await self.bot.edit_message_text(f"✅ Current working directory switched to: {display_name}\nSubsequent tasks will execute in this folder.",
                              chat_id=chat_id, message_id=call.message.message_id)

    async def create_project(self, message):
        try:
            parts = message.text.split()
            if len(parts) < 2:
                await self.bot.reply_to(message, "Usage: /create <project_name>")
                return

            project_name = parts[1]
            if not all(c.isalnum() or c in ('_', '-') for c in project_name):
                 await self.bot.reply_to(message, "Invalid project name. Use alphanumeric characters, underscores, or hyphens.")
                 return

            project_path = os.path.join(self.params.workspace_dir, project_name)
            if os.path.exists(project_path):
                await self.bot.reply_to(message, f"⚠️ Project '{project_name}' already exists.")
                return

            os.makedirs(project_path)
            await self.bot.reply_to(message, f"✅ Project '{project_name}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating project: {e}")
            await self.bot.reply_to(message, f"❌ Failed to create project: {e}")

    async def show_status(self, message):
        async with self.worker_lock:
            active_projects = [p for p, q in self.project_queues.items() if not q.empty()]
            if not self.running_tasks and not active_projects:
                await self.bot.reply_to(message, "📭 No tasks running or queued.")
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
                    # asyncio.Queue is not directly iterable in a safe way to show all items
                    # but we can look at its internal _queue if we really want to, or keep track of it
                    # Let's use a simpler approach for now.
                    status_msg += f"  - (Queue size: {q.qsize()})\n"

            await self.bot.send_message(message.chat.id, status_msg, parse_mode='Markdown')

    async def stop_tasks(self, message):
        try:
            parts = message.text.split()
            if len(parts) < 2:
                await self.bot.reply_to(message, "Usage: /stop {task_id}\nUse /status to see the task_id.")
                return
            task_id = int(parts[1])
            await self.perform_stop_by_id(task_id, message.chat.id)
        except ValueError:
            await self.bot.reply_to(message, "Invalid task ID. Please provide a numeric task_id.")
        except Exception as e:
            logger.error(f"Error in stop_tasks: {e}")
            await self.bot.reply_to(message, f"❌ Error: {e}")

    async def perform_stop_by_id(self, task_id, chat_id):
        async with self.worker_lock:
            task = self.tasks_by_id.get(task_id)
            if not task:
                await self.bot.send_message(chat_id, f"❌ Task `{task_id}` does not exist.")
                return

            if task_id in self.running_tasks:
                info = self.running_tasks[task_id]
                info['stopped'] = True
                # In AICLITool.call, we don't have direct access to the process here.
                # However, the worker can handle it if we signal it.
                # But since it's asyncio, we'd need to cancel the task.
                # Stopping individual tasks in an async queue/worker setup is a bit more complex.
                # For now, let's just mark it as stopped so the worker knows.
                pass

            # Removing from asyncio.Queue is not straightforward.
            # Usually we mark it as cancelled and the worker skips it.
            if task['status'] == 'queued':
                 task['status'] = 'cancelled'
                 await self.bot.send_message(chat_id, f"🛑 Task `{task_id}` marked as cancelled.")
                 return

            status = task.get('status', 'unknown')
            await self.bot.send_message(chat_id, f"ℹ️ Task `{task_id}` is not currently queued (Status: {status}).")

    async def clean_task(self, message):
        try:
            parts = message.text.split()
            if len(parts) < 2:
                await self.bot.reply_to(message, "Usage: /clean <task_id>")
                return

            task_id = parts[1]
            project_dir = os.path.join(self.paper_loop.tasks_dir, task_id)
            if os.path.exists(project_dir):
                import shutil
                shutil.rmtree(project_dir)
                await self.bot.reply_to(message, f"✅ Cleaned task {task_id}")
            else:
                await self.bot.reply_to(message, f"❌ Task {task_id} not found.")
        except Exception as e:
            logger.error(f"Error in clean_task: {e}")
            await self.bot.reply_to(message, f"❌ Failed to clean task: {e}")

    async def clean_all_papers(self, message):
        try:
            import shutil
            if os.path.exists(self.paper_loop.tasks_dir):
                for item in os.listdir(self.paper_loop.tasks_dir):
                    item_path = os.path.join(self.paper_loop.tasks_dir, item)
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                    else:
                        os.remove(item_path)
                await self.bot.reply_to(message, "✅ Cleaned all paper tasks.")
            else:
                await self.bot.reply_to(message, "📁 No paper tasks directory found.")
        except Exception as e:
            logger.error(f"Error in clean_all_papers: {e}")
            await self.bot.reply_to(message, f"❌ Failed to clean all paper tasks: {e}")

    async def handle_document(self, message):
        chat_id = message.chat.id
        if not message.document.file_name.endswith('.zip'):
            await self.bot.reply_to(message, "⚠️ Please upload a .zip file for the paper writing task.")
            return

        try:
            file_info = await self.bot.get_file(message.document.file_id)
            downloaded_file = await self.bot.download_file(file_info.file_path)

            temp_zip_path = os.path.join(self.params.workspace_dir, f"paper_input_{chat_id}.zip")
            with open(temp_zip_path, 'wb') as new_file:
                new_file.write(downloaded_file)

            self.last_zip_paths[chat_id] = temp_zip_path
            await self.bot.reply_to(message, "✅ Zip file received. Use `/write_paper <rounds_n>` to start the loop.")
        except Exception as e:
            logger.error(f"Error handling document: {e}")
            await self.bot.reply_to(message, f"❌ Failed to receive file: {e}")

    async def write_paper(self, message):
        chat_id = message.chat.id
        zip_path = self.last_zip_paths.get(chat_id)
        if not zip_path or not os.path.exists(zip_path):
            await self.bot.reply_to(message, "⚠️ No zip file found. Please upload a .zip file first.")
            return

        parts = message.text.split()
        if len(parts) < 2:
            rounds_n = 3 # Default
        else:
            try:
                rounds_n = int(parts[1])
            except ValueError:
                await self.bot.reply_to(message, "Usage: /write_paper <rounds_n>")
                return

        tid = await self.next_task_id()
        task_id = f"paper_task_{tid}"

        # We run this as a task in the background
        asyncio.create_task(self.run_paper_loop_task(chat_id, task_id, zip_path, rounds_n))
        await self.bot.reply_to(message, f"🚀 Started Paper Writing Loop (ID: {task_id}) for {rounds_n} rounds.")

    async def run_paper_loop_task(self, chat_id, task_id, zip_path, rounds_n):
        async def status_update(msg):
            await self.bot.send_message(chat_id, msg)

        try:
            final_zip_path = await self.paper_loop.run(task_id, zip_path, rounds_n, status_update)

            with open(final_zip_path, 'rb') as f:
                await self.bot.send_document(chat_id, f, caption=f"🏁 Paper writing task {task_id} completed!")

            # Cleanup temp zip
            if os.path.exists(zip_path):
                os.remove(zip_path)
            if chat_id in self.last_zip_paths:
                del self.last_zip_paths[chat_id]

        except Exception as e:
            logger.error(f"Error in run_paper_loop_task: {e}")
            await self.bot.send_message(chat_id, f"❌ Paper loop failed: {e}")

    async def handle_task(self, message):
        chat_id = message.chat.id
        current_dir = self.user_project_state.get(chat_id, self.params.workspace_dir)

        tid = await self.next_task_id()
        task = {
            'id': tid,
            'chat_id': chat_id,
            'text': message.text,
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
        await self.bot.reply_to(message, f"📝 Task queued (ID: {tid}) for {os.path.basename(current_dir)}\n{q_size - 1} tasks ahead in this folder.")

    async def process_task(self, task):
        chat_id = task['chat_id']
        task_text = task['text']
        work_dir = task['cwd']

        if task.get('status') == 'cancelled':
            logger.info(f"Skipping cancelled task {task['id']}")
            return

        try:
            await self.bot.send_message(chat_id, f"⚙️ Executing...\nDirectory: {os.path.basename(work_dir)}")

            agent_rules_path = os.path.join(self.params.workspace_dir, 'AGENT.md')
            if os.path.exists(agent_rules_path) and os.path.isfile(agent_rules_path):
                try:
                    with open(agent_rules_path, 'r') as f:
                        agent_rules = f.read()
                    task_text = f"--- Agent Rules ---\n{agent_rules}\n--- End Rules ---\n\n{task_text}"
                    logger.info(f"Loaded AGENT.md for task in {work_dir}")
                except Exception as e:
                    logger.error(f"Failed to read AGENT.md: {e}")
                    await self.bot.send_message(chat_id, f"⚠️ Warning: Found AGENT.md but failed to read it: {e}")

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

            await self.bot.send_message(chat_id, reply)

        except Exception as e:
            logger.error(f"Worker exception: {e}")
            try:
                await self.bot.send_message(chat_id, f"❌ Internal Worker Error: {e}")
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
            # We can use the AI tool to initialize as well
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
        await self.bot.polling(non_stop=True)
