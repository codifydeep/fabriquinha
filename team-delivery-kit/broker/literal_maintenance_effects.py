"""Controller-only adapter for isolated literal maintenance; no worker endpoint."""
import hashlib
import json
import os
from pathlib import Path
import re
import time
from generic_harness_calibration import digest,require
from structured_response_contract import _unique
import calibration_harness_protocol_probe as protocol
import qualify_harness_protocol as qualification
from literal_inspection_assessment import assess
import literal_poll_capture_experiment as capture
from docker_grouping import grouped_create
try:
    import literal_maintenance_workflow as flow,calibration_controls_diagnostic as diagnostic
    import native,native_scope_note,validation_job,handoff_runtime,test_revision_review
    from incremental_provisioning import NativeIssues
except ImportError:
    from broker import literal_maintenance_workflow as flow,calibration_controls_diagnostic as diagnostic
    from broker import native,native_scope_note,validation_job,handoff_runtime,test_revision_review
    from broker.incremental_provisioning import NativeIssues

STATE=Path('/broker-state')


def current(con,issue):
    flow.initialize(con)
    rows=[tuple(map(json.loads,r)) for r in con.execute('SELECT config,state FROM literal_maintenance_workflows')
        if json.loads(r[1]).get('issue_id')==issue]
    require(len(rows)<=1);return rows[0] if rows else None


def enroll(b,source,receipt):
    try:import controller_maintenance as maintenance
    except ImportError:from broker import controller_maintenance as maintenance
    with b.db() as con:
        require(maintenance.current(con)['stage']=='sealed')
        require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
        row=con.execute('SELECT config,state FROM calibration_control_experiments WHERE author_task=?',(source,)).fetchone();require(row)
        old,held=map(json.loads,row);c=old['source']
        require(held['stage']=='blocked' and held['category']=='diagnostic_objection_review_hold')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()[0])
    require(not maintenance.native_active(b));image=os.environ.get('BROKER_LITERAL_MAINTENANCE_IMAGE','')
    require(bool(re.fullmatch('sha256:[a-f0-9]{64}',image)) and b.docker('GET','/images/'+image+'/json'))
    cfg=dict(source=c,diagnostic_config=old,hold=held['objection_decision'],diagnostic_issue=held['issue_id'],
        parent_issue_id=held['issue_id'],author=route['author'],cto=c['cto'],reviewer=c['reviewer'],
        test_path=c['test_files'][0],literal='NODE_HARNESS',counterexample=receipt,
        route_sha256=digest(route),base=b.issue_base(c['issue_id']),image=image)
    fx=Effects(b);fx.verify(cfg)
    with b.db() as con:s=flow.register(con,cfg)
    return {k:s.get(k) for k in ('stage','owner','source_reset','delivery_approval')}


def prefix(phase):return 'DELIVERY_UNIT_START' if phase=='author' else 'DELIVERY_PLANNING_START'


def expected_note(cfg,s,phase):
    return prefix(phase)+' '+s['marker']+'\nSource: '+flow.dispatch_source(cfg)+'\n'+flow.instruction(cfg,s,phase).strip()


def copy_payload(cfg,identity,source_volume=None):
    return dict(Image=cfg['image'],User='0:0',Entrypoint=['python'],
        Cmd=['-c','from pathlib import Path;import base_copy;base_copy.TARGET=Path("/target");base_copy.main();print("base_copy_complete")'],
        Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'],Labels=identity['labels'],
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=64,
            Mounts=[dict(Type='volume',Source=source_volume or cfg['base']['volume'],Target='/source',ReadOnly=True),
                dict(Type='volume',Source=identity['name'],Target='/target',ReadOnly=False)]))


def maintenance_route(parent,child):
    """Keep tools/roles/contracts; do not inherit a different issue's capsule."""
    route={k:v for k,v in parent.items() if k!='execution_context'}
    return dict(route,issue_id=child,enabled=False,
        review_instruction='Review only the controller-published immutable literal maintenance artifact. '
            'No product implementation, historical Red, regression or delivery approval.')


