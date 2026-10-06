"""Independent native QA evidence assessment, NOT independent test execution.

Operator bridge reobserves the deployment before admission/reconciliation. This
bounded planning task cannot approve release, historical Red or product admission.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time

ASSESSOR='8c1926ec-ae14-4f36-b5ea-388d14c2d726'
SOURCE='01a10c8c-87da-7e33-b9ca-1645588d5c3a'
PARENT='01a10cdc-aebe-77e7-adc8-b6f385c81014'
AUTHOR='ce91fe5b-f6dd-4798-8f8c-6d3618ea83a1'


def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()


def typed_canary():
    from decision_schema import apply as schema
    import typed_decision_contract as typed
    from structured_response_contract import StructuredResponseRejected
    body=typed.apply(schema({'messages':[{'role':'user','content':
        'DELIVERY_DEPLOYMENT_EVIDENCE_V1:'+'a'*64+'\nDELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1:'+'a'*64}],'tools':[]}))
    value=dict(decision='ACCEPT_EVIDENCE',evidence_sha256='a'*64,reason='Canary only.',
        limitations=['Not a real QA assessment.'],release_homologated=False,product_admission_authorized=False,historical_tdd_red=False)
    def wire(v):return json.dumps({'choices':[{'index':0,'finish_reason':'tool_calls','message':{
        'content':None,'tool_calls':[{'type':'function','function':{'name':typed.EVIDENCE_NAME,'arguments':json.dumps(v)}}]}}]}).encode()
    output,_,proof=typed.translate(body,wire(value),'application/json')
    if json.loads(json.loads(output)['choices'][0]['message']['content'])!=value or proof['worker_tool_executed']:
        raise ValueError('typed canary changed values or executed tool')
    rejected=0
    for bad in (dict(value,reason='x'*1201),dict(value,release_homologated=True),dict(value,evidence_sha256='b'*64)):
        try:typed.translate(body,wire(bad),'application/json')
        except StructuredResponseRejected:rejected+=1
    if rejected!=3:raise ValueError('typed negative controls failed')
    return dict(schema='u3-typed-evidence-canary-v1',status='passed',negative_controls=3,
        values_preserved=True,worker_tool_executed=False,model_calls=0,release_homologated=False)


def instruction(config,structured=False,typed=False):
    return ('QUALITY/SECURITY: independently assess the supplied, controller-verified '
        'deployment dossier in this issue description. Existing-behavior coverage only. '
        'Do not claim to have run tests, accessed localhost, read a repository or used tools. '
        'Distinguish the failed cleanup receipt from passing browser assertions and its separate '
        'verified cleanup recovery. Rollback covers only a temporary database slot, not data migration. '
        'Assess whether the evidence is internally consistent and what remains missing before release. '
        'No repository, shell, network or administrative authority. Do not waive historical TDD Red, '
        'approve release or activate dependent product work. Return ONLY a JSON object with exact keys: '
        'decision (ACCEPT_EVIDENCE or REQUEST_CHANGES), evidence_sha256 ('+config['evidence_sha256']+'), '
        'reason (1-1200 characters), limitations (1-6 strings, each 1-300 characters), '
        'release_homologated=false, product_admission_authorized=false, historical_tdd_red=false. '
        'Acceptance is independent evidence assessment, NOT independent execution of QA tests.'+
        ('\nDELIVERY_DEPLOYMENT_EVIDENCE_V1:'+config['evidence_sha256'] if structured else '')+
        ('\nDELIVERY_TYPED_DEPLOYMENT_EVIDENCE_V1:'+config['evidence_sha256'] if typed else ''))


def transport_incident(config,state,task,request,event):
    if (state.get('stage')!='blocked' or 'protocol_recovery' not in state or 'typed_recovery' in state
            or task.get('status')!='failed' or task.get('agent_id')!=config['assessor']
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']
            or event.get('execution_id')!=request or event.get('status')!=502
            or event.get('category')!='structured_decision_response_invalid'
            or event.get('structured_rejection_category')!='nonterminal_or_non_json_response'
            or event.get('structured_format')!='json_schema' or event.get('strict_schema') is not True
            or event.get('require_parameters') is not True or type(event.get('call_number')) is not int):
        raise ValueError('exact failed native structured-response transport incident required')
    return dict(failed_task=task['id'],failed_wakeup=state['wakeup_id'],request_id=request,
        event=event,event_sha256=digest(event),cause='structured_response_transport',approval=False)


def protocol_recovery(config,state,task):
    if state.get('stage')!='blocked' or 'protocol_recovery' in state or state.get('reason')!='exact non-authorizing QA assessment required':
        raise ValueError('one specific protocol recovery required')
    raw=task.get('result',{}).get('output','');body=json.loads(raw)
    if not isinstance(body.get('reason'),str) or not 1200<len(body['reason'])<=1600:
        raise ValueError('only narrowly oversized reason may recover')
    # Validate every original semantic field and execution identity unchanged;
    # the short diagnostic copy is never stored or accepted as an approval.
    diagnostic=dict(body,reason='diagnostic only')
    verdict(config,state,dict(task,result={'output':json.dumps(diagnostic)}))
    return dict(failed_task=task['id'],failed_wakeup=state['wakeup_id'],
        failed_output_sha256=hashlib.sha256(raw.encode()).hexdigest(),reason_chars=len(body['reason']),
        cause='reason_length_overshoot',approval=False)


def verdict(config,state,task):
    if (task.get('status')!='completed' or task.get('agent_id')!=config['assessor']
            or task.get('issue_id')!=state['issue_id'] or task.get('wakeup_id')!=state['wakeup_id']
            or config['assessor']==config.get('author',AUTHOR)):
        raise ValueError('exact completed independent QA assessment required')
    raw=(task.get('result') or {}).get('output')
    if not isinstance(raw,str) or len(raw)>4000:raise ValueError('bounded actual native assessment required')
    body=json.loads(raw)
    keys={'decision','evidence_sha256','reason','limitations','release_homologated',
          'product_admission_authorized','historical_tdd_red'}
    if (not isinstance(body,dict) or set(body)!=keys
            or body['decision'] not in ('ACCEPT_EVIDENCE','REQUEST_CHANGES')
            or body['evidence_sha256']!=config['evidence_sha256']
            or not isinstance(body['reason'],str) or not 1<=len(body['reason'])<=1200
            or not isinstance(body['limitations'],list) or not 1<=len(body['limitations'])<=6
            or any(not isinstance(x,str) or not 1<=len(x)<=300 for x in body['limitations'])
            or any(body[k] is not False for k in ('release_homologated','product_admission_authorized','historical_tdd_red'))):
        raise ValueError('exact non-authorizing QA assessment required')
    return dict(schema='u3-deployment-evidence-assessment-v1',
        stage='evidence_assessment_accepted' if body['decision']=='ACCEPT_EVIDENCE' else 'blocked',
        assessor=config['assessor'],task_id=task['id'],issue_id=state['issue_id'],wakeup_id=state['wakeup_id'],
        evidence_sha256=config['evidence_sha256'],decision=body,independent_agent_qa_approval=False,
        release_homologated=False,product_admission_authorized=False,historical_tdd_red=False)


def controller(packet):
    import broker as b
    import native
    import handoff_runtime
    from incremental_provisioning import NativeIssues
    config=packet['config'];action=packet['action']
    if (config['assessor']!=ASSESSOR or config['source_task']!=SOURCE or config['parent']!=PARENT
            or config['author']!=AUTHOR or config['assessor']==config['author']):
        raise ValueError('fixed QA assessment scope required')
    if digest(config['dossier'])!=config['evidence_sha256']:raise ValueError('QA dossier digest mismatch')
    with b.LOCK:
        settings=json.loads((b.STATE/'native.json').read_text())
        if settings['agents'].get(ASSESSOR)!='planning':raise ValueError('non-executing QA mode required')
        with b.db() as con:
            con.execute('CREATE TABLE IF NOT EXISTS u3_deployment_assessments(evidence_sha256 TEXT PRIMARY KEY,config TEXT,state TEXT)')
            row=con.execute('SELECT config,state FROM u3_deployment_assessments WHERE evidence_sha256=?',
                            (config['evidence_sha256'],)).fetchone()
            if row:
                if json.loads(row['config'])!=config:raise ValueError('immutable assessment drift')
                state=json.loads(row['state'])
            else:
                state={'stage':'issue_intent'}
                con.execute('INSERT INTO u3_deployment_assessments VALUES(?,?,?)',
                    (config['evidence_sha256'],json.dumps(config,sort_keys=True),json.dumps(state)))
        def save():
            with b.db() as con:con.execute('UPDATE u3_deployment_assessments SET state=? WHERE evidence_sha256=?',
                (json.dumps(state,sort_keys=True),config['evidence_sha256']))
        if state['stage']=='issue_intent':
            issues=NativeIssues(settings);parent=issues.request('/issues/'+PARENT)
            description='Controller-verified evidence dossier; NOT a release approval.\n'+json.dumps(config['dossier'],sort_keys=True)
            if len(description)>7500:raise ValueError('bounded QA dossier required')
            issue=issues.ensure(dict(title='U3 post-deploy evidence assessment '+config['evidence_sha256'][:12],
                description=description,parent_issue_id=PARENT,project_id=parent.get('project_id'),stage=4,status='todo'))
            state.update(stage='dispatch_pending',issue_id=issue['id'],identifier=issue['identifier']);save()
        if action in ('capture_transport','resume_typed') and state.get('stage')=='blocked':
            tasks=[t for t in native.issue_task_runs(settings,state['issue_id']) if t.get('wakeup_id')==state['wakeup_id']]
            if len(tasks)!=1:raise ValueError('one failed transport execution required')
            task=native.task_record(settings,tasks[0]['id'],ASSESSOR)
            with b.db() as con:
                bindings=con.execute('SELECT request_id FROM native_bindings WHERE task_id=? AND agent_id=?',
                    (task['id'],ASSESSOR)).fetchall()
            if len(bindings)!=1:raise ValueError('one exact transport capability required')
            request=bindings[0]['request_id']
            if action=='capture_transport':
                events=[]
                for line in b.docker_stdout(b.PREFIX+'-model-proxy-1',limit=65536).splitlines():
                    try:value=json.loads(line)
                    except ValueError:continue
                    if value.get('execution_id')==request and value.get('status')==502:events.append(value)
                if len(events)!=1:raise ValueError('one preserved proxy rejection required')
                state['transport_incident']=transport_incident(config,state,task,request,events[0]);save()
            else:
                old=state.get('transport_incident',{})
                proof=transport_incident(config,state,task,request,old.get('event',{}))
                if proof!=old:raise ValueError('preserved transport evidence drift')
                probe=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
                if probe['Image']!=packet['qualified_proxy']:raise ValueError('qualified typed proxy required')
                canary=packet.get('typed_canary',{})
                if (canary.get('schema')!='u3-typed-evidence-canary-v1' or canary.get('status')!='passed'
                        or canary.get('negative_controls')!=3 or canary.get('model_calls')!=0
                        or canary.get('values_preserved') is not True or canary.get('worker_tool_executed') is not False):
                    raise ValueError('real installed typed canary required')
                proof['canary_sha256']=digest(canary)
                state.update(stage='dispatch_pending',typed_recovery=proof,previous_transport_blocker=state.get('reason'))
                state.pop('reason',None);save();action='dispatch'
        if action=='resume_protocol' and state.get('stage')=='blocked':
            tasks=[t for t in native.issue_task_runs(settings,state['issue_id']) if t.get('wakeup_id')==state['wakeup_id']]
            if len(tasks)!=1:raise ValueError('one failed assessment required')
            task=native.task_record(settings,tasks[0]['id'],ASSESSOR)
            recovery=protocol_recovery(config,state,task)
            # Require deployed proxy enforcement before admitting a fresh run.
            import urllib.request
            proxy=json.load(urllib.request.urlopen('http://model-proxy:8080/status',timeout=5))
            if proxy.get('remaining',0)<8:raise ValueError('bounded recovery budget unavailable')
            probe=b.docker('GET','/containers/'+b.PREFIX+'-model-proxy-1/json')
            if probe['Image']!=packet['qualified_proxy']:raise ValueError('qualified structured proxy required')
            state.update(stage='dispatch_pending',protocol_recovery=recovery,previous_blocker=state['reason'])
            state.pop('reason',None);save();action='dispatch'
        if state['stage'] in ('dispatch_pending','dispatch_intent') and action=='dispatch':
            fx=handoff_runtime.Effects(b,settings)
            if fx.remaining_calls()<8:raise ValueError('at least eight authorized proxy calls required')
            with b.db() as con:
                if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():
                    raise ValueError('idle bounded QA admission required')
            state['stage']='dispatch_intent';save()
            marker=digest(dict(evidence=config['evidence_sha256'],recovery=state['protocol_recovery'],
                typed=state.get('typed_recovery'))) if state.get('protocol_recovery') else config['evidence_sha256']
            wake=native.ensure_planning_start(settings,state['issue_id'],ASSESSOR,SOURCE,marker,
                instruction(config,structured=bool(state.get('protocol_recovery') or config.get('typed_contract')),
                    typed=bool(state.get('typed_recovery') or config.get('typed_contract'))),allow_create=True)
            state.update(stage='awaiting_assessment',wakeup_id=wake['id'],at=time.time());save()
        if state['stage']=='awaiting_assessment':
            tasks=[t for t in native.issue_task_runs(settings,state['issue_id']) if t.get('wakeup_id')==state['wakeup_id']]
            if len(tasks)>1:raise ValueError('duplicate QA assessment')
            if tasks:
                task=native.task_record(settings,tasks[0]['id'],ASSESSOR)
                if task['status'] not in ('queued','running','dispatched'):
                    try:result=verdict(config,state,task)
                    except Exception as error:
                        state.update(stage='blocked',owner='quality_security',reason=str(error)[:300],
                            next_action='CTO diagnoses protocol; no identical retry');save()
                    else:
                        state.update(stage=result['stage'],receipt=result,next_action='Independent executed QA and release lifecycle reconciliation remain pending')
                        state.pop('reason',None);save()
            if state['stage']=='awaiting_assessment' and time.time()-state['at']>1800:
                state.update(stage='blocked',owner='cto',reason='QA assessment deadline');save()
        print(json.dumps(state))


def main():
    import deploy_u3_coverage as deploy
    import integrate_u3_coverage as integration
    from release_eval import save_receipt
    parser=argparse.ArgumentParser();parser.add_argument('--dispatch',action='store_true')
    parser.add_argument('--resume-protocol',action='store_true');parser.add_argument('--qualified-proxy')
    parser.add_argument('--capture-transport',action='store_true');parser.add_argument('--resume-typed',action='store_true');args=parser.parse_args()
    if sum((args.dispatch,args.resume_protocol,args.capture_transport,args.resume_typed))>1:raise ValueError('one admission operation required')
    if (args.resume_protocol or args.resume_typed) and not args.qualified_proxy:raise ValueError('qualified proxy digest required')
    # Reobserve live deployment, exact GitHub CI/protection, independent review
    # and preserved browser/screenshot/cleanup hashes before every operation.
    integration.publication.run('python3',str(Path(__file__).with_name('deploy_u3_coverage.py')))
    r=json.loads(deploy.RECEIPT.read_text());proof=json.loads(Path(r['browser_receipt']).read_text())
    capsule=json.loads(Path(r['cleanup_certificate']).read_text())
    merged=json.loads(integration.RECEIPT.read_text())
    dossier=dict(schema='u3-deployment-dossier-v1',source_sha=r['source_sha'],url=r['url'],
        image=r['image'],container_id=r['container_id'],http_checks=r['http_checks'],browser_checks=r['browser_checks'],
        browser_result=proof['result'],browser_original_status=proof['status'],browser_original_cleanup=proof['cleanup'],
        browser_receipt_sha256=r['browser_sha256'],screenshot_sha256=r['screenshot_sha256'],
        cleanup_recovery=capsule,cleanup_certificate_sha256=r['cleanup_certificate_sha256'],
        rollback_verified=r['rollback_verified'],rollback_scope=r['rollback_scope'],rollback_http_checks=r['rollback_http_checks'],
        previous_sha=r['previous_sha'],application_restored=r['application_restored'],
        independent_code_review_sha256=merged['final_review_sha256'],main_ci=merged['main_ci'],
        release_homologated=False,product_admission_authorized=False,historical_tdd_red=False,
        original_u3_historical_red_hold=True,u4_dependency_released=False,operator_invoked=True)
    config=dict(assessor=ASSESSOR,author=AUTHOR,source_task=SOURCE,parent=PARENT,dossier=dossier,evidence_sha256=digest(dossier))
    action=next((name for enabled,name in ((args.resume_protocol,'resume_protocol'),(args.resume_typed,'resume_typed'),
        (args.capture_transport,'capture_transport'),(args.dispatch,'dispatch')) if enabled),'observe')
    packet=dict(config=config,action=action,
        qualified_proxy=args.qualified_proxy)
    if args.resume_typed:
        import inspect
        code='import json\n'+inspect.getsource(typed_canary)+'\nprint(json.dumps(typed_canary()))\n'
        packet['typed_canary']=json.loads(integration.publication.run('docker','exec','-e','PYTHONPATH=/',
            integration.publication.PROJECT+'-model-proxy-1','python','-c',code))
        save_receipt(deploy.RECEIPT.with_name('U3-COVERAGE-TYPED-CANARY.json'),
            dict(packet['typed_canary'],proxy_image=args.qualified_proxy))
    script=('namespace={"__name__":"operator_qa_assessment"};exec(compile('+repr(Path(__file__).read_text())+
        ',"operator_qa_assessment","exec"),namespace);namespace["controller"]('+repr(packet)+')\n')
    # Python stdin is executed by the operator, never a worker-supplied command.
    result=integration.publication.run('docker','exec','-i','-e','PYTHONPATH=/',
        integration.publication.PROJECT+'-execution-broker-1','python','-',data=script.encode())
    value=json.loads(result);save_receipt(deploy.RECEIPT.with_name('U3-COVERAGE-QA-ASSESSMENT.json'),
        dict(config=config,state=value,operator_invoked=True))
    print(json.dumps(value))


if __name__=='__main__':main()
