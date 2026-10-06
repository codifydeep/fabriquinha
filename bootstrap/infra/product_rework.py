"""Fixed recovery transitions. Agents choose the diagnosis; no arbitrary shell."""
import json
from hermes_cli import kanban_db as kb
from product_workspace import Workspace,digest
from product_claim import NativeClaim
from product_lane import emit
from product_recovery import CONFIGS,is_test,recovery_key
from product_validation_jobs import schema

class Rework:
    def recovery_files(self,pub,cause):
        files=self.source_files(pub['head'])
        task=cause.get('draft_task')
        if task:
            card=self.cfg['cards'].get(task,{})
            if card.get('rework_head')!=pub['head'] or card.get('author')!=pub['author']:raise PermissionError('foreign recovery draft')
            row=self.private.execute('SELECT files FROM product_drafts WHERE attempt=? AND task=?',(self.cfg['attempt'],task)).fetchone()
            if not row:raise PermissionError('missing preserved draft')
            files=json.loads(row[0])
        return files
    def source_files(self,head):
        from product_autonomy import api
        tree=api('git/trees/'+head+'?recursive=1')
        if tree.get('truncated'):raise PermissionError('incomplete source tree')
        return {f['path']:self.content(f['path'],head) for f in tree['tree'] if f['type']=='blob' and (f['path'].startswith(('server/','shared/','web/','src/','tests/','docs/','design/')) or f['path'] in CONFIGS)}
    def recovery(self,pub,pr,cause):
        key=recovery_key(pub,cause);tid=self.get(key)
        if not tid:
            files=self.recovery_files(pub,cause)
            # The lockfile stays in the controller; avoid repeating 130KB in model context.
            lock_sha=digest(files.get('package-lock.json',''));files={n:v for n,v in files.items() if n!='package-lock.json'}
            packet=dict(head=pub['head'],pr=pub['pr'],source_task=pub['source_task'],original_author=pub['author'],files=files,cause=cause,
                required_dependencies={'dependencies':['ws'],'devDependencies':['@types/ws']} if 'server/ws.ts' in files else {},
                rejected_dependencies=cause.get('rejected_dependencies',[]),
                lockfile_sha256=lock_sha,
                allowed_actions=['return_to_author'],constraints='Diagnose actual failure and architecture. Return to ORIGINAL author using specification {brief,dependencies:{},devDependencies:{}}. Dependencies require exact npm registry versions and independent CTO approval; no URLs or scripts. Existing tests cannot be weakened. New empty non-baseline artifacts may be removed by the fixed tool. Do not hand-roll protocols to evade missing dependencies. The planned WebSocket implementation uses ws. Preserve tests, add regression evidence, run full discovery/lint/types/build. Never ask CEO for technical decisions.')
            tid=self.team_task(key,packet,f"RECOVERY-PR{pub['pr']} — Diagnose and return to original author",author='cto' if cause.get('kind')=='preparation_failure' else 'techlead');self.put(key,tid)
        tid=self.escalate(tid,key);answer=self.decision(tid)
        if not answer:return
        proposal,verdict=answer
        if verdict['decision']!='approve':return
        if proposal['head']!=pub['head'] or proposal['action']!='return_to_author':raise PermissionError('stale recovery approval')
        job=digest(dict(task=tid,proposal=digest(proposal)));schema(self.private)
        row=self.private.execute('SELECT result,state,error FROM product_validation_jobs WHERE id=?',(job,)).fetchone()
        if not row:
            files=self.recovery_files(pub,cause)
            request=dict(approval_task=tid,approval_sha=digest(proposal),head=pub['head'],files={n:files[n] for n in CONFIGS})
            with self.private:self.private.execute('INSERT INTO product_validation_jobs VALUES(?,?,NULL,?,NULL)',(job,json.dumps(request),'QUEUED'))
            self.notice(pub,'VALIDATION_PREPARATION',tid,'Technical decision approved; preparing lockfile-bound full-project validation. No worker dispatched yet.')
            return
        if row[1]=='FAILED':
            self.preparation_failure(pub,pr,cause,proposal,job,str(row[2]));return
        if row[1]!='READY':return
        result=json.loads(row[0]);donekey=key+':dispatched'
        prior=self.get(donekey)
        if prior:
            current=kb.get_task(self.native,prior)
            if current.status=='blocked':
                self.recover_blocked_card(prior,self.cfg['cards'][prior])
            return
        files=self.recovery_files(pub,cause);baseline=self.source_files(pr['base']['sha']);original=self.source_files(pub['head'])
        from product_recovery import ready_dependencies
        required={'dependencies':['ws'],'devDependencies':['@types/ws']} if 'server/ws.ts' in files else {}
        try:ready_dependencies(files,proposal['specification'],required)
        except ValueError as exc:
            self.preparation_failure(pub,pr,cause,proposal,job,str(exc));return
        removable=[n for n,v in original.items() if is_test(n) and not v.strip() and n not in baseline]
        files.update(result['configs'])
        protected=[n for n in files if n in CONFIGS or (is_test(n) and n not in removable)]
        brief=proposal['specification']['brief']+'\nThis is original-author correction of PR'+str(pub['pr'])+'. Existing nonempty tests/configurations are immutable. New regression tests are required with Red/Green/full suite. Removal is restricted to controller-verified new empty artifacts: '+json.dumps(removable)+'. Use product_remove_empty_artifact with exact version/hash; do not edit existing tests. Do not invent tools. Technical impediments: product_report_impediment.'
        child=kb.create_task(self.native,title=f"PR{pub['pr']} — Original-author correction",body=brief,assignee=pub['author'],initial_status='blocked',max_runtime_seconds=1200,max_retries=0,idempotency_key=donekey)
        card=dict(author=pub['author'],reviewer='techlead' if pub['author']!='techlead' else 'cto',base=pub['head'],files=files,protected=protected,brief=brief,autonomous=True,rework_pr=pub['pr'],rework_head=pub['head'],release_base=pr['base']['sha'],original_source_task=pub['source_task'],validation_image=result['image'],removable_empty_artifacts=removable,publication_source_files=list(original))
        w=Workspace(self.private,NativeClaim(self.board,self.cfg['attempt'],{child:card}))
        if not self.private.execute('SELECT 1 FROM product_drafts WHERE task=?',(child,)).fetchone():w.seed(self.cfg['attempt'],child,card['author'],card['base'],files,protected,card['reviewer'])
        self.register(child,card);kb.unblock_task(self.native,child);self.put(donekey,child)
        emit(self.board,'author_rework',task=child,profile=pub['author'],next_action=f"Correct PR{pub['pr']} using approved dependencies and full-project validation; prior snapshots preserved.")
    def preparation_failure(self,pub,pr,cause,proposal,job,error):
        depth=cause.get('preparation_depth',0)
        if depth>=3:
            self.notice(pub,'PREPARATION_ESCALATED_BLOCKED',proposal['task'],'CTO: three distinct preparations failed; preserved evidence requires capability diagnosis, no identical rebuild.');return
        rejected=cause.get('rejected_dependencies',[])+[{k:proposal['specification'][k] for k in ('dependencies','devDependencies')}]
        next_cause=dict(kind='preparation_failure',failed_job=job,error=error,rejected_dependencies=rejected,preparation_depth=depth+1,
            instruction='CTO must diagnose actual preparation/audit evidence and propose corrected exact dependency versions. Do not bypass security. Known npm audit remediation is evidence, not automatic approval. Backend can now read every draft file with product_read_file; no generic terminal is needed.')
        for name in ('draft_task','recovery_depth'):
            if name in cause:next_cause[name]=cause[name]
        self.recovery(pub,pr,next_cause)
    def publish_rework(self,tid,card,packet):
        from product_autonomy import api,REPO
        pr=api(f"pulls/{card['rework_pr']}");base=card['rework_head'];head=self.get('publication-head:'+tid)
        if pr['state']!='open' or pr['base']['ref']!='release/v0.1' or pr['base']['sha']!=card['release_base'] or not pr['head']['ref'].startswith('codex/') or pr['head']['repo']['full_name']!=REPO:raise PermissionError('rework PR scope or base changed')
        if pr['head']['sha'] not in (base,head):raise PermissionError('rework head changed')
        if not head:
            removed=set(card.get('publication_source_files',card['files']))-set(packet['files'])
            allowed=set(card.get('removable_empty_artifacts',[]))|set(card.get('reviewed_test_maintenance',{}).get('renames',{}))
            if not removed<=allowed:raise PermissionError('unauthorized deletion')
            entries=[dict(path=n,mode='100644',type='blob',content=v) for n,v in packet['files'].items()]
            from product_attestation import prepare,RECEIPT_PATH
            attestation=prepare(self,card,packet,card['release_base'])
            if attestation:
                if not self.cfg.get('signed_test_maintenance'):raise PermissionError('reviewed CI policy migration pending before maintenance publication')
                entries.append(dict(path=RECEIPT_PATH,mode='100644',type='blob',content=json.dumps(attestation,sort_keys=True)))
            entries += [dict(path=n,mode='100644',type='blob',sha=None) for n in removed]
            tree=api('git/commits/'+base)['tree']['sha'];tree=api('git/trees','POST',dict(base_tree=tree,tree=entries))['sha']
            head=api('git/commits','POST',dict(tree=tree,parents=[base],message=tid+': independently reviewed original-author correction'))['sha'];self.put('publication-head:'+tid,head)
        if pr['head']['sha']==base:api('git/refs/heads/'+pr['head']['ref'],'PATCH',dict(sha=head,force=False))
        pub=self.get('publication:'+str(card['rework_pr']));pub.update(head=head,source_task=tid,state='CI_WAIT',repairs=pub.get('repairs',0)+1)
        self.put('publication:'+str(card['rework_pr']),pub);self.put('published:'+tid,card['rework_pr'])
        emit(self.board,'rework_published',task=tid,profile=card['author'],next_action=f"PR{card['rework_pr']} updated at {head[:12]}; fresh CI and independent exact-head review required.")
