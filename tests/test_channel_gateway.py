import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.channel_gateway import Commands

class CommandTransport(unittest.TestCase):
    def setUp(self):self.commands=Commands(dict(version=1,chat_id='-123',user_ids=['456'],thread_id=None))
    def test_native_prefilter_denies_bot_wrong_group_and_thread(self):
        self.assertTrue(self.commands.authorized('456','group','-123'))
        self.assertFalse(self.commands.authorized('456','group','-123',is_bot=True))
        self.assertFalse(self.commands.authorized('456','group','-123',thread_id='1'))
        self.assertFalse(self.commands.authorized('456','group','-999'))
        self.assertFalse(self.commands.authorized('999','group','-123'))
    def test_plain_text_and_other_commands_never_start_an_agent(self):
        source=SimpleNamespace(user_id='456',chat_id='-123',chat_type='group',thread_id=None,is_bot=False)
        for command in (None,'model','terminal','kanban','approve'):
            event=SimpleNamespace(source=source,get_command=lambda:command)
            with patch('fabriquinha.channel_gateway.handle') as handler:
                self.assertIsNone(asyncio.run(self.commands.message(event)))
                handler.assert_not_called()
    def test_unauthorized_event_never_reaches_handler(self):
        event=SimpleNamespace(source=SimpleNamespace(user_id='999',chat_id='-123',chat_type='group',thread_id=None,is_bot=False))
        with patch('fabriquinha.channel_gateway.handle') as handler:
            self.assertIsNone(asyncio.run(self.commands.message(event)))
            handler.assert_not_called()

if __name__=='__main__':unittest.main()