def inspection_payload(cfg,s):
    return dict(Image=cfg['image'],User='10000:10000',Entrypoint=['python'],
        Cmd=['/literal_test_maintenance.py','/previous','/candidate',cfg['source']['prepared']['manifest_sha256'],'observe',cfg['test_path'],cfg['literal']],
        Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'],Labels={'delivery-kit.literal-maintenance':digest(cfg)},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=536870912,NanoCpus=1000000000,PidsLimit=64,
            Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},Mounts=[
                dict(Type='volume',Source=cfg['source']['candidate_volume'],Target='/previous',ReadOnly=True),
                dict(Type='volume',Source=s['snapshot']['volume'],Target='/candidate',ReadOnly=True)]))


def capture_payload(cfg,s):
    image=os.environ.get('BROKER_LITERAL_CAPTURE_EXPERIMENT_IMAGE','')
    require(bool(re.fullmatch('sha256:[a-f0-9]{64}',image)))
    rejected=s['history'][1]
    return dict(Image=image,User='10000:10000',Entrypoint=['python'],
        Cmd=['/literal_poll_capture_experiment.py','/candidate',rejected['inspection']['candidate_manifest_sha256'],
            cfg['test_path'],digest(s['diagnosis'])],Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'],
        Labels={'delivery-kit.literal-capture-experiment':digest(s['diagnosis'])},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=536870912,NanoCpus=1000000000,PidsLimit=64,Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},
            Mounts=[dict(Type='volume',Source=rejected['snapshot']['volume'],Target='/candidate',ReadOnly=True)]))


