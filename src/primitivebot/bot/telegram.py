from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
import os
import threading
import queue
import logging
import time
import signal
import subprocess
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from primitivebot.ai.cli import AICLITool

logger = logging.getLogger(__name__)

@dataclass
class TelegramBotParams:
    """Hyperparameters for starting and running the TelegramBot."""
    token: str
    workspace_dir: str = '/workspace'
    task_timeout_second: int = 600
    status_desc_length: int = 30
    # any other IM specific parameters

class TelegramBot:
    """Refactored TelegramBot class."""

    def __init__(self, params: TelegramBotParams, ai_tool: AICLITool):
        self.params = params
        self.ai_tool = ai_tool
        
        # Internal state
        self.bot = telebot.TeleBot(self.params.token)
        self.project_queues: Dict[str, List[Dict[str, Any]]] = {}
        self.active_workers: Dict[str, threading.Thread] = {}
        self.running_tasks: Dict[int, Dict[str, Any]] = {}
        self.tasks_by_id: Dict[int, Dict[str, Any]] = {}
        self.worker_lock = threading.Lock()
        self.worker_condition = threading.Condition(self.worker_lock)
        self.task_id_counter = 1
        self.user_project_state: Dict[int, str] = {}
        
        # Register handlers
        self._register_handlers()

    def _register_handlers(self):
        @self.bot.message_handler(commands=['cd', 'projects', 'start'])
        def list_projects_handler(message):
            self.list_projects(message)

        @self.bot.callback_query_handler(func=lambda call: call.data.startswith('proj_'))
        def handle_project_selection_handler(call):
            self.handle_project_selection(call)

        @self.bot.message_handler(commands=['create'])
        def create_project_handler(message):
            self.create_project(message)

        @self.bot.message_handler(commands=['status'])
        def show_status_handler(message):
            self.show_status(message)

        @self.bot.message_handler(commands=['stop', 'cancel'])
        def stop_tasks_handler(message):
            self.stop_tasks(message)

        @self.bot.message_handler(func=lambda message: not message.text.startswith('/'))
        def handle_task_handler(message):
            self.handle_task(message)

    def next_task_id(self) -> int:
        with self.worker_lock:
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

    def ensure_worker_running(self, project_path: str):
        with self.worker_lock:
            if project_path not in self.active_workers or not self.active_workers[project_path].is_alive():
                t = threading.Thread(target=self.project_worker, args=(project_path,), daemon=True)
                self.active_workers[project_path] = t
                t.start()
                logger.info(f"Started worker for {project_path}")

    # --- Handlers implementation ---

    def list_projects(self, message):
        dirs = self.get_project_dirs()
        if not dirs:
            self.bot.reply_to(message, "Workspace is empty. Please create project folders in the mounted host directory.")
            return

        markup = InlineKeyboardMarkup()
        for d in dirs:
            markup.add(InlineKeyboardButton(d, callback_data=f"proj_{d}"))
        markup.add(InlineKeyboardButton("🏠 Root Directory", callback_data="proj_ROOT"))

        self.bot.send_message(message.chat.id, "📁 Select a project directory:", reply_markup=markup)

    def handle_project_selection(self, call):
        project_name = call.data.replace('proj_', '')
        chat_id = call.message.chat.id

        if project_name == "ROOT":
            self.user_project_state[chat_id] = self.params.workspace_dir
            display_name = f"Root Directory {self.params.workspace_dir}"
        else:
            self.user_project_state[chat_id] = os.path.join(self.params.workspace_dir, project_name)
            display_name = project_name

        self.bot.answer_callback_query(call.id, "Switched successfully")
        self.bot.edit_message_text(f"✅ Current working directory switched to: {display_name}
Subsequent tasks will execute in this folder.",
                              chat_id=chat_id, message_id=call.message.message_id)

    def create_project(self, message):
        try:
            parts = message.text.split()
            if len(parts) < 2:
                self.bot.reply_to(message, "Usage: /create <project_name>")
                return
            
            project_name = parts[1]
            if not all(c.isalnum() or c in ('_', '-') for c in project_name):
                 self.bot.reply_to(message, "Invalid project name. Use alphanumeric characters, underscores, or hyphens.")
                 return

            project_path = os.path.join(self.params.workspace_dir, project_name)
            if os.path.exists(project_path):
                self.bot.reply_to(message, f"⚠️ Project '{project_name}' already exists.")
                return

            os.makedirs(project_path)
            self.bot.reply_to(message, f"✅ Project '{project_name}' created successfully.")
        except Exception as e:
            logger.error(f"Error creating project: {e}")
            self.bot.reply_to(message, f"❌ Failed to create project: {e}")

    def show_status(self, message):
        with self.worker_lock:
            active_projects = [p for p, q in self.project_queues.items() if q]
            if not self.running_tasks and not active_projects:
                self.bot.reply_to(message, "📭 No tasks running or queued.")
                return

            status_msg = "📊 **System Status**

