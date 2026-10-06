import sqlite3,unittest,json
from unittest.mock import Mock
from product_memory import Memory
from product_memory_evidence import read

class EvidenceTests(unittest.TestCase):
    def test_integration_receipt_requires_exact_commit_attempt_and_registered_source(self):
        self.db.execute('CREATE TABLE integration_evidence(attempt TEXT,reference TEXT,receipt TEXT)')
        ref='PR:31@'+'a'*40
        self.binding.cards={'t_source':{}}
        self.db.execute('INSERT INTO integration_evidence VALUES(?,?,?)',('current',ref,json.dumps(dict(state='INTEGRATED',source_task='t_source',merge='a'*40,release_homologated=False))))
        result=read(self.db,self.binding,self.who,ref,0)
        self.assertIn('INTEGRATED',result['content']);self.assertFalse(result['authority'])
        for who,reference in ((dict(attempt='other'),ref),(self.who,'PR:31@'+'b'*40)):
            with self.assertRaises(PermissionError):read(self.db,self.binding,who,reference,0)
        self.binding.cards={}
        with self.assertRaises(PermissionError):read(self.db,self.binding,self.who,ref,0)
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close);Memory(self.db)
        self.binding=Mock();self.binding.cards={}
        self.who=dict(attempt='current')
    def test_no_arbitrary_file_url_or_foreign_card(self):
        for reference in ('/control/signing/test-maintenance-private.pem','https://example.com','card:t_foreign'):
            with self.subTest(reference=reference),self.assertRaises(PermissionError):read(self.db,self.binding,self.who,reference,0)
    def test_historical_expired_evidence_is_labeled_not_silently_promoted(self):
        m=Memory(self.db);entry=dict(subject='historical',text='Original rationale.',sources=['card:t_123'],scope='project',valid_until=1500,supersedes=None)
        m.promote('old',entry,dict(author='techlead',reviewer='quality_security',proposal_sha256='a'*64),now=1000)
        value=read(self.db,self.binding,self.who,'knowledge:old:'+'a'*64,0)
        self.assertIn('"expired": true',value['content']);self.assertIn('"historical": true',value['content']);self.assertFalse(value['authority'])
