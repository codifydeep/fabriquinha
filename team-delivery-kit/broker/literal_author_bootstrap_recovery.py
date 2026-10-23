"""One author bootstrap recovery for a proven inherited-context rejection.

Only the dedicated maintenance route changes, under sealed maintenance. Preserve
the failed attempt, old child route, original source and independent decisions.
The isolated constructor probe is not native execution or delivery evidence.
"""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import time
from unittest.mock import patch
from generic_harness_calibration import digest,require
try:
    import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
    import controller_maintenance as maintenance,native_scope_note
    from review_context_recovery import ERROR
except ImportError:
    from broker import literal_maintenance_effects as lane,literal_maintenance_workflow as flow
    from broker import controller_maintenance as maintenance,native_scope_note
    from broker.review_context_recovery import ERROR

ROOT_SHA='2fb62b15773afe836c8b840ef514c3cb664c98e9016873e194ead72c0dca99fe'
AUTHOR_FEEDBACK_ROOT_SHA='e6437bd64b1763f6d40c36ba34576c22637c59d21f09f5582e3cc2e783b0c73a'
AUTHOR_FEEDBACK_ADMISSION_ROOT_SHA='f4f258f63dd8b37315ddc6dd29c4ed7d25c074cb5ef9f7b7aceaab4692626168'
AUTHOR_FEEDBACK_STRATEGY_ROOT_SHA='03f2b0cd18dce00b0a9fba0098c6bd66ba1ba966da5e61790a2c9c8fd3f51e8b'
# Same legacy constructor, with only the two source-qualified v2 admission fences.
V2_ENROLLMENT_FENCE_ROOT_SHA='ab414dc1d296e694102288028b769b06f66f2b381be931fdba6568023583af41'
# Additive opt-in v2 launch hooks; legacy bytes are reconstructed by regression.
V2_AUTHOR_LAUNCH_ROOT_SHA='8d823023b3bf3dad3a1fa03ca7352abdb6aa1c47874321bda3c6222b8c6db550'
V2_PROGRESS_ROOT_SHA='57f50daabc0e767af8f772b3ffd488b9976c4b0a158a6d5be6c1364579fc6b70'
V2_REVIEW_LAUNCH_ROOT_SHA='c4444b9c8c11ad6df8b877602110cc393f0ebbff00fdd4318fa7ddc511f9df98'
V2_GREEN_LAUNCH_ROOT_SHA='bc1fd7da145fca0c9d4527db07e7092ce4f8ca378dc8465b387ff2efbd192ef1'
V2_TEAM_COORDINATION_ROOT_SHA='b08b1eeadfb1bd830f222953ca073816c0e75cd8cda6ed9d89d2e24e55f72b98'
V2_EXCLUSIVE_ROOT_SHA='b5f61a64b8087b445d2f909b6496da5f6cf983cd581e10289151847675925aee'
CONTEXT_SHA='7b182c770b2d0db0880571d4c254d1a158e852752801b69dca494db9c35f16ec'


def qualify(cfg,s,task,binding,events,tool_count,old_route,parent,trial):
    require(s.get('stage')=='blocked' and s.get('category')=='native_author_failed'
        and set(s.get('decisions',{}))=={'triage','plan','permit'} and s.get('revision')==0
        and not s.get('history') and not s.get('author_task') and not s.get('snapshot')
        and not s.get('author_bootstrap_recovery') and s.get('canonical_base_recovery')
        and s['source_reset'] is False and s['functional_red'] is False and s['delivery_approval'] is False
        and task.get('status')=='failed' and task.get('error')==ERROR
        and task['id']!=cfg['source']['author_task'] and task.get('agent_id')==cfg['author']
        and task.get('issue_id')==s['issue_id'] and task.get('wakeup_id')==s['wakeup_id']
        and native_scope_note.canonical(task.get('handoff_note',''),s['wakeup_id'])==lane.expected_note(cfg,s,'author')
        and binding.get('task_id')==task['id'] and binding.get('status')=='closed'
        and binding.get('agent_id')==cfg['author'] and binding.get('issue_id')==s['issue_id']
        and binding.get('scope','').split(':')[-2:]==['implementation',task['id']]
        and events==[{'method':'initialize','success':1},{'method':'session/new','success':1}]
        and type(tool_count) is int and tool_count==0
        and old_route==dict(parent,issue_id=s['issue_id'],enabled=False) and old_route.get('execution_context')
        and trial.get('harness_maintenance_only') is True and trial.get('historic_functional_red') is False
        and trial.get('seed_previous_tests') is True and 'old_red' not in trial
        and trial.get('literal_maintenance')==dict(source_task=cfg['source']['author_task'],config_sha256=digest(cfg)))
    from execution_context import validate
    validate(old_route['execution_context'])


