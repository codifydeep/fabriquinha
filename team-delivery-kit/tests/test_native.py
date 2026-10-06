import importlib.util
import io
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('native', Path(__file__).parents[1] / 'broker/native.py')
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class NativeTests(unittest.TestCase):
    def test_planning_start_is_child_local_idempotent_and_never_an_author_grant(self):
        issue,target,source,wake=[str(uuid.uuid4()) for _ in range(4)]
        settings=dict(agents={target:'planning'},token='test',workspace_id=issue)
        marker='d'*64
        row=dict(id=wake,issue_id=issue,agent_id=target,kind='at',mode='once',event_types=[],
            instruction='DELIVERY_PLANNING_START '+marker+'\nSource: '+source+'\nPlan only')
        with patch.object(native.urllib.request,'urlopen',side_effect=[io.BytesIO(b'[]'),io.BytesIO(json.dumps(row).encode())]) as api:
            self.assertEqual(native.ensure_planning_start(settings,issue,target,source,marker,'Plan only')['id'],wake)
            self.assertNotIn('filter_task_id',json.loads(api.call_args.args[0].data))
        with patch.object(native.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps([row]).encode())) as api:
            self.assertEqual(native.ensure_planning_start(settings,issue,target,source,marker,'Plan only')['id'],wake)
            self.assertEqual(api.call_count,1)
        for mode in ('implementation','review'):
            settings['agents'][target]=mode
            with patch.object(native.urllib.request,'urlopen') as api:
                with self.assertRaises(ValueError):native.ensure_planning_start(settings,issue,target,source,marker,'Plan only')
                api.assert_not_called()

    def test_event_handoff_canonicalizes_trailing_newline_and_rejects_same_marker_drift(self):
        issue,target,source,wake=[str(uuid.uuid4()) for _ in range(4)]
        marker='e'*64;settings=dict(agents={target:'planning'},token='test',workspace_id=issue)
        row=dict(id=wake,issue_id=issue,agent_id=target,filter_task_id=source,kind='event',mode='once',
            instruction='DELIVERY_HANDOFF '+marker+'\nInspect immutable source',event_types=['task.completed','task.failed','task.cancelled'])
        with patch.object(native.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps([row]).encode())) as api:
            self.assertEqual(native.ensure_task_handoff(settings,issue,target,source,marker,'Inspect immutable source\n')['id'],wake)
            self.assertEqual(api.call_count,1)
        with patch.object(native.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps([dict(row,instruction=row['instruction']+' altered')]).encode())) as api:
            with self.assertRaisesRegex(ValueError,'identity drift'):native.ensure_task_handoff(settings,issue,target,source,marker,'Inspect immutable source\n')
            self.assertEqual(api.call_count,1)
    def test_unit_start_canonicalizes_api_trim_before_post_and_recovers_same_marker(self):
        issue,target,source,wake=[str(uuid.uuid4()) for _ in range(4)]
        marker='f'*64;settings=dict(agents={target:'implementation'},token='test',workspace_id=issue)
        note='DELIVERY_UNIT_START '+marker+'\nSource: '+source+'\nTests\nDELIVERY_DRIVER_CHECKPOINT_V3'
        row=dict(id=wake,issue_id=issue,agent_id=target,kind='at',mode='once',instruction=note,event_types=[])
        with patch.object(native.urllib.request,'urlopen',side_effect=[io.BytesIO(b'[]'),io.BytesIO(json.dumps(row).encode())]) as api:
            self.assertEqual(native.ensure_unit_start(settings,issue,target,source,marker,'Tests\nDELIVERY_DRIVER_CHECKPOINT_V3\n')['id'],wake)
            self.assertEqual(json.loads(api.call_args.args[0].data)['instruction'],note)
        with patch.object(native.urllib.request,'urlopen',return_value=io.BytesIO(json.dumps([dict(row,instruction=note+' altered')]).encode())) as api:
            with self.assertRaisesRegex(ValueError,'identity drift'):native.ensure_unit_start(settings,issue,target,source,marker,'Tests\nDELIVERY_DRIVER_CHECKPOINT_V3\n')
            self.assertEqual(api.call_count,1)

    def test_unit_start_uses_child_local_one_shot_not_parent_event(self):
        issue, target, source, wake = [str(uuid.uuid4()) for _ in range(4)]
        marker = 'a'*64
        settings = dict(agents={target:'implementation'}, token='test', workspace_id=issue)
        note = 'DELIVERY_UNIT_START '+marker+'\nSource: '+source+'\nTests only'
        created = dict(id=wake, issue_id=issue, agent_id=target, kind='at', mode='once',
                       instruction=note, event_types=[])
        with patch.object(native.urllib.request, 'urlopen', side_effect=[
                io.BytesIO(b'[]'), io.BytesIO(json.dumps(created).encode())]) as api:
            self.assertEqual(native.ensure_unit_start(settings, issue, target, source, marker, 'Tests only')['id'], wake)
            body = json.loads(api.call_args.args[0].data)
            self.assertEqual(body['kind'], 'at')
            self.assertEqual(body['mode'], 'once')
            self.assertEqual(body['after_seconds'], 1)
            self.assertNotIn('filter_task_id', body)

    def test_unit_start_recovers_consumed_wakeup_and_rejects_drift_or_duplicates(self):
        issue, target, source, wake = [str(uuid.uuid4()) for _ in range(4)]
        settings = dict(agents={target:'implementation'}, token='test', workspace_id=issue)
        row = dict(id=wake, issue_id=issue, agent_id=target, kind='at', mode='once',
                   instruction='DELIVERY_UNIT_START '+'b'*64+'\nSource: '+source+'\nTests', enabled=False)
        def call(rows):
            with patch.object(native.urllib.request, 'urlopen', return_value=io.BytesIO(json.dumps(rows).encode())) as api:
                result=native.ensure_unit_start(settings, issue, target, source, 'b'*64, 'Tests')
                self.assertEqual(api.call_count,1)
                return result
        self.assertEqual(call([row])['id'],wake)
        with self.assertRaisesRegex(ValueError,'identity drift'):call([{**row,'filter_task_id':source}])
        with self.assertRaisesRegex(ValueError,'duplicate'):call([row,row])

    def test_unit_start_no_authority_never_posts(self):
        issue, target, source = [str(uuid.uuid4()) for _ in range(3)]
        settings = dict(agents={target:'implementation'}, token='test', workspace_id=issue)
        with patch.object(native.urllib.request, 'urlopen', return_value=io.BytesIO(b'[]')) as api:
            self.assertIsNone(native.ensure_unit_start(settings,issue,target,source,'c'*64,'Tests',allow_create=False))
            self.assertEqual(api.call_count,1)
        settings['agents'][target]='review'
        with patch.object(native.urllib.request,'urlopen') as api:
            with self.assertRaises(ValueError):native.ensure_unit_start(settings,issue,target,source,'c'*64,'Tests')
            api.assert_not_called()

    def test_handoff_reconciles_consumed_exact_task_wakeup(self):
        issue, target, source, wake = [str(uuid.uuid4()) for _ in range(4)]
        marker = 'a'*64
        found = {'id': wake, 'issue_id': issue, 'agent_id': target, 'filter_task_id': source,
                 'instruction': 'DELIVERY_HANDOFF ' + marker + '\nReview',
                 'kind': 'event', 'mode': 'once', 'enabled': False,
                 'event_types': ['task.completed', 'task.failed', 'task.cancelled']}
        settings = {'agents': {target: 'review'}, 'token': 'test', 'workspace_id': issue}
        with patch.object(native.urllib.request, 'urlopen',
                          return_value=io.BytesIO(json.dumps([found]).encode())) as api:
            self.assertEqual(native.ensure_task_handoff(settings, issue, target, source, marker, 'Review')['id'], wake)
            self.assertEqual(api.call_count, 1)
            self.assertIsNone(api.call_args.args[0].data)

    def test_authoritative_identity_required(self):
        task, agent, workspace, runtime, chat = [str(uuid.uuid4()) for _ in range(5)]
        settings = dict(token='test', workspace_id=workspace, runtime_id=runtime, agents={agent: 'review'})
        valid = dict(id=task, agent_id=agent, workspace_id=workspace, runtime_id=runtime,
                     status='running', chat_session_id=chat,
                     wakeup_id=str(uuid.uuid4()), handoff_note='Reviewer requested a test.')
        def response(value):
            return io.BytesIO(json.dumps([value]).encode())
        with patch.object(native.urllib.request, 'urlopen', return_value=response(valid)):
            binding = native.task_binding(settings, task, agent)
            self.assertEqual(binding['mode'], 'review')
            self.assertIn(task, binding['scope'])
            self.assertNotIn(chat, binding['scope'])
            self.assertEqual(binding['wakeup_id'], valid['wakeup_id'])
            self.assertEqual(binding['handoff_note'], valid['handoff_note'])
        for key, value in dict(status='completed', runtime_id=str(uuid.uuid4()),
                               agent_id=str(uuid.uuid4()), workspace_id=str(uuid.uuid4())).items():
            with self.subTest(key=key), patch.object(native.urllib.request, 'urlopen', return_value=response({**valid, key: value})):
                with self.assertRaises(ValueError):
                    native.task_binding(settings, task, agent)

    def test_unenrolled_agent_is_rejected_without_network(self):
        with patch.object(native.urllib.request, 'urlopen') as network:
            with self.assertRaises(ValueError):
                native.task_binding({'agents': {}}, str(uuid.uuid4()), str(uuid.uuid4()))
            network.assert_not_called()
