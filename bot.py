# Copyright 2026 fshp971
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os
import subprocess
import threading
import queue
import logging
import time
import signal
import yaml
from dotenv import load_dotenv
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load configuration from YAML file
CONFIG_FILE = os.path.join(os.path.dirname(__file__), 'config.yaml')
config = {}
if os.path.exists(CONFIG_FILE):
    try:
        with open(CONFIG_FILE, 'r') as f:
            config = yaml.safe_load(f) or {}
            logger.info(f"Loaded configuration from {CONFIG_FILE}")
    except Exception as e:
        logger.error(f"Error loading {CONFIG_FILE}: {e}")
else:
    logger.info(f"No configuration file found at {CONFIG_FILE}. Using defaults.")

# Default parameters
TASK_TIMEOUT = config.get('task_running_timeout_seconds', 600)

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN not set. Bot will fail to start.")

# Initialize bot
try:
    bot = telebot.TeleBot(TOKEN)
except Exception as e:
    logger.error(f"Failed to initialize bot: {e}")
    bot = None

# Global state for queues and workers
project_queues = {}  # Map: project_path -> queue.Queue
active_workers = {}  # Map: project_path -> threading.Thread
running_tasks = {}   # Map: project_path -> dict(process, task, start_time)
worker_lock = threading.Lock()
user_project_state = {}

WORKSPACE_DIR = os.environ.get('WORKSPACE_DIR', '/workspace')

def get_project_dirs():
    """Scans all project folders in the mounted directory."""
    if not os.path.exists(WORKSPACE_DIR):
        return []
    try:
        return [d for d in os.listdir(WORKSPACE_DIR) if os.path.isdir(os.path.join(WORKSPACE_DIR, d))]
    except OSError as e:
        logger.error(f"Error accessing base directory: {e}")
        return []

def get_project_queue(project_path):
    with worker_lock:
        if project_path not in project_queues:
            project_queues[project_path] = queue.Queue()
        return project_queues[project_path]

def ensure_worker_running(project_path):
    with worker_lock:
        if project_path not in active_workers or not active_workers[project_path].is_alive():
            # Start a new worker
            t = threading.Thread(target=project_worker, args=(project_path,), daemon=True)
            active_workers[project_path] = t
            t.start()
            logger.info(f"Started worker for {project_path}")

