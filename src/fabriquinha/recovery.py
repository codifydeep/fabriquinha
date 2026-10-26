"""Executable technical diagnostics as native Kanban cards, not another workflow DB."""
import json
from pathlib import Path
import tempfile
import time
import re
from .artifacts import digest,encoded
from .board import Run
from .effects import Journal, EffectBlocked, Pending,write_json
from .kanban_lane import native
from .quality import Quality, DeliveryTools, product_mutations, review_decision, suite_report


def browser_refusal_context(store,project,binding,key):
    record=store.receipt(key,kind='browser_job');data=record['payload'];identity=data['identity'];report=data['report']
    if (binding.get('kind')!='integration' or binding.get('reviewing') is not True
            or binding.get('actor')==binding.get('author') or record['binding']!=binding or identity['binding']!=binding
            or identity['project']!=project.fingerprint() or identity['phase']!='browser'
            or identity['image']!=project.browser_image
            or not re.fullmatch('[a-f0-9]{40}',str(identity.get('commit')))
            or data['sandbox']!=dict(network=project.namespace+'-homologation_qa',snapshot='readonly',user='10000:10000')):
        raise ValueError('browser refusal must match the exact independent deployed QA execution')
    store.tree(identity['snapshot'])
    if not data['infrastructure_error']:
        if (data['exit_code']!=1 or not isinstance(report,dict) or type(report.get('version')) is not int or report.get('version')!=1
                or report.get('status')!='failed' or report.get('source_sha')!=identity['commit']
                or not isinstance(report.get('checks'),list) or len(report['checks'])>20
                or not all(isinstance(check,str) and 1<=len(check)<=1000 for check in report['checks'])
                or len(set(report['checks']))!=len(report['checks'])
                or not isinstance(report.get('errors'),list) or not 1<=len(report['errors'])<=100
                or not all(isinstance(error,str) and 1<=len(error)<=1000 for error in report['errors'])):
            raise ValueError('complete negative browser facts required; not a delivery approval')
    classification='infrastructure' if data['infrastructure_error'] else report.get('failure_kind','unclassified')
    return dict(receipt=key,snapshot=identity['snapshot'],commit=identity['commit'],report=report,
        infrastructure_error=data['infrastructure_error'],classification=classification,
        delivery_approval=False,requires_fresh_validation=True)


def suite_refusal_context(store,project,binding,key,current_snapshot):
    record=store.receipt(key,kind='suite_job');data=record['payload'];identity=data['identity']
    if (record['binding']!=binding or identity['binding']!=binding or identity['project']!=project.fingerprint()
            or identity['image']!=project.validation_image or identity['phase']=='diagnostic'
            or data['sandbox']!=dict(network='none',snapshot='readonly',user='65534:65534')):
        raise ValueError('suite refusal must match the exact failed execution and fixed validator')
    report=suite_report(data,diagnostic=True);store.tree(identity['snapshot'])
    if not any(report[field] for field in ('errors','skips','expected_failures','unexpected_successes')) and report.get('qa_preview',{}).get('status')!='failed':
        raise ValueError('negative quality report required, never a passing-job approval')
    return dict(receipt=key,phase=identity['phase'],snapshot=identity['snapshot'],report=report,
        matches_current_snapshot=identity['snapshot']==current_snapshot,delivery_approval=False,requires_fresh_validation=True)


def control_refusal_context(store,project,binding,key,current_snapshot):
    record=store.receipt(key,kind='control_refusal');data=record['payload']
    green=store.receipt(data['green'],kind='green')
    if (binding.get('kind')!='implementation' or binding.get('reviewing') is not False
            or record['binding']!=binding or green['binding']!=binding
            or data['project']!=project.fingerprint() or green['payload']['project']!=project.fingerprint()
            or data['snapshot']!=green['payload']['snapshot'] or data['freeze']!=green['payload']['freeze']
            or data.get('delivery_approval') is not False):
        raise ValueError('control refusal must match its exact failed execution, Green and frozen contract')
    store.tree(data['snapshot'])
    feedback=data['feedback'];missing=data.get('missing',feedback['missing']);coverage=data.get('coverage',feedback['covered'])
    return dict(receipt=key,snapshot=data['snapshot'],matches_current_snapshot=data['snapshot']==current_snapshot,
        feedback=feedback,missing=missing,coverage=coverage,
        complete=len(missing)==feedback['missing_count'] and len(coverage)==feedback['covered_count'],
        delivery_approval=False,requires_fresh_validation=True)


