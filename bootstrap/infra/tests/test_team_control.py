from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import team_control


class TeamCommandTests(unittest.TestCase):
    def test_status_command_with_bot_mention(self):
        with patch.object(team_control,'status',return_value='fenced'):
            self.assertEqual(team_control.handle_command('/kanban@techlead_truco_poc_bot team-status',SimpleNamespace()),'fenced')

    def test_existing_commands_are_not_intercepted(self):
        self.assertIsNone(team_control.handle_command('/kanban list',SimpleNamespace()))

    def test_decision_preserves_verified_source(self):
        source=SimpleNamespace(user_id='ceo',chat_id='group',is_bot=False)
        with patch.object(team_control,'answer',return_value='ok') as action:
            self.assertEqual(team_control.handle_command('/kanban@techlead_truco_poc_bot decision q_scope somente web',source),'ok')
            action.assert_called_once_with('q_scope','somente web','ceo','group',False)

    def test_bot_cannot_answer_as_ceo(self):
        with patch.object(team_control,'execution',return_value=dict(ceo_telegram_id='ceo',telegram_chat_id='group')):
            with self.assertRaises(PermissionError):
                team_control.answer('q1','yes','ceo','group',is_bot=True)

    def test_wrong_user_or_group_cannot_answer(self):
        with patch.object(team_control,'execution',return_value=dict(ceo_telegram_id='ceo',telegram_chat_id='group')):
            with self.assertRaises(PermissionError):
                team_control.answer('q1','yes','other','group')
            with self.assertRaises(PermissionError):
                team_control.answer('q1','yes','ceo','other')
