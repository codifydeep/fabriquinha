"""Durable cooperative coordination ledger, independent of chat/model output.

All identifiers are scoped to an execution attempt. SQLite transactions and
stable operation keys make retries safe. External effects must use these keys
too; this store does not claim exactly-once delivery from Telegram.
"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
import time

PROFILES = {'produto', 'designer', 'cto', 'techlead', 'backend_data', 'frontend',
            'mobile', 'devops', 'quality_security'}
TERMINAL = {'HOMOLOGADA', 'CANCELADA_PELO_CEO'}
EDGES = {
    'EM_DESCOBERTA': {'AGUARDANDO_APROVACAO_DO_BRIEF'},
    'AGUARDANDO_APROVACAO_DO_BRIEF': {'EM_DESCOBERTA', 'ATIVA'},
    'ATIVA': {'BLOQUEADA_AGUARDANDO_CEO', 'EM_HOMOLOGACAO'},
    'BLOQUEADA_AGUARDANDO_CEO': {'ATIVA'},
    'EM_HOMOLOGACAO': {'ATIVA', 'HOMOLOGADA', 'BLOQUEADA_AGUARDANDO_CEO'},
}


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class CoordinationStore:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=15)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS attempts(
            id TEXT PRIMARY KEY, board TEXT UNIQUE NOT NULL, version TEXT NOT NULL,
            state TEXT NOT NULL, updated_at INTEGER NOT NULL);
          CREATE UNIQUE INDEX IF NOT EXISTS one_active ON attempts((1))
            WHERE state NOT IN ('HOMOLOGADA','CANCELADA_PELO_CEO');
          CREATE TABLE IF NOT EXISTS records(
            attempt TEXT NOT NULL REFERENCES attempts(id), kind TEXT NOT NULL,
            id TEXT NOT NULL, data TEXT NOT NULL, updated_at INTEGER NOT NULL,
            PRIMARY KEY(attempt,kind,id));
          CREATE TABLE IF NOT EXISTS events(
            seq INTEGER PRIMARY KEY, attempt TEXT NOT NULL REFERENCES attempts(id),
            kind TEXT NOT NULL, item TEXT NOT NULL, data TEXT NOT NULL, at INTEGER NOT NULL);
          CREATE TABLE IF NOT EXISTS outbox(
            attempt TEXT NOT NULL REFERENCES attempts(id), id TEXT NOT NULL,
            text TEXT NOT NULL, sent_at INTEGER, PRIMARY KEY(attempt,id));
        ''')

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self, attempt=None):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            if attempt:
                row = self.db.execute('SELECT state FROM attempts WHERE id=?', (attempt,)).fetchone()
                if not row or row['state'] in TERMINAL:
                    raise ValueError('unknown, stale or terminal attempt')
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def get(self, attempt, kind, key):
        row = self.db.execute('SELECT data FROM records WHERE attempt=? AND kind=? AND id=?', (attempt, kind, key)).fetchone()
        return json.loads(row['data']) if row else None

    def _put(self, attempt, kind, key, data):
        now = int(time.time())
        self.db.execute('INSERT INTO records VALUES(?,?,?,?,?) ON CONFLICT(attempt,kind,id) DO UPDATE SET data=excluded.data,updated_at=excluded.updated_at',
                        (attempt, kind, key, encoded(data), now))
        self.db.execute('INSERT INTO events(attempt,kind,item,data,at) VALUES(?,?,?,?,?)', (attempt, kind, key, encoded(data), now))

    def create_attempt(self, attempt, board, version):
        if not all((attempt, board, version)):
            raise ValueError('attempt, board and version required')
        with self.transaction():
            existing = self.db.execute('SELECT * FROM attempts WHERE id=?', (attempt,)).fetchone()
            if existing:
                if (existing['board'], existing['version']) != (board, version):
                    raise ValueError('attempt identity conflict')
                return False
            if self.db.execute("SELECT 1 FROM attempts WHERE state NOT IN ('HOMOLOGADA','CANCELADA_PELO_CEO')").fetchone():
                raise ValueError('only one active attempt permitted')
            self.db.execute('INSERT INTO attempts VALUES(?,?,?,?,?)', (attempt, board, version, 'EM_DESCOBERTA', int(time.time())))
            return True

    def transition(self, attempt, expected, target, actor, evidence, *, notification=None):
        with self.transaction(attempt):
            actual = self.db.execute('SELECT state FROM attempts WHERE id=?', (attempt,)).fetchone()['state']
            if actual != expected:
                raise ValueError('stale release transition')
            if target == 'CANCELADA_PELO_CEO':
                if actor != 'ceo' or not evidence.get('reason'):
                    raise ValueError('explicit CEO cancellation required')
            elif target not in EDGES.get(actual, set()):
                raise ValueError('illegal release transition')
            elif target == 'ATIVA' and actual == 'AGUARDANDO_APROVACAO_DO_BRIEF':
                if actor != 'ceo' or not evidence.get('brief_sha256') or not evidence.get('criteria'):
                    raise ValueError('CEO approval bound to brief and criteria required')
                self._put(attempt, 'brief', 'approved', evidence)
            elif target == 'HOMOLOGADA':
                receipt = self.get(attempt, 'verified_receipt', evidence.get('receipt', ''))
                if actor != 'techlead' or not receipt or receipt.get('kind') != 'homologation':
                    raise ValueError('externally verified homologation receipt required')
            elif actor not in {'techlead', 'produto', 'ceo'}:
                raise ValueError('release transition requires coordinator')
            if not evidence:
                raise ValueError('transition evidence required')
            self.db.execute('UPDATE attempts SET state=?,updated_at=? WHERE id=?', (target, int(time.time()), attempt))
            self._put(attempt, 'transition', str(self.db.execute('SELECT COALESCE(MAX(seq),0)+1 FROM events').fetchone()[0]),
                      {'from': actual, 'to': target, 'actor': actor, 'evidence': evidence})
            if notification is not None:
                key,text=notification
                prior=self.db.execute('SELECT text FROM outbox WHERE attempt=? AND id=?',(attempt,key)).fetchone()
                if prior and prior['text']!=text:
                    raise ValueError('notification identity conflict')
                self.db.execute('INSERT OR IGNORE INTO outbox(attempt,id,text) VALUES(?,?,?)',(attempt,key,text))

    def handoff(self, attempt, key, task, sender, recipient, artifacts, expected, deadline):
        if sender not in PROFILES | {'system'} or recipient not in PROFILES or not artifacts or not expected or not task or deadline <= 0:
            raise ValueError('complete handoff with canonical profiles required')
        data = dict(task=task, sender=sender, recipient=recipient, artifacts=artifacts,
                    expected=expected, deadline=deadline, status='offered')
        with self.transaction(attempt):
            prior = self.get(attempt, 'handoff', key)
            if prior:
                if any(prior.get(k) != v for k, v in data.items() if k != 'status'):
                    raise ValueError('handoff idempotency conflict')
                return False
            self._put(attempt, 'handoff', key, data)
            return True

    def accept(self, attempt, key, recipient, run_id):
        with self.transaction(attempt):
            data = self.get(attempt, 'handoff', key)
            if not data or recipient != data['recipient'] or not run_id:
                raise ValueError('only assigned recipient with a live run may accept')
            if data['status'] == 'accepted':
                if data['run_id'] != run_id:
                    raise ValueError('handoff already accepted by another run')
                return False
            data.update(status='accepted', run_id=run_id)
            self._put(attempt, 'handoff', key, data)
            return True

    def incident(self, attempt, task, occurrence, owner, cause):
        if owner not in {'techlead', 'cto'} or not occurrence or not cause:
            raise ValueError('technical owner, occurrence and cause required')
        key = 'i_' + hashlib.sha256(encoded([attempt, task, occurrence]).encode()).hexdigest()[:20]
        with self.transaction(attempt):
            if not self.get(attempt, 'incident', key):
                self._put(attempt, 'incident', key, dict(task=task, occurrence=occurrence, owner=owner, cause=cause, status='open'))
        return key

    def reserve_action(self, attempt, incident, key, action, evidence):
        if not action or not evidence:
            raise ValueError('action and concrete evidence identity required')
        with self.transaction(attempt):
            if not self.get(attempt, 'incident', incident):
                raise ValueError('unknown incident')
            record = dict(incident=incident, action=action, evidence=evidence)
            prior = self.get(attempt, 'action', key)
            if prior:
                if prior != record:
                    raise ValueError('action identity conflict')
                return False
            rows = self.db.execute("SELECT data FROM records WHERE attempt=? AND kind='action'", (attempt,)).fetchall()
            if sum(json.loads(row['data']) == record for row in rows) >= 2:
                raise ValueError('retry budget exhausted; new diagnosis or SPIKE required')
            self._put(attempt, 'action', key, record)
            return True

    def question(self, attempt, key, task, owner, category, prompt, options, ceo_id, expires):
        if category not in {'business', 'user_experience', 'scope', 'credential', 'authorization', 'test_contract_exception'}:
            raise ValueError('technical decisions belong to CTO, not CEO')
        if owner not in PROFILES or not all((task, prompt, options, ceo_id, expires)):
            raise ValueError('scoped question and authorized CEO identity required')
        data = dict(task=task, owner=owner, category=category, prompt=prompt, options=options,
                    ceo_id=ceo_id, expires=expires, status='pending')
        with self.transaction(attempt):
            prior = self.get(attempt, 'question', key)
            if prior:
                if any(prior.get(k) != v for k, v in data.items() if k != 'status'):
                    raise ValueError('question identity conflict')
                return
            self._put(attempt, 'question', key, data)

    def answer(self, attempt, key, actor, answer, now):
        with self.transaction(attempt):
            data = self.get(attempt, 'question', key)
            if not data or data['ceo_id'] != actor or now > data['expires'] or not answer:
                raise ValueError('unknown, unauthorized or expired decision')
            if data['status'] == 'answered':
                if data['answer'] != answer:
                    raise ValueError('decision already answered differently')
                return False
            data.update(status='answered', answer=answer, answered_at=now)
            self._put(attempt, 'question', key, data)
            # Deliberately no Kanban unblock or permission grant here.
            return True

    def enqueue(self, attempt, key, text):
        with self.transaction(attempt):
            prior = self.db.execute('SELECT text FROM outbox WHERE attempt=? AND id=?', (attempt, key)).fetchone()
            if prior and prior['text'] != text:
                raise ValueError('notification identity conflict')
            self.db.execute('INSERT OR IGNORE INTO outbox(attempt,id,text) VALUES(?,?,?)', (attempt, key, text))

    def pending(self, attempt):
        return [dict(row) for row in self.db.execute('SELECT id,text FROM outbox WHERE attempt=? AND sent_at IS NULL ORDER BY rowid', (attempt,))]

    def sent(self, attempt, key):
        # A terminal release still has a final notification to deliver. Only
        # acknowledge an existing scoped envelope; no new operational action.
        with self.transaction():
            self.db.execute('UPDATE outbox SET sent_at=? WHERE attempt=? AND id=? AND sent_at IS NULL', (int(time.time()), attempt, key))