def probe(b,cfg,s,task,old_route,new_route,trial,paths,issue):
    """Real constructor/guard with private minimal state, authenticated inputs.

    Scope/seed callbacks represent separately checked historical identity, NOT
    current authorization. They cannot issue grants, start workers or call LLMs.
    Never replace the running broker's globals or copy its whole private DB.
    """
    from execution_context import __file__ as context_file
    root_sha=hashlib.sha256(Path(b.__file__).read_bytes()).hexdigest()
    require(root_sha in (ROOT_SHA,AUTHOR_FEEDBACK_ROOT_SHA,AUTHOR_FEEDBACK_ADMISSION_ROOT_SHA,AUTHOR_FEEDBACK_STRATEGY_ROOT_SHA,V2_ENROLLMENT_FENCE_ROOT_SHA,V2_AUTHOR_LAUNCH_ROOT_SHA,V2_PROGRESS_ROOT_SHA,V2_REVIEW_LAUNCH_ROOT_SHA,V2_GREEN_LAUNCH_ROOT_SHA,V2_TEAM_COORDINATION_ROOT_SHA,V2_EXCLUSIVE_ROOT_SHA)
        and hashlib.sha256(Path(context_file).read_bytes()).hexdigest()==CONTEXT_SHA)
    spec=importlib.util.spec_from_file_location('isolated_literal_author_prompt',b.__file__)
    isolated=importlib.util.module_from_spec(spec);spec.loader.exec_module(isolated)
    try:import harness_repair_task as harness,test_revision_review as revision
    except ImportError:from broker import harness_repair_task as harness,test_revision_review as revision
    current={k:task[k] for k in ('agent_id','issue_id','wakeup_id','handoff_note')};current['task_id']=task['id']
    note=flow.instruction(cfg,s,'author')
    context=dict(title='Active immutable-literal maintenance',description='CURRENT PHASE ONLY. '+note,handoff_note=note)
    def author(con,issue_id,actor):require(issue_id==s['issue_id'] and actor==cfg['author']);return True
    def presentation(con,actual_issue,actual_task):require(actual_issue==issue and actual_task==current);return context
    def hashes(controller,issue_id,actual_task,actual_trial):
        require(issue_id==s['issue_id'] and actual_task==current and actual_trial==trial)
        selected=cfg['source']['prepared']['test_sha256'];require(set(selected)=={cfg['test_path']});return selected
    frame=dict(method='session/prompt',params=dict(prompt=[]))
    with tempfile.TemporaryDirectory(prefix='literal-bootstrap-probe-') as directory:
        isolated.STATE=Path(directory)
        with isolated.db() as con:
            con.execute('CREATE TABLE delivery_routes(issue_id,config)')
            con.execute('INSERT INTO delivery_routes VALUES(?,?)',(s['issue_id'],json.dumps(old_route)))
            con.execute('CREATE TABLE issue_editables(issue_id,path)')
            con.executemany('INSERT INTO issue_editables VALUES(?,?)',[(s['issue_id'],p) for p in paths])
            revision.initialize(con)
            con.execute('INSERT INTO test_revision_trials VALUES(?,?,?,?)',(s['issue_id'],cfg['source']['issue_id'],json.dumps(trial),'{}'))
        with patch.object(harness,'registered_author',side_effect=author),\
                patch.object(harness,'current_maintenance_context',side_effect=presentation),\
                patch.object(lane,'seeded_hashes',side_effect=hashes):
            try:isolated.native_task_prompt(frame,'implementation',issue,current)
            except ValueError as error:require(str(error)=='execution context role or route mismatch')
            else:raise ValueError('historical pre-transport guard must reject this exact old route')
            with isolated.db() as con:con.execute('UPDATE delivery_routes SET config=?',(json.dumps(new_route),))
            out=isolated.native_task_prompt(frame,'implementation',issue,current)['params']['prompt'][0]['text']
        require(0<len(out)<=10000 and 'LITERAL MAINTENANCE PHASE' in out)
    return dict(operation='literal_author_context_constructor_probe_v1',root_sha256=root_sha,context_sha256=CONTEXT_SHA,
        old_guard_rejection='execution context role or route mismatch',new_prompt_sha256=hashlib.sha256(out.encode()).hexdigest(),
        new_prompt_characters=len(out),historical_scope_checked_separately=True,native_execution=False,delivery_approval=False)


