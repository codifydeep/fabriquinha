"""Opt-in product handlers. Controller-owned DB, runner and identity provider only.

Submission commits evidence and an outbox together. Native board dispatch is a
separate consumer; a prepared handoff is never reported as delivered or approved.
"""
import json
import hashlib
import re
from product_workspace import digest


class ProductController:
    def __init__(self, workspace, tdd, runner):
        self.w = workspace
        self.tdd = tdd
        self.runner = runner
        self.db = workspace.db
        self.db.execute('''CREATE TABLE IF NOT EXISTS product_handoffs(
            attempt TEXT, task TEXT, run INTEGER, version INTEGER,
            revision TEXT, envelope TEXT, state TEXT,
            PRIMARY KEY(attempt,task,run,version))''')
        self.db.commit()

        self.db.execute('''CREATE TABLE IF NOT EXISTS product_verdicts(
            attempt TEXT, task TEXT, review_run INTEGER, envelope TEXT, state TEXT,
            PRIMARY KEY(attempt,task,review_run))''')
        self.db.commit()
        self.db.execute('''CREATE TABLE IF NOT EXISTS product_review_tests(
            attempt TEXT, task TEXT, revision TEXT, review_run INTEGER, receipt TEXT,
            PRIMARY KEY(attempt,task,revision,review_run))''')
        self.db.commit()

    def handle(self, request):
        operation = request.get('operation')
        fields = {
            'product_status': set(),
            'product_read': set(),
            'product_read_file': {'path','offset','revision'},
            'product_read_reference': {'path','offset'},
            'product_edit': {'version', 'sha256', 'replacements'},
            'product_remove_empty_artifact': {'version','sha256','path','reason'},
            'product_test': {'phase'},
            'product_submit': {'version'},
            'product_inspect': {'revision'},
            'product_review_test': {'revision'},
            'product_verdict': {'revision', 'decision', 'reason'},
        }
        if operation not in fields:
            raise PermissionError('unregistered product operation')
        if set(request) - (fields[operation] | {'operation', 'attempt', 'task', 'run', 'claim'}):
            raise PermissionError('unregistered arguments')
        if operation == 'product_status':
            current,_=self.w.state(request)
            verdict=self.db.execute('SELECT envelope FROM product_verdicts WHERE attempt=? AND task=? AND state=? ORDER BY review_run DESC LIMIT 1',(current['attempt'],current['task'],'DELIVERED')).fetchone()
            latest=self.db.execute('SELECT revision,state FROM product_handoffs WHERE attempt=? AND task=? ORDER BY rowid DESC LIMIT 1',
                                   (current['attempt'],current['task'])).fetchone()
            return dict(task=current['task'],mode=current['mode'],revision=latest[0] if latest else None,
                        latest_review=json.loads(verdict[0]) if verdict else None,
                        handoff_state=latest[1] if latest else None,release_homologated=False)
        if operation == 'product_read':
            from product_reading import compact
            result=self.w.read_draft(request)
            return dict(result,**compact(result['files']))
        if operation=='product_read_reference':
            current,_=self.w.state(request,write=True)
            from product_reading import page
            return dict(page(self.w.claim.cards[current['task']].get('reference_delivery',{}),request['path'],request['offset']),historical=True,authority=False)
        if operation == 'product_read_file':
            from product_reading import page
            current,_=self.w.state(request)
            if current['mode']=='review':
                files=self.w.inspect(request,request['revision']);identity=dict(revision=request['revision'])
            else:
                if request['revision']:raise PermissionError('author reads current draft only')
                draft=self.w.read_draft(request);files=draft['files'];identity={k:draft[k] for k in ('version','sha256')}
            return dict(page(files,request['path'],request['offset']),delivery=identity)
        if operation in ('product_edit','product_remove_empty_artifact'):
            current, _ = self.w.state(request, write=True)
            if self.db.execute('SELECT 1 FROM product_handoffs WHERE attempt=? AND task=? AND run=?',
                               (current['attempt'], current['task'], current['run'])).fetchone():
                raise PermissionError('submitted execution is sealed')
            if operation=='product_remove_empty_artifact':
                return self.w.remove_empty_artifact(request,request['version'],request['sha256'],request['path'],request['reason'])
            return self.w.edit(request, request['version'], request['sha256'], request['replacements'])
        if operation == 'product_test':
            return self.tdd.execute(request, request['phase'], self.runner)
        if operation == 'product_inspect':
            from product_reading import compact
            return compact(self.w.inspect(request, request['revision']))
        if operation == 'product_review_test':
            return self.review_test(request)
        if operation == 'product_verdict':
            return self.verdict(request)
        return self.submit(request)

    def verdict(self, request):
        decision=request.get('decision');reason=request.get('reason')
        if decision not in ('approve','request_changes') or not isinstance(reason,str) or not 10<=len(reason.strip())<=4000:
            raise ValueError('explicit decision and substantive reason required')
        with self.db:
            files=self.w.inspect(request,request['revision']);current,_=self.w.state(request)
            latest=self.db.execute('SELECT revision,envelope,state FROM product_handoffs WHERE attempt=? AND task=? ORDER BY rowid DESC LIMIT 1',
                                   (current['attempt'],current['task'])).fetchone()
            if not latest or latest[0]!=request['revision'] or latest[2]!='DELIVERED':
                raise PermissionError('latest delivered revision required')
            delivery=json.loads(latest[1]);key=(current['attempt'],current['task'],current['run'])
            if digest(files)!=delivery['suite']['source_sha256']:
                raise PermissionError('snapshot integrity mismatch')
            proof=None
            if decision=='approve':
                row=self.db.execute('SELECT receipt FROM product_review_tests WHERE attempt=? AND task=? AND revision=? AND review_run=?',
                                    (key[0],key[1],request['revision'],key[2])).fetchone()
                proof=json.loads(row[0]) if row else None
                if not proof or not proof['passed'] or proof['image']!=self.tdd.image or proof['source_sha256']!=digest(files) or proof['reviewer']!=current['profile']:
                    raise PermissionError('same-revision independent validation required')
            envelope=dict(attempt=key[0],task=key[1],review_run=key[2],revision=request['revision'],
                          author=delivery['author'],reviewer=current['profile'],decision=decision,reason=reason.strip(),
                          validation_sha256=digest(proof) if proof else None,release_homologated=False)
            prior=self.db.execute('SELECT envelope FROM product_verdicts WHERE attempt=? AND task=? AND review_run=?',key).fetchone()
            if prior and json.loads(prior[0])!=envelope:
                raise PermissionError('review execution already has a different verdict')
            self.db.execute('INSERT OR IGNORE INTO product_verdicts VALUES(?,?,?,?,?)',(*key,json.dumps(envelope),'PREPARED'))
        return envelope

    def review_test(self, request):
        files = self.w.inspect(request, request['revision'])
        current, _ = self.w.state(request)
        latest = self.db.execute('SELECT revision,envelope,state FROM product_handoffs WHERE attempt=? AND task=? ORDER BY rowid DESC LIMIT 1',
                                 (current['attempt'], current['task'])).fetchone()
        if not latest or latest[0] != request['revision'] or latest[2] != 'DELIVERED':
            raise PermissionError('latest delivered revision required')
        envelope = json.loads(latest[1])
        if envelope['reviewer'] != current['profile'] or digest(files) != envelope['suite']['source_sha256']:
            raise PermissionError('delivery provenance mismatch')
        key = (current['attempt'], current['task'], request['revision'], current['run'])
        previous = self.db.execute('SELECT receipt FROM product_review_tests WHERE attempt=? AND task=? AND revision=? AND review_run=?', key).fetchone()
        if previous:
            return json.loads(previous[0])
        result = self.runner(files, self.tdd.image)
        if self.w.inspect(request, request['revision']) != files:
            raise PermissionError('snapshot changed during review')
        expected = {n: hashlib.sha256(v.encode()).hexdigest() for n,v in files.items()}
        if result.get('snapshot') != expected or result.get('image') != self.tdd.image:
            raise PermissionError('review runner source/image mismatch')
        output = result.get('output', '')
        counts = re.findall(r'^# tests (\d+)$', output, re.M)
        failures = re.findall(r'^# fail (\d+)$', output, re.M)
        ignored = re.findall(r'^# (?:skipped|cancelled|todo) (\d+)$', output, re.M)
        passed = result['exit_code'] == 0 and len(counts) == len(failures) == 1 and int(counts[0]) > 0 and int(failures[0]) == 0 and not any(map(int, ignored))
        receipt = dict(attempt=current['attempt'], task=current['task'], revision=request['revision'],
                       review_run=current['run'], reviewer=current['profile'], author=envelope['author'],
                       image=self.tdd.image, source_sha256=digest(files), passed=passed,
                       log_sha256=result.get('log_sha256') or hashlib.sha256(output.encode()).hexdigest(),
                       output=output[-12000:], approved=False)
        with self.db:
            self.db.execute('INSERT INTO product_review_tests VALUES(?,?,?,?,?)', (*key, json.dumps(receipt)))
        return receipt

    def submit(self, request):
        # No nested Workspace.freeze(): its context manager would commit early.
        self.db.execute('BEGIN IMMEDIATE')
        try:
            current, row = self.w.state(request, write=True)
            if request['version'] != row[2]:
                raise ValueError('stale submission')
            proof = self.tdd.submission_evidence(request)
            if proof['run'] != current['run'] or proof['version'] != row[2] or proof['base'] != row[1]:
                raise PermissionError('same-execution full-suite receipt required')
            key = (current['attempt'], current['task'], current['run'], row[2])
            previous = self.db.execute('SELECT envelope FROM product_handoffs WHERE attempt=? AND task=? AND run=? AND version=?', key).fetchone()
            if previous:
                self.db.commit()
                return json.loads(previous[0])
            files = json.loads(row[3])
            revision = digest(dict(attempt=current['attempt'], task=current['task'], run=current['run'], base=row[1], files=files))
            envelope = dict(attempt=current['attempt'], task=current['task'], run=current['run'],
                            version=row[2], revision=revision, author=row[0], reviewer=row[5],
                            base=row[1], suite=proof, evidence_sha256=digest(proof),
                            state='PREPARED', handed_off=False, approved=False)
            self.db.execute('INSERT OR IGNORE INTO product_submissions VALUES(?,?,?,?,?,?)', (*key, revision, row[3]))
            self.db.execute('INSERT INTO product_handoffs VALUES(?,?,?,?,?,?,?)', (*key, revision, json.dumps(envelope), 'PREPARED'))
            self.w.state(request, write=True)
            self.db.commit()
            return envelope
        except BaseException:
            self.db.rollback()
            raise
