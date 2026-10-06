import json,sqlite3,tempfile,unittest
from pathlib import Path
from product_memory import Memory

class MemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/'memory.db';self.db=sqlite3.connect(self.path)
        self.addCleanup(self.db.close);self.m=Memory(self.db)
        self.who=dict(attempt='a',task='t',run=1,profile='backend_data',mode='implementation')
        self.entry=dict(subject='api-contract',text='Use the reviewed error envelope.',sources=['card:t@sha'],scope='project',valid_until=3000,supersedes=None)
    def promote(self,entry=None,sha='a'*64):
        self.m.promote('a',entry or self.entry,dict(proposal_sha256=sha,author='techlead',reviewer='quality_security',run=2),now=1000)
    def test_proposal_is_not_knowledge(self):
        self.m.propose(self.who,self.entry,now=1000)
        self.assertEqual(self.m.search('a','api',now=1001)['items'],[])
    def test_restart_fresh_session_recovers_source_and_checkpoint(self):
        self.promote();self.m.checkpoint(self.who,'Need to add timeout case.',['card:t@sha'],now=1000)
        with sqlite3.connect(self.path) as db:
            fresh=Memory(db)
            self.assertEqual(fresh.search('a','api',now=1001)['items'][0]['entry']['sources'],['card:t@sha'])
            self.assertEqual(fresh.latest('a','t')['run'],1)
            self.assertFalse(fresh.search('a','api',now=1001)['authority'])
    def test_supersession_expiration_and_attempt_isolation(self):
        self.promote()
        update=dict(self.entry,text='New reviewed envelope.',supersedes='a'*64)
        self.promote(update,'b'*64)
        self.assertEqual([x['id'] for x in self.m.search('a','api',now=1001)['items']],['b'*64])
        self.assertEqual(self.m.search('other','api',now=1001)['items'],[])
        self.assertEqual(self.m.search('a','api',now=3001)['items'],[])
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM team_knowledge').fetchone()[0],2)
    def test_self_review_and_unknown_supersession_denied(self):
        with self.assertRaises(PermissionError):self.m.promote('a',self.entry,dict(proposal_sha256='a'*64,author='techlead',reviewer='techlead',run=2),now=1000)
        with self.assertRaises(PermissionError):self.promote(dict(self.entry,supersedes='unknown'))
    def test_personal_memory_separate_and_pagination(self):
        self.m.personal(self.who,'Prefer small case tables.')
        self.assertEqual(self.m.personal_read('a','frontend'),[])
        for i in range(7):self.promote(dict(self.entry,subject=f'api-{i}'),f'{i:064x}')
        first=self.m.search('a','api',limit=5,now=1001)
        self.assertEqual(len(first['items']),5)
        self.assertEqual(len(self.m.search('a','api',offset=first['next_offset'],now=1001)['items']),2)
    def test_unbounded_or_secret_content_rejected(self):
        for entry in [dict(self.entry,valid_until=0),dict(self.entry,text='OPENROUTER_API_KEY=sk-secret'),dict(self.entry,sources=[])]:
            with self.assertRaises(ValueError):self.m.propose(self.who,entry,now=1000)