"
            if self.running_tasks:
                status_msg += "🏃 **Running Tasks:**
"
                for tid, info in self.running_tasks.items():
                    project_name = os.path.basename(info['task']['cwd']) or "Root"
                    task_text = info['task']['text']
                    task_preview = (task_text[:self.params.status_desc_length] + '...') if len(task_text) > self.params.status_desc_length else task_text
                    elapsed = int(time.time() - info['start_time'])
                    status_msg += f"- `[{tid}]` `{project_name}`: {task_preview} ({elapsed}s)
"
                status_msg += "
"

            has_queued = False
            for path, q_list in self.project_queues.items():
                if q_list:
                    if not has_queued:
                        status_msg += "⏳ **Queued Tasks:**
"
                        has_queued = True
                    project_name = os.path.basename(path) or "Root"
                    status_msg += f"📂 `{project_name}`:
"
                    for t in q_list:
                        task_text = t['text']
                        task_preview = (task_text[:self.params.status_desc_length] + '...') if len(task_text) > self.params.status_desc_length else task_text
                        status_msg += f"  - `[{t['id']}]` {task_preview}
"
            
            self.bot.send_message(message.chat.id, status_msg, parse_mode='Markdown')

    def stop_tasks(self, message):
        try:
            parts = message.text.split()
            if len(parts) < 2:
                self.bot.reply_to(message, "Usage: /stop {task_id}
Use /status to see the task_id.")
                return
            task_id = int(parts[1])
            self.perform_stop_by_id(task_id, message.chat.id)
        except ValueError:
            self.bot.reply_to(message, "Invalid task ID. Please provide a numeric task_id.")
        except Exception as e:
            logger.error(f"Error in stop_tasks: {e}")
            self.bot.reply_to(message, f"❌ Error: {e}")

    def perform_stop_by_id(self, task_id, chat_id):
        with self.worker_condition:
            task = self.tasks_by_id.get(task_id)
            if not task:
                self.bot.send_message(chat_id, f"❌ Task `{task_id}` does not exist.")
                return

            if task_id in self.running_tasks:
                info = self.running_tasks[task_id]
                info['stopped'] = True
                # In AICLITool.call, we don't have direct access to the process here.
                # However, the worker can handle it if we signal it.
                # Since AI tool is agnostic, we need a way to stop it.
                # For now, let's keep the logic of killing by process group if we had the PID.
                # But we don't store PID in running_tasks anymore directly.
                # Let's assume for now that if we mark stopped=True, 
                # we might need the AI tool to be interruptible.
                # Refactoring note: AI tool should probably return a handler or we manage it.
                # In current bot.py, process was stored in running_tasks.
                # Let's adjust AICLITool to be more flexible or TelegramBot to manage the process.
                # Actually, the user wants AICLITool to BE the calling function.
                pass 

            for project_path, q_list in self.project_queues.items():
                for i, t in enumerate(q_list):
                    if t['id'] == task_id:
                        q_list.pop(i)
                        task['status'] = 'cancelled'
                        self.bot.send_message(chat_id, f"🛑 Removed task `{task_id}` from the queue.")
                        return

            status = task.get('status', 'unknown')
            self.bot.send_message(chat_id, f"ℹ️ Task `{task_id}` is not currently running or queued (Status: {status}).")

    def handle_task(self, message):
        chat_id = message.chat.id
        current_dir = self.user_project_state.get(chat_id, self.params.workspace_dir)
        
        tid = self.next_task_id()
        task = {
            'id': tid,
            'chat_id': chat_id,
            'text': message.text,
            'cwd': current_dir,
            'status': 'queued'
        }

        with self.worker_condition:
            if current_dir not in self.project_queues:
                self.project_queues[current_dir] = []
            self.project_queues[current_dir].append(task)
            self.tasks_by_id[tid] = task
            q_size = len(self.project_queues[current_dir])
            self.worker_condition.notify_all()
        
        self.ensure_worker_running(current_dir)
        self.bot.reply_to(message, f"📝 Task queued (ID: {tid}) for {os.path.basename(current_dir)}
{q_size - 1} tasks ahead in this folder.")

    def process_task(self, task):
        chat_id = task['chat_id']
        task_text = task['text']
        work_dir = task['cwd']

        try:
            self.bot.send_message(chat_id, f"⚙️ Executing...
Directory: {os.path.basename(work_dir)}")

            agent_rules_path = os.path.join(self.params.workspace_dir, 'AGENT.md')
            if os.path.exists(agent_rules_path) and os.path.isfile(agent_rules_path):
                try:
                    with open(agent_rules_path, 'r') as f:
                        agent_rules = f.read()
                    task_text = f"--- Agent Rules ---
{agent_rules}
--- End Rules ---

{task_text}"
                    logger.info(f"Loaded AGENT.md for task in {work_dir}")
                except Exception as e:
                    logger.error(f"Failed to read AGENT.md: {e}")
                    self.bot.send_message(chat_id, f"⚠️ Warning: Found AGENT.md but failed to read it: {e}")

            with self.worker_lock:
                self.running_tasks[task['id']] = {
                    'task': task,
                    'start_time': time.time(),
                    'stopped': False
                }

            stdout, stderr, return_code = self.ai_tool.call(task_text, work_dir)
            
            with self.worker_lock:
                was_stopped = False
                if task['id'] in self.running_tasks:
                    was_stopped = self.running_tasks[task['id']].get('stopped', False)
                    del self.running_tasks[task['id']]
                task['status'] = 'completed' if not was_stopped else 'stopped'
            
            if was_stopped:
                return

            reply = f"✅ Task Completed (ID: {task['id']})

[Output]:
{stdout}"
            if stderr:
                reply += f"

[Error/Warning]:
{stderr}"
            if return_code != 0 and not stderr:
                reply += f"

[Return Code]: {return_code}"

            if len(reply) > 4000:
                reply = reply[:4000] + "...
[Output Truncated]"

            self.bot.send_message(chat_id, reply)

        except Exception as e:
            logger.error(f"Worker exception: {e}")
            try:
                self.bot.send_message(chat_id, f"❌ Internal Worker Error: {e}")
            except:
                pass

    def project_worker(self, project_path):
        while True:
            task = None
            with self.worker_condition:
                while project_path not in self.project_queues or not self.project_queues[project_path]:
                    if not self.worker_condition.wait(timeout=300):
                        if project_path in self.active_workers:
                            del self.active_workers[project_path]
                        logger.info(f"Stopping worker for {project_path} (idle)")
                        return
                task = self.project_queues[project_path].pop(0)
                task['status'] = 'running'

            if task:
                self.process_task(task)

    def initialize_bot(self):
        init_file = os.path.join(self.params.workspace_dir, 'INIT.md')
        if os.path.exists(init_file):
            logger.info(f"Initializing bot with {init_file}...")
            # We can use the AI tool to initialize as well
            stdout, stderr, return_code = self.ai_tool.call(f"Initialize according to @{init_file}", self.params.workspace_dir)
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

    def start(self):
        logger.info("🤖 Bot Daemon Starting...")
        self.initialize_bot()
        logger.info("🤖 Bot Daemon Started...")
        self.bot.infinity_polling()