def preparation_journal(con,cfg,s,identity):
    """Never replace a legacy intent; only a qualified separate journal may follow it."""
    if cfg.get('feedback_strategy'):
        con.execute('CREATE TABLE IF NOT EXISTS literal_feedback_volumes(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
        return 'literal_feedback_volumes',cfg['base']['volume']
    con.execute('CREATE TABLE IF NOT EXISTS literal_maintenance_volumes(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
    old=con.execute('SELECT identity,state FROM literal_maintenance_volumes WHERE source_task=?',(cfg['source']['author_task'],)).fetchone()
    if not old or json.loads(old[0])==identity:return 'literal_maintenance_volumes',cfg['base']['volume']
    require(con.execute("SELECT 1 FROM sqlite_master WHERE name='literal_base_recoveries'").fetchone())
    row=con.execute('SELECT receipt FROM literal_base_recoveries WHERE source_task=?',(cfg['source']['author_task'],)).fetchone();require(row)
    receipt=json.loads(row[0]);require(s.get('canonical_base_recovery')==digest(receipt)
        and receipt['config_sha256']==digest(cfg) and receipt['old_intent']==dict(identity=json.loads(old[0]),state=json.loads(old[1]))
        and receipt['new_identity']==identity and receipt['previous_state']['decisions']==s['decisions']
        and receipt['source_reset'] is False and receipt['delivery_approval'] is False)
    return 'literal_maintenance_canonical_volumes',receipt['old_intent']['identity']['name']


class Effects:
    def __init__(self,b):
        self.b=b;self.old=diagnostic.Effects(b);self.plans=self.old.plans;self.settings=self.plans.settings
    def verify(self,cfg):
        if cfg.get('feedback_strategy'):
            try:import literal_feedback_strategy as strategy
            except ImportError:from broker import literal_feedback_strategy as strategy
            strategy.verify(self.b,cfg)
        c=cfg['source'];self.old.verify(cfg['diagnostic_config'])
        with self.b.db() as con:
            stored,state=map(json.loads,con.execute('SELECT config,state FROM calibration_control_experiments WHERE author_task=?',(c['author_task'],)).fetchone())
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(c['issue_id'],)).fetchone()[0])
        require(stored==cfg['diagnostic_config'] and stored['source']==c and state['stage']=='blocked'
            and state['category']=='diagnostic_objection_review_hold' and state['objection_decision']==cfg['hold']
            and cfg['diagnostic_issue']==state['issue_id'] and digest(route)==cfg['route_sha256']
            and cfg['author']==route['author'] and self.b.issue_base(c['issue_id'])==cfg['base']
            and len({cfg['author'],cfg['cto'],cfg['reviewer']})==3
            and self.settings['agents'].get(cfg['author'])=='implementation'
            and all(self.settings['agents'].get(a)=='planning' for a in (cfg['cto'],cfg['reviewer'])))
        p=state['objection']['producer']
        require(self.old.collect(stored,{**state,'wakeup_id':p['wakeup_id']},{'id':p['task_id']})==state['objection']
            and self.old.decision(stored,state,{'id':cfg['hold']['task_id']})==cfg['hold'])
        value=cfg['counterexample'];identity=value['identity'];qualification.validate(value,identity,c)
        require(identity['source_sha256']==digest(c) and identity['hold_sha256']==digest(cfg['hold'])
            and identity['script_sha256']==hashlib.sha256(Path(protocol.__file__).read_bytes()).hexdigest()
            and identity['image']==os.environ['BROKER_GENERIC_CALIBRATION_CONTROLS_IMAGE']
            and c['test_files']==[cfg['test_path']] and cfg['test_path'] not in c['prepared']['baseline_test_sha256']
            and cfg['literal']=='NODE_HARNESS' and cfg['image']==os.environ['BROKER_LITERAL_MAINTENANCE_IMAGE'])
        m=value['facts']['measurements'];require(m['unguarded_witness_satisfies_stale_comparison'] is True
            and m['witness_really_accepts_stale_responses'] is True)
    def reserve(self):return self.plans.native.remaining_calls()>=160
    def issue(self,cfg,first):
        parent=self.plans.issues.request('/issues/'+cfg['parent_issue_id'])
        return self.plans.issues.ensure(dict(title='Immutable literal maintenance '+digest(cfg)[:12],
            description='Separate source-bound maintenance of a NEW test literal. Source '+digest(cfg['source'])+
                '. Original attempts, snapshots, acceptance, baseline and release gates remain unchanged. No product admission.',
            parent_issue_id=cfg['parent_issue_id'],project_id=parent.get('project_id'),stage=1,status='todo'),allow_create=first)
    def wake(self,cfg,s,phase,first):
        if phase in ('plan','diagnose') or (cfg.get('feedback_strategy') and phase=='permit'):flow.preflight_plan(cfg,s,phase)
        function=native.ensure_unit_start if phase=='author' else native.ensure_planning_start
        return function(self.settings,s['issue_id'],flow.actor(cfg,phase),flow.dispatch_source(cfg),
            s['marker'],flow.instruction(cfg,s,phase),allow_create=first)
    def runs(self,cfg,s):return native.issue_task_runs(self.settings,s['issue_id'])
    def decision(self,cfg,s,phase,task):
        role=flow.actor(cfg,phase);actual=self.plans.task(task['id'],role)
        require(actual.get('status')=='completed' and actual.get('agent_id')==role and actual.get('issue_id')==s['issue_id']
            and actual.get('wakeup_id')==s['wakeup_id']
            and native_scope_note.canonical(actual.get('handoff_note',''),s['wakeup_id'])==expected_note(cfg,s,phase))
        binding=self.old.binding(actual,role)
        with self.b.db() as con:count=con.execute('SELECT coalesce(sum(tool_count),0) FROM tool_events WHERE request_id=?',(binding['request_id'],)).fetchone()[0]
        reads={}
        if phase in ('review','diagnose'):
            observed=self.plans.reads(actual)
            for root in (flow.diagnosis_roots(cfg) if phase=='diagnose' else ('candidate','previous')):
                path='/evidence/'+root+'/'+cfg['test_path'];r=observed.get(path,{})
                require(type(r.get('lines')) is int and r['lines']>0 and r['lines']==r.get('total_lines'));reads[path]=r
        else:require(count==0)
        raw=(actual.get('result') or {}).get('output');require(isinstance(raw,str) and 0<len(raw.encode())<=8192)
        value=json.loads(raw,object_pairs_hook=_unique)
        return dict(task_id=actual['id'],agent_id=role,wakeup_id=s['wakeup_id'],execution_id=binding['request_id'],
            output_sha256=hashlib.sha256(raw.encode()).hexdigest(),read_evidence=reads,value=value)
    def preserved_submission(self,cfg,s):
        """Recheck journaled validation, closed author lease and durable snapshot."""
        try:from literal_failed_inspection_review import completed_inspection
        except ImportError:from broker.literal_failed_inspection_review import completed_inspection
        actual=self.plans.task(s['author_task'],cfg['author'])
        require(actual.get('status')=='completed' and actual.get('issue_id')==s['issue_id']
            and actual.get('agent_id')==cfg['author'])
        with self.b.db() as con:
            completed_inspection(con,self.b,cfg,s)
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',
                (s['author_task'],)).fetchall();require(len(rows)==1);binding=dict(rows[0])
            require(binding['status']=='closed' and binding['agent_id']==cfg['author'] and binding['issue_id']==s['issue_id']
                and binding['scope'].split(':')[-2:]==['implementation',s['author_task']])
            snapshot=con.execute('SELECT * FROM snapshots WHERE task_id=?',(s['author_task'],)).fetchone()
            require(snapshot and snapshot['status']=='complete' and snapshot['volume']==s['snapshot']['volume'])
        labels=(self.b.docker('GET','/volumes/'+s['snapshot']['volume']) or {}).get('Labels',{})
        require(labels.get('delivery-kit.owner')==self.b.OWNER and labels.get('delivery-kit.source-task')==s['author_task'])
    def experiment(self,cfg,s):
        job=validation_job.run(self.b,s['diagnosis']['task_id'],'structure',capture_payload(cfg,s))
        require(job['exit_code']==0 and job['output_sha256']==hashlib.sha256(job['output'].encode()).hexdigest())
        return {**json.loads(job['output']),'validation_job':job}
    def validate_experiment(self,cfg,s,value):
        try:from test_first_job import digest as job_digest
        except ImportError:from broker.test_first_job import digest as job_digest
        b=self.b;task=s['diagnosis']['task_id'];h=s['history'][1]
        payload=grouped_create('POST','/containers/create?name=validation',capture_payload(cfg,s),b.PREFIX)
        key=job_digest(dict(task=task,kind='structure',payload=payload))
        expected={**payload,'Labels':{**payload['Labels'],'delivery-kit.owner':b.OWNER,
            'delivery-kit.source-task':task,'delivery-kit.validation-job':key}}
        identity=dict(task=task,kind='structure',name=b.PREFIX+'-validation-job-'+task+'-'+key[:12],payload=expected)
        with b.db() as con:
            row=con.execute('SELECT identity,state FROM validation_jobs WHERE job_key=?',(key,)).fetchone();require(row)
            recorded,job=map(json.loads,row);require(recorded==identity and job['stage']=='complete')
        result=job['result'];require(result==value['validation_job'] and result['approval'] is False and result['exit_code']==0
            and result['container_id']==job['container_id'] and result['validation_job_key']==key
            and result['validation_contract_sha256']==job_digest(identity)
            and result['output_sha256']==hashlib.sha256(result['output'].encode()).hexdigest()
            and {**json.loads(result['output']),'validation_job':result}==value)
        require(value['operation']=='literal_poll_capture_counterfactual_v1' and value['test_path']==cfg['test_path']
            and value['candidate_manifest_sha256']==h['inspection']['candidate_manifest_sha256']
            and value['test_sha256']==h['inspection']['structure']['candidate_test_sha256']
            and value['diagnosis_sha256']==digest(s['diagnosis'])
            and value['experiment_sha256']==hashlib.sha256(Path(capture.__file__).read_bytes()).hexdigest()
            and value['assertion_bindings']=={k:cfg['counterexample']['facts']['assertion_bindings'][k]
                for k in ('initial_expected','poll_minimum','stale_expected')}
            and value['snapshot_unchanged'] is True and value['counterfactual_templates_only'] is True
            and value['model_calls']==0 and all(value[k] is False for k in protocol.FALSE_FLAGS)
            and value['template_sha256']['original']==h['inspection']['structure']['candidate_literal_sha256']
            and value['hypothesis_supported'] is capture.supports(value['assertion_bindings'],value['reports']))
    def prepare(self,cfg,s):
        b=self.b;child=s['issue_id'];base=cfg['base'];name=b.PREFIX+'-base-'+child
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':child,'delivery-kit.base-sha':base['base_sha']}
        with b.db() as con:
            identity=dict(name=name,labels=labels)
            table,source_volume=preparation_journal(con,cfg,s,identity)
            con.execute('CREATE TABLE IF NOT EXISTS '+table+'(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
            row=con.execute('SELECT identity,state FROM '+table+' WHERE source_task=?',(flow.workflow_key(cfg),)).fetchone()
            if row:require(json.loads(row[0])==identity);stage=json.loads(row[1])['stage']
            else:
                require(b.docker('GET','/volumes/'+name) is None);stage='create_intent'
                con.execute('INSERT INTO '+table+' VALUES(?,?,?)',(flow.workflow_key(cfg),json.dumps(identity),json.dumps({'stage':stage})));con.commit()
                try:b.docker('POST','/volumes/create',dict(Name=name,Labels=labels))
                except TimeoutError:raise validation_job.Pending('observe same literal-maintenance base volume') from None
        actual=b.docker('GET','/volumes/'+name)
        if actual is None:raise validation_job.Pending('observe exact owned maintenance volume; no repeated create')
        require(all(actual.get('Labels',{}).get(k)==v for k,v in labels.items()))
        payload=copy_payload(cfg,identity,source_volume)
        job=validation_job.run(b,cfg['source']['author_task'],'structure',payload)
        require(job['exit_code']==0 and job['output'].strip()=='base_copy_complete')
        b.register_issue_base(dict(issue_id=child,base_sha=base['base_sha'],volume=name,manifest_sha256=base['manifest_sha256']))
        with b.db() as con:
            paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(cfg['source']['issue_id'],))]
            command=con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(cfg['source']['issue_id'],)).fetchone()[0]
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(cfg['source']['issue_id'],)).fetchone()[0])
        require('/workspace/'+cfg['test_path'] in paths);b.register_issue_editables(dict(issue_id=child,paths=paths,test_command=command))
        handoff_runtime.register(b,maintenance_route(route,child))
        parent_issue=cfg['parent_issue_id'] if cfg.get('feedback_strategy') else cfg['source']['issue_id']
        trial=dict(issue_id=child,parent_issue=parent_issue,reviewer=cfg['reviewer'],base_sha=base['base_sha'],
            harness_maintenance_only=True,historic_functional_red=False,seed_previous_tests=True,seeded_edit_required=True,
            literal_maintenance=dict(source_task=flow.workflow_key(cfg),config_sha256=digest(cfg)))
        with b.db() as con:
            test_revision_review.initialize(con)
            previous=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(child,)).fetchone()
            if previous:require(json.loads(previous[0])==trial)
            else:con.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',(child,parent_issue,json.dumps(trial,sort_keys=True),'{}'))
        prepared=dict(base_manifest_sha256=base['manifest_sha256'],volume=name,copy_job=job,trial_sha256=digest(trial))
        if cfg.get('feedback_strategy'):
            try:import author_feedback_admission as admission
            except ImportError:from broker import author_feedback_admission as admission
            prepared['feedback_admission']=admission.arm(b,cfg['feedback_strategy']['policy'],cfg['feedback_strategy']['qualification'],
                dict(cto=s['decisions']['plan']['receipt']['task_id'],sponsor=s['decisions']['permit']['receipt']['task_id']))
        return prepared
    def snapshot(self,cfg,s,task):
        actual=self.plans.task(task['id'],cfg['author'])
        require(actual.get('status')=='completed' and actual.get('issue_id')==s['issue_id'] and actual.get('wakeup_id')==s['author_wakeup'])
        return self.b.snapshot_submission({'task_id':task['id']})
    def inspect(self,cfg,s):
        payload=inspection_payload(cfg,s)
        job=validation_job.run(self.b,s['author_task'],'structure',payload)
        require(job['exit_code']==0 and hashlib.sha256(job['output'].encode()).hexdigest()==job['output_sha256'])
        value=json.loads(job['output']);return {**value,'validation_job':job}
    def validate_inspection(self,cfg,s,value):
        require(value['operation']=='immutable_literal_maintenance_inspection_v1' and value['test_path']==cfg['test_path']
            and value['previous_manifest_sha256']==cfg['source']['prepared']['manifest_sha256']
            and value['structure']['previous_test_sha256']==cfg['source']['prepared']['test_sha256'][cfg['test_path']]
            and value['structure']['literal']==cfg['literal'] and value['structure']['outside_literal_bytes_preserved'] is True
            and value['structure']['python_ast_preserved_except_literal'] is True and value['non_target_files_unchanged'] is True
            and value['node_syntax_valid'] is True and value['snapshot_unchanged'] is True
            and all(value[k] is False for k in protocol.FALSE_FLAGS))
        assess(cfg,value)  # The aggregate must agree with the frozen original assertions.
    def reseed(self,cfg,s):
        last=s['history'][-1];require(last['revision']==s['revision']-1 and last['review']['agent_id']==cfg['reviewer']
            and last['review']['value']['action']=='reject_test_revision')
        shadow={**s,'snapshot':last['snapshot'],'inspection':last['inspection'],'revision':last['revision'],
            'wakeup_id':last['wakeup_id'],'marker':last['marker']}
        require(self.decision(cfg,shadow,'review',{'id':last['review']['task_id']})==last['review'])
        return {**s['prepared'],'seed_revision':s['revision']}


