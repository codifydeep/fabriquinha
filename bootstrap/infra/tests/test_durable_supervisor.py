import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from coordination_store import CoordinationStore
import durable_supervisor


class SupervisorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = CoordinationStore(Path(self.tmp.name) / 'coord.db')
        self.addCleanup(self.store.close)
        self.store.create_attempt('r2', 'board2', 'v0.1')
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
          CREATE TABLE tasks(id TEXT PRIMARY KEY,title TEXT,status TEXT,assignee TEXT,current_run_id INTEGER);
          CREATE TABLE task_events(id INTEGER PRIMARY KEY, task_id TEXT,kind TEXT,payload TEXT);
          INSERT INTO tasks VALUES('t_123abc','PLAN','blocked','techlead',NULL);
          INSERT INTO task_events VALUES(1,'t_123abc','blocked','{"reason":"technical failure"}');
        ''')
        self.config = dict(attempt='r2', board='board2')
        self.calls = []
        self.keys = {}

    def cli(self, config, *args):
        self.calls.append(args)
        if args[0] == 'create':
            key = args[args.index('--idempotency-key') + 1]
            if key not in self.keys:
                task = 't_' + str(len(self.keys) + 200)
                self.keys[key] = task
                self.db.execute('INSERT INTO tasks VALUES(?,?,?,?,NULL)',
                                (task,args[1],'ready',args[args.index('--assignee')+1]))
            return json.dumps({'id': self.keys[key]})
        if args[0] == 'schedule':
            self.db.execute("UPDATE tasks SET status='scheduled' WHERE id=?", (args[1],))
        if args[0] == 'unblock':
            self.db.execute("UPDATE tasks SET status='ready' WHERE id=?", (args[1],))
        if args[0] == 'promote':
            self.db.execute("UPDATE tasks SET status='ready' WHERE id=?", (args[1],))
        if args[0] == 'archive':
            self.db.execute("UPDATE tasks SET status='archived' WHERE id=?", (args[1],))
        if args[0] == 'complete':
            status=self.db.execute('SELECT status FROM tasks WHERE id=?',(args[1],)).fetchone()[0]
            if status not in ('ready','blocked','review','running'):
                raise RuntimeError('native completion refuses '+status)
            self.db.execute("UPDATE tasks SET status='done' WHERE id=?",(args[1],))
        return ''

    def test_triaged_incident_closes_once_after_verified_delivery(self):
        self.tick(100)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.db.execute("UPDATE tasks SET status='triage' WHERE id=?",(record['native_task'],))
        self.db.execute("UPDATE tasks SET status='done' WHERE id='t_123abc'")
        self.tick(101); self.tick(102)
        self.assertEqual(sum(c[0]=='promote' for c in self.calls),1)
        self.assertEqual(sum(c[0]=='complete' for c in self.calls),1)
        updated=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.assertEqual(updated['status'],'resolved')

    def test_superseded_diagnosis_archived_once_not_completed(self):
        self.tick(100)
        row=self.store.db.execute("SELECT id,data FROM records WHERE kind='incident'").fetchone()
        record=json.loads(row['data']);record['status']='superseded'
        durable_supervisor._save(self.store,'r2',row['id'],record)
        self.db.execute("UPDATE tasks SET status='done' WHERE id='t_123abc'")
        self.db.execute("UPDATE tasks SET status='triage' WHERE id=?",(record['native_task'],))
        self.tick(101);self.tick(102)
        self.assertEqual(sum(c[0]=='archive' for c in self.calls),1)
        self.assertEqual(sum(c[0]=='complete' for c in self.calls),0)

    def test_restart_after_native_completion_only_reconciles_record(self):
        self.tick(100)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.db.execute("UPDATE tasks SET status='done'")
        self.tick(101); self.tick(102)
        self.assertFalse(any(c[0]=='complete' for c in self.calls))
        updated=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.assertEqual(updated['status'],'resolved')

    def test_resolved_incident_archives_failed_spike_without_approval(self):
        self.tick(100); self.tick(1901)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.db.execute("UPDATE tasks SET status='done' WHERE id='t_123abc'")
        self.db.execute("UPDATE tasks SET status='blocked' WHERE id=?",(record['spike'],))
        self.tick(1902); self.tick(1903); self.tick(1904)
        self.assertEqual(self.db.execute('SELECT status FROM tasks WHERE id=?',(record['spike'],)).fetchone()[0],'archived')
        self.assertEqual(sum(c[0]=='archive' for c in self.calls),1)
        self.assertFalse(any(c[:2]==('complete',record['spike']) for c in self.calls))

    def tick(self, now):
        with patch.object(durable_supervisor, 'cli', self.cli), patch.object(durable_supervisor,'recover_triage',lambda config,task:self.cli(config,'promote',task['id'])):
            return durable_supervisor.tick(self.db,self.config,self.store,now,lambda *_: None)

    def test_cto_timeout_creates_real_spike_once(self):
        self.tick(100)
        self.tick(1901)
        self.tick(1902)
        titles = [args[1] for args in self.calls if args[0] == 'create']
        self.assertEqual(sum(title.startswith('INCIDENT-') for title in titles), 1)
        self.assertEqual(sum(title.startswith('SPIKE-') for title in titles), 1)
        self.assertTrue(any(args[0] == 'schedule' for args in self.calls))

    def test_ready_is_not_resolution(self):
        self.tick(100)
        self.db.execute("UPDATE tasks SET status='ready' WHERE id='t_123abc'")
        self.tick(101)
        records = self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchall()
        self.assertFalse(any(json.loads(row['data'])['status'] == 'resolved' for row in records))

    def test_done_source_does_not_close_incident_before_qa(self):
        self.tick(100)
        self.db.execute("UPDATE tasks SET status='done' WHERE id='t_123abc'")
        with patch('incident_completion.completion_error',return_value='awaiting verified completion: qa'):
            self.tick(101); self.tick(4000)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.assertNotEqual(record['status'],'resolved')
        self.assertEqual(record['stage'],'awaiting_verification')
        self.assertFalse(any(c[0]=='complete' for c in self.calls))
        self.assertFalse(any(c[0]=='create' and c[1].startswith('SPIKE-') for c in self.calls))
        self.tick(4001)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.assertEqual(record['status'],'resolved')

    def test_iteration_error_reaches_diagnosis(self):
        self.db.execute("UPDATE task_events SET kind='gave_up',payload=?",(json.dumps({'error':'Iteration budget exhausted (40/40)'}),))
        self.tick(100)
        created=next(c for c in self.calls if c[0]=='create')
        self.assertIn('Iteration budget exhausted',created[created.index('--body')+1])

    def test_new_block_event_creates_distinct_occurrence(self):
        self.tick(100)
        self.db.execute("INSERT INTO task_events VALUES(2,'t_123abc','blocked','{}')")
        self.tick(101)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM records WHERE kind='incident'").fetchone()[0], 2)

    def test_failed_spike_reactivates_triaged_diagnosis_once(self):
        self.tick(100)
        self.tick(1901)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.db.execute("UPDATE tasks SET status='blocked' WHERE id=?",(record['spike'],))
        self.db.execute("UPDATE tasks SET status='triage' WHERE id=?",(record['native_task'],))
        self.tick(1902)
        self.tick(1903)
        self.assertEqual(self.db.execute('SELECT status FROM tasks WHERE id=?',(record['native_task'],)).fetchone()[0],'ready')
        self.assertEqual(sum(c[0]=='promote' for c in self.calls),1)
        updated=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.assertEqual(updated['stage'],'verification')
        self.assertNotEqual(updated['status'],'resolved')

    def test_failed_reactivation_does_not_repeat_side_effects(self):
        self.tick(100); self.tick(1901)
        record=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.db.execute("UPDATE tasks SET status='blocked' WHERE id=?",(record['spike'],))
        self.db.execute("UPDATE tasks SET status='triage' WHERE id=?",(record['native_task'],))
        original=self.cli
        def fail(config,*args):
            if args[0]=='promote':
                self.calls.append(args)
                raise RuntimeError('simulated native refusal')
            return original(config,*args)
        with patch.object(durable_supervisor,'cli',fail), patch.object(durable_supervisor,'recover_triage',lambda config,task:fail(config,'promote',task['id'])):
            for now in range(1902,2002):
                durable_supervisor.tick(self.db,self.config,self.store,now,lambda *_: None)
        self.assertEqual(sum(c[0]=='promote' for c in self.calls),1)
        self.assertEqual(sum(c[0]=='comment' for c in self.calls),1)
        updated=json.loads(self.store.db.execute("SELECT data FROM records WHERE kind='incident'").fetchone()[0])
        self.assertEqual(updated['stage'],'recovery_failed')
        self.assertNotEqual(updated['status'],'resolved')
