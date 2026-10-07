"""Executed fixed SPIKE -> autonomous CTO proposal -> independent Tech Lead.

This lane consumes controller evidence, never text claiming an experiment ran.
It preserves the exhausted author execution and does not dispatch implementation.
Only a separately qualified executor may consume the exact independent proposal.
"""
import json
import hashlib
import time
from types import SimpleNamespace


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS calibration_failure_plans(source_task TEXT PRIMARY KEY,config TEXT,state TEXT)')


def modules():
    try:import calibration_rework as lane,harness_qualification as jobs,handoffs,native
    except ImportError:from broker import calibration_rework as lane,harness_qualification as jobs,handoffs,native
    return lane,jobs,handoffs,native


def validate_experiment(proof,identity):
    from service_mode_harness_qualification import TEST,validate_controls
    try:from service_mode_observation_hypothesis import FAILED
    except ImportError:from broker.service_mode_observation_hypothesis import FAILED
    if (proof.get('operation')!='fixed_observation_hypothesis_v1' or proof.get('status')!='supported'
            or proof.get('original_manifest_sha256')!=identity['manifest_sha256']
            or proof.get('hypothesis')!='fresh_terminal_observation_after_async_settlement'
            or any(proof.get(k) is not True for k in ('inputs_unchanged','original_test_bodies_unchanged','diagnostic_copy_only'))
            or any(proof.get(k) is not False for k in ('valid_red_green_receipt','author_retry_authorized','delivery_approval'))):
        raise ValueError('actual nonapproving immutable hypothesis proof required')
    original=proof.get('original',{});variant=proof.get('variant',{})
    positive=original.get('facts',{}).get('positive',{})
    if (original.get('phase')!='positive_reference' or original.get('status')!='rejected'
            or original.get('facts',{}).get('manifest_sha256')!=identity['manifest_sha256']
            or positive.get('failures')!=2 or set(positive.get('failed_methods',[]))!=FAILED
            or positive.get('tests',0)<15 or any(positive.get(k)!=0 for k in
                ('errors','skipped','unexpected_successes','expected_failures'))
            or original.get('facts',{}).get('test_sha256')!=proof.get('original_test_sha256')
            or variant.get('manifest_sha256')!=proof.get('variant_manifest_sha256')
            or variant.get('test_sha256')!=proof.get('variant_test_sha256')
            or proof['original_test_sha256']==proof['variant_test_sha256']
            or proof['original_manifest_sha256']==proof['variant_manifest_sha256']):
        raise ValueError('exact changed diagnostic copy and original failure required')
    _,jobs,_,_=modules()
    jobs.validate_result(variant,dict(manifest_sha256=proof['variant_manifest_sha256'],
                                    test_sha256={TEST:proof['variant_test_sha256']}))
    validate_controls(variant['positive'],variant['negative_controls'])


def handle(b,route,runs,source,prior,effects):
    if (not route.get('enabled') or not prior or prior['stage'] not in ('test_first_blocked','calibration_failure_plan')):
        return False
    with b.LOCK:return _handle(b,route,runs,source,prior,effects)