def registered_author(con,issue,author):
    match=current(con,issue)
    if not match:return False
    cfg,s=match
    return cfg['author']==author and s['stage'] in ('author_observe','author_wait') and set(s['decisions'])==flow.required_decisions(cfg)


def authorize_phase(con,cfg,s,task,phase,settings):
    require(s['stage'] in (phase+'_observe',phase+'_wait') and task.get('agent_id')==flow.actor(cfg,phase)
        and task.get('issue_id')==s['issue_id'] and bool(task.get('wakeup_id'))
        and time.time()-s['phase_started']<1800)
    require(native_scope_note.canonical(task.get('handoff_note',''),task['wakeup_id'])==expected_note(cfg,s,phase))
    if s['stage']==phase+'_wait':require(task['wakeup_id']==s['wakeup_id']);return s
    function=native.ensure_unit_start if phase=='author' else native.ensure_planning_start
    wake=function(settings,s['issue_id'],flow.actor(cfg,phase),flow.dispatch_source(cfg),s['marker'],
        flow.instruction(cfg,s,phase),allow_create=False)
    require(wake and wake['id']==task['wakeup_id'])
    updated={**s,'stage':phase+'_wait','wakeup_id':wake['id']}
    changed=con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=? AND state=?',
        (json.dumps(updated,sort_keys=True),flow.workflow_key(cfg),json.dumps(s,sort_keys=True))).rowcount
    if changed==1:return updated
    actual=current(con,s['issue_id']);require(actual and actual[1]['stage']==phase+'_wait' and actual[1]['wakeup_id']==wake['id']);return actual[1]


