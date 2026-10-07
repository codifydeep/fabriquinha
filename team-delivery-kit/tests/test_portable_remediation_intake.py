import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from unittest.mock import Mock
from types import SimpleNamespace
import sys
import sqlite3
import io
from contextlib import contextmanager,redirect_stdout
from execution_context import freeze,reference
from test_portable_contract import contract
from test_portable_run_spec import spec
from portable_remediation_intake import bundle,prepare,candidate,read_input,CANDIDATE_QUERY,INPUT_QUERY,digest,execution_digest


class PortableRemediationIntakeTests(unittest.TestCase):
    def setUp(self):
        self.contract=contract()
        self.contract['files'].append('Dockerfile');self.contract['protected_files'].append('Dockerfile')
        self.spec=spec();self.parent=dict(label=self.spec['label'],issue_id='root',base_sha='1'*40,
            contract_sha256=digest(self.contract),run_spec_sha256=digest(self.spec),durable_handoffs=True)
        capsule=freeze('Complete R2 original brief and all criteria.','Complete immutable review.')
        self.value=dict(version='remediation_execution_contract_v1',source_task='failed',root_issue='root',
            run_id='remediation-run',contract_sha256=digest(self.contract),base={'base_sha':'1'*40},
            original_depth=2,release_homologated=False,steps=[{'id':'R1'},{'id':'R2'},
                dict(id='R3',depends_on=['R2'],edit_scope='controller_only',owner='controller',editable_files=[],
                     gates=['independent_review_exact_sha','product_pr','ci_exact_sha','merge','deploy_exact_sha','browser_qa_exact_sha'])])
        self.delivery=dict(source_task='product',review_task='review',author='author',reviewer='reviewer',
                           volume='snapshot',manifest_sha256='a'*64)
        proof=dict(operation='qualified_remediation_r2_delivery_v1',issue_id='r2',source_task='failed',
            run_id='remediation-run',execution_contract_sha256=execution_digest(self.value),r1_gate_sha256='b'*64,
            reference_sha256='c'*64,delivery=self.delivery,tdd_sha256='d'*64,red_origin_issue='r1',
            red_origin_task='red',original_depth=2,release_homologated=False)
        self.input=dict(operation='remediation_r3_input_v1',execution=self.value,proof=proof,
            route=dict(issue_id='r2',author='author',reviewer='reviewer',enabled=True,
                       execution_context=capsule,review_instruction=reference(capsule,'review')),
            release_homologated=False)

    def build(self,value=None):
        return bundle(self.parent,self.spec,self.contract,self.input if value is None else value)

    def test_same_base_actors_full_context_and_original_depth_without_new_worker(self):
        result=self.build();context=result['context'];selected=result['spec']
        self.assertEqual(context['issue_id'],'r2');self.assertNotEqual(context['label'],self.parent['label'])
        self.assertTrue(context['label'].startswith('REMEDIATION'))
        self.assertEqual(context['base_sha'],self.parent['base_sha'])
        self.assertEqual(context['contract_sha256'],self.parent['contract_sha256'])
        self.assertEqual(context['remediation_parent'],self.parent)
        self.assertEqual(selected['execution_context'],self.input['route']['execution_context'])
        self.assertEqual(selected['qa_host_port'],self.spec['qa_host_port'])
        self.assertEqual(selected['implementer_registry'],self.spec['implementer_registry'])
        self.assertEqual(result['original_depth'],2);self.assertFalse(result['release_homologated'])
        self.assertNotIn('test_revision_parent',context)
        self.assertEqual(self.build(),result)

    def test_missing_r3_gate_scope_base_proof_or_route_drift_rejected(self):
        changes=[lambda v:v['execution']['steps'][2]['gates'].remove('browser_qa_exact_sha'),
            lambda v:v['execution']['steps'][2].update(editable_files=['app.py']),
            lambda v:v['execution']['steps'][2].update(owner='author'),
            lambda v:v['execution'].update(root_issue='other'),
            lambda v:v['execution']['base'].update(base_sha='2'*40),
            lambda v:v['proof'].update(execution_contract_sha256='e'*64),
            lambda v:v['route'].update(enabled=False),
            lambda v:v['route'].update(reviewer='author'),
            lambda v:v.update(release_homologated=True)]
        for change in changes:
            value=copy.deepcopy(self.input);change(value)
            with self.assertRaises(ValueError):self.build(value)

    def test_original_run_spec_drift_cannot_change_ports_or_registries(self):
        with self.assertRaises(ValueError):
            bundle(self.parent,{**self.spec,'qa_host_port':19401},self.contract,self.input)

    def test_unicode_keeps_distinct_portable_and_broker_hash_encodings(self):
        self.spec['title']='Version — checking…';self.parent['run_spec_sha256']=digest(self.spec)
        self.contract['qa_cases'][0]['expected_json']['message']='Checking environment…'
        self.parent['contract_sha256']=digest(self.contract)
        self.value['contract_sha256']=digest(self.contract);self.value['run_id']='remediation—run'
        self.input['proof'].update(run_id=self.value['run_id'],execution_contract_sha256=execution_digest(self.value))
        self.assertNotEqual(digest(self.value),execution_digest(self.value))
        result=self.build();self.assertEqual(result['context']['contract_sha256'],digest(self.contract))

    def test_fixed_queries_bind_issue_and_delivery_without_arbitrary_commands(self):
        command=Mock(return_value='"r2"')
        self.assertEqual(candidate(command,'delivery-kit-port2','root'),'r2')
        args=command.call_args.args;self.assertEqual(args[-1],'root');compile(args[-2],'<candidate>','exec')
        command.return_value=json.dumps(self.input)
        self.assertEqual(read_input(command,'delivery-kit-port2','r2',self.delivery),self.input)
        args=command.call_args.args;self.assertEqual(args[-2],'r2')
        self.assertEqual(json.loads(args[-1]),self.delivery);compile(args[-3],'<input>','exec')

    def test_candidate_query_requires_current_approved_handoff_and_enabled_route(self):
        for enabled,stage,expected in ((False,'approved',None),(True,'accepted',None),(True,'approved','r2')):
            con=sqlite3.connect(':memory:')
            con.execute('CREATE TABLE remediation_executions(contract TEXT,state TEXT)')
            con.execute('INSERT INTO remediation_executions VALUES (?,?)',(json.dumps(self.value),json.dumps({'steps':{'R2':{'issue_id':'r2'}}})))
            con.execute('CREATE TABLE delivery_routes(issue_id TEXT,config TEXT)')
            con.execute('INSERT INTO delivery_routes VALUES (?,?)',('r2',json.dumps({'enabled':enabled})))
            con.execute('CREATE TABLE delivery_handoffs(issue_id TEXT,stage TEXT,updated REAL)')
            con.execute('INSERT INTO delivery_handoffs VALUES (?,?,?)',('r2',stage,1))
            @contextmanager
            def db():
                try:yield con
                finally:con.close()
            output=io.StringIO()
            with patch.dict(sys.modules,{'broker':SimpleNamespace(db=db)}),\
                 patch.object(sys,'argv',['query','root']),redirect_stdout(output):
                exec(CANDIDATE_QUERY,{})
            self.assertEqual(json.loads(output.getvalue()),expected)

    def test_prepare_is_durable_idempotent_and_never_starts_agents(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);result=self.build()
            paths=prepare(root,result);self.assertEqual(prepare(root,result),paths)
            self.assertEqual(json.loads(paths['context'].read_text()),result['context'])
            self.assertEqual(json.loads(paths['spec'].read_text()),result['spec'])
            self.assertEqual(paths['context'].stat().st_mode & 0o777,0o600)
            self.assertFalse(json.loads(paths['intent'].read_text())['execution_authorized'])

    def test_interruption_after_intent_resumes_identical_artifacts(self):
        from portable_remediation_intake import save_receipt
        with tempfile.TemporaryDirectory() as directory:
            calls=[]
            def interrupted(path,value):
                calls.append(path)
                if len(calls)==2:raise OSError('interrupted')
                save_receipt(path,value)
            with patch('portable_remediation_intake.save_receipt',side_effect=interrupted):
                with self.assertRaises(OSError):prepare(Path(directory),self.build())
            paths=prepare(Path(directory),self.build())
            self.assertTrue(paths['context'].is_file())

    def test_symlink_or_existing_context_drift_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);paths=prepare(root,self.build())
            paths['context'].write_text('{}')
            with self.assertRaises(ValueError):prepare(root,self.build())
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'remediation-publication').symlink_to(root)
            with self.assertRaises(ValueError):prepare(root,self.build())
