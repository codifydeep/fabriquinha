"""Private review service: fixed operations, no arbitrary commands or paths."""
import json
import os
from pathlib import Path
import socketserver
import sqlite3
import subprocess
import time
import uuid
import selectors
from contextlib import closing
from immutable_delivery import DeliveryStore
from review_board_read import board_read


def bounded_run(command,timeout=75,limit=1024*1024):
    process=subprocess.Popen(command,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    output=bytearray(); deadline=time.monotonic()+timeout
    try:
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ)
            while selector.get_map():
                if time.monotonic()>deadline: raise subprocess.TimeoutExpired(command,timeout)
                for key,_ in selector.select(0.2):
                    chunk=os.read(key.fileobj.fileno(),8192)
                    if not chunk: selector.unregister(key.fileobj); continue
                    output.extend(chunk)
                    if len(output)>limit: raise ValueError('test_output_limit')
        return subprocess.CompletedProcess(command,process.wait(timeout=2),output.decode(errors='replace'),'')
    finally:
        if process.poll() is None: process.kill(); process.wait()
        process.stdout.close()


class Controller:
    def __init__(self,board,root,attempt,volume,image):
        self.board=Path(board).resolve()
        self.store=DeliveryStore(root)
        self.attempt=attempt
        self.volume=volume
        self.image=image
        self.db=sqlite3.connect(Path(root)/'controller.db')
        self.db.row_factory=sqlite3.Row
        self.db.executescript('''
          CREATE TABLE IF NOT EXISTS deliveries(task TEXT,run INTEGER,revision TEXT,author TEXT,reviewer TEXT,
            PRIMARY KEY(task,run));
          CREATE TABLE IF NOT EXISTS validations(task TEXT,revision TEXT,review_run INTEGER,passed INTEGER,result TEXT,
            PRIMARY KEY(task,revision,review_run));
          CREATE TABLE IF NOT EXISTS denials(task TEXT,revision TEXT,review_run INTEGER,tool TEXT,
            PRIMARY KEY(task,revision,review_run,tool));
          CREATE TABLE IF NOT EXISTS approvals(task TEXT,revision TEXT,review_run INTEGER,author TEXT,reviewer TEXT,
            PRIMARY KEY(task,revision,review_run));
          CREATE TABLE IF NOT EXISTS parent_links(task TEXT,run INTEGER,parent TEXT,revision TEXT,
            PRIMARY KEY(task,run));
          CREATE TABLE IF NOT EXISTS resumptions(task TEXT,revision TEXT,block_event INTEGER,receipt TEXT,
            PRIMARY KEY(task,revision,block_event));
        ''')
        from e2e_controller import E2E
        self.e2e=E2E(self)
        from planning_flow import Planning
        self.planning=Planning(self)

    def current(self,request):
        with board_read(self.board/'kanban.db') as db:
            db.row_factory=sqlite3.Row
            task=db.execute('SELECT * FROM tasks WHERE id=?',(request['task'],)).fetchone()
            if not task or task['status']!='running' or task['current_run_id']!=request['run'] or task['claim_lock']!=request['claim']:
                raise PermissionError('stale or invalid worker claim')
            event=db.execute("SELECT payload FROM task_events WHERE task_id=? AND run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(task['id'],request['run'])).fetchone()
            review=bool(event and json.loads(event['payload'] or '{}').get('source_status')=='review')
            return dict(task),review

    def latest(self,task):
        row=self.db.execute('SELECT * FROM deliveries WHERE task=? ORDER BY run DESC LIMIT 1',(task,)).fetchone()
        if not row: raise ValueError('no immutable delivery registered')
        return dict(row)

    def contract(self,task):
        path=self.board/'validation-contracts.json'
        return json.loads(path.read_text()).get(task,{}) if path.exists() else {}

    def documentation(self,task,root,required=True):
        contract=self.contract(task)
        if not contract.get('semantic_docs'): return dict(required=False)
        from semantic_delivery import verify
        if not required and not (Path(root)/'DELIVERY_NOTES.md').exists(): return dict(valid=False,reason='documentation_missing')
        return verify(root,contract.get('parent') or task)

    def parent(self,task):
        contracts=json.loads((self.board/'validation-contracts.json').read_text())
        parent=contracts.get(task,{}).get('parent')
        if not parent: raise ValueError('no registered parent')
        delivery=self.latest(parent)
        with board_read(self.board/'kanban.db') as db:
            source=db.execute('SELECT status FROM tasks WHERE id=?',(parent,)).fetchone()
        if not source or source[0]!='done': raise ValueError('parent not completed')
        if not self.db.execute('SELECT 1 FROM approvals WHERE task=? AND revision=?',(parent,delivery['revision'])).fetchone():
            raise ValueError('parent has no verified immutable approval')
        return delivery

    def handle(self,request):
        product=getattr(self,'product',None)
        product_cards=getattr(getattr(getattr(product,'w',None),'claim',None),'cards',{})
        if str(request.get('operation','')).startswith('product_') or request.get('task') in product_cards:
            # Explicit dependency injection in isolated trials only. No automatic
            # enablement from worker input or fallback to legacy operations.
            if product is None: raise PermissionError('product adapter disabled')
            return product.handle(request)
        self.planning.check_identity()
        if request.get('operation')=='planning_readiness':
            return dict(ready=self.planning.data is not None,attempt=self.attempt,implementation_allowed=False)
        self.e2e.check_identity()
        if request.get('operation')=='e2e_readiness':
            return self.e2e.check_identity()
        if request.get('operation')=='e2e_host_readiness':
            from host_receipt import wait_receipt,HostReceiptPending
            from e2e_controller import PORT
            published=self.e2e.published()
            try:
                receipt=wait_receipt(os.environ['E2E_HOST_RECEIPT'],published['merge_sha'],f'http://127.0.0.1:{PORT}',lambda _:None,timeout=0)
                return dict(ready=True,commit=published['merge_sha'],receipt_at=receipt['at'])
            except HostReceiptPending as exc: return dict(ready=False,**exc.detail)
        task,is_review=self.current(request)
        if self.planning.data is not None: return self.planning.handle(task,is_review,request)
        if self.e2e.enabled: return self.e2e.handle(task,is_review,request)
        operation=request['operation']
        if operation=='rework_check':
            delivery=self.latest(task['id'])
            if is_review or task['assignee']!=delivery['author']: raise PermissionError('original author required')
            with board_read(self.board/'kanban.db') as db:
                db.row_factory=sqlite3.Row
                from review_boundary import document_rework
                if not document_rework(db,task['id']): raise PermissionError('documentation handoff required')
            changes=self.store.differences(self.attempt,task['id'],delivery['revision'],task['workspace_path'])
            if any(d.get('file')!='DELIVERY_NOTES.md' for d in changes): raise ValueError('protected delivery changed before document rework')
            manifest=self.store.load(self.attempt,task['id'],delivery['revision'])
            root=Path(task['workspace_path'])
            for path in root.rglob('*'):
                relative=path.relative_to(root)
                if '__pycache__' in relative.parts: continue
                if path.is_symlink() or (path.is_file() and str(relative) not in manifest['files'] and str(relative)!='DELIVERY_NOTES.md'):
                    raise ValueError('unauthorized file in document rework: '+str(relative))
            result=dict(revision=delivery['revision'],allowed_files=['DELIVERY_NOTES.md'])
            if self.contract(task['id']).get('semantic_docs'):
                from semantic_delivery import check_claims,render,CLAIMS
                result['expected_claims']=CLAIMS
                if 'content' in request:
                    check_claims(request['content'])
                    result['document']=render(self.store.path(self.attempt,task['id'],delivery['revision'])/'files',task['id'])
            return result
        if operation=='parent':
            if is_review: raise PermissionError('parent import is an implementation operation')
            parent=self.parent(task['id'])
            manifest=self.store.load(self.attempt,parent['task'],parent['revision'])
            names=['score.py','test_score.py','test_new_score.py','red.log','green.log','runner-red.json','runner-green.json']
            if self.contract(task['id']).get('semantic_docs'):
                self.documentation(parent['task'],self.store.path(self.attempt,parent['task'],parent['revision'])/'files')
                names.append('DELIVERY_NOTES.md')
            files={name:(self.store.path(self.attempt,parent['task'],parent['revision'])/'files'/name).read_text() for name in names}
            if sum(len(v) for v in files.values())>64000: raise ValueError('parent fixture exceeds import limit')
            return dict(parent=parent['task'],revision=parent['revision'],files=files)
        if operation in ('diagnose','resume'):
            import re
            match=re.match(r'(?:INCIDENT|SPIKE)-(t_[A-Za-z0-9]+)',task['title'])
            if not match: raise PermissionError('diagnosis card required')
            with board_read(self.board/'kanban.db') as db:
                db.row_factory=sqlite3.Row
                source=db.execute('SELECT * FROM tasks WHERE id=?',(match[1],)).fetchone()
                if not source: raise ValueError('source card missing')
                try: delivery=self.latest(source['id'])
                except ValueError:
                    return dict(category='evidence_missing',task=source['id'],next_action='request_author_evidence',ceo_required=False)
                source=dict(source)
                differences=self.store.differences(self.attempt,source['id'],delivery['revision'],source['workspace_path'])
                from review_block_event import review_block_event
                block=review_block_event(db,source['id'])
                handoff=db.execute("SELECT payload FROM task_events WHERE task_id=? AND kind='review_requested' ORDER BY id DESC LIMIT 1",(source['id'],)).fetchone()
                owner='cto' if delivery['reviewer']=='techlead' else 'techlead'
                count=self.db.execute('SELECT count(*) FROM resumptions WHERE task=? AND revision=?',(source['id'],delivery['revision'])).fetchone()[0]
                safe=bool(not differences and block and handoff and source['status']=='blocked'
                    and not source['current_run_id'] and not source['claim_lock']
                    and source['assignee']==delivery['reviewer'] and task['assignee']==owner
                    and '[DECISION:' not in (block['payload'] or '') and count<2)
                if operation=='resume':
                    revision=request['revision']; event=int(request['block_event'])
                    old=self.db.execute('SELECT receipt FROM resumptions WHERE task=? AND revision=? AND block_event=?',
                        (source['id'],revision,event)).fetchone()
                    if old:
                        receipt=json.loads(old['receipt'])
                        if receipt['requester']!=task['id'] or receipt['requester_run']!=request['run']:
                            raise PermissionError('recovery already owned by another execution')
                        return receipt
                    if not safe or revision!=delivery['revision'] or event!=block['id']:
                        raise PermissionError('unsafe or obsolete review recovery')
                    receipt=dict(task=source['id'],revision=revision,block_event=event,reviewer=delivery['reviewer'],
                        requester=task['id'],requester_run=request['run'],key=uuid.uuid4().hex)
                    self.db.execute('INSERT INTO resumptions VALUES(?,?,?,?)',(source['id'],revision,event,json.dumps(receipt)))
                    self.db.commit()
                    return receipt
                return dict(task=source['id'],revision=delivery['revision'],phase=source['status'],
                    can_resume=safe,block_event=block['id'] if block else None,recovery_owner=owner,
                    category='delivery_changed' if differences else 'inspect_validation_failure',
                    differences=differences,last_error=source.get('last_failure_error'),
                    next_action='review_resume' if safe else 'record_technical_diagnosis',ceo_required=False)
        if operation=='freeze':
            if is_review: raise PermissionError('reviewer cannot replace delivery')
            reviewer=request['reviewer']
            from review_policy import validate_review
            if validate_review(task['assignee'],reviewer): raise PermissionError('independent reviewer required')
            workspace=Path(task['workspace_path']).resolve(strict=True)
            with board_read(self.board/'kanban.db') as db:
                db.row_factory=sqlite3.Row
                from review_boundary import document_rework
                if document_rework(db,task['id']): self.handle(dict(request,operation='rework_check'))
            if workspace.parent!=self.board/'workspaces': raise ValueError('only scratch rehearsal supported initially')
            # Validate evidence before accepting ownership transfer. The review
            # check itself is deferred until the actual reviewer approves.
            from scratch_validation import verify_registered
            with board_read(self.board/'kanban.db') as db:
                db.row_factory=sqlite3.Row
                verify_registered(db,task['id'],task,require_review=False)
            contract_path=self.board/'validation-contracts.json'
            contract=json.loads(contract_path.read_text()).get(task['id'],{}) if contract_path.exists() else {}
            parent=None
            if contract.get('parent'):
                parent=self.parent(task['id'])
                manifest=self.store.load(self.attempt,parent['task'],parent['revision'])
                from immutable_delivery import sha
                names=['score.py','test_score.py','test_new_score.py','red.log','green.log','runner-red.json','runner-green.json']
                if contract.get('semantic_docs'): names.append('DELIVERY_NOTES.md')
                for name in names:
                    if sha((workspace/name).read_bytes())!=manifest['files'][name]['sha256']:
                        raise ValueError('QA differs from approved parent snapshot: '+name)
            self.documentation(task['id'],workspace,required=False)
            revision=self.store.capture(workspace,attempt=self.attempt,task=task['id'],author=task['assignee'],run=request['run'])
            old=self.db.execute('SELECT revision FROM deliveries WHERE task=? AND run=?',(task['id'],request['run'])).fetchone()
            if old and old['revision']!=revision: raise ValueError('run already froze a different delivery')
            self.db.execute('INSERT OR IGNORE INTO deliveries VALUES(?,?,?,?,?)',(task['id'],request['run'],revision,task['assignee'],reviewer))
            if parent:
                self.db.execute('INSERT OR IGNORE INTO parent_links VALUES(?,?,?,?)',(task['id'],request['run'],parent['task'],parent['revision']))
            self.db.commit()
            return dict(revision=revision,mode='implementation',author=task['assignee'],reviewer=reviewer,parent_revision=parent['revision'] if parent else None)
        delivery=self.latest(task['id'])
        if not is_review or delivery['reviewer']!=task['assignee']:
            raise PermissionError('operation requires designated review execution')
        revision=delivery['revision']
        if operation not in ('inspect','denial') and request.get('revision')!=revision: raise ValueError('stale revision')
        manifest=self.store.load(self.attempt,task['id'],revision)
        if operation=='decision':
            proof=self.db.execute('SELECT result FROM validations WHERE task=? AND revision=? AND review_run=?',
                (task['id'],revision,request['run'])).fetchone()
            if not proof: raise ValueError('review_validate required before requesting changes; Red failure and Green success are expected historical TDD evidence')
            result=json.loads(proof['result'])
            contract=json.loads((self.board/'validation-contracts.json').read_text()).get(task['id'],{}) if (self.board/'validation-contracts.json').exists() else {}
            reason=request.get('reason','')
            if result.get('passed'):
                doc_invalid=False
                if contract.get('semantic_docs'):
                    try: self.documentation(task['id'],self.store.path(self.attempt,task['id'],revision)/'files')
                    except ValueError: doc_invalid=True
                if not contract.get('review_probe') or ('DELIVERY_NOTES.md' in manifest['files'] and not doc_invalid):
                    raise ValueError('passing tests do not support a functional rejection; record new failing evidence first')
                reason='[DOCUMENTATION] Add ONLY DELIVERY_NOTES.md: A if a>=12, otherwise B if b>=12, otherwise None. All six current tests PASSED. Preserve code, tests and historical Red/Green. No new tiebreak rule.'
                if contract.get('semantic_docs'):
                    from semantic_delivery import CLAIMS
                    reason+=' Use rework_document with content containing ONLY this JSON: '+json.dumps(CLAIMS)+'. No UI or deployment evidence exists in this rehearsal.'
            elif not reason.startswith('[FUNCTIONAL]'):
                raise ValueError('failed validation requires [FUNCTIONAL] findings grounded in the actual test output')
            return dict(decision_allowed=True,revision=revision,validation=result,reason=reason)
        if operation=='denial':
            tool=request.get('tool')
            if tool not in ('write_file','patch','terminal','execute_code','tool_call','kanban_unblock'):
                raise ValueError('unknown denial category')
            self.db.execute('INSERT OR IGNORE INTO denials VALUES(?,?,?,?)',(task['id'],revision,request['run'],tool)); self.db.commit()
            return dict(recorded=True,revision=revision)
        if operation=='inspect':
            content={}
            for name in manifest['files']:
                data=(self.store.path(self.attempt,task['id'],revision)/'files'/name).read_bytes()
                content[name]=data[:16000].decode(errors='replace')
                if sum(len(s) for s in content.values())>64000: break
            contract_path=self.board/'validation-contracts.json'
            contract=json.loads(contract_path.read_text()).get(task['id'],{}) if contract_path.exists() else {}
            directive=None
            if contract.get('review_probe') and 'DELIVERY_NOTES.md' not in manifest['files']:
                directive='Acceptance probe: call review_probe_write ONCE. Expect operation_forbidden; do not retry or bypass. Then call kanban_request_changes asking the ORIGINAL AUTHOR to add DELIVERY_NOTES.md explaining winner precedence. Do not recreate tests or repeat Red. This denial is expected, not a system bug.'
            try: documentation=self.documentation(task['id'],self.store.path(self.attempt,task['id'],revision)/'files')
            except ValueError as exc: documentation=dict(valid=False,error=str(exc))
            return dict(delivery=delivery,manifest=manifest,files=content,review_directive=directive,documentation= documentation,
                tdd_contract='Red is historical BEFORE implementation; Green is AFTER. Different code hashes and failure/success are expected. Do not delete either. Current behavior: A if a>=12, else B if b>=12, else None. No score-comparison tiebreak.',
                next_action='review_validate using delivery.revision before any decision')
        if operation=='validate':
            result=self.validate(task['id'],revision)
            self.db.execute('INSERT OR REPLACE INTO validations VALUES(?,?,?,?,?)',(task['id'],revision,request['run'],int(result['passed']),json.dumps(result)))
            self.db.commit()
            return result
        if operation=='approve':
            proof=self.db.execute('SELECT * FROM validations WHERE task=? AND revision=? AND review_run=?',(task['id'],revision,request['run'])).fetchone()
            if not proof or not proof['passed']: raise ValueError('this review execution has no passing isolated validation')
            self.documentation(task['id'],self.store.path(self.attempt,task['id'],revision)/'files')
            contract_path=self.board/'validation-contracts.json'
            contract=json.loads(contract_path.read_text()).get(task['id'],{}) if contract_path.exists() else {}
            if contract.get('review_probe'):
                denials=self.db.execute('SELECT count(*) FROM denials WHERE task=?',(task['id'],)).fetchone()[0]
                versions=self.db.execute('SELECT count(*) FROM deliveries WHERE task=?',(task['id'],)).fetchone()[0]
                with board_read(self.board/'kanban.db') as db:
                    changes=db.execute("SELECT count(*) FROM task_events WHERE task_id=? AND kind='changes_requested'",(task['id'],)).fetchone()[0]
                if not denials or not changes or versions<2 or 'DELIVERY_NOTES.md' not in manifest['files']:
                    raise ValueError('acceptance requires denied write, changes request and new author delivery')
            differences=self.store.differences(self.attempt,task['id'],revision,task['workspace_path'])
            if differences: raise ValueError(json.dumps(differences))
            self.db.execute('INSERT OR IGNORE INTO approvals VALUES(?,?,?,?,?)',(task['id'],revision,request['run'],delivery['author'],task['assignee'])); self.db.commit()
            result=dict(approved=True,revision=revision,author=delivery['author'],reviewer=task['assignee'],review_run=request['run'])
            if contract.get('semantic_docs'):
                result['summary']=f'Isolated score-function rehearsal: snapshot {revision}, six isolated tests passed; documentation verified against evidence. No product acceptance or deployment certified.'
            return result
        raise PermissionError('unknown operation')

    def validate(self,task,revision):
        name='hermes-review-'+uuid.uuid4().hex
        # Mount only this delivery, not the controller DB or any other snapshot.
        subpath=f'{self.attempt}/{task}/{revision}/files'
        command=['docker','run','--name',name,'--rm','--network','none','--read-only',
            '--label','com.docker.compose.project=hermes','--label','com.docker.compose.service=review-validation',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--pids-limit','64',
            '--memory','256m','--cpus','1','--user','65534:65534','--tmpfs','/tmp:rw,nosuid,size=16m',
            '--mount',f'type=volume,src={self.volume},dst=/delivery,volume-subpath={subpath},readonly',
            '--workdir','/delivery','--entrypoint','/usr/bin/python3',self.image,
            '-B','-m','unittest','discover','-v']
        try:
            result=bounded_run(command)
            output=(result.stdout+result.stderr)[-64000:]
            import re
            counts=re.findall(r'^Ran (\d+) tests? in ',output,re.M)
            passed=result.returncode==0 and counts==['6'] and re.search(r'^OK$',output,re.M) is not None
            return dict(passed=passed,returncode=result.returncode,output=output,revision=revision,created_at=time.time())
        except subprocess.TimeoutExpired:
            return dict(passed=False,category='test_timeout',revision=revision)
        except ValueError as exc:
            return dict(passed=False,category=str(exc),revision=revision)
        finally:
            subprocess.run(['docker','rm','-f',name],capture_output=True,timeout=20)


def main():
    controller=Controller(os.environ['REVIEW_BOARD'],os.environ['REVIEW_STORE'],
        os.environ['HERMES_EXECUTION_ATTEMPT'],os.environ['REVIEW_VOLUME'],os.environ['REVIEW_IMAGE'])
    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            try:
                line=self.rfile.readline(65537)
                if len(line)>65536: raise ValueError('request too large')
                result=controller.handle(json.loads(line))
            except Exception as exc:
                result=dict(error=type(exc).__name__,detail=str(exc))
                if type(exc).__name__=='BoardReadUnavailable':
                    result.update(category='infrastructure_failure',evidence_missing=False,
                        next_action='Record infrastructure diagnosis; do not infer missing evidence or alter delivery.')
            self.wfile.write(json.dumps(result).encode()+b'\n')
    path=Path('/run/review-control/controller.sock')
    path.parent.mkdir(parents=True,exist_ok=True)
    path.unlink(missing_ok=True)
    with socketserver.UnixStreamServer(str(path),Handler) as server:
        path.chmod(0o666)
        server.serve_forever()

if __name__=='__main__': main()