def author_context(con,issue,task):
    match=current(con,issue['id'])
    if not match:return None
    cfg,s=match;settings=json.loads((STATE/'native.json').read_text());s=authorize_phase(con,cfg,s,task,'author',settings)
    require(set(s['decisions'])==flow.required_decisions(cfg))
    # Full native/journal reauthentication also runs in seed_source before the
    # isolated author workspace is populated; context alone grants no tool.
    if s['revision']==2:require(s['repair_authorization']==flow.replan_authority(cfg,s))
    return dict(title='Active immutable-literal maintenance',description='CURRENT PHASE ONLY. '+flow.instruction(cfg,s,'author'),
        handoff_note=flow.instruction(cfg,s,'author'))


def seed_source(b,issue,trial):
    with b.db() as con:match=current(con,issue)
    require(match);cfg,s=match;require(trial['literal_maintenance']==dict(source_task=flow.workflow_key(cfg),config_sha256=digest(cfg))
        and s['stage'] in ('author_observe','author_wait') and trial['harness_maintenance_only'] is True
        and trial['base_sha']==b.issue_base(issue)['base_sha'] and set(s['decisions'])==flow.required_decisions(cfg))
    fx=Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
    if s['revision']==2:flow.authenticate_replan(cfg,s,fx)
    if cfg.get('feedback_strategy'):
        p=cfg['feedback_strategy']['policy'];volume=p['previous_volume'];manifest=p['previous_manifest_sha256']
        hashes=cfg['feedback_strategy']['test_sha256'];owner_key='delivery-kit.source-task';owner_task=p['source_task']
    elif s['revision']:
        last=s['history'][-1];volume=last['snapshot']['volume'];manifest=last['inspection']['candidate_manifest_sha256']
        hashes={cfg['test_path']:last['inspection']['structure']['candidate_test_sha256']};owner_key='delivery-kit.source-task';owner_task=last['author_task']
    else:
        volume=cfg['source']['candidate_volume'];manifest=cfg['source']['prepared']['manifest_sha256']
        hashes=cfg['source']['prepared']['test_sha256'];owner_key='delivery-kit.test-first-task';owner_task=cfg['source']['author_task']
    labels=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get(owner_key)==owner_task)
    return dict(mount=dict(Type='volume',Source=volume,Target='/previous',ReadOnly=True),
        selection=dict(manifest_sha256=manifest,test_sha256=hashes))