def register(b,source,failed):
    with b.LOCK:
        with b.db() as con:
            seal=maintenance.current(con);require(seal and seal['stage']=='sealed')
            require(not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone())
            con.execute('CREATE TABLE IF NOT EXISTS literal_author_bootstrap_recoveries(source_task TEXT PRIMARY KEY,receipt TEXT)')
            prior=con.execute('SELECT receipt FROM literal_author_bootstrap_recoveries WHERE source_task=?',(source,)).fetchone()
            if prior:
                receipt=json.loads(prior[0]);require(receipt['failed_task']==failed);return receipt
            cfg,s=map(json.loads,con.execute('SELECT config,state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone())
            old_raw=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(s['issue_id'],)).fetchone()[0];old=json.loads(old_raw)
            parent=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(cfg['source']['issue_id'],)).fetchone()[0])
            trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(s['issue_id'],)).fetchone()[0])
            paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(s['issue_id'],))]
            rows=con.execute('SELECT n.*,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=?',(failed,)).fetchall();require(len(rows)==1)
            binding=dict(rows[0]);request=binding['request_id']
            events=[dict(r) for r in con.execute('SELECT method,success FROM acp_events WHERE request_id=? ORDER BY rowid',(request,))]
            tools=con.execute('SELECT count(*) FROM tool_events WHERE request_id=?',(request,)).fetchone()[0]
            require(not con.execute('SELECT 1 FROM snapshots WHERE task_id=?',(failed,)).fetchone()
                and not con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(s['issue_id'],)).fetchone())
        require(not maintenance.native_active(b));fx=lane.Effects(b);fx.verify(cfg);flow.authenticate(cfg,s,fx)
        task=fx.plans.task(failed,cfg['author']);qualify(cfg,s,task,binding,events,tools,old,parent,trial)
        require(b.issue_base(s['issue_id'])['volume']==s['prepared']['volume'])
        new=lane.maintenance_route(parent,s['issue_id']);issue=fx.plans.issues.request('/issues/'+s['issue_id'])
        checked=probe(b,cfg,s,task,old,new,trial,paths,issue)
        # Only the fixed-length receipt digest is unknown until serialization;
        # zeros measure its length, never stand in for an executed permission.
        planned=flow.instruction(cfg,{**s,'author_bootstrap_recovery':'0'*64},'author')
        prompt_bound=checked['new_prompt_characters']+2*(len(planned)-len(flow.instruction(cfg,s,'author')))
        require(0<prompt_bound<=10000
            and len('DELIVERY_UNIT_START '+'0'*64+'\nSource: '+source+'\n'+planned)+512<=4000)
        checked={**checked,'planned_prompt_characters_bound':prompt_bound}
        receipt=dict(operation='literal_author_context_bootstrap_recovery_v1',failed_task=failed,execution_id=request,
            config_sha256=digest(cfg),previous_state=s,old_route=old,new_route=new,closed_binding=binding,
            acp_events=events,tool_events=tools,constructor_probe=checked,maintenance_operation=seal['operation_id'],
            qualified_at=time.time(),attempt_limit=1,maintenance_author_retry_authorized=True,source_author_retry_authorized=False,
            source_reset=False,historical_http_absence_proven=False,pre_transport_guard_rejection_proven=True,
            execution_authorized=False,delivery_approval=False)
        require(not maintenance.native_active(b))
        with b.db() as con:
            con.execute('BEGIN IMMEDIATE')
            require(maintenance.current(con)==seal)
            require(json.loads(con.execute('SELECT state FROM literal_maintenance_workflows WHERE source_task=?',(source,)).fetchone()[0])==s
                and con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(s['issue_id'],)).fetchone()[0]==old_raw)
            con.execute('INSERT INTO literal_author_bootstrap_recoveries VALUES(?,?)',(source,json.dumps(receipt,sort_keys=True)))
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(new,sort_keys=True),s['issue_id']))
            updated={**s,'stage':'author_dispatch','author_bootstrap_recovery':digest(receipt),'owner':cfg['author'],
                'required_action':'New isolated maintenance author after qualified pre-model context repair; original source unchanged'}
            for key in ('category','wakeup_id','marker','phase_started'):updated.pop(key,None)
            con.execute('UPDATE literal_maintenance_workflows SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
        return receipt
