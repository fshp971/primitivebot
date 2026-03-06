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

import unittest
from unittest.mock import AsyncMock, MagicMock, patch, mock_open
import os
import sys
import asyncio
import time

# Mock telebot before importing to avoid network calls
mock_telebot = MagicMock()
mock_telebot.async_telebot = MagicMock()
mock_telebot.types = MagicMock()

sys.modules['telebot'] = mock_telebot
sys.modules['telebot.async_telebot'] = mock_telebot.async_telebot
sys.modules['telebot.types'] = mock_telebot.types

# Add src to path for bot import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
from primitivebot.bot.telegram import TelegramBot, TelegramBotParams
from primitivebot.ai.cli import AICLITool, AICLIToolParams

class TestTelegramBot(unittest.IsolatedAsyncioTestCase):

    async def asyncSetUp(self):
        # Reset the bot params
        self.params = TelegramBotParams(
            token='TEST_TOKEN',
            workspace_dir='/tmp/test_workspace',
            task_timeout_second=600,
            status_desc_length=30
        )

        self.ai_params = AICLIToolParams(
            command=['gemini', '--yolo', '--prompt', '-'],
            timeout=600,
            model_version='auto'
        )

        self.ai_tool = MagicMock(spec=AICLITool)
        self.ai_tool.call = AsyncMock()

        # Mock AsyncTeleBot
        self.mock_async_bot = MagicMock()
        self.mock_async_bot.reply_to = AsyncMock()
        self.mock_async_bot.send_message = AsyncMock()
        self.mock_async_bot.answer_callback_query = AsyncMock()
        self.mock_async_bot.edit_message_text = AsyncMock()

        # Configure decorators to return identity
        def identity_decorator(*args, **kwargs):
            def wrapper(func):
                return func
            return wrapper
        self.mock_async_bot.message_handler.side_effect = identity_decorator
        self.mock_async_bot.callback_query_handler.side_effect = identity_decorator

        mock_telebot.async_telebot.AsyncTeleBot.return_value = self.mock_async_bot

        self.telegram_bot = TelegramBot(self.params, self.ai_tool)
        self.telegram_bot.bot = self.mock_async_bot

    @patch('os.listdir')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    async def test_get_project_dirs(self, mock_isdir, mock_exists, mock_listdir):
        mock_exists.return_value = True
        mock_listdir.return_value = ['project1', 'file.txt', 'project2']
        # mock isdir: project1 -> True, file.txt -> False, project2 -> True
        def side_effect(path):
            if path.endswith('project1') or path.endswith('project2'):
                return True
            return False
        mock_isdir.side_effect = side_effect

        dirs = self.telegram_bot.get_project_dirs()
        self.assertEqual(dirs, ['project1', 'project2'])

    @patch('os.listdir')
    @patch('os.path.exists')
    async def test_list_projects_empty(self, mock_exists, mock_listdir):
        mock_exists.return_value = True
        mock_listdir.return_value = [] # Empty directory

        message = MagicMock()
        await self.telegram_bot.list_projects(message)

        # Verify bot reply
        self.mock_async_bot.reply_to.assert_called_with(message, "Workspace is empty. Please create project folders in the mounted host directory.")

    @patch('os.listdir')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    async def test_list_projects_with_dirs(self, mock_isdir, mock_exists, mock_listdir):
        mock_exists.return_value = True
        mock_listdir.return_value = ['project1']
        mock_isdir.return_value = True

        message = MagicMock()
        await self.telegram_bot.list_projects(message)

        # Verify bot sends message with markup
        self.mock_async_bot.send_message.assert_called()
        args, kwargs = self.mock_async_bot.send_message.call_args
        self.assertIn("Select a project directory", args[1])
        self.assertIn("reply_markup", kwargs)

    async def test_handle_project_selection(self):
        call = MagicMock()
        call.data = "proj_project1"
        call.message.chat.id = 123
        call.message.message_id = 456

        await self.telegram_bot.handle_project_selection(call)

        self.assertEqual(self.telegram_bot.user_project_state[123], os.path.join(self.params.workspace_dir, 'project1'))
        self.mock_async_bot.answer_callback_query.assert_called_with(call.id, "Switched successfully")
        self.mock_async_bot.edit_message_text.assert_called()

    @patch.object(TelegramBot, 'ensure_worker_running', new_callable=AsyncMock)
    async def test_handle_task(self, mock_ensure_worker):
        message = MagicMock()
        message.chat.id = 123
        message.text = "Do something"

        await self.telegram_bot.handle_task(message)

        # Check if task is in the correct queue
        cwd = self.params.workspace_dir
        self.assertIn(cwd, self.telegram_bot.project_queues)
        q = self.telegram_bot.project_queues[cwd]
        self.assertEqual(q.qsize(), 1)

        task = await q.get()
        self.assertEqual(task['chat_id'], 123)
        self.assertEqual(task['text'], "Do something")
        self.assertEqual(task['cwd'], cwd) # Default dir
        self.assertIn('id', task)

        mock_ensure_worker.assert_called_with(cwd)

    @patch('os.path.exists')
    @patch('os.path.isfile')
    async def test_process_task(self, mock_isfile, mock_exists):
        # Setup task
        task = {
            'id': 1,
            'chat_id': 123,
            'text': 'Run this',
            'cwd': '/tmp/test_workspace/project1'
        }

        # No AGENT.md
        mock_exists.return_value = False 
        mock_isfile.return_value = False

        self.ai_tool.call.return_value = ("Output", "", 0)

        await self.telegram_bot.process_task(task)

        # Verify gemini-cli call
        self.ai_tool.call.assert_called_with('Run this', '/tmp/test_workspace/project1')

        # Verify bot reply
        self.mock_async_bot.send_message.assert_called()
        # Find the last send_message call that contains Task Completed
        found = False
        for call in self.mock_async_bot.send_message.call_args_list:
            if "Task Completed" in call.args[1]:
                self.assertIn("Output", call.args[1])
                found = True
                break
        self.assertTrue(found)

    @patch('os.path.exists')
    @patch('os.path.isfile')
    @patch('builtins.open', new_callable=mock_open, read_data="Use strict mode.")
    async def test_process_task_with_agent_md(self, mock_file, mock_isfile, mock_exists):
        # Setup task
        task = {
            'id': 2,
            'chat_id': 123,
            'text': 'Fix bug',
            'cwd': '/tmp/test_workspace/project1'
        }

        # Mock AGENT.md exists
        def exists_side_effect(path):
            if path.endswith('AGENT.md'):
                return True
            return False

        mock_exists.side_effect = exists_side_effect
        mock_isfile.side_effect = exists_side_effect

        self.ai_tool.call.return_value = ("Output", "", 0)

        await self.telegram_bot.process_task(task)

        # Expected combined prompt
        expected_prompt = "--- Agent Rules ---\nUse strict mode.\n--- End Rules ---\n\nFix bug"

        # Verify gemini-cli call with prepended rules
        self.ai_tool.call.assert_called_with(expected_prompt, '/tmp/test_workspace/project1')

    @patch('os.makedirs')
    @patch('os.path.exists')
    async def test_create_project_success(self, mock_exists, mock_makedirs):
        mock_exists.return_value = False
        message = MagicMock()
        message.text = "/create new_project"

        await self.telegram_bot.create_project(message)

        expected_path = os.path.join(self.params.workspace_dir, 'new_project')
        mock_makedirs.assert_called_with(expected_path)
        self.mock_async_bot.reply_to.assert_called()
        args, _ = self.mock_async_bot.reply_to.call_args
        self.assertIn("created successfully", args[1])

    async def test_show_status_empty(self):
        message = MagicMock()
        await self.telegram_bot.show_status(message)
        self.mock_async_bot.reply_to.assert_called_with(message, "📭 No tasks running or queued.")

    async def test_show_status_active(self):
        # Mock a running task
        self.telegram_bot.running_tasks[1] = {
            'task': {'id': 1, 'text': 'Running Task', 'cwd': '/tmp/test_workspace/project1'},
            'start_time': time.time()
        }

        # Mock a queued task
        cwd2 = '/tmp/test_workspace/project2'
        self.telegram_bot.project_queues[cwd2] = asyncio.Queue()
        await self.telegram_bot.project_queues[cwd2].put({'id': 2, 'text': 'Queued Task', 'cwd': cwd2})

        message = MagicMock()
        await self.telegram_bot.show_status(message)

        self.mock_async_bot.send_message.assert_called()
        args, kwargs = self.mock_async_bot.send_message.call_args
        self.assertIn("Running Tasks", args[1])
        self.assertIn("Queued Tasks", args[1])
        self.assertIn("[1]", args[1])
        # Queue items are not directly listed in show_status anymore (just size)
        self.assertIn("Queue size: 1", args[1])
        self.assertIn("project1", args[1])
        self.assertIn("project2", args[1])

    async def test_ensure_worker_running(self):
        with patch('asyncio.create_task') as mock_create_task:
            await self.telegram_bot.ensure_worker_running('p1')
            mock_create_task.assert_called()
            self.assertIn('p1', self.telegram_bot.active_workers)

if __name__ == '__main__':
    unittest.main()
