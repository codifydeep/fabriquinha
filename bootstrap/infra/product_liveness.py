"""Persistent pre/post-PR impediment routing. No blind unblocking or evidence bypass."""
import json,time
from hermes_cli import kanban_db as kb
from product_workspace import digest
from product_tdd_contract import CONTRACT
from product_lane import emit

class Liveness:
    def recover_blocked_card(self,task,card):
        event=self.native.execute("SELECT id,payload FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(task,)).fetchone()
        if not event:raise PermissionError('blocked card lacks durable cause')
        key='blocked-work:'+task+':'+str(event[0]);state=self.get(key)
        if state and state.get('state') in ('RESUMED','SUPERSEDED'):return
        if card.get('rework_pr'):
            pub=self.get('publication:'+str(card['rework_pr']))
            if pub and (pub.get('state')=='INTEGRATED' or pub.get('source_task')!=card.get('original_source_task')):
                self.put(key,dict(state='SUPERSEDED',evidence=pub,owner='techlead'));return
        row=self.private.execute('SELECT version,files FROM product_drafts WHERE attempt=? AND task=?',(self.cfg['attempt'],task)).fetchone()
        if not row:raise PermissionError('missing preserved author draft')
        version,raw=row;files=json.loads(raw);sha=digest(files)
        target=kb.get_task(self.native,task)
        review_mode=target.assignee==card['reviewer']
        action='resume_review' if review_mode else 'resume_author'
        changes=[json.loads(r[0]) for r in self.private.execute("SELECT envelope FROM product_verdicts WHERE task=? AND state='DELIVERED' ORDER BY review_run DESC LIMIT 2",(task,)).fetchall()]
        recurring=len(changes)==2 and all(v['decision']=='request_changes' for v in changes)
        from product_policy import VERSION
        if (self.cfg.get('process_policy')==VERSION and state and state.get('state')=='CAPABILITY_BLOCKED'
                and not state.get('maintenance_offered') and not review_mode and card.get('validation_image')
                and 'test' in str(event[1]).lower() and any(word in str(event[1]).lower() for word in ('baseline','protected','frozen'))):
            packet=dict(head=card['base'],target_task=task,draft_sha256=sha,draft_version=version,
                removable_empty_artifacts=[n for n,v in files.items() if not v.strip() and n not in card.get('files',{}) and n not in card.get('protected',[])],
                original_author=card['author'],files={n:v for n,v in files.items() if n!='package-lock.json'},
                validation_image=card['validation_image'],latest_reviews=changes,blocked_event=json.loads(event[1]),
                allowed_contract_sources=['card:'+task]+['review:'+v['revision'] for v in changes],
                allowed_actions=['maintain_tests','resume_author'],
                instruction='QA owns reviewed technical test maintenance, not product implementation. Diagnose whether the baseline test contradicts the current approved contract. Use maintain_tests with exact fields {target_task,draft_sha256,brief,replacements,renames,case_mapping,contract_sources,change_kind}. replacements: complete test file contents only; renames and case_mapping may be {}. contract_sources must reference the registered card/review. Allowed change_kind: coverage_extension, technical_refactor, fixture_correction, align_approved_contract. Preserve all behaviors/cases, never skip or focus tests or alter code/config. Explain preservation and actionable original-author correction in brief. Reviewer must run team_validate then independently judge semantic preservation; a new behavioral Red is acceptable only in the changed tests. If no test change is justified, use resume_author with an executable correction or report the real capability gap. CEO decides business scope, not technical test upkeep.')
            incident=self.team_task(key+':test-maintenance-v2',packet,'QA — Reviewed test maintenance '+task,author='quality_security',capability='test_maintenance')
            state.update(state='DIAGNOSIS',prior_incidents=state.get('prior_incidents',[])+[state['incident']],incident=incident,
                         owner='quality_security',draft_sha256=sha,maintenance_offered=True)
            self.put(key,state)
        if not state:
            receipts=[]
            for (receipt,) in self.private.execute('SELECT receipt FROM product_test_receipts WHERE task=? ORDER BY rowid DESC LIMIT 4',(task,)):
                receipt=json.loads(receipt);output=receipt.get('output','')
                receipt['observed_failure']={'missing_module':'Cannot find module' in output,'unimplemented_exception':'Error: not implemented' in output,'assertion_marker':'ERR_ASSERTION' in output}
                receipt['output']=output[-1800:];receipts.append(receipt)
            packet=dict(head=card['base'],target_task=task,draft_sha256=sha,draft_version=version,original_author=card['author'],
                latest_reviews=changes,
                files={n:v for n,v in files.items() if n!='package-lock.json'},blocked_event=json.loads(event[1]),receipts=receipts,
                allowed_actions=[action],tdd_contract=CONTRACT,
                instruction='Diagnose actual receipts, not the worker claim. Propose '+action+' with {target_task,draft_sha256,brief}. Preserve draft/tests/history and native phase. Reviewer remains read-only; never run Red in review. Author must produce fresh valid evidence; never retroactively approve rejected Red, bypass tests, or complete work. Give concrete corrective steps. If tools cannot resolve this, report a structured technical impediment. Technical owner is Tech Lead/CTO, not CEO.')
            if recurring and not review_mode and any(n.startswith('shared/') for n in files):
                from product_build_contract import enable_shared_build
                try:enable_shared_build(files['tsconfig.build.json'])
                except (ValueError,KeyError,PermissionError):pass
                else:
                    packet['allowed_actions'].append('enable_shared_build')
                    packet['build_capability']='enable_shared_build uses the same {target_task,draft_sha256,brief} fields. Fixed controller operation: widen only build rootDir from server to . and include shared/**/*.ts alongside server/**/*.ts. All test/lint/dependency config remains unchanged. New immutable validation image and fresh TDD evidence required. Consider resulting dist/server output paths; do not weaken acceptance. This resolves the actual TS6059 constraint; a textual promise cannot change protected configuration.'
                    packet['instruction']+=' Resolve the protected-config conflict through enable_shared_build when appropriate; resume_author alone is valid only with a concrete feasible alternative satisfying the same acceptance criteria. Do not send another instruction to edit a still-protected config.'
            if card.get('prerequisite_for') and not review_mode:
                packet['allowed_actions'].append('revise_technical_contract')
                packet['technical_contract_revision_allowed']=True
                packet['technical_contract_rules']='A replacement brief may refine a technical implementation prerequisite only, preserving the required runtime behavior, all regression gates and independent review. Remove unnecessary implementation prescriptions only with evidence. Cannot change product scope, waive tests or grant protected file writes. The original brief remains archived.'
            incident=self.team_task(key,packet,'UNBLOCK — Diagnose '+task,author='cto' if review_mode or recurring else 'techlead')
            state=dict(state='DIAGNOSIS',incident=incident,owner='techlead',target=task,draft_sha256=sha,created_at=time.time(),next_action='Independent diagnosis and exact-draft resume approval')
            self.put(key,state)
            kb.add_comment(self.native,task,'techlead','Recovery owner: '+incident+'. Original draft preserved; waiting for independently reviewed diagnosis, not blind retry.')
        from product_recovery_approval import approved_maintenance
        approved=approved_maintenance(self,task,card,sha) if state.get('maintenance_offered') else None
        incident=approved or self.escalate(state['incident'],key+':escalation')
        if incident!=state['incident']:
            state.update(incident=incident,owner='cto');self.put(key,state)
        current=kb.get_task(self.native,incident)
        if current.status in ('blocked','triage'):
            state.update(state='CAPABILITY_BLOCKED',owner='cto',next_action='CTO diagnosis cannot execute with current capabilities; preserve incident and request explicit infrastructure intervention')
            if not state.get('alerted'):
                emit(self.board,'capability_intervention_required',task=incident,profile='cto',next_action=state['next_action']);state['alerted']=True
            self.put(key,state);return
        answer=self.decision(incident)
        if not answer or answer[1]['decision']!='approve':return
        p,v=answer;spec=p['specification']
        if p['action'] not in (action,'enable_shared_build','maintain_tests','revise_technical_contract') or p['head']!=card['base'] or spec['target_task']!=task or spec['draft_sha256']!=state['draft_sha256']:raise PermissionError('recovery approval became stale')
        if p['action']=='revise_technical_contract':
            if sha!=state['draft_sha256']:raise PermissionError('technical contract draft changed')
            from product_technical_contract import apply
            card=apply(self,task,card,p,incident)
        elif p['action']=='maintain_tests':
            from product_test_maintenance import apply
            card=apply(self,task,card,p,v,incident)
        elif p['action']=='enable_shared_build':
            from product_build_recovery import prepare
            card=prepare(self,task,card,p,incident)
            if card is None:return
        elif sha!=state['draft_sha256']:raise PermissionError('recovery approval became stale')
        original=kb.get_task(self.native,task)
        if original.status not in ('blocked','triage') or original.assignee not in (card['author'],card['reviewer']):raise PermissionError('registered role required')
        if original.status=='triage' and review_mode:raise PermissionError('review triage requires explicit phase-preserving capability diagnosis')
        # Write intent before unblocking: restart may retry the registration but not the execution.
        state.update(state='RESUME_PREPARED',approval=incident);self.put(key,state)
        checkpoint=max((v['review_run'] for v in changes),default=card.get('review_checkpoint',0))
        new=dict(card,review_checkpoint=checkpoint,brief=card['brief']+'\nAPPROVED RECOVERY '+incident+': '+spec['brief']+'\n'+CONTRACT)
        self.register(task,new)
        if original.status=='triage':
            latest=self.native.execute("SELECT id FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(task,)).fetchone()
            if latest[0]!=event[0]:raise PermissionError('triage occurrence changed')
            ok=kb.specify_triage_task(self.native,task,body=new['brief'],assignee=card['author'],author=p['author'])
        else:ok=kb.unblock_task(self.native,task,expected_block_event=event[0])
        if not ok:raise PermissionError('approved resume refused')
        state.update(state='RESUMED',next_action='Original author executes; incident remains linked, release not completed');self.put(key,state)
        emit(self.board,'worker_resumed',task=task,profile=original.assignee,next_action='Execute independently approved diagnosis '+incident+'; preserve native phase and tests. No evidence bypass.')

    def reconcile_work(self):
        self.cfg=json.loads((self.root/'config.json').read_text())
        for task,card in list(self.cfg['cards'].items()):
            if card.get('scope')=='coordination':
                self.isolate('coordination:'+task,lambda task=task,card=card:self.reconcile_coordination(task,card))
                continue
            if not card.get('autonomous'):continue
            def check(task=task,card=card):
                from product_review_feedback import contain
                contain(self.native,task,card)
                current=kb.get_task(self.native,task)
                if current.status in ('blocked','triage'):self.recover_blocked_card(task,card)
            self.isolate('work:'+task,check)
        # Recover acknowledgement lost after native unblock, without replaying it.
        for key,raw in self.db.execute("SELECT key,value FROM records WHERE key LIKE 'blocked-work:%'").fetchall():
            state=json.loads(raw)
            # The same historical namespace also contains string task references.
            # They are not resume intents and must not abort the entire scan.
            if not isinstance(state,dict):continue
            if state.get('state')!='RESUME_PREPARED':continue
            current=kb.get_task(self.native,state['target'])
            if current.status in ('ready','running','review','done'):
                state.update(state='RESUMED',next_action='Continue approved original-author execution');self.put(key,state)

    def reconcile_coordination(self,task,card):
        from product_review_feedback import contain
        contain(self.native,task,card)
        current=kb.get_task(self.native,task)
        if current.status not in ('blocked','triage'):return
        target=self.escalate(task,'coordination-watch:'+task)
        if target!=task:return
        event=self.native.execute("SELECT id FROM task_events WHERE task_id=? AND kind IN ('blocked','block_loop_detected') ORDER BY id DESC LIMIT 1",(task,)).fetchone()
        if not event:raise PermissionError('coordination block lacks occurrence identity')
        key='platform-needed:'+task+':'+str(event[0])
        if self.get(key):return
        next_action='CTO diagnosis lacks an executable capability. Platform owner devops must assess the required adapter; no identical retry, automatic approval or CEO architecture question. Original card and evidence remain blocked.'
        self.put(key,dict(state='CAPABILITY_BLOCKED',owner='devops',technical_owner='cto',task=task,occurrence=event[0],next_action=next_action))
        emit(self.board,'platform_capability_required',task=task,profile='cto',next_action=next_action)

    def isolate(self,key,operation):
        try:
            result=operation()
            old=self.get('fault:'+key)
            if old and old.get('state')=='OPEN':
                old.update(state='CHECK_CLEAR',last_checked=time.time(),resolution_proven=False);self.put('fault:'+key,old)
            return result
        except Exception as exc:
            fingerprint=type(exc).__name__+': '+str(exc);old=self.get('fault:'+key,{})
            record=dict(state='OPEN',owner='cto',error=fingerprint,first_seen=old.get('first_seen',time.time()),last_checked=time.time(),next_action='Reconcile this item without blocking unrelated work')
            self.put('fault:'+key,record)
            if old.get('error')!=fingerprint or old.get('state')!='OPEN':emit(self.board,'item_impediment',task=key,profile='cto',next_action=fingerprint)
