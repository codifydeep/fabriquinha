import copy
import hashlib
import json
import sqlite3
import unittest
import threading
from types import SimpleNamespace
from unittest.mock import Mock,patch
from broker import literal_base_recovery as recovery
from broker import literal_maintenance_effects as lane
from generic_harness_calibration import digest
import recover_literal_base as cli


class BaseRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='delivery-kit-port2-broker-v1')
        self.cfg=dict(source=dict(author_task='source',prepared=dict(baseline_test_sha256={'tests/test_old.py':'d'*64})),
            base=dict(base_sha='a'*40,manifest_sha256='b'*64,volume='original-base'),image='sha256:'+'c'*64)
        self.state=dict(issue_id='child',stage='blocked',category='maintenance_evidence_rejected',revision=0,history=[],
            decisions={p:{} for p in ('triage','plan','permit')},source_reset=False,functional_red=False,delivery_approval=False)
        labels={'delivery-kit.owner':self.b.OWNER,'delivery-kit.issue-id':'child','delivery-kit.base-sha':'a'*40}
        self.old=dict(identity=dict(name=self.b.PREFIX+'-literal-base-child',labels=labels),state={'stage':'create_intent'})
        self.new=dict(name=self.b.PREFIX+'-base-child',labels=labels)
        self.spec=dict(base_sha='a'*40,manifest_sha256='b'*64,baseline_test_sha256={'tests/test_old.py':'d'*64})
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)

    def qualify(self,**kwargs):
        recovery.qualify(self.b,kwargs.get('cfg',self.cfg),kwargs.get('state',self.state),
            kwargs.get('old',self.old),kwargs.get('new',self.new),kwargs.get('spec',self.spec))

    def test_only_exact_unused_legacy_base_and_unchanged_protected_hashes_qualify(self):
        self.qualify()
        for change in (dict(author_task='already-started'),dict(prepared={'exists':True}),dict(revision=1),
                dict(canonical_base_recovery='spent'),dict(delivery_approval=True),dict(stage='prepare')):
            with self.assertRaises(ValueError):self.qualify(state={**self.state,**change})
        for change in (dict(base_sha='e'*40),dict(manifest_sha256='e'*64),dict(baseline_test_sha256={})):
            with self.assertRaises(ValueError):self.qualify(spec={**self.spec,**change})

    def test_foreign_or_noncanonical_volume_identity_cannot_be_inspected_or_registered(self):
        for field in ('name','labels'):
            bad=copy.deepcopy(self.old);bad['identity'][field]='foreign' if field=='name' else {}
            with self.assertRaises(ValueError):self.qualify(old=bad)
        with self.assertRaises(ValueError):self.qualify(new={**self.new,'name':'foreign'})

    def copy_journal(self):
        key,identity=recovery.copy_identity(self.b,self.cfg,self.old['identity'])
        result=dict(approval=False,exit_code=0,container_id='captured-helper',validation_job_key=key,
            validation_contract_sha256=recovery.job_digest(identity),output='base_copy_complete\n',
            output_sha256=hashlib.sha256(b'base_copy_complete\n').hexdigest())
        self.con.execute('CREATE TABLE validation_jobs(job_key,identity,state)')
        self.con.execute('INSERT INTO validation_jobs VALUES(?,?,?)',
            (key,json.dumps(identity),json.dumps(dict(stage='complete',container_id='captured-helper',result=result))))
        return result

    def test_completed_copy_is_read_from_its_exact_journal_not_reexecuted(self):
        result=self.copy_journal()
        self.assertEqual(recovery.completed_copy(self.con,self.b,self.cfg,self.old['identity']),result)
        row=json.loads(self.con.execute('SELECT state FROM validation_jobs').fetchone()[0])
        for change in (dict(stage='running'),dict(container_id='other')):
            self.con.execute('UPDATE validation_jobs SET state=?',(json.dumps({**row,**change}),))
            with self.assertRaises(ValueError):recovery.completed_copy(self.con,self.b,self.cfg,self.old['identity'])

    def test_qualified_preparation_uses_separate_journal_and_readonly_legacy_source(self):
        self.con.execute('CREATE TABLE literal_maintenance_volumes(source_task PRIMARY KEY,identity,state)')
        self.con.execute('INSERT INTO literal_maintenance_volumes VALUES(?,?,?)',
            ('source',json.dumps(self.old['identity']),json.dumps(self.old['state'])))
        self.con.execute('CREATE TABLE literal_base_recoveries(source_task PRIMARY KEY,receipt)')
        receipt=dict(config_sha256=digest(self.cfg),old_intent=self.old,new_identity=self.new,
            previous_state=self.state,source_reset=False,delivery_approval=False)
        self.con.execute('INSERT INTO literal_base_recoveries VALUES(?,?)',('source',json.dumps(receipt)))
        state={**self.state,'canonical_base_recovery':digest(receipt)}
        table,source=lane.preparation_journal(self.con,self.cfg,state,self.new)
        self.assertEqual(table,'literal_maintenance_canonical_volumes');self.assertEqual(source,self.old['identity']['name'])
        payload=lane.copy_payload(self.cfg,self.new,source)
        self.assertTrue(payload['HostConfig']['Mounts'][0]['ReadOnly'])
        self.assertEqual(payload['HostConfig']['Mounts'][0]['Source'],source)
        self.assertEqual(json.loads(self.con.execute('SELECT identity FROM literal_maintenance_volumes').fetchone()[0]),self.old['identity'])
        with self.assertRaises(ValueError):lane.preparation_journal(self.con,self.cfg,{**state,'canonical_base_recovery':'foreign'},self.new)

    def test_operator_program_compiles_without_arbitrary_worker_command(self):
        compile(cli.PROGRAM,'canonical-base-qualification','exec')
        self.assertNotIn('eval(',cli.PROGRAM)

    def registration_database(self):
        self.copy_journal()
        self.con.executescript('CREATE TABLE leases(status);CREATE TABLE literal_maintenance_workflows(source_task,config,state);'
            'CREATE TABLE literal_maintenance_volumes(source_task PRIMARY KEY,identity,state);')
        for table in ('issue_bases','issue_editables','delivery_routes','test_revision_trials'):
            self.con.execute('CREATE TABLE '+table+'(issue_id)')
        self.con.execute('INSERT INTO literal_maintenance_workflows VALUES(?,?,?)',('source',json.dumps(self.cfg),json.dumps(self.state)))
        self.con.execute('INSERT INTO literal_maintenance_volumes VALUES(?,?,?)',('source',json.dumps(self.old['identity']),json.dumps(self.old['state'])));self.con.commit()
        self.b.LOCK=threading.RLock();self.b.db=lambda:self.con
        self.b.docker=lambda method,path: {'Labels':self.old['identity']['labels']} if path=='/volumes/'+self.old['identity']['name'] else None
        output=json.dumps(self.spec)
        return dict(approval=False,exit_code=0,output=output,output_sha256=hashlib.sha256(output.encode()).hexdigest())

    def test_registration_is_idempotent_and_keeps_old_intent_and_decisions(self):
        inspection=self.registration_database()
        with patch.object(recovery.maintenance,'current',return_value=dict(stage='sealed',operation_id='maintenance')),\
                patch.object(recovery.maintenance,'native_active',return_value=[]),\
                patch.object(recovery.lane,'Effects',return_value=Mock()),patch.object(recovery.flow,'authenticate'),\
                patch.object(recovery.os,'environ',{'BROKER_LITERAL_BASE_INSPECTION_IMAGE':'sha256:'+'e'*64}),\
                patch.object(recovery.validation_job,'run',return_value=inspection) as job:
            receipt=recovery.register(self.b,'source');self.assertEqual(recovery.register(self.b,'source'),receipt)
        job.assert_called_once()
        actual=json.loads(self.con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()[0])
        self.assertEqual(actual['stage'],'prepare');self.assertEqual(actual['decisions'],self.state['decisions'])
        self.assertEqual(actual['phase_started'],receipt['qualified_at'])
        self.assertEqual(receipt['old_intent'],self.old);self.assertEqual(receipt['previous_state'],self.state)
        old=json.loads(self.con.execute('SELECT identity FROM literal_maintenance_volumes').fetchone()[0])
        self.assertEqual(old,self.old['identity']);self.assertFalse(receipt['author_retry_authorized'])

    def test_pending_readonly_inspection_cannot_advance_or_create_a_recovery_receipt(self):
        self.registration_database()
        with patch.object(recovery.maintenance,'current',return_value=dict(stage='sealed',operation_id='maintenance')),\
                patch.object(recovery.maintenance,'native_active',return_value=[]),\
                patch.object(recovery.lane,'Effects',return_value=Mock()),patch.object(recovery.flow,'authenticate'),\
                patch.object(recovery.os,'environ',{'BROKER_LITERAL_BASE_INSPECTION_IMAGE':'sha256:'+'e'*64}),\
                patch.object(recovery.validation_job,'run',side_effect=recovery.validation_job.Pending('same running helper')):
            with self.assertRaises(TimeoutError):recovery.register(self.b,'source')
        self.assertEqual(self.con.execute('SELECT count(*) FROM literal_base_recoveries').fetchone()[0],0)
        self.assertEqual(json.loads(self.con.execute('SELECT state FROM literal_maintenance_workflows').fetchone()[0]),self.state)
