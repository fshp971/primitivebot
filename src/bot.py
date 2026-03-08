import os
import yaml
import logging
import argparse
import asyncio
from dotenv import load_dotenv
from primitivebot.ai.cli import AICLITool, AICLIToolParams
from primitivebot.bot.telegram import TelegramBot, TelegramBotParams

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def main():
    parser = argparse.ArgumentParser(description="PrimitiveBot Telegram Bot")
    parser.add_argument("--config", type=str, default=os.environ.get("BOT_CONFIG", "src/config.yaml"), help="Path to config file")
    args = parser.parse_args()

    # Load configuration
    config = {}
    if os.path.exists(args.config):
        try:
            with open(args.config, 'r') as f:
                config = yaml.safe_load(f) or {}
                logger.info(f"Loaded configuration from {args.config}")
        except Exception as e:
            logger.error(f"Error loading {args.config}: {e}")
    else:
        logger.info(f"No configuration file found at {args.config}. Using defaults.")

    # Parameters from config/env
    WORKSPACE_DIR = os.environ.get('WORKSPACE_DIR', '/workspace')
    TASK_TIMEOUT = config.get('task_timeout_second', 600)
    STATUS_DESC_LENGTH = config.get('status_desc_length', 30)
    MODEL_VERSION = config.get('model_version', "auto")
    WHITELIST = config.get('whitelist', [])
    TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')

    if not TOKEN:
        logger.error("TELEGRAM_BOT_TOKEN not set. Exiting.")
        return

    # Initialize AI tool
    # Agnostic command construction
    ai_command = ['gemini', '--yolo', '-m', MODEL_VERSION, '--prompt', '-']
    ai_params = AICLIToolParams(
        command=ai_command,
        timeout=TASK_TIMEOUT,
        model_version=MODEL_VERSION
    )
    ai_tool = AICLITool(ai_params)

    # Initialize Bot
    bot_params = TelegramBotParams(
        token=TOKEN,
        workspace_dir=WORKSPACE_DIR,
        task_timeout_second=TASK_TIMEOUT,
        status_desc_length=STATUS_DESC_LENGTH,
        whitelist=WHITELIST
    )
    telegram_bot = TelegramBot(bot_params, ai_tool)

    # Start Bot
    await telegram_bot.start()

if __name__ == '__main__':
    asyncio.run(main())
