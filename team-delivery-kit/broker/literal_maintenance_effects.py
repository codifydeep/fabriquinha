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
    return prefix(phase)+' '+s['marker']+'\nSource: '+cfg['source']['author_task']+'\n'+flow.instruction(cfg,s,phase).strip()


class Effects:
    def __init__(self,b):
        self.b=b;self.old=diagnostic.Effects(b);self.plans=self.old.plans;self.settings=self.plans.settings
    def verify(self,cfg):
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
        if phase=='plan':flow.preflight_plan(cfg,s)
        function=native.ensure_unit_start if phase=='author' else native.ensure_planning_start
        return function(self.settings,s['issue_id'],flow.actor(cfg,phase),cfg['source']['author_task'],
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
        if phase=='review':
            observed=self.plans.reads(actual)
            for root in ('candidate','previous'):
                path='/evidence/'+root+'/'+cfg['test_path'];r=observed.get(path,{})
                require(type(r.get('lines')) is int and r['lines']>0 and r['lines']==r.get('total_lines'));reads[path]=r
        else:require(count==0)
        raw=(actual.get('result') or {}).get('output');require(isinstance(raw,str) and 0<len(raw.encode())<=8192)
        value=json.loads(raw,object_pairs_hook=_unique)
        return dict(task_id=actual['id'],agent_id=role,wakeup_id=s['wakeup_id'],execution_id=binding['request_id'],
            output_sha256=hashlib.sha256(raw.encode()).hexdigest(),read_evidence=reads,value=value)
    def prepare(self,cfg,s):
        b=self.b;child=s['issue_id'];base=cfg['base'];name=b.PREFIX+'-literal-base-'+child
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':child,'delivery-kit.base-sha':base['base_sha']}
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS literal_maintenance_volumes(source_task TEXT PRIMARY KEY,identity TEXT,state TEXT)')
            row=con.execute('SELECT identity,state FROM literal_maintenance_volumes WHERE source_task=?',(cfg['source']['author_task'],)).fetchone()
            identity=dict(name=name,labels=labels)
            if row:require(json.loads(row[0])==identity);stage=json.loads(row[1])['stage']
            else:
                require(b.docker('GET','/volumes/'+name) is None);stage='create_intent'
                con.execute('INSERT INTO literal_maintenance_volumes VALUES(?,?,?)',(cfg['source']['author_task'],json.dumps(identity),json.dumps({'stage':stage})));con.commit()
                try:b.docker('POST','/volumes/create',dict(Name=name,Labels=labels))
                except TimeoutError:raise validation_job.Pending('observe same literal-maintenance base volume') from None
        actual=b.docker('GET','/volumes/'+name)
        if actual is None:raise validation_job.Pending('observe exact owned maintenance volume; no repeated create')
        require(all(actual.get('Labels',{}).get(k)==v for k,v in labels.items()))
        payload=dict(Image=cfg['image'],User='0:0',Entrypoint=['python'],
            Cmd=['-c','from pathlib import Path;import base_copy;base_copy.TARGET=Path("/target");base_copy.main();print("base_copy_complete")'],
            Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'],Labels=labels,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=64,
                Mounts=[dict(Type='volume',Source=base['volume'],Target='/source',ReadOnly=True),dict(Type='volume',Source=name,Target='/target',ReadOnly=False)]))
        job=validation_job.run(b,cfg['source']['author_task'],'structure',payload)
        require(job['exit_code']==0 and job['output'].strip()=='base_copy_complete')
        b.register_issue_base(dict(issue_id=child,base_sha=base['base_sha'],volume=name,manifest_sha256=base['manifest_sha256']))
        with b.db() as con:
            paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(cfg['source']['issue_id'],))]
            command=con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(cfg['source']['issue_id'],)).fetchone()[0]
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(cfg['source']['issue_id'],)).fetchone()[0])
        require('/workspace/'+cfg['test_path'] in paths);b.register_issue_editables(dict(issue_id=child,paths=paths,test_command=command))
        handoff_runtime.register(b,dict(route,issue_id=child,enabled=False))
        trial=dict(issue_id=child,parent_issue=cfg['source']['issue_id'],reviewer=cfg['reviewer'],base_sha=base['base_sha'],
            harness_maintenance_only=True,historic_functional_red=False,seed_previous_tests=True,seeded_edit_required=True,
            literal_maintenance=dict(source_task=cfg['source']['author_task'],config_sha256=digest(cfg)))
        with b.db() as con:
            test_revision_review.initialize(con)
            previous=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(child,)).fetchone()
            if previous:require(json.loads(previous[0])==trial)
            else:con.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',(child,cfg['source']['issue_id'],json.dumps(trial,sort_keys=True),'{}'))
        return dict(base_manifest_sha256=base['manifest_sha256'],volume=name,copy_job=job,trial_sha256=digest(trial))
    def snapshot(self,cfg,s,task):
        actual=self.plans.task(task['id'],cfg['author'])
        require(actual.get('status')=='completed' and actual.get('issue_id')==s['issue_id'] and actual.get('wakeup_id')==s['author_wakeup'])
        return self.b.snapshot_submission({'task_id':task['id']})
    def inspect(self,cfg,s):
        payload=dict(Image=cfg['image'],User='10000:10000',Entrypoint=['python'],
            Cmd=['/literal_test_maintenance.py','/previous','/candidate',cfg['source']['prepared']['manifest_sha256'],'observe',cfg['test_path'],cfg['literal']],
            Env=['PYTHONDONTWRITEBYTECODE=1','PYTHONPATH=/'],Labels={'delivery-kit.literal-maintenance':digest(cfg)},
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=536870912,NanoCpus=1000000000,PidsLimit=64,
                Tmpfs={'/tmp':'rw,nosuid,nodev,size=64m,mode=1777'},Mounts=[
                    dict(Type='volume',Source=cfg['source']['candidate_volume'],Target='/previous',ReadOnly=True),
                    dict(Type='volume',Source=s['snapshot']['volume'],Target='/candidate',ReadOnly=True)]))
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
    return cfg['author']==author and s['stage'] in ('author_observe','author_wait') and set(s['decisions'])=={'triage','plan','permit'}