class Diagnostic:
    def __init__(self,sandbox,quality):
        self.sandbox,self.q,self.run=sandbox,quality,sandbox.run
        self.store,self.board=quality.store,quality.board
        self.board.ensure(self.run)
        record=self.store.receipt(self.board.input(self.run,'incident'),kind='incident')
        self.incident,self.original=record['payload'],record['binding']
        roles=quality.project.technical_roles
        if (self.run.kind!='diagnostic' or self.run.reviewing or not roles or self.run.actor not in roles.values()
                or self.incident['project']!=quality.project.fingerprint()
                or self.original['release']!=self.run.release):
            raise ValueError('controller-assigned technical diagnosis required')
        self.level=next(level for level,actor in roles.items() if actor==self.run.actor)
        self.experiment=None
        self.repair=None
        reader=getattr(self.board,'repair_for_task',None);key=reader(self.incident.get('source')) if reader else None
        if isinstance(key,str):
            from .repairs import reviewed
            self.repair=reviewed(self.q.project,self.store,key)
            if self.store.receipt(key)['binding']['release']!=self.run.release:raise ValueError('foreign corrective diagnosis')

    def actions(self):
        return (['resume'] if self.incident.get('resume_allowed',True) else [])+(['escalate'] if self.level=='lead' else [])+['hold']

    def qa_correction(self):
        return self.original['kind']=='tests' and self.repair and self.repair['proposal']['classification']=='test_contract'

    def evidence(self):
        from .config import execution_context
        result=dict(incident={**self.incident,'workspace':'/workspace'},failed_execution=self.original,execution=execution_context(self.q.project),
            workspace='/workspace',files=sorted(self.store.manifest(self.incident['snapshot'])),
            allowed_actions=self.actions(),limits='No source writes, approvals, breaker resets or controller repairs. A held incident must state a concrete next technical action.')
        result['phase_expectation']=(
            'Tests author: product behavior is not implemented yet. Assertion failures are expected Red; test errors need author repair. '
            'Do not require Green or start implementation before independent test freeze.'
            if self.original['kind']=='tests' and not self.original['reviewing'] else
            'Review the existing immutable handoff; do not reproduce Red or edit the author.'
            if self.original['reviewing'] else
            'Diagnose the current implementation/integration phase; preserve frozen tests and its existing delivery gates.')
        result['experiment_semantics']='A complete diagnostic report may contain failures, errors or skips. These are evidence for guidance, not a delivery approval. Resume permits a fresh attempt in the same phase; it does not certify success.'
        if self.qa_correction():
            from .repairs import context_view
            result['repair_authority']={**self.repair,'context':context_view(self.store,self.repair['context'])}
            reviewed=self.store.receipt(self.repair['review'],kind='plan_review')
            approval=self.store.receipt(reviewed['payload']['plan'],kind='work_plan')['payload'].get('approval')
            if isinstance(approval,str):
                from .intake import Intake
                result['approved_brief']=Intake(self.q.project,self.store,self.board).approved(approval)[1]['payload']['document']
            result['phase_expectation']='Authorized QA expected-text correction, not a new feature Red. The independent corrective plan permits only its listed QA text paths. Diagnose all frozen-preview failures against the approved brief. Do not tell the author to edit product code or preserve a known incorrect QA expectation; do not silently override the reviewed authority. diagnostic_validate runs both full suite and QA preview; negative results remain observations, not approval.'
        if self.incident.get('control_refusal'):
            result['last_control_refusal']=control_refusal_context(self.store,self.q.project,self.original,
                self.incident['control_refusal'],self.incident['snapshot'])
        if self.incident.get('suite_refusal'):
            result['last_suite_refusal']=suite_refusal_context(self.store,self.q.project,self.original,
                self.incident['suite_refusal'],self.incident['snapshot'])
        if self.incident.get('browser_refusal'):
            result['last_browser_refusal']=browser_refusal_context(self.store,self.q.project,self.original,self.incident['browser_refusal'])
            result['browser_limits']='A green unittest experiment cannot establish deployed QA success. Use the actual browser error; do not repeat unchanged QA as a substitute for code/contract diagnosis.'
        if self.incident.get('review_escalation'):
            escalation=self.store.receipt(self.incident['review_escalation'],kind='review_escalation')['payload']
            result['review_feedback']=self.store.receipt(escalation['review'])['payload']['verdict']
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            body=json.loads(kb.get_task(conn,self.run.task).body)
            if body.get('escalated_from'):
                prior=kb.latest_run(conn,body['escalated_from'])
                result['previous_diagnosis']=dict(summary=prior.summary,error=prior.error) if prior else None
                if prior and prior.metadata and prior.metadata.get('diagnosis'):
                    receipt=self.store.receipt(prior.metadata['diagnosis'],kind='diagnostic_decision')
                    if receipt['payload']['incident']==self.board.input(self.run,'incident'):
                        result['previous_diagnosis']=receipt['payload']
        return result

    def validate(self,args):
        self.board.ensure(self.run)
        document_kind=self.incident.get('document_kind')
        field='document' if document_kind else 'replacements'
        if (not isinstance(args,dict) or not {'hypothesis'}<=set(args) or set(args)-{'hypothesis',field}
                or not isinstance(args['hypothesis'],str) or not 1<=len(args['hypothesis'].strip())<=2000):
            raise ValueError('bounded experiment hypothesis and optional '+field+' required')
        snapshot=self.incident['snapshot']
        if document_kind:
            from .intake import brief,plan
            tree=self.store.tree(snapshot)
            candidate=args.get('document',json.loads((tree/'document.json').read_bytes()))
            if len(encoded(candidate))>64000:raise ValueError('bounded diagnostic document required')
            try:
                if document_kind=='brief':brief(candidate)
                elif document_kind=='plan':plan(candidate,json.loads((tree/'approved_brief.json').read_bytes()),self.q.project)
                else:raise ValueError('unknown document validator')
                report=dict(valid=True,error=None)
            except ValueError as error:report=dict(valid=False,error=str(error)[:2000])
            self.experiment=self.q.record(self.run,'diagnostic_experiment',dict(incident=self.board.input(self.run,'incident'),
                snapshot=snapshot,hypothesis=args['hypothesis'],validator=document_kind,document=candidate,report=report))
            return dict(experiment=self.experiment,report=report,delivery_approval=False)
        correction=self.qa_correction()
        if 'replacements' in args:
            if correction:
                with tempfile.TemporaryDirectory(prefix='.diagnostic-qa-',dir=self.store.root.parent) as folder:
                    work=Path(folder);self.store.checkout(snapshot,work)
                    replacements=args['replacements']
                    if (not isinstance(replacements,dict) or not replacements
                            or not set(replacements)<=set(self.repair['proposal']['test_paths'])
                            or any(not isinstance(v,str) or len(v)>131072 for v in replacements.values())):
                        raise ValueError('diagnostic correction may propose only authorized QA expected-text files')
                    for path,content in replacements.items():(work/path).write_text(content)
                    snapshot=self.store.capture(work)
                self.q.correction_diff(self.repair['context']['snapshot'],snapshot,self.repair['proposal']['test_paths'])
            else:snapshot=product_mutations(self.q,snapshot,[args['replacements']])[0]
        job,report=DeliveryTools.wait(self,lambda:self.q.observe(self.run,snapshot,'green' if correction else 'diagnostic'))
        self.experiment=self.q.record(self.run,'diagnostic_experiment',dict(incident=self.board.input(self.run,'incident'),
            snapshot=snapshot,hypothesis=args['hypothesis'],job=job,report=report))
        return dict(experiment=self.experiment,report=report,delivery_approval=False)

    @property
    def quality(self):return self.q  # Reuse the bounded fixed-job observation helper.

    def decide(self,args):
        self.board.ensure(self.run)
        if (not isinstance(args,dict) or set(args)!={'action','reason','findings'}
                or args['action'] not in self.actions()):
            raise ValueError('permitted technical actions: '+', '.join(self.actions())+'; preserve native triage and never send technical decisions to CEO')
        if args['action']=='resume' and self.experiment is None:
            raise ValueError('resume requires a real experiment in this execution')
        snapshot=self.incident['snapshot']
        if (not isinstance(args['reason'],str) or not 1<=len(args['reason'].strip())<=2000
                or not isinstance(args['findings'],list) or not 1<=len(args['findings'])<=8):
            raise ValueError('concrete bounded technical reason and findings required')
        files=[]
        for finding in args['findings']:
            if isinstance(finding,dict) and set(finding)=={'evidence','detail'}:
                if (finding['evidence'] not in ('incident','experiment')
                        or finding['evidence']=='experiment' and self.experiment is None
                        or not isinstance(finding['detail'],str) or not 1<=len(finding['detail'].strip())<=2000):
                    raise ValueError('finding must cite the current incident or actual experiment')
            else:files.append(finding)
        if (args['action']=='resume' and self.qa_correction()
                and any(f.get('path') not in self.repair['proposal']['test_paths'] for f in files)):
            raise ValueError('resume guidance cannot require writes outside the independently authorized QA paths; cite other observations as incident/experiment evidence')
        if files:review_decision(dict(decision='changes',reason=args['reason'],findings=files),self.store.manifest(snapshot),self.store.tree(snapshot))
        verdict=dict(decision='changes',reason=args['reason'],findings=args['findings'])
        receipt=self.q.record(self.run,'diagnostic_decision',dict(incident=self.board.input(self.run,'incident'),
            action=args['action'],verdict=verdict,experiment=self.experiment,delivery_approval=False))
        self.sandbox.close()
        kb,kbc,_=native()
        with kbc.connect_closing() as conn:
            if not kb.complete_task(conn,self.run.task,summary=verdict['reason'],metadata={'diagnosis':receipt},
                                    expected_run_id=self.run.number):
                raise ValueError('native diagnostic completion refused')
        return dict(status='diagnosis_completed',action=args['action'],diagnosis=receipt,delivery_approval=False)