def _handle(b,route,runs,source,prior,effects):
    lane,jobs,handoffs,_=modules();key=source['id'];issue=route['issue_id']
    with b.LOCK,b.db() as con:
        initialize(con)
        existing=con.execute('SELECT config,state FROM calibration_failure_plans WHERE source_task=?',(key,)).fetchone()
        if not existing:
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='observation_hypothesis_experiments'").fetchone():return False
            observed=con.execute('SELECT identity,state FROM observation_hypothesis_experiments WHERE source_task=?',(key,)).fetchone()
            if not observed:return False
            identity,experiment=map(json.loads,observed)
            if experiment.get('stage')!='complete':return False
            saved=con.execute('SELECT config,state FROM calibration_reworks WHERE issue_id=?',(issue,)).fetchone()
            if not saved:return False
            previous,held=map(json.loads,saved)
            bindings=con.execute('SELECT n.agent_id,l.status FROM native_bindings n JOIN leases l USING(request_id) WHERE n.task_id=? AND n.issue_id=?',(key,issue)).fetchall()
            if (source.get('status')!='failed' or source.get('agent_id')!=route['author']
                    or held.get('stage')!='blocked' or held.get('category')!='calibration_author_failed'
                    or held.get('author_task')!=key or source.get('wakeup_id')!=held.get('author_wakeup')
                    or len(bindings)!=1 or bindings[0][0]!=route['author'] or bindings[0][1]!='closed'
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()
                    or con.execute('SELECT 1 FROM test_first_red WHERE issue_id=?',(issue,)).fetchone()
                    or any(t['status'] in ('queued','dispatched','running') for t in runs)
                    or identity.get('source_task')!=key or identity.get('issue_id')!=issue
                    or previous['contract_sha256']!=route['contract_sha256']
                    or any(previous[k]!=route[v] for k,v in (('author','author'),('cto','cto'),('peer','techlead')))):
                return False
            info=b.docker('GET','/containers/'+experiment['container_id']+'/json')
            original_image=SimpleNamespace(IMAGE=identity['payload']['Image'],OWNER=b.OWNER,docker=b.docker)
            expected=jobs.payload(original_image,key,identity['volume'],identity['manifest_sha256'])
            expected['Cmd']=['/service_mode_observation_hypothesis.py','/delivery',identity['manifest_sha256']]
            expected['Labels']['delivery-kit.purpose']='observation-hypothesis'
            if identity['payload']!=expected:raise ValueError('fixed hypothesis job policy drift')
            jobs.verify_job(info,expected)
            if info['State']['Running'] or info['State']['Status']!='exited' or info['State']['ExitCode']!=0:
                raise ValueError('actual completed fixed experiment required')
            raw=b.docker_stdout(info['Id'],include_stderr=False,limit=32768)
            if hashlib.sha256(raw.encode()).hexdigest()!=experiment['receipt_sha256'] or json.loads(raw)!=experiment['proof']:
                raise ValueError('durable experiment receipt drift')
            proof=experiment['proof'];validate_experiment(proof,identity)
            labels=b.docker('GET','/volumes/'+identity['volume']).get('Labels',{})
            if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=key
                    or labels.get('delivery-kit.diagnostic-only')!='true'):
                raise ValueError('owned failed diagnostic snapshot required')
            config={**previous,'source_task':key,'volume':identity['volume'],
                'manifest_sha256':identity['manifest_sha256'],'diagnosis_only':True,
                'diagnostic':proof['original']['facts'],
                'experiment_summary':dict(receipt_sha256=experiment['receipt_sha256'],
                    hypothesis=proof['hypothesis'],original_failures=2,variant_positive_tests=proof['variant']['positive']['tests'],
                    variant_negative_controls=len(proof['variant']['negative_controls']),
                    diagnostic_copy_only=True,delivery_approval=False)}
            config['diagnostic']['phase']=proof['original']['phase']
            state=dict(stage='cto_pending',previous_failure=held,delivery_approval=False,author_retry_authorized=False)
            lane.instruction(config,state)
            con.execute('INSERT INTO calibration_failure_plans VALUES(?,?,?)',(key,json.dumps(config,sort_keys=True),json.dumps(state,sort_keys=True)))
        else:config,state=map(json.loads,existing)
        if (config['contract_sha256']!=route['contract_sha256'] or any(config[k]!=route[v]
                for k,v in (('author','author'),('cto','cto'),('peer','techlead')))):raise ValueError('diagnostic plan route drift')
    def persist(new):
        with b.db() as con:
            current=handoffs.load(con,key);data=json.loads(current['data'])
            con.execute('UPDATE calibration_failure_plans SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),key))
            data['calibration_failure_plan']=dict(source_task=key,manifest_sha256=config['manifest_sha256'],state=new)
            data['required_action']=new.get('required_action','calibration_failure_plan:'+new['stage'])
            owner=config['peer'] if new['stage'].startswith('peer') else config['cto']
            handoffs.save(con,key,issue,'calibration_failure_plan',owner,data,time.time())
    try:lane.advance(config,state,runs,effects,persist)
    except (ValueError,TypeError,KeyError) as error:
        persist({**state,'stage':'blocked','category':'calibration_failure_plan_rejected',
                 'error_type':type(error).__name__,'owner':config['cto'],'author_retry_authorized':False})
    return True


def mounts(b,binding):
    lane,_,_,native=modules()
    with b.db() as con:
        initialize(con)
        rows=con.execute('SELECT config,state FROM calibration_failure_plans').fetchall()
        matching=[tuple(map(json.loads,row)) for row in rows if json.loads(row[0])['issue_id']==binding['issue_id']]
        matching=[(c,s) for c,s in matching if s['stage'].startswith(('cto','peer'))]
        if not matching:return []
        if len(matching)!=1:raise ValueError('one active calibration failure plan required')
        config,state=matching[0];role='cto' if state['stage'].startswith('cto') else 'peer'
        if config[role]!=binding['agent_id']:return []
        task=con.execute('SELECT task_id FROM native_bindings WHERE request_id=?',(binding['request_id'],)).fetchone()
    if not task:raise ValueError('diagnostic planner binding required')
    settings=json.loads((b.STATE/'native.json').read_text())
    run=native.task_record(settings,task[0],binding['agent_id']);wake=state.get(role+'_wakeup')
    if not wake and state['stage']==role+'_intent':
        observed=native.ensure_task_handoff(settings,config['issue_id'],config[role],
            config['source_task'] if role=='cto' else state['cto_task'],lane.marker(config,role),lane.instruction(config,state),allow_create=False)
        wake=observed['id'] if observed else None
    if not wake or run.get('wakeup_id')!=wake:return []
    labels=b.docker('GET','/volumes/'+config['volume']).get('Labels',{})
    if (labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=config['source_task']
            or labels.get('delivery-kit.diagnostic-only')!='true'):
        raise ValueError('diagnostic plan immutable ownership drift')
    return [dict(Type='volume',Source=config['volume'],Target='/evidence/candidate',ReadOnly=True)]
