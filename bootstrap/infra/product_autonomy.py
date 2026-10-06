"""Persistent product coordinator. GitHub credentials never enter workers/tests.

Agents diagnose and decide; this service executes fixed verified transitions.
No arbitrary commands, forced merges, branch deletion or release completion.
"""
import base64,hashlib,json,os,sqlite3,subprocess,time,fcntl
from pathlib import Path
from hermes_cli import kanban_db as kb
from product_workspace import digest,Workspace
from product_claim import NativeClaim
from product_publication import approved_packet
from product_lane import emit
from product_rework import Rework
from product_liveness import Liveness

REPO='codifydeep/truco-online'
def api(path,method='GET',payload=None):
    cmd=['gh','api','repos/'+REPO+'/'+path,'--method',method]
    if payload is not None:cmd+=['--input','-']
    r=subprocess.run(cmd,input=json.dumps(payload) if payload is not None else None,text=True,capture_output=True,timeout=45)
    if r.returncode:raise RuntimeError('GitHub API failed: '+str(r.returncode)+' '+path.split('?')[0])
    return json.loads(r.stdout) if r.stdout.strip() else {}
def atomic(path,data):
    tmp=path.with_suffix(path.suffix+'.new');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.chmod(0o644);os.replace(tmp,path)

class Coordinator(Rework,Liveness):
    def __init__(self,root=Path('/control'),board=Path('/board')):
        self.root=root;self.board=board
        self.db=sqlite3.connect(root/'autonomy.db',timeout=15)
        self.db.execute('CREATE TABLE IF NOT EXISTS records(key TEXT PRIMARY KEY,value TEXT)');self.db.commit()
        self.native=kb.connect(board/'kanban.db');self.private=sqlite3.connect(root/'controller.db',timeout=15)
        self.cfg=json.loads((root/'config.json').read_text())
        # Private controller registration is authoritative; repair interrupted projection.
        if json.loads((board/'product-adapter.json').read_text())!=self.cfg:atomic(board/'product-adapter.json',self.cfg)
    def get(self,key,default=None):
        row=self.db.execute('SELECT value FROM records WHERE key=?',(key,)).fetchone();return json.loads(row[0]) if row else default
    def put(self,key,value):
        with self.db:self.db.execute('INSERT OR REPLACE INTO records VALUES(?,?)',(key,json.dumps(value)))
    def content(self,path,head):return base64.b64decode(api('contents/'+path+'?ref='+head)['content']).decode()
    def failure_log(self,run):
        jobs=api(f'actions/runs/{run}/jobs')['jobs'];chunks=[]
        for job in jobs:
            if job['conclusion']!='failure':continue
            result=subprocess.run(['gh','api',f'repos/{REPO}/actions/jobs/{job["id"]}/logs'],capture_output=True,text=True,timeout=45)
            if result.returncode or not result.stdout.strip():raise RuntimeError('actual failed job log unavailable')
            chunks.append(result.stdout[-24000:])
        if not chunks:raise RuntimeError('failed job evidence missing')
        return '\n'.join(chunks)[-32000:]
    def register(self,tid,card,packet=None):
        if packet is not None:
            folder=self.root/('pr-packets' if card['scope']=='pr_review' else 'team-packets');folder.mkdir(exist_ok=True)
            raw=(json.dumps(packet,indent=2)+'\n').encode();(folder/f'{tid}.json').write_bytes(raw)
            card['packet_sha256']=hashlib.sha256(raw).hexdigest()
        self.cfg=json.loads((self.root/'config.json').read_text());self.cfg['cards'][tid]=card
        atomic(self.root/'config.json',self.cfg);atomic(self.board/'product-adapter.json',self.cfg)
    def team_task(self,key,packet,title,author='techlead',capability='technical_recovery'):
        from product_policy import context
        policy=context(capability,author);reviewer=policy['reviewer']
        tid=kb.create_task(self.native,title=title,assignee=author,body='Persistent technical handoff. Inspect team_status, diagnose evidence, propose a supported action; independent technical review required. No CEO technical question.',initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=key)
        if tid not in self.cfg['cards']:
            self.register(tid,dict(policy,scope='coordination',brief='Start with team_status. Record evidence-backed technical proposal using exactly the packet action/specification contract; reviewer checks scope and immutable proposal. If blocked, use product_report_impediment with evidence and next action. No promise without an operation.'),packet)
            kb.unblock_task(self.native,tid)
            emit(self.board,'technical_handoff',task=tid,profile=author,next_action=title)
        return tid
    def escalate(self,tid,key):
        current=kb.get_task(self.native,tid)
        if current.status not in ('blocked','triage'):return tid
        from product_deployment_jobs import infrastructure_failure
        infrastructure=infrastructure_failure(self.private,tid)
        if infrastructure:
            self.put('deployment-infrastructure:'+tid,infrastructure)
            return tid
        card=self.cfg['cards'][tid]
        if card['author']=='cto':return tid
        raw=(self.root/'team-packets'/f'{tid}.json').read_text();packet=json.loads(raw)
        if packet.get('ci_run') and not packet.get('failed_log'):packet['failed_log']=self.failure_log(packet['ci_run'])
        event=self.native.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(tid,)).fetchone()
        if not event:raise PermissionError('coordination block lacks occurrence identity')
        prior=dict(task=tid,event_id=event[0],evidence=json.loads(event[1]))
        # Reuse earlier-runtime escalations for the same preserved occurrence.
        # All callers converge on the same CTO task, including the watchdog.
        for candidate,registered in list(self.cfg['cards'].items()):
            if registered.get('scope')!='coordination' or registered['author']!='cto':continue
            path=self.root/'team-packets'/f'{candidate}.json'
            if not path.exists():continue
            existing=json.loads(path.read_text()).get('prior_impediment',{})
            if existing.get('task')==tid and existing.get('evidence')==prior['evidence'] and existing.get('event_id',event[0])==event[0]:
                self.put(key,candidate);return candidate
        packet['prior_impediment']=prior
        new=self.team_task('coordination-escalation:'+tid+':'+str(event[0]),packet,'CTO — Escalated technical impediment '+tid,author='cto')
        self.put(key,new);return new
    def decision(self,tid):
        row=self.private.execute("SELECT proposal,verdict,state FROM team_decisions WHERE task=?",(tid,)).fetchone()
        if not row or row[2]!='DELIVERED':return None
        p,v=json.loads(row[0]),json.loads(row[1])
        from product_review_policy import validate
        if validate(p['author'],v['reviewer'],self.cfg['cards'].get(tid)) or v['proposal_sha256']!=digest(p):raise PermissionError('technical review provenance')
        closed=self.native.execute('SELECT outcome,summary FROM task_runs WHERE id=? AND task_id=?',(v['run'],tid)).fetchone()
        outcome='completed' if v['decision']=='approve' else 'changes_requested'
        if not closed or tuple(closed)!=(outcome,'team-decision:'+digest(v)+'\n'+v['reason']):raise PermissionError('decision not durably closed')
        return p,v
    def ci(self,head):
        runs=[r for r in api('actions/runs?head_sha='+head+'&event=pull_request')['workflow_runs'] if r['name']=='quality-gates']
        return max(runs,key=lambda r:r['id']) if runs else None
    def review(self,pub,pr,ci):
        key=f"pr:{pub['pr']}:{pub['head']}:{pr['base']['sha']}:review"
        tid=self.get(key)
        if tid:return tid
        diff=api(f"pulls/{pub['pr']}/files?per_page=100")
        if len(diff)!=pr['changed_files']:raise PermissionError('incomplete PR diff')
        files={f['filename']:self.content(f['filename'],pub['head']) for f in diff if f['status']!='removed' and f['filename']!='package-lock.json'}
        packet=dict(pr=pub['pr'],head=pub['head'],base=pr['base']['sha'],ci={k:ci[k] for k in ('id','head_sha','event','conclusion','html_url')},files=files,
            diff=[{k:f.get(k) for k in ('filename','status','sha','additions','deletions')} for f in diff],
            purpose='Review the actual incremental product PR and added configuration. Snapshot approval is not PR approval. No release completeness claim.',
            security_findings=['PR23: local audit reported two moderate Vitest/mocker advisories GHSA-82fw-gwwq-j7x9; evaluate scope and require changes if needed. No high/critical in initial local audit.'],
            source_task=pub['source_task'],author=pub['author'])
        source=self.cfg['cards'].get(pub['source_task'],{})
        policy={k:source[k] for k in ('policy_version','capability','risk') if k in source}
        reviewer=source.get('reviewer') or ('cto' if pub['author']=='techlead' else 'techlead')
        tid=kb.create_task(self.native,title=f"PR{pub['pr']} — Independent exact-head review",assignee=pub['author'],body=packet['purpose'],initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=key)
        current=kb.get_task(self.native,tid)
        if tid in self.cfg['cards'] and current.status in ('review','running','done'):
            self.put(key,tid);return tid
        self.register(tid,dict(policy,scope='pr_review',author=pub['author'],reviewer=reviewer,pr=pub['pr'],brief='Inspect exact frozen PR and actual CI. Approve or request concrete changes using product_verdict. No edits or merge.'),packet)
        kb.unblock_task(self.native,tid);claim=kb.claim_task(self.native,tid,claimer='autonomy-review-registration')
        if not claim or not kb.request_review(self.native,tid,reviewer=reviewer,expected_run_id=claim.current_run_id,summary='Fixed coordinator assembled exact Git packet; no model authorship claimed.'):raise RuntimeError('PR handoff refused')
        self.put(key,tid);emit(self.board,'pr_review',task=tid,profile=reviewer,next_action=f"Independently review PR{pub['pr']} at {pub['head'][:12]}")
        return tid
    def repair(self,pub,pr,ci):
        key=f"pr:{pub['pr']}:{pub['head']}:incident:{ci['id']}";tid=self.get(key)
        if not tid:
            names=['.hermes/team/generated-manifest.json','scripts/ci/run-project-checks.sh','scripts/ci/check-generated-contract.py','scripts/ci/node-checks.sh']
            files={n:self.content(n,pub['head']) for n in names}
            packet=dict(head=pub['head'],pr=pub['pr'],ci_run=ci['id'],files=files,failed_log=self.failure_log(ci['id']),refreshable=['scripts/ci/run-project-checks.sh'],
                allowed_actions=['refresh_generated_manifest'],
                constraints='Only reconcile the registered generated-file digest after assessing the full script. Never disable the drift checker or weaken tests. If the available action cannot fix the evidenced cause, do not approve it; record the unsupported technical impediment.')
            tid=self.team_task(key,packet,f"INCIDENT-PR{pub['pr']} — Diagnose CI {ci['id']}");self.put(key,tid)
        tid=self.escalate(tid,key);answer=self.decision(tid)
        if not answer:return
        p,v=answer
        if v['decision']!='approve':
            self.notice(pub,'CTO_CHANGES_REQUIRED',tid,'CTO rejected proposed recovery. Technical diagnosis remains open; no repeated action.');return
        if p['head']!=pub['head'] or p['action']!='refresh_generated_manifest':raise PermissionError('stale repair')
        commitkey=key+':commit';head=self.get(commitkey)
        if not head:
            tree=api('git/commits/'+pub['head'])['tree']['sha']
            tree=api('git/trees','POST',dict(base_tree=tree,tree=[dict(path=n,mode='100644',type='blob',content=s) for n,s in p['changes'].items()]))['sha']
            head=api('git/commits','POST',dict(tree=tree,parents=[pub['head']],message='chore: team-approved generated contract reconciliation'))['sha'];self.put(commitkey,head)
        current=api(f"pulls/{pub['pr']}")
        if current['base']['ref']!='release/v0.1' or not current['head']['ref'].startswith('codex/') or current['head']['repo']['full_name']!=REPO:raise PermissionError('repair branch scope')
        if current['head']['sha']==pub['head']:api('git/refs/heads/'+current['head']['ref'],'PATCH',dict(sha=head,force=False))
        elif current['head']['sha']!=head:raise PermissionError('PR changed externally')
        old=pub['head'];pub['head']=head;pub['repairs']=pub.get('repairs',0)+1;self.put('publication:'+str(pub['pr']),pub)
        emit(self.board,'repair_published',task=tid,profile='cto',next_action=f"PR{pub['pr']} {old[:8]} → {head[:8]}; await actual CI. Incident not resolved yet.")
    def notice(self,pub,state,tid,message):
        key=f"notice:{pub['pr']}:{pub['head']}:{state}"
        if not self.get(key):emit(self.board,state,task=tid,profile='cto',next_action=message);self.put(key,True)
    def integrate(self,pub,pr,ci,tid):
        row=self.private.execute('SELECT envelope,state FROM product_pr_verdicts WHERE task=? ORDER BY run DESC LIMIT 1',(tid,)).fetchone()
        if not row or row[1]!='DELIVERED':return
        v=json.loads(row[0]);expected=self.cfg['cards'][tid]['reviewer']
        from product_review_policy import validate
        if validate(pub['author'],expected,self.cfg['cards'][tid]):raise PermissionError('review policy drift')
        if v['head']!=pub['head'] or v['author']!=pub['author'] or v['reviewer']!=expected or v['base']!=pr['base']['sha']:raise PermissionError('stale review or matrix')
        closed=self.native.execute('SELECT outcome,summary FROM task_runs WHERE id=? AND task_id=?',(v['run'],tid)).fetchone()
        outcome='completed' if v['decision']=='approve' else 'changes_requested'
        if not closed or tuple(closed)!=(outcome,'product-pr-verdict:'+digest(v)+'\n'+v['reason']):raise PermissionError('native PR verdict mismatch')
        if v['decision']!='approve':
            self.recovery(pub,pr,dict(kind='review_changes',review_task=tid,reason=v['reason']));return
        fresh=api(f"pulls/{pub['pr']}");latest=self.ci(pub['head'])
        if fresh['head']['sha']!=v['head'] or fresh['base']['sha']!=v['base'] or latest['id']!=ci['id'] or latest['conclusion']!='success':raise PermissionError('merge preconditions changed')
        if fresh['base']['ref']!='release/v0.1' or fresh['head']['repo']['full_name']!=REPO:raise PermissionError('repository scope')
        checks=api('commits/'+pub['head']+'/check-runs')['check_runs']
        if not checks or any(c['status']!='completed' or c['conclusion'] not in ('success','neutral','skipped') for c in checks):raise PermissionError('checks pending or failed')
        self.put('merge-intent:'+str(pub['pr']),dict(head=v['head'],base=v['base'],review=tid,ci=ci['id']))
        api('statuses/'+pub['head'],'POST',dict(state='success',context='hermes-independent-review',description=f"{expected}: {tid}, exact-head approval"))
        result=api(f"pulls/{pub['pr']}/merge",'PUT',dict(sha=pub['head'],merge_method='merge'))
        if not result.get('merged'):raise RuntimeError('merge refused')
        self.finish_merge(pub,api(f"pulls/{pub['pr']}"))
    def finish_merge(self,pub,pr):
        intent=self.get('merge-intent:'+str(pub['pr']))
        if not intent or pr['head']['sha']!=intent['head']:raise PermissionError('foreign merge')
        commit=api('git/commits/'+pr['merge_commit_sha'])
        if [p['sha'] for p in commit['parents']]!=[intent['base'],intent['head']]:raise PermissionError('unexpected merge parents')
        pub.update(state='INTEGRATED',merge=pr['merge_commit_sha']);self.put('publication:'+str(pub['pr']),pub)
        from product_resolution import integrated
        integrated(self,pub)
        emit(self.board,'integrated',task=pub['source_task'],profile='techlead',next_action=f"PR{pub['pr']} integrated at {pub['merge'][:12]}; Tech Lead selects next bounded increment. Not homologation.")
    def plan_next(self,pub):
        key='continuation:'+pub['merge'];tid=self.get(key)
        if not tid:
            parent='t_03489102'
            packet=dict(head=pub['merge'],parent=parent,allowed_actions=['dispatch_increment'],integrated=pub,
                build_config=self.cfg['cards'].get(pub['source_task'],{}).get('files',{}).get('tsconfig.build.json'),
                tdd_contract=__import__('product_tdd_contract').CONTRACT,
                parent_scope=kb.get_task(self.native,parent).body,
                approved_plan=(self.board/'approved-plan.md').read_text(),
                capability='Choose a small meaningful backend TypeScript increment within unfinished TDD-01, not sessions/rooms until prerequisites complete. Only dependencies declared in the integrated package/lockfile are available. No shell, downloads, database services, Compose or frontend runtime yet. Existing tests/config immutable; new tests must demonstrate Red before implementation. Do not duplicate health. Missing capability must use product_report_impediment, never hand-roll a substitute or invent delivery.',
                instruction='Tech Lead: propose dispatch_increment with specification {title,brief,parent}. CTO: independently approve scope, dependency preservation and feasible test evidence. This does not complete parent TDD-01 or release.')
            tid=self.team_task(key,packet,'TECHLEAD — Plan next executable increment',capability='planning');self.put(key,tid)
        tid=self.escalate(tid,key);result=self.decision(tid)
        if not result:return
        p,v=result
        if v['decision']!='approve':self.notice(pub,'PLANNING_CHANGES_REQUIRED',tid,'CTO requires revised technical plan. No downstream dependency released.');return
        donekey=key+':dispatched'
        if self.get(donekey):return
        if api('git/ref/heads/release/v0.1')['object']['sha']!=p['head']:raise PermissionError('planning base moved')
        spec=p['specification'];tree=api('git/trees/'+p['head']+'?recursive=1')
        if tree.get('truncated'):raise PermissionError('incomplete tree')
        from product_recovery import CONFIGS,is_test
        names=[f['path'] for f in tree['tree'] if f['type']=='blob' and (f['path'].startswith(('server/','shared/','tests/')) or f['path'] in CONFIGS)]
        files={n:self.content(n,p['head']) for n in names};protected=[n for n in names if is_test(n) or n in CONFIGS]
        source=self.cfg['cards'].get(pub['source_task'],{})
        if not source.get('validation_image'):raise PermissionError('full-project validation image required before new product dispatch')
        child=kb.create_task(self.native,title=spec['title'],body=spec['brief'],assignee='backend_data',initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=donekey)
        card=dict(author='backend_data',reviewer='techlead',base=p['head'],files=files,protected=protected,brief=spec['brief'],parent_work_item=spec['parent'],autonomous=True,validation_image=source['validation_image'])
        w=Workspace(self.private,NativeClaim(self.board,self.cfg['attempt'],{child:card}))
        if not self.private.execute('SELECT 1 FROM product_drafts WHERE task=?',(child,)).fetchone():w.seed(self.cfg['attempt'],child,'backend_data',p['head'],files,protected,'techlead')
        self.register(child,card);kb.unblock_task(self.native,child);self.put(donekey,child)
        emit(self.board,'dependency_handoff',task=child,profile='backend_data',next_action='Execute CTO-approved increment with TDD on integrated base; parent remains incomplete.')
    def publish_completed(self):
        self.cfg=json.loads((self.root/'config.json').read_text())
        for tid,card in self.cfg['cards'].items():
            self.isolate('publish:'+tid,lambda tid=tid,card=card:self.publish_one(tid,card))
    def publish_one(self,tid,card):
        if not card.get('autonomous') or self.get('published:'+tid) or self.get('superseded:'+tid):return
        if kb.get_task(self.native,tid).status!='done':return
        packet=approved_packet(self.private,self.native,self.cfg['attempt'],tid)
        if card.get('rework_pr'):
            self.publish_rework(tid,card,packet);return
        # Two worker slots, but only one integration in flight. Waiting snapshots
        # revalidate on the new base rather than reusing stale test attestations.
        pending=[json.loads(r[0]) for r in self.db.execute("SELECT value FROM records WHERE key LIKE 'publication:%'")]
        if any(p['state'] not in ('INTEGRATED','SUPERSEDED') for p in pending):return
        base=card['base']
        latest_base=api('git/ref/heads/release/v0.1')['object']['sha']
        if latest_base!=base:
            from product_base_update import prepare
            prepare(self,tid,card,packet,latest_base);return
        branch='codex/'+tid+'-product';head=self.get('publication-head:'+tid)
        if not head:
            tree=api('git/commits/'+base)['tree']['sha']
            removed=set(card['files'])-set(packet['files'])
            allowed=set(card.get('reviewed_test_maintenance',{}).get('renames',{}))|set(card.get('removable_empty_artifacts',[]))
            if not removed<=allowed:raise PermissionError('unauthorized publication deletion')
            entries=[dict(path=n,mode='100644',type='blob',content=v) for n,v in packet['files'].items()]
            from product_attestation import prepare,RECEIPT_PATH
            attestation=prepare(self,card,packet,base)
            if attestation:
                if not self.cfg.get('signed_test_maintenance'):raise PermissionError('reviewed CI policy migration pending before maintenance publication')
                entries.append(dict(path=RECEIPT_PATH,mode='100644',type='blob',content=json.dumps(attestation,sort_keys=True)))
            entries += [dict(path=n,mode='100644',type='blob',sha=None) for n in removed]
            tree=api('git/trees','POST',dict(base_tree=tree,tree=entries))['sha']
            head=api('git/commits','POST',dict(tree=tree,parents=[base],message=tid+': independently reviewed product increment'))['sha'];self.put('publication-head:'+tid,head)
        refs=api('git/matching-refs/heads/'+branch);exact=[r for r in refs if r['ref']=='refs/heads/'+branch]
        if exact:
            if exact[0]['object']['sha']!=head:raise PermissionError('branch drift')
        else:api('git/refs','POST',dict(ref='refs/heads/'+branch,sha=head))
        prs=api('pulls?state=all&head=codifydeep:'+branch+'&base=release/v0.1')
        pr=prs[0] if prs else api('pulls','POST',dict(title=kb.get_task(self.native,tid).title,head=branch,base='release/v0.1',body='Autonomous source publication. Card '+tid+' snapshot '+packet['revision']+'. Author '+packet['author']+', independent snapshot reviewer '+packet['reviewer']+'. Exact-head CI and independent PR review still required. Not homologation.'))
        self.put('publication:'+str(pr['number']),dict(pr=pr['number'],head=head,release_base=base,source_task=tid,author=packet['author'],state='CI_WAIT',repairs=0));self.put('published:'+tid,pr['number'])
        emit(self.board,'pr_published',task=tid,profile=packet['author'],next_action=pr['html_url'])
    def tick(self):
        if (self.board/'MAINTENANCE').exists() or (self.board/'DRAIN').exists():return
        from product_manifest import verify
        verify(self.cfg)
        from product_memory import curate
        self.isolate('knowledge-curation',lambda:curate(self))
        self.reconcile_work()
        from product_roadmap import tick as plan_dag
        self.isolate('dag-planning',lambda:plan_dag(self))
        from product_planning_watch import watch
        self.isolate('planning-watch',lambda:watch(self))
        from product_platform import tick as platform_tick
        self.isolate('platform',lambda:platform_tick(self))
        self.isolate('publish',self.publish_completed)
        for key,raw in self.db.execute("SELECT key,value FROM records WHERE key LIKE 'publication:%'").fetchall():
            self.isolate(key,lambda key=key:self.advance_publication(key))
        self.put('coordinator-heartbeat',dict(at=time.time(),state='SCAN_COMPLETE'))
        from product_projection import project
        self.isolate('delivery-projection',lambda:project(self))
        from product_metrics import export
        self.isolate('process-metrics',lambda:export(self))

    def advance_publication(self,key):
        pub=self.get(key) # Fresh state: another transition may have updated this PR.
        if pub.get('state')=='SUPERSEDED':return
        if pub.get('state')=='INTEGRATED':
            if not self.cfg.get('dag_planning'):self.plan_next(pub)
            return
        pr=api(f"pulls/{pub['pr']}")
        if pr['merged']:self.finish_merge(pub,pr);return
        from product_pr_base import refresh
        if refresh(self,pub,pr):return
        if pr['head']['sha']!=pub['head']:raise PermissionError('external head drift')
        ci=self.ci(pub['head'])
        if not ci or ci['status']!='completed':return
        if ci['conclusion']!='success':
            self.recovery(pub,pr,dict(kind='ci_failure',ci_run=ci['id'],failed_log=self.failure_log(ci['id'])))
        else:self.integrate(pub,pr,ci,self.review(pub,pr,ci))

def main():
    root=Path('/control');lock=(root/'autonomy.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    c=Coordinator()
    while True:
        try:c.tick()
        except Exception as exc:
            key='runtime-error:'+type(exc).__name__+':'+str(exc)
            print(json.dumps(dict(event='autonomy_error',category=type(exc).__name__,detail=str(exc))),flush=True)
            if not c.get(key):emit(c.board,'controller_impediment',task='autonomy',profile='cto',next_action=str(exc));c.put(key,True)
        time.sleep(30)
if __name__=='__main__':main()