class Recovery:
    def __init__(self,project,store,board):
        self.project,self.store,self.board=project,store,board
        self.journal=Journal(store.root/'effects')

    def cards(self,conn):
        kb,_,_=native()
        return [kb.get_task(conn,row[0]) for row in conn.execute('SELECT id FROM tasks ORDER BY created_at,id')]

    def stage_for(self,reviewing,actor):
        return 'cto' if reviewing or actor==self.project.technical_roles['lead'] else 'lead'

    def expired_effects(self,task):
        result=[]
        for path in self.journal.root.glob('*.json'):
            effect=json.loads(path.read_bytes());identity=effect.get('identity',{})
            binding=identity.get('binding',{}) if isinstance(identity,dict) else {}
            if (isinstance(binding,dict) and binding.get('task')==task and effect.get('state')!='done'
                    and (effect.get('state')=='blocked' or effect.get('deadline',float('inf'))<=time.time())):result.append(path.stem)
        return result

    def guidance(self,run):
        """Resolve full applied guidance; native prose may be length-capped."""
        if not self.project.technical_roles or run.kind=='diagnostic':return []
        self.board.ensure(run);_,api,_=native();result=[]
        with api.connect_closing() as conn:
            rows=conn.execute("SELECT author,body FROM task_comments WHERE task_id=? AND body LIKE 'DIAG %' ORDER BY id DESC LIMIT 2",(run.task,)).fetchall()
        for row in reversed(rows):
            if row['author'] not in self.project.technical_roles.values():continue
            key=row['body'].split(' ',2)[1];record=self.store.receipt(key,kind='diagnostic_decision')
            incident=self.store.receipt(record['payload']['incident'],kind='incident')
            scope=incident['binding']
            if (record['binding']['actor']!=row['author'] or record['binding']['kind']!='diagnostic'
                    or record['payload']['project']!=self.project.fingerprint() or record['payload']['action']!='resume'
                    or any(scope[k]!=getattr(run,k) for k in ('task','kind','author','release','contract')) or scope['number']>=run.number):
                raise ValueError('diagnostic guidance belongs to another phase, owner or execution')
            # A completed implementation may now be in independent QA/review.
            # Prior-phase advice is historical context, never a veto or new authority.
            if scope['reviewing']!=run.reviewing or scope['actor']!=run.actor:continue
            experiment=self.store.receipt(record['payload']['experiment'],kind='diagnostic_experiment')
            if experiment['binding']!=record['binding'] or experiment['payload']['incident']!=record['payload']['incident']:
                raise ValueError('diagnostic guidance lacks its exact experiment')
            result.append(dict(receipt=key,verdict=record['payload']['verdict'],experiment=experiment['payload']))
        return result

    def handoff(self,conn,task):
        row=conn.execute("SELECT e.payload,r.metadata FROM task_events e JOIN task_runs r ON r.id=e.run_id "
            "WHERE e.task_id=? AND e.kind='review_requested' ORDER BY e.id DESC LIMIT 1",(task.id,)).fetchone()
        return (json.loads(row['payload']),json.loads(row['metadata'] or '{}')) if row else ({},{})

    def input(self,conn,task,name):
        """Controller read of an inactive task, never authority for a worker."""
        value=json.loads(task.body).get('inputs',{}).get(name)
        if isinstance(value,str) and value.startswith('parent:'):
            _,parent,key=value.split(':',2)
            if not conn.execute('SELECT 1 FROM task_links WHERE parent_id=? AND child_id=?',(parent,task.id)).fetchone():
                raise ValueError('diagnosis requires the actual parent handoff')
            _,metadata,_=self.board.closed_review(parent);value=metadata.get(key)
        if not isinstance(value,str) or value.startswith('parent:'):raise ValueError('diagnostic input missing: '+name)
        return value

    def snapshot(self,conn,task,source,handoff):
        if source.kind in ('brief','plan'):
            from .intake import Intake
            documents={'task.json':json.loads(task.body),'document.json':{}}
            proposal=handoff.get('plan' if source.kind=='plan' else 'request')
            if proposal:
                record=self.store.receipt(proposal)
                if record['kind'] in ('product_brief','work_plan'):
                    origin=source.binding();origin.update(actor=source.author,reviewing=False)
                    if (not Run(**origin).same_subject(record['binding']) or record['payload']['project']!=self.project.fingerprint()):
                        raise ValueError('document incident must match its actual author and contract')
                    documents['document.json']=record['payload']['document']
            if source.kind=='plan':
                approval,brief=Intake(self.project,self.store,self.board).approved(self.input(conn,task,'approved_brief'))
                if approval['binding']['release']!=source.release:raise ValueError('foreign business approval in diagnostic')
                documents['approved_brief.json']=brief['payload']['document']
            with tempfile.TemporaryDirectory(prefix='.recovery-context-',dir=self.store.root.parent) as folder:
                for name,data in documents.items():write_json(Path(folder)/name,data)
                return self.store.capture(Path(folder))
        if source.kind=='integration':
            if source.reviewing:
                rollout=self.store.receipt(handoff['rollout'],kind='rollout')
                expected={**source.binding(),'actor':source.author,'reviewing':False}
                if (not Run(**expected).same_subject(rollout['binding'])
                        or rollout['payload']['project']!=self.project.fingerprint()):raise ValueError('foreign deployed QA handoff')
                record=self.store.receipt(rollout['payload']['candidate'],kind='artifact')
            else:
                record=self.store.receipt(self.input(conn,task,'delivery'),kind='delivery_review')
                verdict=record['payload']['verdict']
                if (record['binding']['kind']!='implementation' or record['binding']['reviewing'] is not True
                        or record['binding']['actor'] not in self.project.reviewers_for(record['binding']['author'])
                        or verdict['decision']!='approve' or verdict['findings']):raise ValueError('approved independent delivery required for integration diagnosis')
            if record['payload']['project']!=self.project.fingerprint() or record['binding']['release']!=source.release:
                raise ValueError('foreign integration snapshot')
            self.store.tree(record['payload']['snapshot']);return record['payload']['snapshot']
        if source.reviewing:
            kind='red' if source.kind=='tests' else 'green'
            record=(Quality(self.project,self.store,None,self.board).test_evidence(handoff[kind]) if kind=='red'
                    else self.store.receipt(handoff[kind],kind=kind))
            expected={**source.binding(),'actor':source.author,'reviewing':False}
            if (not Run(**expected).same_subject(record['binding']) or record['payload']['project']!=self.project.fingerprint()):
                raise ValueError('review diagnostic must match its exact immutable author handoff')
            return record['payload']['snapshot']
        return self.store.capture(Path(task.workspace_path))

    def create(self,conn,incident,stage,*,previous=None):
        kb,_,_=native();record=self.store.receipt(incident,kind='incident');data=record['payload']
        actor=self.project.technical_roles[stage]
        return kb.create_task(conn,title='DIAG '+stage+' — '+data['source'],assignee=actor,priority=100,
            body=json.dumps(dict(version=1,kind='diagnostic',release=record['binding']['release'],stage=stage,
                source=data['source'],source_run=data['source_run'],block_event=data['block_event'],
                cause=data['cause'],inputs={'incident':incident},escalated_from=previous)),
            workspace_kind='dir',workspace_path=str(self.store.tree(data['snapshot'])),completion_contract='local-only',
            max_retries=2,max_runtime_seconds=600,idempotency_key=digest([
                self.project.fingerprint(),data['source'],data['source_run'],data['block_event'],'diagnostic',stage]))

    def discover(self,conn,task,settle):
        kb,_,_=native();body=json.loads(task.body)
        if body.get('kind')=='diagnostic':
            if body['stage']=='lead':self.create(conn,body['inputs']['incident'],'cto',previous=task.id)
            return
        if body.get('version')!=1 or body.get('kind') not in ('brief','plan','tests','implementation','integration'):return
        row=conn.execute('SELECT * FROM task_runs WHERE task_id=? ORDER BY id DESC LIMIT 1',(task.id,)).fetchone()
        event=conn.execute("SELECT * FROM task_events WHERE task_id=? AND kind IN ('blocked','gave_up','block_loop_detected') ORDER BY id DESC LIMIT 1",(task.id,)).fetchone()
        if not row or not row['ended_at'] or not event:return
        claimed=conn.execute("SELECT payload FROM task_events WHERE run_id=? AND kind='claimed' ORDER BY id DESC LIMIT 1",(row['id'],)).fetchone()
        reviewing=bool(claimed and json.loads(claimed[0]).get('source_status')=='review')
        stage='cto' if task.status=='triage' else self.stage_for(reviewing,row['profile'])
        key=digest([self.project.fingerprint(),task.id,row['id'],event['id'],'diagnostic',stage])
        existing=conn.execute('SELECT id FROM tasks WHERE idempotency_key=?',(key,)).fetchone()
        if existing:return
        settle(task.id,conn=conn)
        author=row['profile'];origin,handoff=self.handoff(conn,task)
        if reviewing:
            author=origin['implementer']
        source=Run(task.id,row['id'],row['profile'],body['kind'],reviewing,author,body['release'],digest(body))
        snapshot=self.snapshot(conn,task,source,handoff)
        failure=row['summary'] or row['error'] or task.result or 'Native worker could not complete'
        payload=json.loads(event['payload'] or '{}')
        reason=payload.get('reason');escalation_id=None;control_refusal=None;suite_refusal=None;browser_refusal=None
        if isinstance(reason,str):
            try:data=json.loads(reason)
            except (ValueError,TypeError):data=None
            if isinstance(data,dict):
                if data.get('failure'):
                    failure_record=self.store.receipt(data['failure'],kind='worker_failure')
                    if failure_record['binding']==source.binding():
                        failure=failure_record['payload']['message']
                        control_refusal=failure_record['payload'].get('control_refusal')
                        if control_refusal:control_refusal_context(self.store,self.project,source.binding(),control_refusal,snapshot)
                        suite_refusal=failure_record['payload'].get('suite_refusal')
                        if suite_refusal:suite_refusal_context(self.store,self.project,source.binding(),suite_refusal,snapshot)
                        browser_refusal=failure_record['payload'].get('browser_refusal')
                        if browser_refusal:browser_refusal_context(self.store,self.project,source.binding(),browser_refusal)
                if data.get('category')=='review_escalation':
                    record=self.store.receipt(data['escalation'],kind='review_escalation')
                    review=self.store.receipt(record['payload']['review'],kind='test_review' if source.kind=='tests' else 'delivery_review')
                    if (not source.reviewing or record['binding']!=source.binding()
                            or record['payload']['project']!=self.project.fingerprint()
                            or record['payload']['snapshot']!=snapshot or review['binding']!=source.binding()
                            or review['payload']['project']!=self.project.fingerprint()
                            or review['payload']['snapshot']!=snapshot or review['payload']['verdict']['decision']!='changes'):
                        raise ValueError('exact review escalation required')
                    escalation_id=data['escalation']
                    failure='Independent review technical impasse; CTO experiment and guidance required'
        cause=digest([task.id,source.contract,reviewing,snapshot,failure])
        effects=self.expired_effects(task.id)
        allowed=task.status=='blocked' and not effects
        category=('native_triage' if task.status=='triage' else 'controller_effect' if effects else
                  'technical_impasse' if escalation_id else 'document_activity' if source.kind in ('brief','plan') else
                  'integration_activity' if source.kind=='integration' else 'quality_gate' if control_refusal or suite_refusal else 'worker_activity')
        incident=self.store.record('incident',source.binding(),dict(project=self.project.fingerprint(),snapshot=snapshot,
            source=task.id,source_run=row['id'],block_event=event['id'],cause=cause,failure=failure,category=category,
            source_state=task.status,resume_allowed=allowed,controller_effects=effects,
            recovery_limit=None if allowed else 'Native triage or expired controller effect requires a scoped technical repair; preserve phase and breaker, never repeat the mutation.',
            **({'document_kind':source.kind} if source.kind in ('brief','plan') else {}),
            **({'control_refusal':control_refusal} if control_refusal else {}),
            **({'suite_refusal':suite_refusal} if suite_refusal else {}),
            **({'browser_refusal':browser_refusal} if browser_refusal else {}),
            workspace=task.workspace_path,**({'review_escalation':escalation_id} if escalation_id else {})))
        # A native idempotent anchor survives restart before stage materialization.
        self.create(conn,incident,stage)

    def apply(self,conn,task):
        kb,_,_=native();body=json.loads(task.body);row=kb.latest_run(conn,task.id)
        if not row or row.outcome!='completed' or not row.metadata or 'diagnosis' not in row.metadata:return
        receipt_id=row.metadata['diagnosis'];receipt=self.store.receipt(receipt_id,kind='diagnostic_decision');data=receipt['payload']
        expected=Run(task.id,row.id,task.assignee,'diagnostic',False,task.assignee,body['release'],digest(body))
        if (receipt['binding']!=expected.binding() or data['project']!=self.project.fingerprint()
                or data['incident']!=body['inputs']['incident']
                or task.assignee!=self.project.technical_roles[body['stage']]):raise ValueError('exact native diagnostic evidence required')
        incident=self.store.receipt(data['incident'],kind='incident');source=incident['payload']
        if data['action']=='escalate':
            if body['stage']!='lead':raise ValueError('only lead escalates to CTO')
            self.create(conn,data['incident'],'cto',previous=task.id);return
        if data['action']=='hold':return
        if source.get('resume_allowed') is False:raise EffectBlocked('native triage/controller effect needs scoped repair; preserve source')
        experiment=self.store.receipt(data['experiment'],kind='diagnostic_experiment')
        if experiment['binding']!=expected.binding() or experiment['payload']['incident']!=data['incident']:
            raise ValueError('resume requires its current validated experiment')
        identity=dict(diagnosis=receipt_id,source=source['source'],block_event=source['block_event'])
        key=digest(identity)
        path=self.journal.root/(digest(key+':resume')+'.json')
        if path.exists() and json.loads(path.read_bytes())['state']=='done':return
        attempts=0
        for other in self.cards(conn):
            previous=json.loads(other.body or '{}')
            if previous.get('kind')!='diagnostic' or previous.get('cause')!=source['cause']:continue
            prior=kb.latest_run(conn,other.id)
            if not prior or not prior.metadata or not prior.metadata.get('diagnosis'):continue
            old_id=prior.metadata['diagnosis'];old=self.store.receipt(old_id,kind='diagnostic_decision')['payload']
            old_incident=self.store.receipt(old['incident'],kind='incident')['payload']
            old_key=digest(dict(diagnosis=old_id,source=old_incident['source'],block_event=old_incident['block_event']))
            old_path=self.journal.root/(digest(old_key+':resume')+'.json')
            if old_path.exists() and json.loads(old_path.read_bytes())['state']=='done':attempts+=1
        if attempts>=2:raise EffectBlocked('two recoveries without changed evidence; require new diagnosis or changed preconditions')
        def fresh():
            target=kb.get_task(conn,source['source'])
            latest=kb.latest_run(conn,target.id)
            event=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind IN ('blocked','gave_up') ORDER BY id DESC LIMIT 1",(target.id,)).fetchone()
            if (target.status!='blocked' or not latest or latest.id!=source['source_run'] or not event or event[0]!=source['block_event']
                    or target.assignee!=incident['binding']['actor']
                    or target.workspace_path!=source['workspace']
                    or digest(json.loads(target.body))!=incident['binding']['contract']):
                raise EffectBlocked('diagnosis is stale for the current source impediment')
            if self.expired_effects(target.id):raise EffectBlocked('controller effect expired during diagnosis; preserve its identity')
            if (incident['binding']['kind'] in ('tests','implementation') and not incident['binding']['reviewing']
                    and self.store.capture(Path(target.workspace_path))!=source['snapshot']):
                raise EffectBlocked('source workspace changed after the diagnostic snapshot')
        guidance='DIAG '+receipt_id+' '+json.dumps(data['verdict'],sort_keys=True)
        def comment_observed():
            row=conn.execute('SELECT id FROM task_comments WHERE task_id=? AND author=? AND body=?',
                (source['source'],task.assignee,guidance)).fetchone()
            return {'comment':row[0]} if row else None
        def comment():
            fresh();return {'comment':kb.add_comment(conn,source['source'],task.assignee,guidance)}
        self.journal.do(key+':guidance',identity,comment,comment_observed)
        def resumed():
            row=conn.execute("SELECT id FROM task_events WHERE task_id=? AND kind='unblocked' AND id>? ORDER BY id LIMIT 1",
                (source['source'],source['block_event'])).fetchone()
            return {'event':row[0]} if row and comment_observed() else None
        def resume():
            fresh()
            if not kb.unblock_task(conn,source['source']):raise EffectBlocked('native resume refused')
            return resumed()
        self.journal.do(key+':resume',identity,resume,resumed)

    def reconcile(self,conn,settle):
        if not self.project.technical_roles:return {}
        issues={}
        for task in self.cards(conn):
            try:
                body=json.loads(task.body or '{}')
                if body.get('kind')=='diagnostic' and task.status=='done':self.apply(conn,task)
                elif task.status in ('blocked','triage'):self.discover(conn,task,settle)
            except (ValueError,KeyError,TypeError,EffectBlocked,Pending,OSError) as error:
                issues[task.id]=dict(category=type(error).__name__,owner=self.project.technical_roles['cto'],
                    detail=str(error)[:500],next_action='Observe the recorded identity/effect and repair preconditions; never reset or resubmit blindly.')
        return issues

    def status(self,conn):
        if not self.project.technical_roles:return []
        kb,_,_=native();incidents={};tasks=self.cards(conn)
        for task in tasks:
            body=json.loads(task.body or '{}')
            if body.get('kind')!='diagnostic':continue
            key=body['inputs']['incident'];record=self.store.receipt(key,kind='incident')
            target=kb.get_task(conn,body['source']);state='blocked'
            if target.status in ('ready','running','review'):state='revalidating'
            if target.status in ('blocked','triage'):
                latest=kb.latest_run(conn,target.id)
                if latest and latest.id!=record['payload']['source_run']:state='revalidation_failed'
            if target.status=='done':
                last=kb.latest_run(conn,target.id);metadata=last.metadata if last else {}
                kind=record['binding']['kind']
                name,evidence_kind={'tests':('tests','tests_frozen'),'implementation':('delivery','delivery_review'),
                    'integration':('release_evidence','release_evidence'),'plan':('plan_review','plan_review'),
                    'brief':('approved_brief','brief_approval')}[kind]
                state='evidence_missing'
                if metadata and metadata.get(name):
                    evidence=self.store.receipt(metadata[name],kind=evidence_kind)
                    if kind=='brief':
                        from .intake import Intake
                        approval,proposal=Intake(self.project,self.store,self.board).approved(metadata[name])
                        valid=(approval['binding']['task']==target.id and proposal['binding']['contract']==record['binding']['contract'])
                    else:
                        reviewed,_,_=self.board.closed_review(target.id)
                        valid=(evidence['binding']==reviewed.binding() and reviewed.contract==record['binding']['contract'])
                    if valid and evidence['payload']['project']==self.project.fingerprint():state='resolved'
            row=kb.latest_run(conn,task.id);decision=None
            if row and isinstance(row.metadata,dict) and row.metadata.get('diagnosis'):
                decision=self.store.receipt(row.metadata['diagnosis'],kind='diagnostic_decision')['payload']
                if decision['incident']!=key:raise ValueError('diagnostic outcome belongs to another incident')
                if decision['action']=='hold' and state!='resolved':state='held'
            if task.status in ('blocked','triage') and state!='resolved':state='diagnosis_failed'
            previous=incidents.get(key)
            if previous and previous['stage']=='cto' and body['stage']=='lead':continue
            incidents[key]=dict(source=target.id,diagnostic=task.id,stage=body['stage'],state=state,
                category=record['payload'].get('category','worker_activity'),
                source_run=record['payload']['source_run'],block_event=record['payload']['block_event'],
                owner=target.assignee if state=='revalidating' else task.assignee,
                resume_allowed=record['payload'].get('resume_allowed',True),
                next_action=(decision['verdict'] if decision else
                    'CTO diagnostic failed: inspect its retained run and repair protocol/capability before another attempt.' if state=='diagnosis_failed' else
                    'Assigned technical diagnosis; inspect recorded failure and execute a permitted experiment.'),
                delivery_approval=False)
            for candidate in tasks:
                correction=json.loads(candidate.body or '{}')
                if correction.get('repair_of')!=target.id:continue
                context=self.store.receipt(correction['repair_context'],kind='repair_context')
                if context['payload']['source']!=target.id or context['payload']['project']!=self.project.fingerprint():
                    raise ValueError('corrective incident link changed')
                current=incidents[key]
                current.update(state='correction_blocked' if candidate.status in ('blocked','triage') else 'repairing',
                    corrective_task=candidate.id,owner=candidate.assignee,
                    next_action='Follow corrective card '+candidate.id+' and its reviewed package; the original failure remains preserved.')
                anchor=kb.get_task(conn,correction['anchor'])
                from .intake import Intake
                if Intake(self.project,self.store,self.board).terminal(anchor):current.update(state='resolved_by_repair',next_action='Release homologated with corrective evidence; original failed execution remains historical.')
        return list(incidents.values())


