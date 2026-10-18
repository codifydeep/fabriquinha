import json
import sqlite3
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from broker import literal_maintenance_effects as effects


class LiteralPreparationTests(unittest.TestCase):
    def setUp(self):
        self.con=sqlite3.connect(':memory:');self.con.row_factory=sqlite3.Row;self.addCleanup(self.con.close)
        self.con.executescript('CREATE TABLE issue_editables(issue_id,path);'
            'CREATE TABLE issue_test_commands(issue_id,command);CREATE TABLE delivery_routes(issue_id,config);')
        self.con.execute('INSERT INTO issue_editables VALUES(?,?)',('original','/workspace/tests/test.py'))
        self.con.execute('INSERT INTO issue_test_commands VALUES(?,?)',('original','python -m unittest discover -s tests'))
        self.con.execute('INSERT INTO delivery_routes VALUES(?,?)',('original',json.dumps({'issue_id':'original','enabled':True})))
        self.con.commit();self.volumes={};self.calls=[]
        self.cfg=dict(source=dict(issue_id='original',author_task='source-task'),reviewer='lead',test_path='tests/test.py',
            image='sha256:'+'a'*64,base=dict(base_sha='b'*40,manifest_sha256='c'*64,volume='original-base'))
        self.state=dict(issue_id='11111111-1111-4111-8111-111111111111')
        self.b=SimpleNamespace(PREFIX='delivery-kit-port2',OWNER='delivery-kit-port2-broker-v1',db=lambda:self.con,
            docker=self.docker,register_issue_base=self.register_base,register_issue_editables=Mock())
        self.fx=effects.Effects.__new__(effects.Effects);self.fx.b=self.b

    def docker(self,method,path,data=None):
        self.calls.append((method,path))
        if method=='GET' and path.startswith('/volumes/'):return self.volumes.get(path[len('/volumes/'):])
        if method=='POST' and path=='/volumes/create':
            self.volumes[data['Name']]={'Labels':data['Labels']};return self.volumes[data['Name']]
        self.fail('unexpected Docker operation')

    def register_base(self,payload):
        # The installed root registration API deliberately accepts only this
        # canonical namespace. Do not loosen it to accommodate an adapter bug.
        self.assertEqual(payload['volume'],self.b.PREFIX+'-base-'+payload['issue_id'])
        self.assertEqual(payload['manifest_sha256'],self.cfg['base']['manifest_sha256'])

    def test_preparation_uses_root_api_canonical_volume_and_fixed_offline_copy(self):
        with patch.object(effects.validation_job,'run',return_value=dict(exit_code=0,output='base_copy_complete\n')) as job,\
                patch.object(effects.handoff_runtime,'register') as register:
            prepared=self.fx.prepare(self.cfg,self.state)
        self.assertEqual(prepared['volume'],self.b.PREFIX+'-base-'+self.state['issue_id'])
        payload=job.call_args.args[3];self.assertEqual(payload['HostConfig']['NetworkMode'],'none')
        self.assertTrue(payload['HostConfig']['ReadonlyRootfs'])
        self.assertTrue(payload['HostConfig']['Mounts'][0]['ReadOnly'])
        self.assertFalse(payload['HostConfig']['Mounts'][1]['ReadOnly'])
        self.assertFalse(register.call_args.args[1]['enabled'])
        trial=json.loads(self.con.execute('SELECT config FROM test_revision_trials').fetchone()[0])
        self.assertTrue(trial['harness_maintenance_only']);self.assertFalse(trial['historic_functional_red'])
        self.assertNotIn('old_red',trial)

    def test_existing_different_volume_intent_is_preserved_and_never_overwritten(self):
        self.con.execute('CREATE TABLE literal_maintenance_volumes(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        old=json.dumps({'name':'historical-incompatible-name','labels':{}})
        self.con.execute('INSERT INTO literal_maintenance_volumes VALUES(?,?,?)',('source-task',old,'{"stage":"create_intent"}'));self.con.commit()
        with self.assertRaises(ValueError):self.fx.prepare(self.cfg,self.state)
        self.assertEqual(self.con.execute('SELECT identity FROM literal_maintenance_volumes').fetchone()[0],old)
        self.assertEqual(self.calls,[])

    def test_child_route_does_not_inherit_product_execution_capsule(self):
        from execution_context import freeze,reference
        capsule=freeze('Original approved product brief.','Original product review.')
        parent=dict(issue_id='original',enabled=True,execution_context=capsule,
            review_instruction=reference(capsule,'review'))
        self.con.execute('UPDATE delivery_routes SET config=?',(json.dumps(parent),));self.con.commit()
        with patch.object(effects.validation_job,'run',return_value=dict(exit_code=0,output='base_copy_complete\n')),\
                patch.object(effects.handoff_runtime,'register') as registered:
            self.fx.prepare(self.cfg,self.state)
        child=registered.call_args.args[1]
        self.assertNotIn('execution_context',child)
        self.assertFalse(child['enabled']);self.assertEqual(child['issue_id'],self.state['issue_id'])
        self.assertNotIn('DELIVERY_EXECUTION_CONTEXT',child['review_instruction'])
        self.assertEqual(json.loads(self.con.execute('SELECT config FROM delivery_routes').fetchone()[0]),parent)
