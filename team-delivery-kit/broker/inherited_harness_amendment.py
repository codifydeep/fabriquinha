"""Evidence-bound amendment planning, not a recursive test revision or reset."""
import json
import time
try:
    import technical_remediation_plan as plans,remediation_red_reference as refs,native,handoff_runtime,handoffs
except ImportError:
    from broker import technical_remediation_plan as plans,remediation_red_reference as refs,native,handoff_runtime,handoffs


def config(proposal,peer,experiment,reference,previous,route,base):
    result=experiment.get('result') or {};proof=experiment.get('proof') or {}
    if (peer.get('stage')!='peer_reviewed' or peer.get('decision',{}).get('action')!='request_test_revision'
            or peer.get('execution_authorized') is not False or not peer.get('task_id')
            or experiment.get('stage')!='experiment_recorded' or experiment.get('result_sha256')!=plans.digest(result)
            or proof.get('proposal_sha256')!=plans.digest(proposal) or proof.get('peer_task')!=peer['task_id']
            or proof.get('peer_decision_sha256')!=plans.digest(peer['decision'])
            or reference['source_task']!=previous['source_task']
            or plans.digest(previous)!=reference['execution_contract_sha256']
            or proposal['reference_sha256']!=plans.digest(reference)
            or proposal['issue_id']!=route['issue_id'] or reference['issue_id']!=route['issue_id']
            or proposal['criteria']!=reference['criteria'] or proposal['criteria']!=previous['criteria']
            or proposal['original_depth']!=2 or previous['original_depth']!=2
            or len(previous['revision_lineage'])!=2 or previous.get('amendment')
            or len({route[k] for k in ('author','reviewer','techlead','cto')})!=4
            or route['author']!=previous['steps'][1]['owner'] or route['techlead']!=proposal['reviewer']
            or base['base_sha']!=previous['base']['base_sha'] or base['manifest_sha256']!=previous['base']['manifest_sha256']
            or route['contract_sha256']!=previous['contract_sha256']
            or result.get('operation')!='immutable_embedded_harness_syntax_experiment_v1'
            or result.get('test_sha256')!=reference['red']['red']['test_sha256'].get(result.get('test_file'))
            or proof.get('test_sha256')!=reference['red']['red']['test_sha256']
            or result.get('harness',{}).get('category') not in ('syntax_error','illegal_return')
            or result.get('harness',{}).get('exit_code')!=1
            or result.get('control',{}).get('exit_code')!=0 or result.get('product',{}).get('exit_code')!=0
            or any(result.get(k) is not False for k in ('test_edits_authorized','delivery_approval','product_executed'))):
        raise ValueError('exact independently supported immutable harness amendment required')
    amendment=dict(operation='inherited_harness_contract_amendment_v1',
        previous_source=previous['source_task'],previous_execution_sha256=plans.digest(previous),
        peer_task=peer['task_id'],peer_decision_sha256=plans.digest(peer['decision']),
        experiment_sha256=plans.digest(experiment),seed_red=reference['red'],
        original_depth=2,revision_depth_reset=False,attempt_limit=1,
        required_gates=['embedded_harness_compiles','behavioral_negative_controls','real_red_on_original_base',
            'independent_test_review','full_green','independent_product_review','pr_ci_same_sha','deploy_browser_qa_same_sha'],
        execution_authorized=False)
    inputs={result['test_file']:result['test_sha256'],result['product_file']:result['product_sha256']}
    return dict(source_task=proposal['source_task'],source_issue=route['issue_id'],root_issue=previous['root_issue'],
        original_depth=2,revision_lineage=previous['revision_lineage'],cto=route['cto'],reviewer=route['techlead'],
        original_author=route['author'],contract_sha256=route['contract_sha256'],
        context_sha256=route['execution_context']['sha256'],criteria=proposal['criteria'],base=base,
        volume=experiment['volume'],required_paths=proposal['required_paths'],
        diagnostic_task=proposal['cto_task'],diagnostic_wakeup=proposal['cto_wakeup'],amendment=amendment,
        experiment=dict(operation='inherited_harness_experiment_reference_v1',receipt_sha256=plans.digest(experiment),
            proof=dict(input_sha256=inputs,facts=dict(harness_syntax=result['harness']['category'],
                product_syntax=result['product']['category'],compiler_control=result['control']['category'],
                source_manifest=result['manifest_sha256'],historical_tests_changed=False))))


