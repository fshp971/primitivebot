import os
import subprocess
import threading
import queue
import logging
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

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not TOKEN:
    logger.warning("TELEGRAM_BOT_TOKEN not set. Bot will fail to start.")

# Initialize bot
try:
    bot = telebot.TeleBot(TOKEN)
except Exception as e:
    logger.error(f"Failed to initialize bot: {e}")
    bot = None

task_queue = queue.Queue()

BASE_DIR = os.environ.get('WORKSPACE_DIR', '/workspace')
user_project_state = {}

def get_project_dirs():
    """Scans all project folders in the mounted directory."""
    if not os.path.exists(BASE_DIR):
        return []
    try:
        return [d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d))]
    except OSError as e:
        logger.error(f"Error accessing base directory: {e}")
        return []

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
        user_project_state[chat_id] = BASE_DIR
        display_name = f"Root Directory {BASE_DIR}"
    else:
        user_project_state[chat_id] = os.path.join(BASE_DIR, project_name)
        display_name = project_name

    bot.answer_callback_query(call.id, "Switched successfully")
    bot.edit_message_text(f"✅ Current working directory switched to: {display_name}\nSubsequent tasks will execute in this folder.",
                          chat_id=chat_id, message_id=call.message.message_id)

# --- Management Module: Project Creation ---
@bot.message_handler(commands=['create'])
def create_project(message):
    try:
        # Extract project name. Support both /create and \create if the user treats them similarly,
        # but technically commands=['create'] only catches /create.
        # The prompt asked for \create, but we'll implement standard /create.
        # If we really want \create, we'd need a func filter.
        # For now, we stick to standard Telegram /create.
        parts = message.text.split()
        if len(parts) < 2:
            bot.reply_to(message, "Usage: /create <project_name>")
            return
        
        project_name = parts[1]
        
        # Basic validation
        if not all(c.isalnum() or c in ('_', '-') for c in project_name):
             bot.reply_to(message, "Invalid project name. Use alphanumeric characters, underscores, or hyphens.")
             return

        project_path = os.path.join(BASE_DIR, project_name)

        if os.path.exists(project_path):
            bot.reply_to(message, f"⚠️ Project '{project_name}' already exists.")
            return

        os.makedirs(project_path)
        bot.reply_to(message, f"✅ Project '{project_name}' created successfully.")
    
    except Exception as e:
        logger.error(f"Error creating project: {e}")
        bot.reply_to(message, f"❌ Failed to create project: {e}")

# --- Reception Module: Task Enqueuing ---
@bot.message_handler(func=lambda message: not message.text.startswith('/'))
def handle_task(message):
    chat_id = message.chat.id
    current_dir = user_project_state.get(chat_id, BASE_DIR)

    task_queue.put({
        'chat_id': chat_id,
        'text': message.text,
        'cwd': current_dir
    })

    bot.reply_to(message, f"📝 Task queued (Current Dir: {os.path.basename(current_dir)})\n{task_queue.qsize() - 1} tasks ahead.")

# --- Execution Module: Background Consumption & Gemini Call ---
def process_task(task):
    """Process a single task from the queue."""
    chat_id = task['chat_id']
    task_text = task['text']
    work_dir = task['cwd']

    try:
        bot.send_message(chat_id, f"⚙️ Executing...\nDirectory: {os.path.basename(work_dir)}")

        # Call gemini, strictly restricted to work_dir for safety
        try:
            result = subprocess.run(
                ['gemini', '--yolo', '--prompt', task_text],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=600
            )

            reply = f"✅ Task Completed\n\n[Output]:\n{result.stdout}"
            if result.stderr:
                reply += f"\n\n[Error/Warning]:\n{result.stderr}"

        except FileNotFoundError:
             reply = "❌ Execution Failed: 'gemini' not found. Please ensure it is installed and in PATH."
        except subprocess.TimeoutExpired:
             reply = "❌ Execution Failed: Task timed out after 600 seconds."
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

def worker():
    while True:
        task = task_queue.get()
        try:
            process_task(task)
        finally:
            task_queue.task_done()

if __name__ == '__main__':
    if bot:
        threading.Thread(target=worker, daemon=True).start()
        logger.info("🤖 Bot Daemon Started...")
        bot.infinity_polling()
    else:
        logger.error("Bot could not start due to configuration errors.")
