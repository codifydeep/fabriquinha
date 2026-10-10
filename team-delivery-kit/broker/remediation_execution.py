"""Bind approved recovery to durable work; provisioning is not worker authority."""
import json
import re
import time
import urllib.error
from jsonschema import Draft202012Validator
from remediation_plan_contract import schema
try:
    import technical_remediation_plan as planning
except ImportError:
    from broker import technical_remediation_plan as planning


def contract(config,state,tests,products):
    if config.get('intake_kind')=='rejected_remediation_r1_v1' and not config.get('r1_feedback'):
        raise ValueError('R1 feedback lineage required')
    sha=planning.digest(state.get('plan'))
    if (state.get('stage')!='plan_approved' or state.get('plan_sha256')!=sha
            or not state.get('plan_task') or not state.get('review_task') or state['plan_task']==state['review_task']
            or config['cto']==config['reviewer'] or config['original_author'] in (config['cto'],config['reviewer'])
            or config.get('original_depth')!=2 or not tests or not products
            or len(set(tests))!=len(tests) or len(set(products))!=len(products) or set(tests)&set(products)):
        raise ValueError('independent approved scoped recovery required')
    if any(not isinstance(p,str) or not re.fullmatch(r'[A-Za-z0-9_./-]+',p)
           or p.startswith('/') or any(v in ('','.','..') for v in p.split('/')) for p in [*tests,*products]):
        raise ValueError('canonical relative edit scope required')
    if any(p.startswith('tests/') or p.rsplit('/',1)[-1].startswith('test_') or p.endswith(('.test.js','.spec.js')) for p in products):
        raise ValueError('product stage cannot receive test permissions')
    Draft202012Validator(schema('plan',planning.digest(config),sorted(config['criteria']))).validate(state['plan'])
    Draft202012Validator(schema('review',sha,sorted(config['criteria']))).validate(state['review'])
    if state['plan']['action']!='propose_remediation_plan' or state['review']['decision']!='approve_plan':
        raise ValueError('approved exact remediation proposal required')
    steps=state['plan']['steps']
    if len(steps)!=3:raise ValueError('complete recovery chain required')
    result=[]
    for i,(step,scope) in enumerate(zip(steps,('new_tests_only','product_only','controller_only')),1):
        if (step['id']!='R'+str(i) or step['depends_on']!=([] if i==1 else ['R'+str(i-1)])
                or step['edit_scope']!=scope or set(step['criteria'])!=set(config['criteria'])):
            raise ValueError('unchanged full scope and dependencies required')
        result.append({**step,'owner':config['original_author'] if i<3 else 'controller',
            'editable_files':list(tests) if i==1 else list(products) if i==2 else [],
            'gates':(['original_base','preserved_previous_new_tests','real_red','independent_test_review'] if i==1 else
                ['approved_exact_r1_red','frozen_tests_readonly','full_green','independent_product_review'] if i==2 else
                ['independent_review_exact_sha','product_pr','ci_exact_sha','merge','deploy_exact_sha','browser_qa_exact_sha'])})
    value=dict(version='remediation_execution_contract_v1',run_id='remediation-'+planning.digest(dict(
        source=config['source_task'],plan=sha))[:20],source_task=config['source_task'],source_issue=config['source_issue'],
        root_issue=config['root_issue'],plan_sha256=sha,plan_task=state['plan_task'],review_task=state['review_task'],
        criteria=config['criteria'],steps=result,base=config['base'],contract_sha256=config['contract_sha256'],
        context_sha256=config['context_sha256'],original_depth=config['original_depth'],
        revision_lineage=config['revision_lineage'],baseline_edits_allowed=False,
        historical_snapshots_editable=False,release_homologated=False)
    if config.get('amendment'):
        amendment=config['amendment']
        if (amendment.get('operation')!='inherited_harness_contract_amendment_v1'
                or amendment.get('original_depth')!=2 or amendment.get('attempt_limit')!=1
                or amendment.get('revision_depth_reset') is not False or amendment.get('execution_authorized') is not False
                or not amendment.get('seed_red') or not amendment.get('experiment_sha256')):
            raise ValueError('exact independently reviewed harness amendment required')
        value['amendment']=amendment
    if config.get('r1_feedback'):
        feedback=config['r1_feedback']
        if (config.get('intake_kind')!='rejected_remediation_r1_v1'
                or feedback.get('operation')!='remediation_r1_review_feedback_v1'
                or type(feedback.get('round')) is not int or not 1<=feedback['round']<=2
                or feedback.get('original_depth')!=2 or feedback.get('revision_depth_reset') is not False
                or feedback.get('execution_authorized') is not False or feedback.get('attempt_limit')!=2
                or not feedback.get('previous_source') or not feedback.get('certificate')):
            raise ValueError('bounded independently sponsored R1 feedback required')
        value['r1_feedback']=feedback
    return value


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS remediation_executions(source_task TEXT PRIMARY KEY,contract TEXT,state TEXT)')