def register(b,source):
    with b.LOCK:
        with b.db() as con:
            plans.initialize(con)
            old=con.execute('SELECT config,state FROM technical_remediation_plans WHERE source_task=?',(source,)).fetchone()
            if old:
                if json.loads(old['config']).get('amendment',{}).get('operation')!='inherited_harness_contract_amendment_v1':
                    raise ValueError('foreign existing amendment registration')
                return json.loads(old['state'])
            row=con.execute('SELECT proposal,state FROM inherited_test_replans WHERE source_task=?',(source,)).fetchone()
            proposal,peer=map(json.loads,row)
            receipt=json.loads(con.execute('SELECT receipt FROM inherited_harness_experiments WHERE source_task=?',(source,)).fetchone()[0])
            current=handoffs.load(con,source);data=json.loads(current['data'])
            route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(proposal['issue_id'],)).fetchone()[0])
            if (current['stage']!='inherited_replan_required' or data.get('inherited_harness_experiment')!=receipt
                    or data.get('inherited_peer_review')!=peer or data.get('inherited_test_replan')!=proposal
                    or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()):
                raise ValueError('idle exact current amendment hold required')
            snapshot=con.execute('SELECT volume,status FROM failed_execution_snapshots WHERE task_id=?',(source,)).fetchone()
            if not snapshot or snapshot['status']!='complete':raise ValueError('complete failed diagnostic snapshot required')
            reference=refs.qualified(b,proposal['issue_id'])
            previous=json.loads(con.execute('SELECT contract FROM remediation_executions WHERE source_task=?',(reference['source_task'],)).fetchone()[0])
            experiment={**receipt,'volume':snapshot['volume']}
        base=b.issue_base(proposal['issue_id']);value=config(proposal,peer,experiment,reference,previous,route,base)
        settings=json.loads((b.STATE/'native.json').read_text());fx=handoff_runtime.Effects(b,settings)
        for tid,actor,wake,decision in ((proposal['cto_task'],route['cto'],proposal['cto_wakeup'],proposal['cto_decision']),
                                     (peer['task_id'],route['techlead'],peer['wakeup_id'],peer['decision'])):
            task=native.task_record(settings,tid,actor);reads=fx.read_evidence(task)
            if (task['status']!='completed' or task['issue_id']!=proposal['issue_id'] or task['wakeup_id']!=wake
                    or fx.decision(task)!=decision or any(reads.get(p,{}).get('lines',0)<=0
                        or reads[p]['lines']!=reads[p]['total_lines'] for p in value['required_paths'])):
                raise ValueError('live independent full-read CTO and peer decisions required')
        author=native.task_record(settings,source,route['author'])
        if author['status']!='failed' or author['issue_id']!=value['source_issue'] or any(
                t['status'] in ('queued','dispatched','running') for t in native.issue_task_runs(settings,value['source_issue'])):
            raise ValueError('closed exact failed implementation and no pending task required')
        labels=(b.docker('GET','/volumes/'+value['volume']) or {}).get('Labels',{})
        if labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.source-task')!=source or labels.get('delivery-kit.diagnostic-only')!='true':
            raise ValueError('controller-owned immutable experiment snapshot required')
        state=dict(stage='issue_intent',owner=value['cto'],execution_authorized=False,release_homologated=False)
        with b.db() as con:
            if handoffs.load(con,source)!=current or con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone():
                raise ValueError('amendment source changed before registration')
            con.execute('INSERT INTO technical_remediation_plans VALUES(?,?,?)',(source,json.dumps(value,sort_keys=True),json.dumps(state,sort_keys=True)))
            route['enabled']=False
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),value['source_issue']))
            data.update(harness_contract_amendment=dict(source_task=source,config_sha256=plans.digest(value),execution_authorized=False),
                required_action='CTO propose exact harness amendment; independent Tech Lead contract review required')
            handoffs.save(con,source,value['source_issue'],'inherited_replan_required',value['cto'],data,time.time())
        return state
