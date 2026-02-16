import unittest
from unittest.mock import MagicMock, patch, mock_open
import os
import sys
import queue

# Set environment variable for testing before importing bot
os.environ['TELEGRAM_BOT_TOKEN'] = 'TEST_TOKEN'
os.environ['WORKSPACE_DIR'] = '/tmp/test_workspace'

# Mock telebot before importing bot.py to avoid network calls
mock_telebot = MagicMock()
mock_telebot.types = MagicMock()

# Configure TeleBot mock to return identity decorators
def identity_decorator(*args, **kwargs):
    def wrapper(func):
        return func
    return wrapper

mock_telebot.TeleBot.return_value.message_handler.side_effect = identity_decorator
mock_telebot.TeleBot.return_value.callback_query_handler.side_effect = identity_decorator

sys.modules['telebot'] = mock_telebot
sys.modules['telebot.types'] = mock_telebot.types

import bot

class TestGeminiBot(unittest.TestCase):

    def setUp(self):
        # Reset the bot mock and other states
        bot.bot = MagicMock()
        bot.task_queue = queue.Queue()
        bot.user_project_state = {}
        bot.BASE_DIR = '/tmp/test_workspace'

    @patch('os.listdir')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_get_project_dirs(self, mock_isdir, mock_exists, mock_listdir):
        mock_exists.return_value = True
        mock_listdir.return_value = ['project1', 'file.txt', 'project2']
        # mock isdir: project1 -> True, file.txt -> False, project2 -> True
        def side_effect(path):
            if path.endswith('project1') or path.endswith('project2'):
                return True
            return False
        mock_isdir.side_effect = side_effect

        dirs = bot.get_project_dirs()
        self.assertEqual(dirs, ['project1', 'project2'])

    @patch('os.listdir')
    @patch('os.path.exists')
    def test_list_projects_empty(self, mock_exists, mock_listdir):
        mock_exists.return_value = True
        mock_listdir.return_value = [] # Empty directory

        message = MagicMock()
        bot.list_projects(message)

        # Verify bot reply
        bot.bot.reply_to.assert_called_with(message, "Workspace is empty. Please create project folders in the mounted host directory.")

    @patch('os.listdir')
    @patch('os.path.exists')
    @patch('os.path.isdir')
    def test_list_projects_with_dirs(self, mock_isdir, mock_exists, mock_listdir):
        mock_exists.return_value = True
        mock_listdir.return_value = ['project1']
        mock_isdir.return_value = True

        message = MagicMock()
        bot.list_projects(message)

        # Verify bot sends message with markup
        bot.bot.send_message.assert_called()
        args, kwargs = bot.bot.send_message.call_args
        self.assertIn("Select a project directory", args[1])
        self.assertIn("reply_markup", kwargs)

    def test_handle_project_selection(self):
        call = MagicMock()
        call.data = "proj_project1"
        call.message.chat.id = 123

        bot.handle_project_selection(call)

        self.assertEqual(bot.user_project_state[123], os.path.join(bot.BASE_DIR, 'project1'))
        bot.bot.answer_callback_query.assert_called_with(call.id, "Switched successfully")
        bot.bot.edit_message_text.assert_called()

    def test_handle_task(self):
        message = MagicMock()
        message.chat.id = 123
        message.text = "Do something"

        bot.handle_task(message)

        # Check if task is in queue
        self.assertEqual(bot.task_queue.qsize(), 1)
        task = bot.task_queue.get()
        self.assertEqual(task['chat_id'], 123)
        self.assertEqual(task['text'], "Do something")
        self.assertEqual(task['cwd'], bot.BASE_DIR) # Default dir

    @patch('subprocess.run')
    @patch('os.path.exists') # For context file check
    def test_process_task(self, mock_exists, mock_subprocess):
        # Setup task
        task = {
            'chat_id': 123,
            'text': 'Run this',
            'cwd': '/tmp/test_workspace/project1'
        }

        mock_exists.return_value = False # No context file
        mock_subprocess.return_value = MagicMock(stdout="Output", stderr="")

        bot.process_task(task)

        # Verify gemini-cli call
        mock_subprocess.assert_called_with(
            ['gemini-cli', '--prompt', 'Run this'],
            cwd='/tmp/test_workspace/project1',
            capture_output=True,
            text=True,
            timeout=600
        )

        # Verify bot reply
        bot.bot.send_message.assert_called()
        args, kwargs = bot.bot.send_message.call_args_list[-1]
        self.assertIn("Task Completed", args[1])
        self.assertIn("Output", args[1])

    @patch('subprocess.run')
    @patch('os.path.exists')
    def test_process_task_with_context(self, mock_exists, mock_subprocess):
        task = {
            'chat_id': 123,
            'text': 'Run this',
            'cwd': '/tmp/test_workspace/project1'
        }

        # Mock context file exists
        mock_exists.return_value = True

        # Mock file open
        with patch('builtins.open', mock_open(read_data="Context data")) as mock_file:
            mock_subprocess.return_value = MagicMock(stdout="Output", stderr="")

            bot.process_task(task)

            # Verify prompt contains context
            mock_subprocess.assert_called()
            call_args = mock_subprocess.call_args
            # call_args[0] is positional args. First arg is the list.
            cmd_list = call_args[0][0]
            self.assertEqual(cmd_list[0], 'gemini-cli')
            self.assertEqual(cmd_list[1], '--prompt')
            self.assertIn("[System Context]", cmd_list[2])
            self.assertIn("Context data", cmd_list[2])
            self.assertIn("Run this", cmd_list[2])

    def test_handle_project_selection(self):
        call = MagicMock()
        call.data = "proj_project1"
        call.message.chat.id = 123

        bot.handle_project_selection(call)

        self.assertEqual(bot.user_project_state[123], os.path.join(bot.BASE_DIR, 'project1'))
        bot.bot.answer_callback_query.assert_called_with(call.id, "Switched successfully")
        bot.bot.edit_message_text.assert_called()

    def test_handle_task(self):
        message = MagicMock()
        message.chat.id = 123
        message.text = "Do something"

        bot.handle_task(message)

        # Check if task is in queue
        self.assertEqual(bot.task_queue.qsize(), 1)
        task = bot.task_queue.get()
        self.assertEqual(task['chat_id'], 123)
        self.assertEqual(task['text'], "Do something")
        self.assertEqual(task['cwd'], bot.BASE_DIR) # Default dir

if __name__ == '__main__':
    unittest.main()
