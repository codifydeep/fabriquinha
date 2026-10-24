"""Durable, model-free notifications; uncertainty never authorizes blind resend."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.artifacts import Store
from fabriquinha.config import Project
from fabriquinha.board import Run
from fabriquinha.quality import Quality
from fabriquinha.notifications import Outbox, Transport, RetryLater, Rejected, alerts
from fabriquinha.effects import write_json
from test_delivery_core import configuration


class NotificationDelivery(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name).resolve();self.project=Project.parse(configuration())
        self.store=Store(self.root/'private');self.clock=[1000.0]
        self.outbox=Outbox(self.project,self.store,clock=lambda:self.clock[0])

    def message(self,key='one'):
        return self.outbox.enqueue(key,dict(task='t_12345678',run=1,actor='backend',mode='tests',event='started',
            text='backend iniciou testes em t_12345678'))

    def test_known_nonacceptance_retries_after_restart_but_does_not_duplicate(self):
        key=self.message();attempts=[]
        class Transport:
            destination='local-test'
            def send(self,message,key):
                attempts.append(key)
                if len(attempts)==1:raise RetryLater(5)
                return {'message_id':7}
            def observe(self,key):return None
        transport=Transport();self.outbox.flush(transport)
        self.assertEqual(self.outbox.summary()['queued'],1)
        self.clock[0]+=6
        restored=Outbox(self.project,self.store,clock=lambda:self.clock[0]);restored.flush(transport)
        restored.flush(transport)
        self.assertEqual(restored.summary()['delivered'],1);self.assertEqual(attempts,[key,key])

    def test_lost_ack_observes_the_same_message_never_sends_again(self):
        key=self.message();sent=[]
        class Transport:
            destination='local-test'
            def send(self,message,key):sent.append(key);raise TimeoutError('accepted but response lost')
            def observe(self,key):return {'message_id':9}
        transport=Transport();self.outbox.flush(transport)
        self.assertEqual(self.outbox.summary()['uncertain'],1)
        self.clock[0]+=31
        restored=Outbox(self.project,self.store,clock=lambda:self.clock[0]);restored.flush(transport)
        self.assertEqual(sent,[key]);self.assertEqual(restored.summary()['delivered'],1)

    def test_unobservable_telegram_ack_remains_visible_without_resend(self):
        self.message();sent=[]
        class Transport:
            destination='telegram-test'
            def send(self,message,key):sent.append(key);raise TimeoutError()
            def observe(self,key):return None
        transport=Transport();self.outbox.flush(transport);self.clock[0]+=31
        self.outbox.flush(transport)
        self.assertEqual(len(sent),1);self.assertEqual(self.outbox.summary()['uncertain'],1)

    def test_rejected_credentials_are_visible_not_retried_forever(self):
        self.message();sent=[]
        class Transport:
            destination='telegram-test'
            def send(self,message,key):sent.append(key);raise Rejected()
            def observe(self,key):return None
        transport=Transport();self.outbox.flush(transport);self.clock[0]+=1000;self.outbox.flush(transport)
        self.assertEqual(len(sent),1);self.assertEqual(self.outbox.summary()['rejected'],1)

    def test_historical_events_are_not_replayed_and_start_is_deduplicated_by_run(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;self.addCleanup(conn.close)
        conn.executescript('CREATE TABLE tasks(id,assignee,body);CREATE TABLE task_runs(id,profile);'
            'CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id,run_id,kind,payload,created_at);'
            "INSERT INTO tasks VALUES('t_12345678','lead','{\"kind\":\"tests\"}');"
            "INSERT INTO task_runs VALUES(1,'backend');"
            "INSERT INTO task_events VALUES(1,'t_12345678',1,'claimed','{\"source_status\":\"ready\"}',900);")
        self.outbox.capture(conn)
        self.assertEqual(self.outbox.summary()['queued'],0)
        conn.execute("INSERT INTO task_events VALUES(2,'t_12345678',1,'spawned','{}',901)")
        conn.execute("INSERT INTO task_events VALUES(3,'t_12345678',1,'worker_registered','{}',901)")
        self.outbox.capture(conn);self.outbox.capture(conn)
        self.assertEqual(self.outbox.summary()['queued'],1)
        records=self.outbox.records()
        self.assertEqual(records[0]['message']['actor'],'backend')
        self.assertNotIn('lead',records[0]['message']['text'])

    def test_alerts_use_validation_evidence_not_heartbeat_and_dedupe_by_evidence(self):
        cards=[dict(id='t_12345678',status='ready',assignee='backend',current_run_id=None,
            last_event_at=0,created_at=0,last_heartbeat_at=99999)]
        self.clock[0]=601
        alerts(self.outbox,cards,self.store,now=self.clock[0]);alerts(self.outbox,cards,self.store,now=self.clock[0])
        self.assertEqual(self.outbox.summary()['queued'],1)
        self.clock[0]=1801;alerts(self.outbox,cards,self.store,now=self.clock[0])
        self.assertEqual(self.outbox.summary()['queued'],2)
        self.assertEqual({r['message']['event'] for r in self.outbox.records()},{'unattended','stalled'})

    def test_pending_business_response_is_not_a_technical_cto_stall(self):
        card=dict(id='t_12345678',status='review',assignee='fabriquinha-ceo',current_run_id=None,
            last_event_at=0,created_at=0,business_input=dict(request='a'*64))
        self.clock[0]=2000
        alerts(self.outbox,[card],self.store,now=2000)
        records=self.outbox.records()
        self.assertEqual(len(records),1)
        self.assertEqual(records[0]['message']['event'],'business_input_pending')
        self.assertEqual(records[0]['message']['actor'],'ceo')
        self.assertNotIn('Technical owner',records[0]['message']['text'])

    def test_repeated_same_validation_job_cannot_keep_refreshing_progress(self):
        board=Mock();quality=Quality(self.project,self.store,None,board)
        run=Run('t_12345678',1,'backend','tests',False,'backend','v1','contract')
        path=self.store.root/'progress/t_12345678-1.json'
        quality.record(run,'green',dict(job='unobserved'))
        self.assertFalse(path.exists())
        quality.observed_jobs.add('observed')
        with patch('fabriquinha.quality.time.time',return_value=10):
            quality.record(run,'green',dict(job='observed'))
        with patch('fabriquinha.quality.time.time',return_value=20):
            quality.record(run,'diagnostic_experiment',dict(job='observed',hypothesis='Only prose changed'))
        self.assertEqual(json.loads(path.read_bytes())['at'],10)
        quality.observed_jobs.add('new-job')
        with patch('fabriquinha.quality.time.time',return_value=30):
            quality.record(run,'green',dict(job='new-job'))
        self.assertEqual(json.loads(path.read_bytes())['at'],30)

    def test_monitor_projection_failure_cannot_invalidate_a_durable_quality_receipt(self):
        quality=Quality(self.project,self.store,None,Mock());quality.observed_jobs.add('observed')
        run=Run('t_12345678',1,'backend','tests',False,'backend','v1','contract')
        with patch('fabriquinha.quality.write_json',side_effect=OSError('projection unavailable')):
            receipt=quality.record(run,'green',dict(job='observed'))
        self.assertEqual(self.store.receipt(receipt,kind='green')['binding'],run.binding())

    def test_production_transport_uses_fixed_https_no_paid_broadcast_or_redirects(self):
        config=configuration();config['qualification']=False;project=Project.parse(config)
        path=self.root/'notifications.json'
        write_json(path,dict(transport='telegram',bot_token='12345678:'+('A'*35),chat_id='-123',thread_id=1))
        transport=Transport(project,path)
        with patch('fabriquinha.notifications.http.client.HTTPSConnection') as factory:
            connection=factory.return_value
            response=connection.getresponse.return_value;response.status=200
            response.read.return_value=b'{"ok":true,"result":{"message_id":7}}'
            self.assertEqual(transport.send({'text':'status'},'key'),{'message_id':7})
            self.assertEqual(factory.call_args.args,('api.telegram.org',))
            sent=json.loads(connection.request.call_args.args[2])
            self.assertFalse(sent['allow_paid_broadcast']);self.assertNotIn('parse_mode',sent)
            response.status=302
            with self.assertRaises(ValueError):transport.send({'text':'status'},'key')
            self.assertEqual(factory.call_count,2)  # One connection per call, never a redirect follow.
        with self.assertRaises(ValueError):Transport(self.project,path)

    def test_connection_refusal_is_retryable_but_429_respects_retry_after(self):
        path=self.root/'notifications.json';write_json(path,dict(transport='local',endpoint='http://127.0.0.1:12345'))
        transport=Transport(self.project,path)
        with patch('fabriquinha.notifications.http.client.HTTPConnection') as factory:
            connection=factory.return_value;connection.connect.side_effect=ConnectionRefusedError()
            with self.assertRaises(RetryLater):transport.send({'text':'status'},'key')
            connection.request.assert_not_called()
            connection.connect.side_effect=None
            response=connection.getresponse.return_value;response.status=429
            response.read.return_value=b'{"ok":false,"parameters":{"retry_after":17}}'
            with self.assertRaises(RetryLater) as error:transport.send({'text':'status'},'key')
            self.assertEqual(error.exception.seconds,17)

    def test_invalid_local_route_and_public_secret_file_are_refused(self):
        path=self.root/'notifications.json';write_json(path,dict(transport='local',endpoint='http://example.com'))
        with self.assertRaises(ValueError):Transport(self.project,path)
        write_json(path,dict(transport='local',endpoint='http://127.0.0.1:12345'));path.chmod(0o644)
        with self.assertRaises(ValueError):Transport(self.project,path)

    def test_valid_new_job_suppresses_alert_not_an_arbitrary_heartbeat(self):
        quality=Quality(self.project,self.store,None,Mock());quality.observed_jobs.add('observed')
        run=Run('t_12345678',1,'backend','tests',False,'backend','v1','contract')
        with patch('fabriquinha.quality.time.time',return_value=1000):quality.record(run,'green',dict(job='observed'))
        card=dict(id=run.task,status='running',assignee='backend',current_run_id=1,run_started_at=0,
            created_at=0,last_event_at=1,last_heartbeat_at=999999,contract=run.contract)
        alerts(self.outbox,[card],self.store,now=1100)
        self.assertEqual(self.outbox.summary()['queued'],0)
        alerts(self.outbox,[card],self.store,now=1601)
        self.assertEqual(self.outbox.summary()['queued'],1)

    def test_destination_change_cannot_forward_old_uncertain_messages(self):
        self.message();sent=[]
        class Transport:
            destination='old-target'
            def send(self,message,key):sent.append(key);raise TimeoutError()
            def observe(self,key):return None
        transport=Transport();self.outbox.flush(transport);self.clock[0]+=31
        transport.destination='new-target';self.outbox.flush(transport)
        self.assertEqual(len(sent),1);self.assertEqual(self.outbox.summary()['rejected'],1)

    def test_rate_limit_defers_whole_destination_not_each_message_individually(self):
        self.message();self.message('two');attempts=[]
        class Transport:
            destination='local-test'
            def send(self,message,key):attempts.append(key);raise RetryLater(7200)
            def observe(self,key):return None
        transport=Transport();self.outbox.flush(transport);self.outbox.flush(transport)
        self.clock[0]+=3600;self.outbox.flush(transport)
        self.assertEqual(len(attempts),1)
        self.assertEqual(self.outbox.summary()['queued'],2)

    def test_board_reset_cannot_silently_reuse_the_outbox_cursor(self):
        conn=sqlite3.connect(':memory:');conn.row_factory=sqlite3.Row;self.addCleanup(conn.close)
        conn.executescript('CREATE TABLE tasks(id,assignee,body);CREATE TABLE task_runs(id,profile);'
            'CREATE TABLE task_events(id INTEGER PRIMARY KEY,task_id,run_id,kind,payload,created_at);'
            "INSERT INTO task_events VALUES(1,'t_12345678',NULL,'created','{}',900);")
        self.outbox.capture(conn)
        conn.execute("UPDATE task_events SET task_id='t_87654321' WHERE id=1")
        with self.assertRaisesRegex(ValueError,'history changed'):self.outbox.capture(conn)

    def test_corrupt_queue_record_is_visible_without_breaking_controller_status(self):
        key=self.message();write_json(self.outbox.root/(key+'.json'),{})
        self.assertEqual(self.outbox.summary()['corrupt'],1)
        self.assertEqual(self.outbox.summary()['queued'],0)


if __name__=='__main__':unittest.main()
