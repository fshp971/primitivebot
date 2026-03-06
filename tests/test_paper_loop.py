import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import os
import sys
import asyncio
import zipfile
import shutil
import io

# Mock telebot
mock_telebot = MagicMock()
mock_telebot.async_telebot = MagicMock()
mock_telebot.types = MagicMock()

sys.modules['telebot'] = mock_telebot
sys.modules['telebot.async_telebot'] = mock_telebot.async_telebot
sys.modules['telebot.types'] = mock_telebot.types

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

        self.mock_async_bot = MagicMock()
        self.mock_async_bot.reply_to = AsyncMock()
        self.mock_async_bot.send_message = AsyncMock()
        self.mock_async_bot.get_file = AsyncMock()
        self.mock_async_bot.download_file = AsyncMock()
        self.mock_async_bot.send_document = AsyncMock()

        mock_telebot.async_telebot.AsyncTeleBot.return_value = self.mock_async_bot

        self.telegram_bot = TelegramBot(self.params, self.ai_tool)
        self.telegram_bot.bot = self.mock_async_bot

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
        message = MagicMock()
        message.chat.id = 123
        message.document.file_name = "test.zip"
        message.document.file_id = "file123"

        file_info = MagicMock()
        file_info.file_path = "path/to/file"
        self.mock_async_bot.get_file.return_value = file_info
        self.mock_async_bot.download_file.return_value = b"zip_content"

        await self.telegram_bot.handle_document(message)

        self.mock_async_bot.download_file.assert_called_with("path/to/file")
        self.assertIn(123, self.telegram_bot.last_zip_paths)
        self.mock_async_bot.reply_to.assert_called_with(message, unittest.mock.ANY)
        self.assertIn("Zip file received", self.mock_async_bot.reply_to.call_args[0][1])

    async def test_write_paper_command(self):
        self.telegram_bot.last_zip_paths[123] = "/tmp/test_workspace/input.zip"
        
        # Mock file exists
        with patch('os.path.exists', return_value=True):
            message = MagicMock()
            message.chat.id = 123
            message.text = "/write_paper 2"

            with patch('asyncio.create_task') as mock_create_task:
                await self.telegram_bot.write_paper(message)
                
                mock_create_task.assert_called()
                self.mock_async_bot.reply_to.assert_called_with(message, unittest.mock.ANY)
                self.assertIn("Started Paper Writing Loop", self.mock_async_bot.reply_to.call_args[0][1])

    @patch('shutil.rmtree')
    @patch('os.path.exists')
    async def test_clean_task(self, mock_exists, mock_rmtree):
        mock_exists.return_value = True
        message = MagicMock()
        message.text = "/clean task1"
        
        await self.telegram_bot.clean_task(message)
        
        mock_rmtree.assert_called()
        self.mock_async_bot.reply_to.assert_called_with(message, "✅ Cleaned task task1")

if __name__ == '__main__':
    unittest.main()
