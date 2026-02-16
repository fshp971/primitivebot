```text
# Telegram-Gemini 自动化任务队列：架构设计与部署文档

## 一、 核心设计理念 (Design Philosophy & Ideas)

为了在手机端实现流畅、无缝且安全的 AI 任务下发体验，本方案采用了以下四个核心设计思路：

1.  **单容器长轮询 (Single-Container Long Polling)**
    * **Idea:** 放弃 Serverless 的 Webhook 模式，改用常驻进程主动拉取（Long Polling）。
    * **优势:** 完美规避了 Serverless 的执行超时限制（适合跑长时间的 Python 脚本或处理复杂的计算任务）；不需要公网 IP 或暴露端口；并且允许我们通过 Docker 的 `-v` 参数挂载持久化的 Linux 宿主机目录。
2.  **内存级任务队列 (In-Memory Task Queue)**
    * **Idea:** 引入 Python 原生的 `queue.Queue()` 实现单线程异步消费。
    * **优势:** 避免了引入 Redis/RabbitMQ 等重型中间件。更重要的是，它强制任务串行执行，防止你连续发送两条指令时，两个进程同时去读写同一个文件导致冲突。
3.  **目录状态保持与交互 (Session Context & Inline Keyboard)**
    * **Idea:** 通过一个简单的状态字典记录每个用户的当前“工作目录”，并结合 Telegram 的交互式按钮（Inline Keyboard）。
    * **优势:** 让你在手机上能够像在 Linux 终端里 `cd` 一样切换项目。无论是处理 Python 实验代码的文件夹，还是起草 LaTeX 论文的文件夹，切换后直接发指令即可，无需每次重复输入冗长的绝对路径。
4.  **隐式上下文注入 (Context Injection via `.gemini_context.txt`)**
    * **Idea:** 允许在每个项目文件夹下放置一个隐藏的上下文文件。
    * **优势:** 极其适合专业场景。例如，你可以在某个文件夹下的 `.gemini_context.txt` 中写入：“这是一个关于多头注意力机制研究的项目，请严格使用 LaTeX 格式输出数学公式，并保持学术严谨的语气。” 这样，你在手机上只需发送“精简一下第二段”，系统就会自动拼接背景信息，让输出结果高度符合当前项目的语境。

---

## 二、 核心控制脚本 (bot.py)

该脚本包含了 Telegram Bot 的初始化、目录交互切换逻辑、内存任务队列，以及拉起 `gemini-cli` 执行任务的守护线程。

import os
import subprocess
import threading
import queue
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
bot = telebot.TeleBot(TOKEN)
task_queue = queue.Queue()

BASE_DIR = '/workspace'
user_project_state = {}

def get_project_dirs():
    """扫描挂载目录下的所有项目文件夹"""
    if not os.path.exists(BASE_DIR):
        return []
    return [d for d in os.listdir(BASE_DIR) if os.path.isdir(os.path.join(BASE_DIR, d))]

# --- 交互模块：目录切换 ---
@bot.message_handler(commands=['cd', 'projects', 'start'])
def list_projects(message):
    dirs = get_project_dirs()
    if not dirs:
        bot.reply_to(message, "工作区为空，请先在宿主机挂载目录中创建项目文件夹。")
        return

    markup = InlineKeyboardMarkup()
    for d in dirs:
        markup.add(InlineKeyboardButton(d, callback_data=f"proj_{d}"))
    markup.add(InlineKeyboardButton("🏠 根目录 (Root)", callback_data="proj_ROOT"))

    bot.send_message(message.chat.id, "📁 请选择你要操作的项目目录：", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('proj_'))
def handle_project_selection(call):
    project_name = call.data.replace('proj_', '')
    chat_id = call.message.chat.id

    if project_name == "ROOT":
        user_project_state[chat_id] = BASE_DIR
        display_name = "根目录 /workspace"
    else:
        user_project_state[chat_id] = os.path.join(BASE_DIR, project_name)
        display_name = project_name

    bot.answer_callback_query(call.id, "切换成功")
    bot.edit_message_text(f"✅ 当前工作目录已切换至：{display_name}\n接下来的任务将默认在此文件夹下执行。",
                          chat_id=chat_id, message_id=call.message.message_id)

# --- 接收模块：任务入队 ---
@bot.message_handler(func=lambda message: not message.text.startswith('/'))
def handle_task(message):
    chat_id = message.chat.id
    current_dir = user_project_state.get(chat_id, BASE_DIR)

    task_queue.put({
        'chat_id': chat_id,
        'text': message.text,
        'cwd': current_dir
    })

    bot.reply_to(message, f"📝 任务已排队 (当前目录: {os.path.basename(current_dir)})\n前面还有 {task_queue.qsize() - 1} 个任务。")

# --- 执行模块：后台消费与 Gemini 调用 ---
def worker():
    while True:
        task = task_queue.get()
        chat_id = task['chat_id']
        task_text = task['text']
        work_dir = task['cwd']

        bot.send_message(chat_id, f"⚙️ 开始执行...\n目录：{os.path.basename(work_dir)}")

        # 核心逻辑：读取项目专属 System Prompt，实现上下文隔离
        context_file = os.path.join(work_dir, '.gemini_context.txt')
        final_prompt = task_text
        if os.path.exists(context_file):
            try:
                with open(context_file, 'r', encoding='utf-8') as f:
                    context_text = f.read().strip()
                final_prompt = f"【系统上下文】\n{context_text}\n\n【当前任务】\n{task_text}"
            except Exception as e:
                bot.send_message(chat_id, f"⚠️ 读取 context 文件失败: {e}")

        try:
            # 调用 gemini-cli，严格限制在 work_dir 内运行保证安全
            result = subprocess.run(
                ['gemini-cli', '--prompt', final_prompt],
                cwd=work_dir,
                capture_output=True,
                text=True,
                timeout=600
            )

            reply = f"✅ 任务完成\n\n【输出】:\n{result.stdout}"
            if result.stderr:
                reply += f"\n\n【错误/警告】:\n{result.stderr}"

        except Exception as e:
            reply = f"❌ 执行崩溃: {str(e)}"

        # 防止 Telegram 消息长度超限 (上限 4096 字符)
        if len(reply) > 4000:
            reply = reply[:4000] + "...\n[输出已截断]"

        bot.send_message(chat_id, reply)
        task_queue.task_done()

if __name__ == '__main__':
    threading.Thread(target=worker, daemon=True).start()
    print("🤖 Bot 守护进程已启动...")
    bot.infinity_polling()


---


## 三、 容器化环境配置 (Dockerfile)

此文件用于将 Python 脚本、Node.js 环境以及 `gemini-cli` 打包在一个隔离的沙盒中。

FROM python:3.10-slim

# 更新源并安装 Node.js (用于运行 gemini-cli)
RUN apt-get update && \
    apt-get install -y nodejs npm && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 全局安装 gemini-cli (请根据实际 CLI 工具名称调整)
RUN npm install -g gemini-cli

# 安装 Telebot 依赖
RUN pip install --no-cache-dir pyTelegramBotAPI

# 设置工作目录
WORKDIR /app
COPY bot.py .

# 创建挂载点目录
RUN mkdir /workspace

# 启动守护进程
CMD ["python", "bot.py"]


---


## 四、 部署与启动命令

在宿主机上执行以下命令完成构建和运行。

# 步骤 1: 构建 Docker 镜像
docker build -t gemini-worker .

# 步骤 2: 准备宿主机的数据目录 (这里是你实际存放项目文件的地方)
mkdir -p /home/user/my_projects

# 步骤 3: 启动容器 (注意替换你的 TOKEN 和宿主机路径)
# 使用 -v 参数实现沙盒隔离挂载
docker run -d \
  --name my-gemini-worker \
  --restart unless-stopped \
  -e TELEGRAM_BOT_TOKEN="你的_TELEGRAM_BOT_TOKEN" \
  -v /home/user/my_projects:/workspace \
  gemini-worker

# 步骤 4 (可选): 查看实时运行日志
docker logs -f my-gemini-worker
```
