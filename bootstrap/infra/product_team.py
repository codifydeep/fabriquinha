"""Evidence-bound technical decisions. No shell, credentials or implicit merge."""
import json,hashlib
from pathlib import Path
from product_workspace import digest

def refresh_manifest(packet):
    files=packet['files'];name='.hermes/team/generated-manifest.json'
    manifest=json.loads(files[name]);before=dict(manifest['files'])
    targets=packet.get('refreshable',[])
    if not targets or any(n not in before or n not in files for n in targets):raise ValueError('unregistered generated artifact')
    for n in targets:manifest['files'][n]=hashlib.sha256(files[n].encode()).hexdigest()
    if before==manifest['files']:raise ValueError('no generated drift')
    return {name:json.dumps(manifest,indent=2,ensure_ascii=False)+'\n'}

class Team:
    def __init__(self,root,binding,native,db,runner=None,governance_runner=None,governance_image=None):
        self.root=Path(root);self.binding=binding;self.native=native;self.db=db;self.runner=runner
        self.governance_runner=governance_runner;self.governance_image=governance_image
        db.execute('CREATE TABLE IF NOT EXISTS team_decisions(task TEXT PRIMARY KEY,proposal TEXT,verdict TEXT,state TEXT)');db.commit()
        db.execute('CREATE TABLE IF NOT EXISTS team_decision_history(task TEXT,proposal TEXT,verdict TEXT)');db.commit()
        db.execute('CREATE TABLE IF NOT EXISTS team_validation_errors(task TEXT,run INTEGER,proposal_sha TEXT,diagnostic TEXT,PRIMARY KEY(task,run,proposal_sha))');db.commit()
        db.execute('CREATE TABLE IF NOT EXISTS governance_validation(task TEXT,run INTEGER,proposal_sha TEXT,receipt TEXT,PRIMARY KEY(task,run,proposal_sha))');db.commit()
    def packet(self,task):
        raw=(self.root/'team-packets'/f'{task}.json').read_bytes()
        if hashlib.sha256(raw).hexdigest()!=self.binding.cards[task]['packet_sha256']:raise PermissionError('packet drift')
        return json.loads(raw)
    def handle(self,req):
        who=self.binding(req);task=who['task'];packet=self.packet(task)
        op=req['operation'];row=self.db.execute('SELECT proposal,verdict,state FROM team_decisions WHERE task=?',(task,)).fetchone()
        identity={'attempt','task','run','claim','operation'}
        if op in ('team_read_file','team_read_proposal_file'):
            if set(req)!=identity|{'path','offset'}:raise ValueError('exact read arguments required')
            from product_reading import page
            if op=='team_read_proposal_file':
                if not row:raise PermissionError('no current immutable proposal')
                p=json.loads(row[0]);files=p.get('changes',{}) or p.get('specification',{}).get('replacements',{})
            else:files=packet.get('files',{})
            return page(files,req['path'],req['offset'])
        if op=='team_status':
            if set(req)!=identity:raise ValueError('exact arguments required')
            prior=self.db.execute('SELECT verdict FROM team_decision_history WHERE task=? ORDER BY rowid DESC LIMIT 1',(task,)).fetchone()
            verdict=row[1] if row and row[1] else prior[0] if prior else None
            error=self.db.execute('SELECT diagnostic FROM team_validation_errors WHERE task=? ORDER BY run DESC LIMIT 1',(task,)).fetchone()
            if 'maintain_tests' in packet.get('allowed_actions',[]):
                packet=dict(packet,case_mapping_contract='Map exact executed IDs path::fullName to exact executed successor IDs path::fullName. Bare test titles, code names, rationale strings and unchanged/changed markers are invalid. Omit unchanged identities. team_validate returns the actual before/after IDs on a mapping error. Optional remove_empty may list only removable_empty_artifacts; those are verified new zero-byte files, never historical tests.')
            from product_reading import compact
            original_files=packet.get('files',{});paged=compact(original_files)
            packet=dict(packet,files=paged['files'],file_manifest=paged['file_manifest'],read_instruction='Use team_read_file(path,offset) until next_offset is null. Spillover filesystem access is neither needed nor authorized.')
            if 'changes' in packet:
                packet=dict(packet);packet.pop('changes');packet['changes_are_frozen_in_files']=True
            proposal=json.loads(row[0]) if row else None
            proposal_manifest={}
            if proposal:
                content=proposal.get('changes',{}) or proposal.get('specification',{}).get('replacements',{})
                if content:
                    bounded=compact(content);proposal_manifest=bounded['file_manifest']
                    if proposal.get('changes'):proposal['changes']=bounded['files']
                    else:proposal['specification']['replacements']=bounded['files']
            return dict(packet=packet,file_sha256={n:hashlib.sha256(v.encode()).hexdigest() for n,v in original_files.items()},proposal=proposal,proposal_file_manifest=proposal_manifest,proposal_read_instruction='Use team_read_proposal_file(path,offset) for omitted immutable proposal content; proposal_sha256 is computed over the FULL stored proposal.',proposal_sha256=digest(json.loads(row[0])) if row else None,state=row[2] if row else 'DIAGNOSIS',mode=who['mode'],latest_review=json.loads(verdict) if verdict else None,last_validation_diagnostic=json.loads(error[0]) if error else None)
        if op=='team_validate':
            if set(req)!=identity|{'proposal_sha256'} or who['mode']!='review' or not row or not self.runner:raise PermissionError('independent fixed validation required')
            p=json.loads(row[0])
            if digest(p)!=req['proposal_sha256'] or p['author']==who['profile']:raise PermissionError('exact independent validation scope')
            if p['action']=='publish_governance':
                if not self.governance_runner or not self.governance_image:raise PermissionError('fixed governance validator unavailable')
                result=self.governance_runner(p['changes'],self.governance_image)
                self.binding(req)
                receipt=dict(result,proposal_sha256=digest(p),review_run=who['run'],reviewer=who['profile'])
                with self.db:self.db.execute('INSERT OR REPLACE INTO governance_validation VALUES(?,?,?,?)',(task,who['run'],digest(p),json.dumps(receipt)))
                return receipt
            if p['action']=='deploy_local':
                from product_deployment_jobs import request
                result=request(self.db,who,p,packet);self.binding(req);return result
            if p['action']!='maintain_tests':raise PermissionError('no fixed validator for this action')
            from product_test_maintenance import validate_proposal
            try:result=validate_proposal(self.db,who,p,packet,self.runner)
            except (ValueError,PermissionError) as exc:
                detail=dict(proposal_sha256=digest(p),review_run=who['run'],error=str(exc),evidence=getattr(exc,'diagnostic',None),next_action='Diagnose the executed evidence. Request changes for missing case mappings or new empty artifacts; never waive a failing baseline.')
                with self.db:self.db.execute('INSERT OR REPLACE INTO team_validation_errors VALUES(?,?,?,?)',(task,who['run'],digest(p),json.dumps(detail)))
                exc.diagnostic=detail;raise
            self.binding(req)
            return result
        if op=='team_propose':
            if set(req)!=identity|{'action','reason','specification'} or who['mode']!='implementation':raise PermissionError('technical owner only')
            if not isinstance(req['reason'],str) or not 80<=len(req['reason'])<=6000:raise ValueError('evidence-backed diagnosis required')
            if req['action'] not in packet['allowed_actions']:raise PermissionError('unsupported action')
            spec=req['specification']
            if req['action']=='request_prerequisite':
                from product_prerequisite import validate
                validate(spec)
            elif req['action']=='deploy_local':
                from product_deployment import validate
                validate(spec,packet)
            elif req['action']=='prepare_toolchain':
                from product_platform import validate,fingerprint
                validate(spec,packet['requested_capability'])
                if fingerprint(spec) in packet.get('rejected_preparations',[]):raise PermissionError('identical failed platform preparation; changed evidence/configuration required')
            elif req['action'] in ('dispatch_work','accept_work_item','request_capability'):
                from product_roadmap import validate_spec
                validate_spec(packet,req['action'],spec)
            elif req['action']=='revise_technical_contract':
                from product_technical_contract import validate
                validate(packet,spec)
            elif req['action']=='promote_knowledge':
                from product_memory import validate
                import time
                validate(spec,int(time.time()))
                if {k:v for k,v in spec.items() if k!='sources'}!={k:v for k,v in packet['entry'].items() if k!='sources'}:raise PermissionError('only citation corrections are permitted; semantic changes need a new nomination')
            elif req['action']=='dispatch_increment':
                if not isinstance(spec,dict) or set(spec)!={'title','brief','parent'} or spec['parent']!=packet['parent'] or not 100<=len(spec['brief'])<=8000 or not 10<=len(spec['title'])<=200:raise ValueError('bounded backlog increment required')
            elif req['action'] in ('resume_author','resume_review','enable_shared_build'):
                if not isinstance(spec,dict) or set(spec)!={'brief','target_task','draft_sha256'} or spec['target_task']!=packet['target_task'] or spec['draft_sha256']!=packet['draft_sha256'] or not isinstance(spec['brief'],str) or not 100<=len(spec['brief'])<=8000:raise ValueError('exact blocked draft and actionable recovery brief required')
            elif req['action']=='maintain_tests':
                from product_test_maintenance import proposed_files
                draft=self.db.execute('SELECT files FROM product_drafts WHERE attempt=? AND task=?',(who['attempt'],packet['target_task'])).fetchone()
                if not draft:raise PermissionError('preserved maintenance target required')
                proposed_files(packet,spec,json.loads(draft[0]))
            elif req['action']=='return_to_author':
                from product_recovery import request_spec,ready_dependencies
                request_spec(spec)
                if packet.get('required_dependencies'):ready_dependencies(packet['files'],spec,packet['required_dependencies'])
                deps={k:spec[k] for k in ('dependencies','devDependencies')}
                if deps in packet.get('rejected_dependencies',[]):raise ValueError('Same failed dependency selection; use new evidence and corrected versions')
            elif spec!={}:raise ValueError('no extra authority accepted')
            changes=refresh_manifest(packet) if req['action']=='refresh_generated_manifest' else packet['changes'] if req['action']=='publish_governance' else {}
            p=dict(task=task,author=who['profile'],run=who['run'],head=packet['head'],action=req['action'],reason=req['reason'],changes=changes,specification=spec)
            if row and json.loads(row[0])!=p:
                if not row[1] or json.loads(row[1])['decision']!='request_changes':raise PermissionError('immutable proposal; preserve original diagnosis')
                with self.db:
                    self.db.execute('INSERT INTO team_decision_history VALUES(?,?,?)',(task,row[0],row[1]))
                    self.db.execute('DELETE FROM team_decisions WHERE task=?',(task,))
            with self.db:self.db.execute('INSERT OR IGNORE INTO team_decisions VALUES(?,?,NULL,?)',(task,json.dumps(p),'PROPOSED'))
            self.recover();return dict(proposal_sha256=digest(p),state='REVIEW_REQUESTED')
        if op=='team_decide':
            if set(req)!=identity|{'proposal_sha256','decision','reason'} or who['mode']!='review' or not row:raise PermissionError('independent technical reviewer only')
            p=json.loads(row[0])
            if p['author']==who['profile'] or req['proposal_sha256']!=digest(p):raise PermissionError('stale or self review')
            if req['decision'] not in ('approve','request_changes') or not isinstance(req['reason'],str) or len(req['reason'])<60:raise ValueError('substantive decision required')
            if req['decision']=='approve' and p['action']=='maintain_tests':
                from product_test_maintenance import schema
                schema(self.db)
                proof=self.db.execute('SELECT receipt FROM test_maintenance_validation WHERE proposal_sha=? AND review_run=?',(digest(p),who['run'])).fetchone()
                if not proof or json.loads(proof[0])['reviewer']!=who['profile']:raise PermissionError('run team_validate before approving test maintenance')
            if req['decision']=='approve' and p['action']=='publish_governance':
                proof=self.db.execute('SELECT receipt FROM governance_validation WHERE task=? AND run=? AND proposal_sha=?',(task,who['run'],digest(p))).fetchone()
                if not proof or not json.loads(proof[0]).get('passed') or json.loads(proof[0])['reviewer']!=who['profile']:raise PermissionError('passing isolated governance validation in this review required')
            if req['decision']=='approve' and p['action']=='deploy_local':
                from product_deployment_jobs import proof
                result=proof(self.db,who,p)
                if not result or not result['passed'] or result['reviewer']!=who['profile'] or result['proposal_sha256']!=digest(p):raise PermissionError('same-proposal executed environment QA required')
            v=dict(task=task,run=who['run'],reviewer=who['profile'],proposal_sha256=digest(p),decision=req['decision'],reason=req['reason'])
            if row[1] and json.loads(row[1])!=v:raise PermissionError('conflicting decision')
            with self.db:self.db.execute('UPDATE team_decisions SET verdict=?,state=? WHERE task=?',(json.dumps(v),'DECIDED',task))
            self.recover();return dict(state='DECISION_RECORDED',decision=v['decision'],merge_authorized=False)
        raise PermissionError('unsupported team operation')
    def recover(self):
        from hermes_cli import kanban_db as kb
        if (self.binding.board/'MAINTENANCE').exists():return
        for task,praw,vraw,state in self.db.execute("SELECT * FROM team_decisions WHERE state IN ('PROPOSED','DECIDED')").fetchall():
            p=json.loads(praw);current=kb.get_task(self.native,task)
            if state=='PROPOSED':
                if current.status=='running' and current.current_run_id==p['run']:
                    if not kb.request_review(self.native,task,reviewer=self.binding.cards[task]['reviewer'],expected_run_id=p['run'],summary='team-proposal:'+digest(p)):raise PermissionError('handoff refused')
                elif current.status!='review':raise PermissionError('proposal handoff conflict')
                with self.db:self.db.execute("UPDATE team_decisions SET state='IN_REVIEW' WHERE task=?",(task,))
            else:
                v=json.loads(vraw);summary='team-decision:'+digest(v)+'\n'+v['reason']
                closed=self.native.execute('SELECT outcome,summary FROM task_runs WHERE id=? AND task_id=?',(v['run'],task)).fetchone()
                outcome='completed' if v['decision']=='approve' else 'changes_requested'
                if not closed or tuple(closed)!=(outcome,summary):
                    ok=kb.complete_task(self.native,task,expected_run_id=v['run'],summary=summary,result=summary,fire_lifecycle_hook=False) if v['decision']=='approve' else kb.request_changes(self.native,task,expected_run_id=v['run'],reason=summary)[0]
                    if not ok:raise PermissionError('decision completion refused')
                with self.db:self.db.execute("UPDATE team_decisions SET state='DELIVERED' WHERE task=?",(task,))
