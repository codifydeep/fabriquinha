import copy
import json
import tempfile
import unittest
from pathlib import Path
from decision_memory import nominate,curate,read

REPO='https://github.com/acme/example';NS='delivery-kit-one'
AUTHOR='11111111-1111-4111-8111-111111111111'
REVIEWER='22222222-2222-4222-8222-222222222222'
SOURCE='33333333-3333-4333-8333-333333333333'
TASK='44444444-4444-4444-8444-444444444444'

class DecisionMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.entry={'subject':'Storage decision','decisions':['Use a local SQLite database.'],
            'commit':'a'*40,'source_release':'TEST-1','expires':1000,'supersedes':None}
        self.source={'task_id':SOURCE,'agent_id':AUTHOR,'status':'completed',
            'mode':'planning','lease_status':'closed','content_sha256':'b'*64}
        self.review={'task_id':TASK,'agent_id':REVIEWER,'status':'completed',
            'mode':'planning','lease_status':'closed','content_sha256':'c'*64}
    def propose(self):return nominate(self.root,REPO,NS,self.entry,self.source,now=100)
    def approve(self,key):return curate(self.root,REPO,NS,key,
        {'role':'techlead','decision':'approve','entry_sha256':key,'reason':'Supported by cited decision.'},self.review,now=101)
    def context(self,**kw):
        args={'base_sha':'d'*40,'is_ancestor':lambda a,b:True,'now':102};args.update(kw)
        return read(self.root,REPO,NS,**args)
    def test_nomination_not_shared_until_independent_exact_review(self):
        key=self.propose();self.assertEqual(self.context(),[])
        self.assertEqual(self.propose(),key);self.approve(key)
        values=self.context();self.assertEqual(values[0]['entry'],self.entry)
        self.assertFalse(values[0]['authority']);self.assertEqual(values[0]['validity'],'historical_recommendation_revalidate')
    def test_same_agent_wrong_hash_open_lease_and_wrong_mode_cannot_curate(self):
        key=self.propose()
        for field,value in (('agent_id',AUTHOR),('task_id',SOURCE),('lease_status','running'),('mode','implementation')):
            proof={**self.review,field:value}
            with self.assertRaises(ValueError):curate(self.root,REPO,NS,key,
                {'role':'techlead','decision':'approve','entry_sha256':key,'reason':'Valid'},proof,now=101)
        with self.assertRaises(ValueError):curate(self.root,REPO,NS,key,
            {'role':'techlead','decision':'approve','entry_sha256':'f'*64,'reason':'Valid'},self.review,now=101)
        self.assertEqual(self.context(),[])
    def test_rejection_terminal_and_restart_cannot_turn_it_into_approval(self):
        key=self.propose();answer={'role':'techlead','decision':'reject','entry_sha256':key,'reason':'Unsupported'}
        curate(self.root,REPO,NS,key,answer,self.review,now=101)
        with self.assertRaises(ValueError):self.approve(key)
        self.assertEqual(self.context(),[])
    def test_repository_namespace_expiry_and_nonancestor_are_filtered(self):
        key=self.propose();self.approve(key)
        self.assertEqual(self.context(now=1001),[])
        self.assertEqual(self.context(is_ancestor=lambda a,b:False),[])
        self.assertEqual(read(self.root,REPO,'delivery-kit-two',base_sha='d'*40,is_ancestor=lambda a,b:True,now=102),[])
    def test_supersession_requires_same_subject_and_current_review(self):
        first=self.propose();self.approve(first)
        self.entry.update(decisions=['Use SQLite with WAL.'],supersedes=first)
        second=self.propose();self.assertEqual(len(self.context()),1)
        self.approve(second)
        self.assertEqual([v['id'] for v in self.context()],[second])
    def test_secrets_and_unbounded_payload_rejected(self):
        for value in ('Authorization: Bearer private','x'*301):
            self.entry['decisions']=[value]
            with self.assertRaises(ValueError):self.propose()
