import hashlib
import json
import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch
from memory_native import observe,nominate_cto

TASK='33333333-3333-4333-8333-333333333333';AGENT='11111111-1111-4111-8111-111111111111'

class NativeMemoryTests(unittest.TestCase):
    def setUp(self):
        self.row={'task_id':TASK,'agent_id':AGENT,'issue_id':'issue','scope':'x:planning:y',
            'mode':'planning','lease_status':'closed'}
        self.run={'id':TASK,'agent_id':AGENT,'status':'completed','result':{'output':'{"role":"cto"}'}}
    def call(self):
        labels={'com.docker.compose.project':'delivery-kit-one','com.docker.compose.service':'execution-broker'}
        with patch('memory_native.subprocess.check_output',side_effect=[json.dumps(labels),json.dumps([self.row])]):
            return observe(TASK,AGENT,'delivery-kit-one',lambda *a:[self.run])
    def test_complete_exact_native_output_is_bound(self):
        proof,output=self.call()
        self.assertEqual(proof['content_sha256'],hashlib.sha256(output.encode()).hexdigest())
        self.assertEqual(proof['task_id'],TASK)
    def test_live_or_wrong_mode_binding_cannot_supply_memory(self):
        for field,value in [('lease_status','running'),('mode','implementation'),('agent_id','other')]:
            original=self.row[field];self.row[field]=value
            with self.assertRaises(ValueError):self.call()
            self.row[field]=original
    def test_native_failed_task_is_not_a_memory_source(self):
        self.run['status']='failed'
        with self.assertRaises(ValueError):self.call()

    def test_nomination_restart_keeps_original_hash_and_expiry(self):
        proposal={'role':'cto','stack':'Local','components':['Server'],'security':['No secrets'],
            'technical_decisions':['SQLite'],'risks':[]}
        output=json.dumps(proposal)
        proof={'task_id':TASK,'agent_id':AGENT,'status':'completed','mode':'planning',
            'lease_status':'closed','content_sha256':hashlib.sha256(output.encode()).hexdigest()}
        ledger={'stage':'plan_ready','configuration_sha256':'c'*64,'name':'TEST-1','base_sha':'d'*40,
            'outputs':{'cto':{'task_id':TASK,'content_sha256':proof['content_sha256'],'proposal':proposal}}}
        with tempfile.TemporaryDirectory() as folder,patch('memory_native.observe',return_value=(proof,output)):
            first=nominate_cto(Path(folder),'https://github.com/acme/example','delivery-kit-one',ledger,AGENT,None,now=100)
            second=nominate_cto(Path(folder),'https://github.com/acme/example','delivery-kit-one',ledger,AGENT,None,now=200)
            self.assertEqual(first,second)
