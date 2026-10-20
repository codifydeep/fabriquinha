import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from broker import literal_review_audit as audit


class AuditContractTests(unittest.TestCase):
    def setUp(self):
        self.cfg=dict(test_path='tests/test.py',source=dict(candidate_volume='original',prepared=dict(manifest_sha256='a'*64)),
            feedback_strategy=dict(policy=dict(previous_volume='seed',previous_manifest_sha256='b'*64)))
        self.s=dict(reconsideration=dict(value=dict(reason='A disputed finding')),finding_audit_policy=dict(image='sha256:'+'d'*64),
            finding_audit_authority=dict(bound=True),finding_audit_decision=dict(value=dict(action='request_review_reconsideration')),
            snapshot=dict(volume='candidate'),inspection=dict(candidate_manifest_sha256='c'*64))

    def test_preflight_and_completed_read_wire_keep_typed_findings_without_approval(self):
        self.assertEqual(len(audit.preflight(self.cfg,self.s)),64)
        from decision_schema import apply
        from typed_decision_contract import apply as typed,NAME
        note=audit.instruction(self.cfg,self.s);messages=[dict(role='user',content=note)]
        # Synthetic numbered reads exercise request shape only. These are NOT
        # native receipts and are never sent to the controller or a model.
        import re
        for i,path in enumerate(re.findall(r'^DELIVERY_REVIEW_READ_PATH:(.+)$',note,re.M)):
            identifier='fixture-'+str(i)
            messages.extend([dict(role='assistant',tool_calls=[dict(id=identifier,function=dict(name='read_file',
                arguments=json.dumps(dict(path=path,offset=1,limit=100))))]),dict(role='tool',tool_call_id=identifier,
                content=json.dumps(dict(content='1|tick();',total_lines=1)))])
        body=typed(apply(dict(messages=messages,tools=[dict(type='function',function=dict(name='read_file',parameters={}))])))
        tool=next(t['function'] for t in body['tools'] if t['function']['name']==NAME)
        props=tool['parameters']['properties']
        self.assertEqual(set(props),{'action','reason','optional_files','findings'})
        self.assertNotIn('approve_test_revision',props['action']['enum'])
        self.assertIn('request_review_reconsideration',props['action']['enum'])
        from provider_tool_routing import wire
        body['model']='anthropic/claude-haiku-5.5'
        projected=wire(body)
        self.assertIn('anyOf',tool['parameters'])
        self.assertNotIn('anyOf',projected['tools'][0]['function']['parameters'])
        self.assertEqual(set(projected['tools'][0]['function']['parameters']['properties']),set(props))

    def test_fixed_helper_payload_has_only_readonly_snapshot_mounts_and_no_host_secrets(self):
        body=audit.payload(self.cfg,self.s)
        self.assertEqual(body['User'],'10000:10000');self.assertEqual(body['HostConfig']['NetworkMode'],'none')
        self.assertTrue(body['HostConfig']['ReadonlyRootfs']);self.assertEqual(body['HostConfig']['CapDrop'],['ALL'])
        self.assertTrue(all(m['ReadOnly'] for m in body['HostConfig']['Mounts']))
        self.assertEqual(body['Cmd'][0],'/literal_review_findings.py')
        self.assertEqual(set(body['Env']),{'PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1'})

    def test_helper_policy_requires_an_existing_immutable_image_and_binds_both_scripts(self):
        b=SimpleNamespace(docker=lambda *args:dict(present=True))
        with patch.dict(os.environ,BROKER_LITERAL_REVIEW_FINDINGS_IMAGE='sha256:'+'a'*64):
            p=audit.policy(b);self.assertEqual(p['native_attempt_limit'],1)
            self.assertEqual(len(p['findings_sha256']),64);self.assertEqual(len(p['claims_sha256']),64)
            self.assertFalse(p['review_override']);self.assertFalse(p['delivery_approval'])
        with patch.dict(os.environ,BROKER_LITERAL_REVIEW_FINDINGS_IMAGE='mutable:latest'):
            with self.assertRaises(ValueError):audit.policy(b)
