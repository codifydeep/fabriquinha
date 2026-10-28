import contextvars
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.channel import command,session_identity,execute,format_pending

class Channel(unittest.TestCase):
    def setUp(self):
        self.policy=dict(version=1,chat_id='-123',user_ids=['456'],thread_id=None)
        self.identity=dict(platform='telegram',chat_id='-123',chat_type='group',thread_id='',user_id='456',message_id='10')
    def test_wrong_sender_destination_thread_and_platform_refused(self):
        for change in ({'user_id':'999'},{'chat_id':'-999'},{'thread_id':'2'},{'platform':'cli'},{'chat_type':'private'}):
            with self.subTest(change=change),self.assertRaises(ValueError):command('status',self.policy,{**self.identity,**change})
    def test_start_replay_identity_is_stable_and_objective_not_executed(self):
        raw='start v1 $(touch /tmp/should-not-execute)'
        first=command(raw,self.policy,self.identity)
        self.assertEqual(first,command(raw,self.policy,self.identity))
        self.assertIn('$(touch',first['value']['objective'])
        self.assertNotEqual(first['value']['request'],command(raw,self.policy,{**self.identity,'message_id':'11'})['value']['request'])
    def test_approval_binds_exact_request_without_implicit_yes(self):
        for raw in ('yes','approve t_12345678','approve t_12345678 deadbeef yes','merge t_12345678'):
            with self.subTest(raw=raw),self.assertRaises(ValueError):command(raw,self.policy,self.identity)
        value=command('approve t_12345678 '+'a'*64+' Approved scope',self.policy,self.identity)
        runtime=Mock();execute(runtime,value)
        runtime.control.ensure.assert_called_once()
        runtime.intake.respond.assert_called_once_with('t_12345678','a'*64,'approve','Approved scope')
    def test_no_environment_fallback_or_cross_request_identity(self):
        with patch.dict(os.environ,{'HERMES_SESSION_USER_ID':'456'}):
            self.assertEqual(contextvars.Context().run(session_identity)['user_id'],'')
        var=contextvars.ContextVar('HERMES_SESSION_USER_ID');token=var.set('456')
        try:self.assertEqual(session_identity()['user_id'],'456')
        finally:var.reset(token)
    def test_gateway_handler_refuses_without_model_fallthrough(self):
        from fabriquinha.channel_plugin import handle
        with patch.dict(os.environ,{},clear=True),patch('subprocess.run') as process:
            self.assertIn('refused',handle('approve anything'))
            process.assert_not_called()

    def test_gateway_uses_fixed_child_and_does_not_forward_credentials(self):
        from fabriquinha.channel_plugin import handle
        config=dict(source='/verified',digest='a'*64,python='/sdk/python',root='/installation',upstream='/hermes',policy='/policy')
        with patch.dict(os.environ,{'FABRIQUINHA_CHANNEL_CONFIG':'/config','OPENROUTER_API_KEY':'not-forwarded'}), \
             patch('fabriquinha.channel_plugin.private_json',side_effect=[config,self.policy]), \
             patch('fabriquinha.channel_plugin.session_identity',return_value=self.identity), \
             patch('fabriquinha.channel_plugin.verify'), \
             patch('fabriquinha.channel_plugin.subprocess.run',return_value=Mock(returncode=0,stdout='{"paused":false}')) as process:
            self.assertEqual(handle('status'),'{"paused":false}')
            args=process.call_args
            self.assertEqual(args.args[0][:4],['/sdk/python','-B','-m','fabriquinha.channel'])
            self.assertNotIn('shell',args.kwargs)
            self.assertNotIn('OPENROUTER_API_KEY',args.kwargs['env'])

    def test_paused_control_prevents_mutation(self):
        runtime=Mock();runtime.control.ensure.side_effect=ValueError('paused')
        with self.assertRaises(ValueError):execute(runtime,command('start v1 objective',self.policy,self.identity))
        runtime.intake.start.assert_not_called()

if __name__=='__main__':unittest.main()

class PendingInstructions(unittest.TestCase):
    def test_question_and_brief_offer_only_their_scoped_decisions(self):
        value=dict(task='t_12345678',request='a'*64,audience='ceo',scope='product',document={'summary':'Keep existing tests'})
        question=format_pending({**value,'kind':'product_question'})
        self.assertIn('/fabrica answer t_12345678 '+'a'*64+' YOUR_RESPONSE',question)
        self.assertNotIn('/fabrica approve',question)
        brief=format_pending({**value,'kind':'product_brief'})
        self.assertIn('/fabrica approve',brief);self.assertIn('/fabrica changes',brief)
        self.assertNotIn('/fabrica answer',brief)
        self.assertIn('Keep existing tests',brief)
        with self.assertRaises(ValueError):format_pending({**value,'kind':'product_brief','scope':'technical'})
