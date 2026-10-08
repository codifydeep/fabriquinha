import unittest
import io
import json
from unittest.mock import patch
from broker import native
from broker.native_scope_note import canonical


class NativeScopeNoteTests(unittest.TestCase):
    def setUp(self):
        self.note='DELIVERY_PLANNING_START '+'a'*64+'\nSource: source\nDELIVERY_PRODUCT_SCOPE_V1: exact protocol'
        self.prefix='Wakeup wake-id triggered. Instruction:\n'
        self.footer='\nTrigger facts (read current state before deciding what to do):\ntime.due '
        self.fact='{"kind":"at","planned_at":"2026-10-08T23:11:26Z"}'
        self.wrapped=self.prefix+self.note+self.footer+self.fact+'\n'

    def test_known_envelope_returns_only_instruction_without_claiming_authority(self):
        self.assertEqual(canonical(self.wrapped,'wake-id'),self.note)
        self.assertEqual(canonical(self.note,'wake-id'),self.note)

    def test_wrong_wakeup_extra_facts_duplicate_keys_or_changed_footer_rejected(self):
        for value in (self.wrapped.replace('Wakeup wake-id','Wakeup foreign'),
                      self.wrapped+'extra',self.wrapped.replace('time.due','task.completed'),
                      self.wrapped.replace('"kind":"at"','"kind":"at","kind":"at"'),
                      self.wrapped.replace('"kind":"at"','"kind":"event"'),
                      self.wrapped.replace('23:11:26','99:11:26'),
                      self.prefix+self.note+self.footer+'{}\n',
                      self.prefix+self.note+self.footer+self.fact+'\nsecond fact\n'):
            with self.subTest(value=value),self.assertRaises(ValueError):canonical(value,'wake-id')

    def test_instruction_changes_are_not_hidden_by_decoder(self):
        modified=self.wrapped.replace('exact protocol','forged protocol')
        self.assertNotEqual(canonical(modified,'wake-id'),self.note)

    def test_native_task_and_binding_use_authenticated_envelope_not_raw_ui_text(self):
        actor='00000000-0000-4000-8000-000000000001'
        task='00000000-0000-4000-8000-000000000002'
        issue='00000000-0000-4000-8000-000000000003'
        settings=dict(agents={actor:'planning'},workspace_id='workspace',runtime_id='runtime',token='test-only')
        record=dict(id=task,agent_id=actor,workspace_id='workspace',runtime_id='runtime',issue_id=issue,
                    status='running',wakeup_id='wake-id',handoff_note=self.wrapped)
        with patch.object(native.urllib.request,'urlopen',side_effect=lambda *a,**k:io.StringIO(json.dumps([record]))):
            self.assertEqual(native.task_record(settings,task,actor)['handoff_note'],self.note)
            binding=native.task_binding(settings,task,actor)
            self.assertEqual(binding['handoff_note'],self.note)
            self.assertTrue(binding['scope'].endswith(':'+task))
        record['workspace_id']='foreign'
        with patch.object(native.urllib.request,'urlopen',return_value=io.StringIO(json.dumps([record]))),self.assertRaises(ValueError):
            native.task_record(settings,task,actor)