def seeded_hashes(b,issue,task,trial):
    """Explicit seed metadata, never a manufactured historical Red receipt."""
    with b.db() as con:
        match=current(con,issue);require(match)
        cfg,s=match
        require(author_context(con,{'id':issue},task) is not None)
    selected=seed_source(b,issue,trial)['selection']['test_sha256']
    require(set(selected)=={cfg['test_path']})
    return selected


def maintenance_prompt(instruction):
    start=instruction.index('\nDELIVERY_TEST_ARTIFACT_V1:')
    return ('LITERAL MAINTENANCE PHASE. Edit only the NODE_HARNESS literal in the declared NEW test. '
        'Preserve every byte outside that literal, all assertions and every other file. '
        'No product implementation, terminal, shell or tests. The controller freezes the submission, '
        'checks preservation and executes fixed guarded/unguarded harness witnesses before independent review. '
        'This is not historical Red, product Green, full regression or delivery approval. '
        'Do not fabricate any execution report.'+instruction[start:])


def mounts(b,binding):
    with b.db() as con:match=current(con,binding['issue_id'])
    if not match:return []
    cfg,s=match
    phase='diagnose' if s['stage'].startswith('diagnose_') else 'review'
    if s['stage'] not in (phase+'_observe',phase+'_wait'):return []
    role=flow.actor(cfg,phase);require(binding['agent_id']==role)
    fx=Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
    if phase=='diagnose':flow.authenticate_rejections(cfg,s,fx)
    with b.db() as con:
        row=con.execute('SELECT n.task_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.request_id=?',
            (binding['request_id'],)).fetchone();require(row and row['status'] in ('creating','starting','running'))
        task=fx.plans.task(row['task_id'],role);s=authorize_phase(con,cfg,s,task,phase,fx.settings)
    labels=(b.docker('GET','/volumes/'+s['snapshot']['volume']) or {}).get('Labels',{})
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get('delivery-kit.source-task')==s['author_task'])
    volumes=[('previous',s['history'][0]['snapshot']['volume'] if phase=='diagnose' and not cfg.get('feedback_strategy')
        else cfg['source']['candidate_volume']),('candidate',s['snapshot']['volume'])]
    if phase=='diagnose' and cfg.get('feedback_strategy'):
        volumes.append(('seed',cfg['feedback_strategy']['policy']['previous_volume']))
    return [dict(Type='volume',Source=volume,Target='/evidence/'+role,ReadOnly=True) for role,volume in volumes]


