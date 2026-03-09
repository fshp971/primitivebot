import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import os
import sys
import asyncio
import zipfile
import shutil
import io

# Mock telegram
mock_telegram = MagicMock()
mock_telegram_ext = MagicMock()
mock_telegram_constants = MagicMock()

sys.modules['telegram'] = mock_telegram
sys.modules['telegram.ext'] = mock_telegram_ext
sys.modules['telegram.constants'] = mock_telegram_constants

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from primitivebot.bot.telegram import TelegramBot, TelegramBotParams
from primitivebot.ai.cli import AICLITool, AICLIToolParams
from primitivebot.bot.paper_loop import PaperWritingLoop

class TestPaperWritingLoop(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        self.params = TelegramBotParams(
            token='TEST_TOKEN',
            workspace_dir='/tmp/test_workspace',
            task_timeout_second=600,
            status_desc_length=30
        )

        self.ai_tool = MagicMock(spec=AICLITool)
        self.ai_tool.call = AsyncMock()

        self.mock_app = MagicMock()
        self.mock_app.bot = AsyncMock()
        self.mock_app.bot.send_message = AsyncMock()
        self.mock_app.bot.send_document = AsyncMock()

        mock_builder = MagicMock()
        mock_builder.token.return_value = mock_builder
        mock_builder.build.return_value = self.mock_app
        mock_telegram_ext.ApplicationBuilder.return_value = mock_builder

        self.telegram_bot = TelegramBot(self.params, self.ai_tool)
        self.telegram_bot.application = self.mock_app

        # Ensure workspace exists
        if not os.path.exists(self.params.workspace_dir):
            os.makedirs(self.params.workspace_dir)

    async def asyncTearDown(self):
        if os.path.exists(self.params.workspace_dir):
            shutil.rmtree(self.params.workspace_dir)

    @patch('os.makedirs')
    @patch('shutil.rmtree')
    @patch('zipfile.ZipFile')
    @patch('os.path.exists')
    @patch('builtins.open', new_callable=mock_open, read_data="Goal content")
    @patch('os.listdir')
    @patch('shutil.copy2')
    @patch('shutil.copytree')
    async def test_paper_loop_run(self, mock_copytree, mock_copy2, mock_listdir, mock_file, mock_exists, mock_zip, mock_rmtree, mock_makedirs):
        # Mock file system and external calls
        mock_exists.return_value = True
        mock_listdir.return_value = ['writing_goal.md', 'reviewing_goal.md', 'paper.pdf', 'review.md']

        # We need to mock the context manager for ZipFile
        mock_zip_instance = MagicMock()
        mock_zip.return_value.__enter__.return_value = mock_zip_instance

        # AI tool returns success
        self.ai_tool.call.return_value = ("Output", "", 0)

        status_callback = AsyncMock()

        paper_loop = PaperWritingLoop(self.ai_tool, self.params.workspace_dir)

        # Create a dummy zip file path
        zip_path = os.path.join(self.params.workspace_dir, 'input.zip')

        # Run 1 round
        final_zip = await paper_loop.run("task1", zip_path, 1, status_callback)

        self.assertIn("task1_final.zip", final_zip)
        self.assertEqual(self.ai_tool.call.call_count, 2) # 1 Writer + 1 Reviewer
        status_callback.assert_called()

    async def test_handle_document_zip(self):
        update = MagicMock()
        update.effective_chat.id = 123
        update.message = AsyncMock()
        update.message.document.file_name = "test.zip"
        update.message.document.file_id = "file123"

        context = MagicMock()
        context.bot.get_file = AsyncMock()

        mock_file = AsyncMock()
        context.bot.get_file.return_value = mock_file

        await self.telegram_bot.handle_document(update, context)

        mock_file.download_to_drive.assert_called()
        self.assertIn(123, self.telegram_bot.last_zip_paths)
        update.message.reply_text.assert_called()
        self.assertIn("Zip file received", update.message.reply_text.call_args[0][0])

    async def test_write_paper_command(self):
        self.telegram_bot.last_zip_paths[123] = "/tmp/test_workspace/input.zip"

        # Mock file exists
        with patch('os.path.exists', return_value=True):
            update = MagicMock()
            update.effective_chat.id = 123
            update.message = AsyncMock()
            context = MagicMock()
            context.args = ["2"]

            with patch('asyncio.create_task') as mock_create_task:
                await self.telegram_bot.write_paper(update, context)

                mock_create_task.assert_called()
                update.message.reply_text.assert_called()
                self.assertIn("Started Paper Writing Loop", update.message.reply_text.call_args[0][0])

if __name__ == '__main__':
    unittest.main()