def register_diagnostic(sandbox,quality,on_terminal):
    from tools.registry import registry
    operations=Diagnostic(sandbox,quality)
    finding=dict(type='object',additionalProperties=False,required=['path','line','detail'],properties=dict(
        path={'type':'string'},line={'type':'integer','minimum':1},detail={'type':'string','minLength':1,'maxLength':2000}))
    reference=dict(type='object',additionalProperties=False,required=['evidence','detail'],properties=dict(
        evidence=dict(type='string',enum=['incident','experiment']),detail=dict(type='string',minLength=1,maxLength=2000)))
    schemas=dict(diagnostic_validate=dict(type='object',additionalProperties=False,required=['hypothesis'],properties=dict(
        hypothesis={'type':'string','minLength':1,'maxLength':2000},replacements=dict(type='object',minProperties=1,maxProperties=16,
            additionalProperties={'type':'string','maxLength':131072}))),
        diagnostic_decide=dict(type='object',additionalProperties=False,required=['action','reason','findings'],properties=dict(
            action={'type':'string','enum':operations.actions()},reason={'type':'string','minLength':1,'maxLength':2000},
            findings=dict(type='array',minItems=1,maxItems=8,items={'oneOf':[finding,reference]}))))
    if operations.incident.get('document_kind'):
        properties=schemas['diagnostic_validate']['properties'];properties.pop('replacements')
        properties['document']=dict(type='object',description='Optional proposed brief/plan for the fixed validator. Never writes the source. Omit to validate document.json from the incident.')
    def handler(method,terminal):
        def invoke(args,**kwargs):
            result=method(args)
            if terminal and on_terminal:on_terminal(result)
            return json.dumps(result)
        return invoke
    for name,method in (('diagnostic_validate',operations.validate),('diagnostic_decide',operations.decide)):
        registry.register(name=name,toolset='fabriquinha_delivery',schema=dict(name=name,parameters=schemas[name],
            description='Technical diagnosis only. Read immutable evidence, run a fixed disposable SPIKE, propose guidance or escalate. '
                'Cite a real source line or evidence=incident/experiment for an operational finding; never invent a product defect. '
                'Never edit the author, weaken tests, approve delivery or send technical decisions to the CEO.'),
            handler=handler(method,name=='diagnostic_decide'))
    return set(schemas),operations