def authorize_phase(con,cfg,s,task,phase,settings):
    require(s['stage'] in (phase+'_observe',phase+'_wait') and task.get('agent_id')==flow.actor(cfg,phase)
        and task.get('issue_id')==s['issue_id'] and bool(task.get('wakeup_id'))
        and time.time()-s['phase_started']<1800)
    require(native_scope_note.canonical(task.get('handoff_note',''),task['wakeup_id'])==expected_note(cfg,s,phase))
    if s['stage']==phase+'_wait':require(task['wakeup_id']==s['wakeup_id']);return s
    function=native.ensure_unit_start if phase=='author' else native.ensure_planning_start
    wake=function(settings,s['issue_id'],flow.actor(cfg,phase),cfg['source']['author_task'],s['marker'],
        flow.instruction(cfg,s,phase),allow_create=False)
    require(wake and wake['id']==task['wakeup_id'])
    updated={**s,'stage':phase+'_wait','wakeup_id':wake['id']}
    changed=con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=? AND state=?',
        (json.dumps(updated,sort_keys=True),cfg['source']['author_task'],json.dumps(s,sort_keys=True))).rowcount
    if changed==1:return updated
    actual=current(con,s['issue_id']);require(actual and actual[1]['stage']==phase+'_wait' and actual[1]['wakeup_id']==wake['id']);return actual[1]


def author_context(con,issue,task):
    match=current(con,issue['id'])
    if not match:return None
    cfg,s=match;settings=json.loads((STATE/'native.json').read_text());s=authorize_phase(con,cfg,s,task,'author',settings)
    require(set(s['decisions'])=={'triage','plan','permit'})
    return dict(title='Active immutable-literal maintenance',description='CURRENT PHASE ONLY. '+flow.instruction(cfg,s,'author'),
        handoff_note=flow.instruction(cfg,s,'author'))


def seed_source(b,issue,trial):
    with b.db() as con:match=current(con,issue)
    require(match);cfg,s=match;require(trial['literal_maintenance']==dict(source_task=cfg['source']['author_task'],config_sha256=digest(cfg))
        and s['stage'] in ('author_observe','author_wait') and trial['harness_maintenance_only'] is True
        and trial['base_sha']==b.issue_base(issue)['base_sha'] and set(s['decisions'])=={'triage','plan','permit'})
    fx=Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
    if s['revision']:
        last=s['history'][-1];volume=last['snapshot']['volume'];manifest=last['inspection']['candidate_manifest_sha256']
        hashes={cfg['test_path']:last['inspection']['structure']['candidate_test_sha256']};owner_key='delivery-kit.source-task';owner_task=last['author_task']
    else:
        volume=cfg['source']['candidate_volume'];manifest=cfg['source']['prepared']['manifest_sha256']
        hashes=cfg['source']['prepared']['test_sha256'];owner_key='delivery-kit.test-first-task';owner_task=cfg['source']['author_task']
    labels=(b.docker('GET','/volumes/'+volume) or {}).get('Labels',{})
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get(owner_key)==owner_task)
    return dict(mount=dict(Type='volume',Source=volume,Target='/previous',ReadOnly=True),
        selection=dict(manifest_sha256=manifest,test_sha256=hashes))


def mounts(b,binding):
    with b.db() as con:match=current(con,binding['issue_id'])
    if not match:return []
    cfg,s=match
    if s['stage'] not in ('review_observe','review_wait'):return []
    require(binding['agent_id']==cfg['reviewer'])
    fx=Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
    with b.db() as con:
        row=con.execute('SELECT n.task_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.request_id=?',
            (binding['request_id'],)).fetchone();require(row and row['status'] in ('creating','starting','running'))
        task=fx.plans.task(row['task_id'],cfg['reviewer']);s=authorize_phase(con,cfg,s,task,'review',fx.settings)
    labels=(b.docker('GET','/volumes/'+s['snapshot']['volume']) or {}).get('Labels',{})
    require(labels.get('delivery-kit.owner')==b.OWNER and labels.get('delivery-kit.source-task')==s['author_task'])
    return [dict(Type='volume',Source=volume,Target='/evidence/'+role,ReadOnly=True) for role,volume in (
        ('previous',cfg['source']['candidate_volume']),('candidate',s['snapshot']['volume']))]


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