def register(b,source):
    with b.LOCK:
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            config,state=map(json.loads,row)
            if config.get('amendment',{}).get('kind')=='inherited_frozen_suite':
                try:import inherited_suite_intake
                except ImportError:from broker import inherited_suite_intake
                inherited_suite_intake.validate_parent(con,config)
            if config.get('r1_feedback'):
                try:import remediation_r1_feedback
                except ImportError:from broker import remediation_r1_feedback
                remediation_r1_feedback.validate_parent(con,config)
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['source_issue'],)).fetchone()[0])
            if (route.get('author')!=config['original_author'] or route.get('cto')!=config['cto']
                    or route.get('techlead')!=config['reviewer'] or route.get('contract_sha256')!=config['contract_sha256']
                    or route.get('execution_context',{}).get('sha256')!=config['context_sha256']):
                raise ValueError('approved source route or context drift')
            if config.get('amendment'):
                try:import remediation_red_reference as references
                except ImportError:from broker import remediation_red_reference as references
                origin=references.qualified(b,config['source_issue'])
                if (not origin or origin['red']!=config['amendment']['seed_red']
                        or origin['source_task']!=config['amendment']['previous_source']
                        or origin['execution_contract_sha256']!=config['amendment']['previous_execution_sha256']):
                    raise ValueError('unchanged inherited amendment seed required')
                old_red=origin['red'];tests=sorted(old_red['red']['test_sha256'])
            else:
                old_red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(config['source_issue'],)).fetchone()[0])
                tests=sorted(route['test_first_files'])
            if set(tests)!=set(old_red['red']['test_sha256']):raise ValueError('historic NEW-test scope drift')
            inputs=config['experiment']['proof']['input_sha256']
            if any(inputs.get(p)!=sha for p,sha in old_red['red']['test_sha256'].items()):raise ValueError('approved diagnostic test seed drift')
            paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(config['source_issue'],))]
            products=sorted(p.removeprefix('/workspace/') for p in paths
                if p.removeprefix('/workspace/') not in tests)
            value=contract(config,state,tests,products)
            value['previous_new_test_delivery']=dict(task_id=old_red['task_id'],volume=old_red['volume'],
                manifest_sha256=old_red['red']['manifest_sha256'],test_sha256=old_red['red']['test_sha256'])
            previous=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
            if previous:
                if json.loads(previous[0])!=value:raise ValueError('immutable execution contract drift')
                return json.loads(previous[1])
            if route.get('enabled') or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                raise ValueError('idle preserved source route required')
        fx=planning.Effects(b)
        for phase,key,role,wake in [('awaiting_plan','plan_task','cto',state['plan_wakeup']),
                                     ('awaiting_review','review_task','reviewer',state['wakeup_id'])]:
            task=fx.task(state[key],config[role]);body=fx.result(task)
            if not planning.validate_result(config,{**state,'stage':phase,'wakeup_id':wake},task,body,fx.reads(task)):
                raise ValueError('live independent approval required')
            if body!=state['plan' if role=='cto' else 'review']:raise ValueError('native approved artifact drift')
        current_base=b.issue_base(config['source_issue'])
        if current_base!=config['base']:
            try:import base_equivalence
            except ImportError:from broker import base_equivalence
            base_equivalence.qualify(b,config,current_base)
        receipt=dict(stage='r1_issue_intent',owner=config['original_author'],execution_authorized=False,
            contract_sha256=planning.digest(value),created_at=time.time(),
            steps={step['id']:dict(stage='provision_pending' if step['id']=='R1' else 'waiting_dependency') for step in value['steps']})
        with b.db() as con:
            current=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            if list(map(json.loads,current))!=[config,state]:raise ValueError('approved recovery changed before registration')
            if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('execution started during qualification')
            con.execute('INSERT INTO remediation_executions VALUES(?,?,?)',(source,json.dumps(value,sort_keys=True),json.dumps(receipt,sort_keys=True)))
        return receipt


def issue_spec(value,parent):
    step=value['steps'][0]
    text=('REMEDIATION R1 — TESTS ONLY; no worker dispatch yet.\nRun: '+value['run_id']+
        '\nApproved plan: '+value['plan_sha256']+'\nOriginal source: '+value['source_task']+
        '\nOriginal Git base: '+value['base']['base_sha']+'\nObjective: '+step['objective']+
        '\nApproved acceptance (unchanged):\n'+'\n'.join(k+': '+v for k,v in value['criteria'].items())+
        '\nEditable NEW tests: '+json.dumps(step['editable_files'])+
        '\nDo not edit product, historical snapshots or baseline tests. Preserve all existing methods/assertions. '
        'Provisioning, original-base verification and preserved-test seeding must precede dispatch. '
        'Actual Red and independent immutable test review must precede product authority. '
        'This card is not a release or homologation approval.')
    if len(text)>7000:raise ValueError('split lossless R1 context before provisioning')
    return dict(title='Remediation R1 '+planning.digest(value)[:16],description=text,parent_issue_id=value['root_issue'],
                project_id=parent.get('project_id'),stage=1,status='todo')


def provision_issue(b,source):
    """One durable native issue creation; uncertain writes are observation-only."""
    with b.LOCK:
        register(b,source)
        with b.db() as con:
            value,s=map(json.loads,con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
        if s['stage']=='r1_provision_pending':return s
        if s['stage'] not in ('r1_issue_intent','r1_issue_post_pending','r1_issue_observe'):raise ValueError('pending R1 issue required')
        fx=planning.Effects(b);parent=fx.issues.request('/issues/'+value['root_issue']);desired=issue_spec(value,parent)
        allow=s['stage']=='r1_issue_intent'
        if allow:
            s={**s,'stage':'r1_issue_post_pending'}
            with b.db() as con:
                con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(s,sort_keys=True),source))
        try:item=fx.issues.ensure(desired,allow_create=allow)
        except (TimeoutError,urllib.error.URLError):item=None
        if item is None:
            new={**s,'stage':'r1_issue_observe','required_action':'Tech Lead reconcile exact issue creation; no repeated POST'}
        else:
            new={**s,'stage':'r1_provision_pending','issue_id':item['id'],'identifier':item.get('identifier'),
                 'required_action':'qualify_original_base_and_preserved_seed_before_r1_dispatch'}
            new['steps']={**s['steps'],'R1':{**s['steps']['R1'],'issue_id':item['id'],'stage':'provision_pending'}}
        with b.db() as con:
            current=json.loads(con.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])
            if current!=s:raise ValueError('concurrent R1 provisioning transition')
            con.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
        return new
