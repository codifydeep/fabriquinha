import base64
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
import zlib

from broker import qa_artifacts as qa


class QaArtifactTests(unittest.TestCase):
    def spike(self):
        code=(Path(__file__).resolve().parents[1]/'browser_runtime_probe.py').read_bytes()
        receipt={'status':'causal_spike_passed','cleanup':'passed','scope':'diagnostic_only_not_delivery',
            'identity':{'source_sha':'b'*40,'image':'sha256:'+'e'*64,
                        'script_sha256':'f'*64,'probe_sha256':hashlib.sha256(code).hexdigest()},
            'proof':{'status':'causal_spike_passed','scope':'diagnostic_only_not_delivery',
                     'source_sha':'b'*40,'script_sha256':'f'*64,'original_source_unchanged':True}}
        return {'receipt':receipt,'probe_zlib':base64.b64encode(zlib.compress(code)).decode()}

    def test_spike_uses_only_fixed_recipe_and_exact_product_identity(self):
        p={**self.payload,'runtime_spike':self.spike()}
        self.assertEqual(set(qa.unpack(p)),{'qa.json','scenario.py','spike.json','probe.py'})
        p['runtime_spike']['receipt']['proof']['original_source_unchanged']=False
        with self.assertRaises(ValueError):qa.unpack(p)
        p={**self.payload,'runtime_spike':self.spike()}
        p['runtime_spike']['probe_zlib']=base64.b64encode(zlib.compress(b'arbitrary code')).decode()
        with self.assertRaises(ValueError):qa.unpack(p)

    def test_runtime_spike_reads_are_required_not_optional_summary(self):
        self.payload['runtime_spike']=self.spike();self.register()
        observed={'/evidence/previous/qa.json':{},'/evidence/previous/scenario.py':{},
                  '/evidence/candidate/app/static/app.js':{}}
        with patch('broker.native.task_messages',return_value=[]),patch.object(qa,'observations',return_value=observed):
            with self.assertRaises(ValueError):qa.verify_reads(self.broker,'diagnostic')
            observed.update({'/evidence/previous/spike.json':{},'/evidence/previous/probe.py':{}})
            self.assertEqual(qa.verify_reads(self.broker,'diagnostic')['status'],'read_evidence_verified')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.database = root / 'state.db'
        self.issue = '11111111-1111-4111-8111-111111111111'
        self.root_issue = '22222222-2222-4222-8222-222222222222'
        self.agent = '33333333-3333-4333-8333-333333333333'
        self.task = '44444444-4444-4444-8444-444444444444'
        (root / 'native.json').write_text(json.dumps({'agents': {self.agent: 'planning'}}))
        code = b'print("fixed browser scenario")\n'
        self.payload = {'issue_id': self.issue, 'root_issue_id': self.root_issue,
                        'agent_id': self.agent, 'source_task': self.task,
                        'manifest_sha256': 'a' * 64, 'source_sha': 'b' * 40,
                        'scenario_zlib': base64.b64encode(zlib.compress(code)).decode(),
                        'read_files': ['app/static/app.js'],
                        'browser_receipt': {'status': 'failed', 'cleanup': 'passed',
                          'automated': True, 'error': 'element absent', 'identity': {
                            'source_sha': 'b' * 40, 'scenario_sha256': hashlib.sha256(code).hexdigest(),
                            'deployed_container_id': 'd' * 64, 'application_image': 'sha256:'+'e'*64,
                            'runtime_env': {'FEEDBACK_DB_PATH': '/tmp/feedback.db'},
                            'config': {'scenario': 'feedback-board-filter-v1',
                                       'browser_image': 'sha256:' + 'c' * 64}}}}
        self.broker = SimpleNamespace(STATE=root, LOCK=threading.RLock(), db=self.db,
                     PREFIX='delivery-kit-port2', OWNER='owner', docker=Mock(return_value=None))
        with self.db() as c:
            c.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            c.execute('CREATE TABLE delivery_handoffs(source_task TEXT,issue_id TEXT,stage TEXT,data TEXT)')
            c.execute('CREATE TABLE snapshots(task_id TEXT,status TEXT,volume TEXT)')
            c.execute('CREATE TABLE native_bindings(request_id TEXT,task_id TEXT,issue_id TEXT,agent_id TEXT)')
            c.execute('INSERT INTO delivery_routes VALUES (?,?)', (self.root_issue,
                json.dumps({'techlead': self.agent, 'cto': 'cto'})))
            c.execute('INSERT INTO delivery_handoffs VALUES (?,?,?,?)',
                      (self.task, self.root_issue, 'approved',
                       json.dumps({'evidence': {'manifest_sha256': 'a' * 64},
                                   'review': {'status':'approved','manifest_sha256':'a'*64}})))
            c.execute('INSERT INTO snapshots VALUES (?,?,?)', (self.task,'complete','snapshot'))
            c.execute('INSERT INTO native_bindings VALUES (?,?,?,?)', ('request','diagnostic',self.issue,self.agent))

    @contextmanager
    def db(self):
        c = sqlite3.connect(self.database)
        c.row_factory = sqlite3.Row
        try:
            with c: yield c
        finally: c.close()

    def register(self):
        with patch('broker.native.issue_record', return_value={'parent_issue_id': self.root_issue,
                       'assignee_id': self.agent}), patch('broker.native.issue_task_runs', return_value=[]), \
                patch.object(qa, 'copy_bundle') as copy:
            qa.register(self.broker, self.payload)
            qa.register(self.broker, self.payload)
            copy.assert_called_once()

    def test_every_supported_browser_scenario_can_register_diagnostic_evidence(self):
        import portable_browser_qa
        from browser_qa_recipes import SCENARIOS, LEGACY_SCENARIOS
        scenarios=set(SCENARIOS)
        self.assertEqual(len(LEGACY_SCENARIOS),14)
        self.assertEqual(len(scenarios),18)
        config=self.payload['browser_receipt']['identity']['config']
        for scenario in scenarios:
            config['scenario']=scenario
            self.assertEqual(portable_browser_qa.validate(config),config)
            script=portable_browser_qa.script_for(config).read_bytes()
            self.assertLessEqual(len(script),32768)
            self.payload['scenario_zlib']=base64.b64encode(zlib.compress(script)).decode()
            self.payload['browser_receipt']['identity']['scenario_sha256']=hashlib.sha256(script).hexdigest()
            with self.subTest(scenario=scenario):self.assertIn('scenario.py',qa.unpack(self.payload))
        config['scenario']='arbitrary-agent-command'
        with self.assertRaises(ValueError):qa.unpack(self.payload)

    def test_bundle_hash_and_decompression_bound_fail_closed(self):
        self.assertEqual(set(qa.unpack(self.payload)), {'qa.json','scenario.py'})
        self.assertTrue(qa.unpack(self.payload)['qa.json'].endswith(b'\n'))
        p = {**self.payload, 'scenario_zlib': base64.b64encode(zlib.compress(b'x'*32769)).decode()}
        with self.assertRaises(ValueError): qa.unpack(p)
        p = {**self.payload, 'read_files': ['../secret']}
        with self.assertRaises(ValueError): qa.unpack(p)

    def test_registration_is_idempotent_and_mounts_only_readonly(self):
        self.register()
        config = qa.config_for(self.broker, self.issue, self.agent)
        def docker(method,path,*args):
            return {'Labels': {'delivery-kit.owner': 'owner',
                'delivery-kit.source-task': self.task,
                'delivery-kit.qa-evidence': config['digest']}}
        self.broker.docker.side_effect = docker
        mounts = qa.mounts(self.broker, 'request')
        self.assertEqual([m['Target'] for m in mounts], ['/evidence/candidate','/evidence/previous'])
        self.assertTrue(all(m['ReadOnly'] for m in mounts))
        self.broker.docker.side_effect = None
        self.broker.docker.return_value = {'Labels': {'delivery-kit.owner': 'foreign'}}
        with self.assertRaises(ValueError): qa.mounts(self.broker, 'request')

    def test_wrong_role_or_unapproved_source_cannot_register(self):
        with self.db() as c: c.execute("UPDATE delivery_handoffs SET stage='technical_decision_required'")
        with self.assertRaises(ValueError): qa.register(self.broker,self.payload)
        self.broker.docker.assert_not_called()

    def test_diagnosis_cannot_claim_reads_without_tool_receipts(self):
        self.register()
        with patch('broker.native.task_messages',return_value=[]):
            with self.assertRaisesRegex(ValueError,'reads'): qa.verify_reads(self.broker,'diagnostic')
        with patch('broker.native.task_messages',return_value=[]), patch.object(qa,'observations',return_value={
                '/evidence/previous/qa.json': {}, '/evidence/previous/scenario.py': {},
                '/evidence/candidate/app/static/app.js': {}}):
            self.assertEqual(qa.verify_reads(self.broker,'diagnostic')['status'],'read_evidence_verified')