# --- Interaction Module: Directory Switching ---
@bot.message_handler(commands=['cd', 'projects', 'start'])
def list_projects(message):
    dirs = get_project_dirs()
    if not dirs:
        bot.reply_to(message, "Workspace is empty. Please create project folders in the mounted host directory.")
        return

    markup = InlineKeyboardMarkup()
    for d in dirs:
        markup.add(InlineKeyboardButton(d, callback_data=f"proj_{d}"))
    markup.add(InlineKeyboardButton("🏠 Root Directory", callback_data="proj_ROOT"))

    bot.send_message(message.chat.id, "📁 Select a project directory:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('proj_'))
def handle_project_selection(call):
    project_name = call.data.replace('proj_', '')
    chat_id = call.message.chat.id

    if project_name == "ROOT":
        user_project_state[chat_id] = WORKSPACE_DIR
        display_name = f"Root Directory {WORKSPACE_DIR}"
    else:
        user_project_state[chat_id] = os.path.join(WORKSPACE_DIR, project_name)
        display_name = project_name

    bot.answer_callback_query(call.id, "Switched successfully")
    bot.edit_message_text(f"✅ Current working directory switched to: {display_name}\nSubsequent tasks will execute in this folder.",
                          chat_id=chat_id, message_id=call.message.message_id)

# --- Management Module: Project Creation ---
@bot.message_handler(commands=['create'])
def create_project(message):
    try:
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /create <project_name>")
            return
        
        project_name = parts[1]
        
        # Basic validation
        if not all(c.isalnum() or c in ('_', '-') for c in project_name):
             bot.reply_to(message, "Invalid project name. Use alphanumeric characters, underscores, or hyphens.")
             return

        project_path = os.path.join(WORKSPACE_DIR, project_name)

        if os.path.exists(project_path):
            bot.reply_to(message, f"⚠️ Project '{project_name}' already exists.")
            return

        os.makedirs(project_path)
        bot.reply_to(message, f"✅ Project '{project_name}' created successfully.")
    
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        bot.reply_to(message, f"❌ Failed to create project: {e}")

@bot.message_handler(commands=['status'])
def show_status(message):
    with worker_lock:
        active_projects = [p for p, q in project_queues.items() if not q.empty()]
        
        if not running_tasks and not active_projects:
            bot.reply_to(message, "📭 No tasks running or queued.")
            return

        status_msg = "📊 **System Status**\n\n"
        
        if running_tasks:
            status_msg += "🏃 **Running Tasks:**\n"
            for path, info in running_tasks.items():
                project_name = os.path.basename(path) or "Root"
                task_text = info['task']['text']
                # Truncate task text if too long
                task_preview = (task_text[:30] + '...') if len(task_text) > 30 else task_text
                elapsed = int(time.time() - info['start_time'])
                status_msg += f"- `{project_name}`: {task_preview} ({elapsed}s)\n"
            status_msg += "\n"

        has_queued = False
        for path, q in project_queues.items():
            if not q.empty():
                if not has_queued:
                    status_msg += "⏳ **Queued Tasks:**\n"
                    has_queued = True
                project_name = os.path.basename(path) or "Root"
                status_msg += f"- `{project_name}`: {q.qsize()} tasks waiting\n"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🛑 Stop/Cancel Tasks", callback_data="stop_prompt"))
        
        bot.send_message(message.chat.id, status_msg, parse_mode='Markdown', reply_markup=markup)

# --- Control Module: Stopping Tasks ---
@bot.message_handler(commands=['stop', 'cancel'])
def stop_tasks(message):
    prompt_stop(message.chat.id)

@bot.callback_query_handler(func=lambda call: call.data == 'stop_prompt')
def handle_stop_prompt(call):
    prompt_stop(call.message.chat.id)
    bot.answer_callback_query(call.id)

def prompt_stop(chat_id):
    current_dir = user_project_state.get(chat_id, WORKSPACE_DIR)
    
    with worker_lock:
        running = current_dir in running_tasks
        q = project_queues.get(current_dir)
        queued_count = q.qsize() if q else 0
        
        # Check if there are other active projects
        active_dirs = set(running_tasks.keys()) | {p for p, q in project_queues.items() if not q.empty()}

    if not running and queued_count == 0:
        if not active_dirs:
            bot.send_message(chat_id, "📭 No tasks running or queued in any project.")
            return
        
        markup = InlineKeyboardMarkup()
        for d in active_dirs:
            project_name = os.path.basename(d) or "Root"
            markup.add(InlineKeyboardButton(f"Stop {project_name}", callback_data=f"stop_{d}"))
        
        bot.send_message(chat_id, "Select a project to stop its tasks:", reply_markup=markup)
        return

    perform_stop(current_dir, chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('stop_'))
def handle_stop_selection(call):
    project_path = call.data.replace('stop_', '')
    chat_id = call.message.chat.id
    
    perform_stop(project_path, chat_id)
    bot.answer_callback_query(call.id, "Stop command executed")
    # Edit the message to remove the buttons
    bot.edit_message_text(f"🛑 Processing stop for {os.path.basename(project_path) or 'Root'}...",
                          chat_id=chat_id, message_id=call.message.message_id)

def perform_stop(project_path, chat_id):
    project_name = os.path.basename(project_path) or "Root"
    stopped_running = False
    cancelled_count = 0

    with worker_lock:
        # 1. Kill running task
        if project_path in running_tasks:
            info = running_tasks[project_path]
            info['stopped'] = True
            process = info['process']
            try:
                os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                stopped_running = True
            except Exception as e:
                logger.error(f"Failed to kill process for {project_path}: {e}")

        # 2. Clear queue
        q = project_queues.get(project_path)
        if q:
            while not q.empty():
                try:
                    q.get_nowait()
                    q.task_done()
                    cancelled_count += 1
                except queue.Empty:
                    break
    
    msg = f"🛑 **Stopped tasks for `{project_name}`**\n"
    if stopped_running:
        msg += "- Terminated the currently running task.\n"
    if cancelled_count > 0:
        msg += f"- Cancelled {cancelled_count} queued tasks.\n"
    
    if not stopped_running and cancelled_count == 0:
        msg = f"ℹ️ No active tasks found for `{project_name}` to stop."

    bot.send_message(chat_id, msg, parse_mode='Markdown')

# --- Reception Module: Task Enqueuing ---
@bot.message_handler(func=lambda message: not message.text.startswith('/'))
def handle_task(message):
    chat_id = message.chat.id
    current_dir = user_project_state.get(chat_id, WORKSPACE_DIR)
    
    # Get the queue for this specific project folder
    q = get_project_queue(current_dir)
    
    task = {
        'chat_id': chat_id,
        'text': message.text,
        'cwd': current_dir
    }
    q.put(task)
    
    ensure_worker_running(current_dir)

    bot.reply_to(message, f"📝 Task queued for {os.path.basename(current_dir)}\n{q.qsize() - 1} tasks ahead in this folder.")

# --- Execution Module: Background Consumption & Gemini Call ---
def process_task(task):
    """Process a single task from the queue."""
    chat_id = task['chat_id']
    task_text = task['text']
    work_dir = task['cwd']

    try:
        bot.send_message(chat_id, f"⚙️ Executing...\nDirectory: {os.path.basename(work_dir)}")

        # Check for AGENT.md in the current working directory
        agent_rules_path = os.path.join(WORKSPACE_DIR, 'AGENT.md')
        if os.path.exists(agent_rules_path) and os.path.isfile(agent_rules_path):
            try:
                with open(agent_rules_path, 'r') as f:
                    agent_rules = f.read()
                task_text = f"--- Agent Rules ---\n{agent_rules}\n--- End Rules ---\n\n{task_text}"
                logger.info(f"Loaded AGENT.md for task in {work_dir}")
            except Exception as e:
                logger.error(f"Failed to read AGENT.md: {e}")
                bot.send_message(chat_id, f"⚠️ Warning: Found AGENT.md but failed to read it: {e}")

        # Call gemini, strictly restricted to work_dir for safety
        try:
            # We use Popen to allow tracking and future termination
            process = subprocess.Popen(
                ['gemini', '--yolo', '--prompt', '-'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=work_dir,
                text=True,
                preexec_fn=os.setsid  # To allow killing the whole process group later
            )

            with worker_lock:
                running_tasks[work_dir] = {
                    'process': process,
                    'task': task,
                    'start_time': time.time(),
                    'stopped': False
                }

            try:
                stdout, stderr = process.communicate(input=task_text, timeout=TASK_TIMEOUT)
                
                reply = f"✅ Task Completed\n\n[Output]:\n{stdout}"
                if stderr:
                    reply += f"\n\n[Error/Warning]:\n{stderr}"
            except subprocess.TimeoutExpired:
                 # Kill the whole process group
                 try:
                     os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                 except:
                     pass
                 process.communicate() # ensure it is cleaned up
                 reply = f"❌ Execution Failed: Task timed out after {TASK_TIMEOUT} seconds."
            finally:
                with worker_lock:
                    was_stopped = False
                    if work_dir in running_tasks:
                        was_stopped = running_tasks[work_dir].get('stopped', False)
                        del running_tasks[work_dir]
                
                if was_stopped:
                    return # Skip sending the completion message if it was manually stopped

        except FileNotFoundError:
             reply = "❌ Execution Failed: 'gemini' not found. Please ensure it is installed and in PATH."
        except Exception as e:
            reply = f"❌ Execution Crashed: {str(e)}"

        # Prevent Telegram message length limit (4096 chars)
        if len(reply) > 4000:
            reply = reply[:4000] + "...\n[Output Truncated]"

        bot.send_message(chat_id, reply)

    except Exception as e:
        logger.error(f"Worker exception: {e}")
        if bot:
            try:
                bot.send_message(chat_id, f"❌ Internal Worker Error: {e}")
            except:
                pass

def project_worker(project_path):
    q = get_project_queue(project_path)

    while True:
        try:
            # Wait for a task, timeout to let the thread die if idle (e.g. 5 mins) 
            task = q.get(timeout=300) 
        except queue.Empty:
            # Check if we should exit
            with worker_lock:
                if q.empty():
                    if project_path in active_workers:
                        del active_workers[project_path]
                    logger.info(f"Stopping worker for {project_path} (idle)")
                    return
            continue

        try:
            process_task(task)
        finally:
            q.task_done()

def initialize_bot():
    """Performs initialization using gemini-cli and INIT.md if it exists."""
    init_file = os.path.join(WORKSPACE_DIR, 'INIT.md')
    if os.path.exists(init_file):
        logger.info(f"Initializing bot with {init_file}...")
        try:
            result = subprocess.run(
                ['gemini', '--yolo', '--prompt', f"Initialize according to @{init_file}"],
                cwd=WORKSPACE_DIR,
                capture_output=True,
                text=True,
                timeout=TASK_TIMEOUT
            )
            if result.returncode == 0:
                logger.info("Bot initialization successful.")
                if result.stdout:
                    logger.info(f"Initialization Output: {result.stdout}")
            else:
                logger.error(f"Bot initialization failed with exit code {result.returncode}")
                if result.stderr:
                    logger.error(f"Initialization Error: {result.stderr}")
        except Exception as e:
            logger.error(f"Error during bot initialization: {e}")
    else:
        logger.info(f"No initialization file found at {init_file}. Skipping initialization.")

if __name__ == '__main__':
    if bot:
        logger.info("🤖 Bot Daemon Starting...")
        initialize_bot()
        logger.info("🤖 Bot Daemon Started...")
        bot.infinity_polling()
    else:
        logger.error("Bot could not start due to configuration errors.")
