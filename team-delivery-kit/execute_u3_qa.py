"""Fixed controller QA execution requested by an independent native QA task.

No agent argv/URL/image, no shell capability or release approval. An interrupted
validation is observed/diagnosed, never automatically repeated. Operator bridge
is intentionally separate from future durable workflow activity integration.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import time
ASSESSOR='8c1926ec-ae14-4f36-b5ea-388d14c2d726'
AUTHOR='ce91fe5b-f6dd-4798-8f8c-6d3618ea83a1'
SOURCE='01a10c8c-87da-7e33-b9ca-1645588d5c3a'
PARENT='01a10cdc-aebe-77e7-adc8-b6f385c81014'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

SHA='e45c26256d8d0d3fa20b5d7bd021234421bcc2c1'


def request_canary():
    from decision_schema import apply as schema
    import typed_decision_contract as typed
    from structured_response_contract import StructuredResponseRejected
    body=typed.apply(schema({'messages':[{'role':'user','content':'DELIVERY_DEPLOYMENT_VALIDATION_V1:'+'a'*64+
        '\nDELIVERY_TYPED_DEPLOYMENT_VALIDATION_V1:'+'a'*64}],'tools':[]}))
    value=dict(operation='run_fixed_deployment_qa',evidence_sha256='a'*64,reason='Canary only.',
        release_homologated=False,product_admission_authorized=False)
    def wire(v):return json.dumps({'choices':[{'finish_reason':'tool_calls','message':{'content':None,
        'tool_calls':[{'type':'function','function':{'name':'submit_deployment_validation_request','arguments':json.dumps(v)}}]}}]}).encode()
    out,_,proof=typed.translate(body,wire(value),'application/json')
    if proof['worker_tool_executed'] or json.loads(json.loads(out)['choices'][0]['message']['content'])!=value:
        raise ValueError('fixed QA request canary failed')
    count=0
    for bad in (dict(value,command='arbitrary'),dict(value,evidence_sha256='b'*64),dict(value,release_homologated=True)):
        try:typed.translate(body,wire(bad),'application/json')
        except StructuredResponseRejected:count+=1
    if count!=3:raise ValueError('fixed QA request negative controls failed')
    padded=json.loads(wire(value));padded['choices'][0]['message']['content']=' '
    normalized,padding=typed.normalize_validation_padding(body,json.dumps(padded).encode(),'application/json')
    recovered,_,proof=typed.translate(body,normalized,'application/json')
    if (not padding or padding['padding_chars']!=1 or not padding['model_arguments_unchanged']
            or json.loads(json.loads(recovered)['choices'][0]['message']['content'])!=value):
        raise ValueError('installed bounded QA padding support required')
    return dict(status='passed',negative_controls=3,model_calls=0,worker_tool_executed=False)


def request_receipt(config,state,task,decision):
    if (config.get('assessor')!=ASSESSOR or config.get('author')!=AUTHOR or ASSESSOR==AUTHOR
            or config.get('source_sha')!=SHA or task.get('status')!='completed'
            or task.get('agent_id')!=ASSESSOR or task.get('issue_id')!=state['issue_id']
            or task.get('wakeup_id')!=state['wakeup_id'] or not isinstance(decision,dict)
            or set(decision)!={'operation','evidence_sha256','reason','release_homologated','product_admission_authorized'}
            or decision['operation']!='run_fixed_deployment_qa' or decision['evidence_sha256']!=config['evidence_sha256']
            or not isinstance(decision['reason'],str) or not 1<=len(decision['reason'])<=600
            or decision['release_homologated'] is not False or decision['product_admission_authorized'] is not False):
        raise ValueError('exact independently requested fixed QA operation required')
    return dict(schema='u3-fixed-qa-request-v1',task_id=task['id'],assessor=ASSESSOR,issue_id=state['issue_id'],
        wakeup_id=state['wakeup_id'],source_sha=SHA,evidence_sha256=config['evidence_sha256'],
        operation=decision['operation'],decision_sha256=digest(decision),release_homologated=False)


def may_validate(state):return state.get('stage')=='validation_requested'


def padding_incident(state,task,request,rejection):
    shape=rejection.get('response_shape',{})
    if (state.get('stage')!='blocked' or 'padding_recovery' in state
            or task.get('status')!='failed' or task.get('agent_id')!=ASSESSOR
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']
            or rejection.get('operation')!='rejected_typed_decision_adapter_v1'
            or rejection.get('category')!='typed_mixed_content'
            or any(shape.get(k) is not True for k in
                ('parsed','terminal','expected_tool','arguments_json_valid','arguments_schema_valid'))
            or shape.get('legacy_function_call') is not False or shape.get('submissions')!=1
            or shape.get('content_shape')!='whitespace_only' or shape.get('content_chars')!=1
            or rejection.get('worker_tool_executed') is not False
            or rejection.get('delivery_approval') is not False):
        raise ValueError('exact failed one-character padding incident required')
    return dict(failed_task=task['id'],failed_wakeup=state['wakeup_id'],request_id=request,
        rejection=rejection,rejection_sha256=digest(rejection),approval=False)


def executed_receipt(request,deployment,proof,http):
    if (deployment.get('source_sha')!=SHA or proof.get('status')!='passed' or proof.get('cleanup')!='passed'
            or proof.get('automated') is not True or proof.get('identity',{}).get('source_sha')!=SHA
            or proof['identity'].get('application_image')!=deployment['image']
            or proof.get('result',{}).get('status')!='passed' or proof['result'].get('source_sha')!=SHA
            or proof['result'].get('contexts')!=2 or proof['result'].get('checks')!=deployment['browser_checks']
            or len(proof['result']['checks'])!=40
            or http!=['/health','/ready','/','/static/app.js','/static/style.css']):
        raise ValueError('new exact-SHA controlled QA evidence required')
    return dict(schema='u3-controller-executed-qa-v1',request_task=request['task_id'],assessor=ASSESSOR,
        source_sha=SHA,executed_by='fixed_controller_qa_runner',http_checks=http,browser_checks=proof['result']['checks'],
        browser_sha256=digest(proof),screenshot_sha256=proof['screenshot_sha256'],cleanup='passed',
        independent_agent_qa_approval=False,release_homologated=False,historical_tdd_red=False,
        product_admission_authorized=False,model_calls_for_validation=0)


def instruction(config):
    return ('QUALITY/SECURITY: request the fixed deployment QA operation on source '+SHA+
        '. Prior EVAL-129 accepted supplied evidence only. You have NOT independently executed QA yet. '
        'Request run_fixed_deployment_qa; the controller will verify this exact native execution and '
        'run five HTTP checks plus the unchanged 40-check browser scenario in two fresh contexts. '
        'No arbitrary argv, URLs, images, files, terminal or administrative authority. '
        'Do not claim tests executed or release approved. Supply a concise reason <=600 characters.\n'
        'DELIVERY_DEPLOYMENT_VALIDATION_V1:'+config['evidence_sha256']+'\n'
        'DELIVERY_TYPED_DEPLOYMENT_VALIDATION_V1:'+config['evidence_sha256'])


def controller(packet):
    import broker as b
    import native,handoff_runtime
    from incremental_provisioning import NativeIssues
    config=packet['config']
    if config.get('assessor')!=ASSESSOR or config.get('author')!=AUTHOR or config.get('source_sha')!=SHA:
        raise ValueError('fixed QA execution scope required')
    with b.LOCK:
        settings=json.loads((b.STATE/'native.json').read_text())
        if settings['agents'].get(ASSESSOR)!='planning':raise ValueError('no-tools QA requester required')
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS u3_qa_executions(evidence_sha256 TEXT PRIMARY KEY,config TEXT,state TEXT)')
            row=con.execute('SELECT config,state FROM u3_qa_executions WHERE evidence_sha256=?',(config['evidence_sha256'],)).fetchone()
            if row:
                if json.loads(row['config'])!=config:raise ValueError('immutable QA execution config drift')
                state=json.loads(row['state'])
            else:
                state={'stage':'issue_intent'}
                con.execute('INSERT INTO u3_qa_executions VALUES(?,?,?)',
                    (config['evidence_sha256'],json.dumps(config,sort_keys=True),json.dumps(state)))
            approved=con.execute('SELECT state FROM u3_deployment_assessments WHERE evidence_sha256=?',
                (config['evidence_sha256'],)).fetchone()
            if not approved or json.loads(approved['state']).get('receipt')!=config['assessment']:
                raise ValueError('actual independent prior evidence assessment required')
        def save():
            with b.db() as con:con.execute('UPDATE u3_qa_executions SET state=? WHERE evidence_sha256=?',
                (json.dumps(state,sort_keys=True),config['evidence_sha256']))
        if state['stage']=='issue_intent':
            issues=NativeIssues(settings);parent=issues.request('/issues/'+PARENT)
            issue=issues.ensure(dict(title='U3 independent fixed QA execution '+config['evidence_sha256'][:12],
                description='QA request only, not release approval. Prior accepted assessment: '+json.dumps(config['assessment'],sort_keys=True),
                parent_issue_id=PARENT,project_id=parent.get('project_id'),stage=5,status='todo'))
            state.update(stage='dispatch_pending',issue_id=issue['id'],identifier=issue['identifier']);save()
        if packet.get('recover_padding') and state['stage']=='blocked':
            runs=[r for r in native.issue_task_runs(settings,state['issue_id']) if r.get('wakeup_id')==state['wakeup_id']]
            if len(runs)!=1:raise ValueError('one failed padding task required')
            task=native.task_record(settings,runs[0]['id'],ASSESSOR)
            with b.db() as con:
                bindings=con.execute('SELECT request_id FROM native_bindings WHERE task_id=? AND agent_id=?',
                    (task['id'],ASSESSOR)).fetchall()
            if len(bindings)!=1 or bindings[0]['request_id']!=packet['incident_request']:
                raise ValueError('exact failed padding capability required')
            incident=padding_incident(state,task,bindings[0]['request_id'],packet['rejection'])
            if b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')['Image']!=packet['qualified_proxy']:
                raise ValueError('qualified padding recovery proxy required')
            state.update(stage='dispatch_pending',padding_recovery=incident);save()
        if (packet['dispatch'] or packet.get('recover_padding')) and state['stage'] in ('dispatch_pending','dispatch_intent'):
            fx=handoff_runtime.Effects(b,settings)
            if fx.remaining_calls()<8:raise ValueError('authorized QA budget required')
            with b.db() as con:
                if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                    raise ValueError('idle QA execution admission required')
            if b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')['Image']!=packet['qualified_proxy']:
                raise ValueError('qualified fixed QA request proxy required')
            state['stage']='dispatch_intent';save()
            key=digest(dict(config=config,padding_recovery=state['padding_recovery'])) if 'padding_recovery' in state else digest(config)
            wake=native.ensure_planning_start(settings,state['issue_id'],ASSESSOR,SOURCE,key,instruction(config),allow_create=True)
            state.update(stage='awaiting_request',wakeup_id=wake['id'],at=time.time());save()
        if state['stage']=='awaiting_request':
            runs=[r for r in native.issue_task_runs(settings,state['issue_id']) if r.get('wakeup_id')==state['wakeup_id']]
            if len(runs)>1:raise ValueError('duplicate QA execution request')
            if runs:
                task=native.task_record(settings,runs[0]['id'],ASSESSOR)
                if task['status'] not in ('queued','running','dispatched'):
                    try:
                        if task['status']!='completed':
                            raise ValueError('native QA request failed before valid typed submission')
                        value=json.loads((task.get('result') or {}).get('output',''))
                        proof=request_receipt(config,state,task,value)
                        with b.db() as con:
                            bindings=con.execute('SELECT request_id FROM native_bindings WHERE task_id=? AND agent_id=?',
                                (task['id'],ASSESSOR)).fetchall()
                        if len(bindings)!=1:raise ValueError('one fixed QA capability required')
                        proof['request_id']=bindings[0]['request_id']
                    except Exception as error:
                        state.update(stage='blocked',reason=str(error)[:300],owner='cto',next_action='Diagnose, no identical retry');save()
                    else:state.update(stage='validation_requested',request=proof);save()
            if state['stage']=='awaiting_request' and time.time()-state['at']>1800:
                state.update(stage='blocked',reason='QA request deadline',owner='cto');save()
        print(json.dumps(state))


def main():
    import deploy_u3_coverage as deploy
    import integrate_u3_coverage as integration
    from release_eval import save_receipt
    parser=argparse.ArgumentParser();parser.add_argument('--dispatch',action='store_true');parser.add_argument('--qualified-proxy')
    parser.add_argument('--recover-padding',action='store_true')
    args=parser.parse_args()
    if (args.dispatch or args.recover_padding) and not args.qualified_proxy:raise ValueError('qualified proxy digest required')
    pub=integration.publication
    if args.dispatch or args.recover_padding:
        import inspect
        code='import json\n'+inspect.getsource(request_canary)+'\nprint(json.dumps(request_canary()))\n'
        canary=json.loads(pub.run('docker','exec','-e','PYTHONPATH=/',pub.PROJECT+'-model-proxy-1','python','-c',code))
        if canary!=dict(status='passed',negative_controls=3,model_calls=0,worker_tool_executed=False):
            raise ValueError('installed fixed QA request canary required')
        save_receipt(deploy.RECEIPT.with_name('U3-COVERAGE-QA-REQUEST-CANARY.json'),dict(canary,proxy_image=args.qualified_proxy))
    pub.run('python3',str(Path(__file__).with_name('assess_u3_deployment.py')))
    assessment=json.loads(deploy.RECEIPT.with_name('U3-COVERAGE-QA-ASSESSMENT.json').read_text())
    if assessment['state']['stage']!='evidence_assessment_accepted':raise ValueError('prior QA evidence assessment required')
    config=dict(assessor=ASSESSOR,author=AUTHOR,source_sha=SHA,evidence_sha256=assessment['config']['evidence_sha256'],
        assessment=assessment['state']['receipt'])
    packet=dict(config=config,dispatch=args.dispatch,qualified_proxy=args.qualified_proxy)
    if args.recover_padding:
        request='db29e8d4-014d-4d97-bc27-ab014083a264'
        query='import sqlite3,json; c=sqlite3.connect("/meter/deterministic-reads.sqlite"); print(json.dumps([json.loads(r[0]) for r in c.execute("SELECT receipt FROM typed_decision_rejections WHERE execution_id=?",('+repr(request)+',))])); c.close()'
        rejections=json.loads(pub.run('docker','exec',pub.PROJECT+'-model-proxy-1','python','-c',query))
        if len(rejections)!=1:raise ValueError('one durable padding rejection required')
        packet.update(recover_padding=True,incident_request=request,rejection=rejections[0])
    script=('namespace={"__name__":"operator_fixed_qa"};exec(compile('+repr(Path(__file__).read_text())+
        ',"operator_fixed_qa","exec"),namespace);namespace["controller"]('+repr(packet)+')\n')
    state=json.loads(pub.run('docker','exec','-i','-e','PYTHONPATH=/',pub.PROJECT+'-execution-broker-1','python','-',data=script.encode()))
    receipt_path=deploy.RECEIPT.with_name('U3-COVERAGE-EXECUTED-QA.json')
    previous=json.loads(receipt_path.read_text()) if receipt_path.exists() else None
    if not may_validate(state):
        if previous and previous.get('stage') not in ('awaiting_request','dispatch_pending') and not args.recover_padding:
            print(json.dumps(previous));return
        save_receipt(receipt_path,state);print(json.dumps(state));return
    if previous and previous.get('stage') in ('validation_intent','blocked','validation_passed'):
        if previous.get('reason')=='post-deploy browser QA  cleanup: browser QA cleanup timeout; absence unproven':
            from enroll_u3_cleanup import enroll
            enroll()  # no identical QA execution or uncertain deletion
        print(json.dumps(previous));return
    # Correlate controller request to the real validated proxy adapter receipt.
    query='import sqlite3,json; c=sqlite3.connect("/meter/deterministic-reads.sqlite"); print(json.dumps([json.loads(r[0]) for r in c.execute("SELECT receipt FROM typed_decisions WHERE execution_id=?",('+repr(state['request']['request_id'])+',))])); c.close()'
    typed=json.loads(pub.run('docker','exec','-e','PYTHONPATH=/',pub.PROJECT+'-model-proxy-1','python','-c',query))
    if (len(typed)!=1 or typed[0].get('mode')!='deployment_validation_request'
            or typed[0].get('evidence_sha256')!=config['evidence_sha256']
            or typed[0].get('operation')!='validated_typed_decision_adapter_v1'
            or typed[0].get('model_values_preserved') is not True
            or typed[0].get('delivery_approval') is not False
            or typed[0].get('worker_tool_executed') is not False or typed[0].get('validation_executed') is not False):
        raise ValueError('actual non-executing typed validation request receipt required')
    state.update(stage='validation_intent',typed_request_receipt=typed[0],operator_invoked=True)
    save_receipt(receipt_path,state)
    try:
        pub.run('python3',str(Path(__file__).with_name('deploy_u3_coverage.py')))
        deployment=json.loads(deploy.RECEIPT.read_text())
        http=deploy.ready(SHA)
        folder=pub.ROOT/'.local-port2/browser-acceptance/U3-INDEPENDENT-QA'
        old=os.environ.get('DELIVERY_KIT_COMPOSE_PROJECT');os.environ['DELIVERY_KIT_COMPOSE_PROJECT']=pub.PROJECT
        try:
            proof=deploy.browser.qualify(config=deployment['browser_config'],deployed_container=deploy.NAME,
                source_sha=SHA,evidence_dir=folder,runtime_env={'FEEDBACK_DB_PATH':'/tmp/feedback.db'})
        finally:
            if old is None:os.environ.pop('DELIVERY_KIT_COMPOSE_PROJECT',None)
            else:os.environ['DELIVERY_KIT_COMPOSE_PROJECT']=old
        paths=[p for p in folder.glob('*.json') if json.loads(p.read_text())==proof]
        if len(paths)!=1:raise ValueError('unique new browser QA execution required')
        if str(paths[0])==deployment['browser_receipt']:raise ValueError('old browser evidence cannot substitute new QA execution')
        result=executed_receipt(state['request'],deployment,proof,http)
        result['browser_receipt']=str(paths[0]);state.update(stage='validation_passed',receipt=result,
            next_action='QA must independently assess this new execution receipt; release remains blocked')
    except Exception as error:
        state.update(stage='blocked',owner='devops',reason=str(error)[:300],
            next_action='Inspect preserved fixed QA attempt; no identical retry')
        save_receipt(receipt_path,state)
        if state['reason']=='post-deploy browser QA  cleanup: browser QA cleanup timeout; absence unproven':
            try:
                from enroll_u3_cleanup import enroll
                enroll()
            except Exception as enrollment_error:
                # Preserve the original failed receipt. A controller re-entry
                # retries only enrollment, never QA or deletion.
                print(json.dumps(dict(event='qa_cleanup_enrollment_pending',
                    category=type(enrollment_error).__name__)),flush=True)
        raise
    save_receipt(receipt_path,state);print(json.dumps(state))


if __name__=='__main__':main()
