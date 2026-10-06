import json,sqlite3,unittest
from product_notice_queue import flush,schema

class NoticeQueueTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:');self.addCleanup(self.db.close)
        schema(self.db);self.sent=[]
    def add(self,profile='techlead',**kwargs):
        event=dict(event='started',task='t_test',profile=profile,**kwargs)
        with self.db:return self.db.execute('INSERT INTO events(payload) VALUES(?)',(json.dumps(event),)).lastrowid
    def test_failed_destination_does_not_starve_next(self):
        bad=self.add('cto');good=self.add('frontend')
        def send(profile,text):
            if profile=='cto':raise ConnectionError('secret URL must never be stored')
            self.sent.append(profile)
        flush(self.db,send,now=100)
        self.assertEqual(self.sent,['frontend'])
        row=self.db.execute('SELECT sent,delivery_attempts,next_attempt,last_error FROM events WHERE id=?',(bad,)).fetchone()
        self.assertEqual(row[:2],(0,1));self.assertGreater(row[2],100);self.assertEqual(row[3],'ConnectionError')
        self.assertEqual(self.db.execute('SELECT sent FROM events WHERE id=?',(good,)).fetchone()[0],1)
    def test_invalid_profile_is_quarantined_not_global_crash(self):
        bad=self.add('unknown');self.add('quality_security')
        flush(self.db,lambda p,t:self.sent.append(p),now=100)
        self.assertIn('quality_security',self.sent)
        self.assertEqual(self.db.execute('SELECT delivery_state FROM events WHERE id=?',(bad,)).fetchone()[0],'QUARANTINED')
    def test_backoff_and_restart_do_not_repeat_acknowledged_messages(self):
        self.add()
        def fail(p,t):raise TimeoutError()
        flush(self.db,fail,now=100);flush(self.db,fail,now=101)
        self.assertEqual(self.db.execute('SELECT delivery_attempts FROM events WHERE id=1').fetchone()[0],1)
        schema(self.db);flush(self.db,lambda p,t:self.sent.append(p),now=1000);flush(self.db,lambda p,t:self.sent.append(p),now=1100)
        self.assertEqual(self.sent,['techlead'])
    def test_malformed_payload_does_not_starve_queue(self):
        with self.db:self.db.execute("INSERT INTO events(payload) VALUES('not-json')")
        self.add('produto');flush(self.db,lambda p,t:self.sent.append(p),now=100)
        self.assertIn('produto',self.sent)
    def test_migrates_original_queue_without_losing_ack(self):
        db=sqlite3.connect(':memory:');self.addCleanup(db.close)
        db.execute('CREATE TABLE events(id INTEGER PRIMARY KEY,payload TEXT,sent INTEGER DEFAULT 0)')
        db.execute("INSERT INTO events VALUES(7,'{}',1)");db.commit();schema(db)
        self.assertEqual(db.execute('SELECT id,payload,sent FROM events').fetchone(),(7,'{}',1))
    def test_retry_alert_deduplicates(self):
        self.add('cto')
        def fail(p,t):raise ConnectionError()
        for now in (100,1000,2000,3000,4000,5000):flush(self.db,fail,now=now)
        notices=[json.loads(r[0]) for r in self.db.execute('SELECT payload FROM events')]
        self.assertEqual(sum(x.get('event')=='notification_degraded' and x.get('source_event')==1 for x in notices),1)