def handle(b,source):
    with b.db() as con:
        flow.initialize(con);row=con.execute('SELECT config FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone()
        if not row:return None
        cfg=json.loads(row[0]);state=flow.advance(con,source,Effects(b))
    if state.get('issue_id'):
        try:handoff_runtime.publish(b,dict(issue_id=state['issue_id'],enabled=True,techlead=cfg['reviewer']),
            dict(stage='literal_maintenance_'+state['stage'],owner=state['owner'],source_task=source,
                data=json.dumps(dict(required_action=state.get('required_action'),delivery_approval=False))))
        except Exception as error:
            # Notification failure never grants completion or stops execution.
            # Retain a bounded, credential-free incident; the next tick retries.
            with b.db() as con:
                actual=current(con,state['issue_id'])
                if actual:
                    pending={**actual[1],'notification_error':type(error).__name__}
                    con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',
                        (json.dumps(pending,sort_keys=True),source))
    return state


def tick(b):
    """Enrolled maintenance advances even when the original route is paused.

    The ordinary controller maintenance barrier still owns this scheduler call.
    Enrollment does not enable a product route or reset its exhausted task.
    """
    with b.db() as con:
        rows=con.execute('SELECT source_task FROM literal_maintenance_workflows').fetchall()
    for row in rows:handle(b,row[0])
