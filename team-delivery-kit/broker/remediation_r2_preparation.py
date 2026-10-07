"""Prepare an original R2 base and qualify approved R1 tests without granting work."""
import json
import time
import urllib.error
try:
    import remediation_author_context as context
    import remediation_preparation as preparation
    import remediation_r2_issue as issues
    import remediation_test_review as review
    import technical_remediation_plan as planning
except ImportError:
    from broker import remediation_author_context as context
    from broker import remediation_preparation as preparation
    from broker import remediation_r2_issue as issues
    from broker import remediation_test_review as review
    from broker import technical_remediation_plan as planning


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS remediation_r2_preparations(source_task TEXT PRIMARY KEY,input_sha256 TEXT,state TEXT)')


def inputs(b,source,effects):
    with b.db() as con:
        row=con.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()
        if not row:raise ValueError('registered remediation required')
        value,state=map(json.loads,row)
        inputs=context.product_input(value,state)
        card=con.execute('SELECT state FROM remediation_r2_issues WHERE source_task=?',(source,)).fetchone()
        card=json.loads(card[0]) if card else {}
        step=state.get('steps',{}).get('R2',{})
        if (card.get('stage')!='issue_created' or not card.get('issue_id')
                or step.get('issue_id')!=card.get('issue_id') or step.get('stage')!='provision_pending'
                or state.get('r2_issue_hold')):
            raise ValueError('exact unassigned dependent R2 card required')
        route=con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(inputs['origin_issue'],)).fetchone()
        if not route:raise ValueError('preserved R1 route required')
        route=json.loads(route[0])
        if route.get('enabled') is not False:raise ValueError('approved R1 route must remain paused')
        if issues.dependency_busy(con,state):raise ValueError('R1 dependency lease still closing')
        if con.execute("SELECT 1 FROM native_bindings n JOIN leases l USING(request_id) "
                "WHERE n.issue_id=? AND l.status IN ('creating','starting','running','closing')",(card['issue_id'],)).fetchone():
            raise ValueError('R2 workspace is in use; preparation must not mutate it')
    root=effects.issues.request('/issues/'+value['root_issue'])
    if root.get('id')!=value['root_issue'] or root.get('status') in ('done','cancelled'):
        raise ValueError('nonterminal exact root required for R2 preparation')
    review.verify(b,inputs['origin_issue'],route,inputs['red'],effects.native)
    red=inputs['red']
    # Projection only: never relabel the persisted execution contract or Red origin.
    projection={**value,'previous_new_test_delivery':dict(volume=red['volume'],task_id=red['task_id'],
        manifest_sha256=red['red']['manifest_sha256'],test_sha256=red['red']['test_sha256'])}
    return value,state,projection


def prepare(b,source):
    with b.LOCK:
        fx=planning.Effects(b)
        value,parent,projection=inputs(b,source,fx)
        issue=parent['steps']['R2']['issue_id'];volume=b.PREFIX+'-base-'+issue
        input_sha=planning.digest(dict(contract=value,gate=parent['r1_gate'],issue_id=issue))
        with b.db() as con:
            initialize(con)
            row=con.execute('SELECT input_sha256,state FROM remediation_r2_preparations WHERE source_task=?',(source,)).fetchone()
            if row:
                if row[0]!=input_sha:raise ValueError('immutable R2 preparation input drift')
                state=json.loads(row[1])
            else:
                state=dict(stage='volume_pending',issue_id=issue,volume=volume,image=b.IMAGE,started_at=time.time(),
                    execution_authorized=False,release_homologated=False)
                con.execute('INSERT INTO remediation_r2_preparations VALUES (?,?,?)',(source,input_sha,json.dumps(state,sort_keys=True)))
        if state['stage']=='base_qualified':return state
        if state['stage']=='blocked':raise ValueError('retained R2 technical hold requires diagnosis')
        if state.get('image')!=b.IMAGE:raise ValueError('pinned preparation image drift; reconcile instead of recreate')
        def save(stage,**extra):
            nonlocal state
            updated={**state,'stage':stage,**extra}
            with b.db() as con:
                actual=con.execute('SELECT state FROM remediation_r2_preparations WHERE source_task=?',(source,)).fetchone()
                if not actual or json.loads(actual[0])!=state:raise ValueError('concurrent R2 preparation')
                con.execute('UPDATE remediation_r2_preparations SET state=? WHERE source_task=?',(json.dumps(updated,sort_keys=True),source))
            state=updated
        seed=projection['previous_new_test_delivery']
        for name,task in ((value['base']['volume'],None),(seed['volume'],seed['task_id'])):
            resource=b.docker('GET','/volumes/'+name);labels=resource.get('Labels',{}) if resource else {}
            if labels.get('delivery-kit.owner')!=b.OWNER or (task and labels.get('delivery-kit.test-first-task')!=task):
                raise ValueError('exact owned original base and approved Red snapshot required')
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':issue,'delivery-kit.base-sha':value['base']['base_sha']}
        target=b.docker('GET','/volumes/'+volume)
        if state['stage']=='volume_pending':
            if not target:
                save('volume_observe')
                b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
                target=b.docker('GET','/volumes/'+volume)
            else:save('volume_observe')
        if not target:raise ValueError('uncertain R2 volume creation; observe exact name only')
        if any(target.get('Labels',{}).get(k)!=v for k,v in labels.items()):raise ValueError('foreign R2 base volume')
        if state['stage']=='volume_observe':save('copy_pending')
        phase='seed' if state['stage'].startswith('seed_') else 'copy'
        name=b.PREFIX+'-remediation-r2-'+phase+'-'+issue
        expected=preparation.payload(b,projection,issue,volume,phase)
        expected['Labels']['delivery-kit.operation']='remediation-r2-original-base-'+phase
        info=b.docker('GET','/containers/'+name+'/json')
        if state['stage']==phase+'_pending':
            if info:raise ValueError('unrecorded R2 job requires reconciliation')
            save(phase+'_create_observe',job=dict(name=name,payload_sha256=planning.digest(expected)))
            b.docker('POST','/containers/create?name='+name,expected)
            info=b.docker('GET','/containers/'+name+'/json')
        if not info:raise ValueError('uncertain R2 job create; observe exact handle only')
        if state['job']['payload_sha256']!=planning.digest(expected):raise ValueError('fixed R2 payload drift')
        preparation.validate_job(b,info,expected)
        if state['stage']==phase+'_create_observe':save(phase+'_created',job={**state['job'],'container_id':info['Id']})
        if state['job']['container_id']!=info['Id']:raise ValueError('R2 job identity changed')
        if state['stage']==phase+'_created':
            save(phase+'_start_observe')
            b.docker('POST','/containers/'+info['Id']+'/start')
            info=b.docker('GET','/containers/'+name+'/json')
            if not info:raise ValueError('uncertain R2 start; observe exact handle only')
        if info['State']['Running']:return state
        if info['State'].get('Status')=='created':raise ValueError('uncertain R2 start; no identical start')
        if info['State']['ExitCode']!=0:raise ValueError('R2 fixed preparation failed; preserve job')
        proof=json.loads(b.docker_stdout(info['Id']))
        if phase=='copy':
            if (proof.get('operation')!='remediation_original_base_copy_v2'
                    or any(proof.get(k)!=value['base'][k] for k in ('base_sha','manifest_sha256'))
                    or proof.get('contract_sha256')!=value['contract_sha256'] or not proof.get('baseline_test_sha256')
                    or proof.get('baseline_unchanged') is not True or proof.get('product_unchanged') is not True
                    or proof.get('red_executed') is not False or proof.get('execution_authorized') is not False):
                raise ValueError('exact original R2 base copy receipt required')
            save('seed_pending',copy_job=state['job'],copy_proof=proof)
            return state
        preparation.validate_proof(projection,proof)
        if proof['baseline_test_sha256']!=state['copy_proof']['baseline_test_sha256']:
            raise ValueError('R2 copy/seed baseline inventory diverged')
        # Recheck approval after the real Docker operation, before admission.
        current,latest,_=inputs(b,source,fx)
        if planning.digest(dict(contract=current,gate=latest['r1_gate'],issue_id=issue))!=input_sha:
            raise ValueError('R1 approval changed during R2 preparation')
        b.register_issue_base(dict(issue_id=issue,base_sha=value['base']['base_sha'],volume=volume,
                                  manifest_sha256=value['base']['manifest_sha256']))
        save('base_qualified',seed_proof=proof,qualified_at=time.time(),
             required_action='install_paused_product_only_route_and_exact_foreign_red_reference_before_dispatch')
        return state


def tick(b):
    """Advance only exact created dependent cards; retain bounded technical holds."""
    with b.db() as con:
        initialize(con);issues.initialize(con)
        if not con.execute("SELECT 1 FROM sqlite_master WHERE name='remediation_executions'").fetchone():return
        rows=con.execute('SELECT e.source_task,e.state,p.state FROM remediation_executions e '
            'JOIN remediation_r2_issues i USING(source_task) '
            'LEFT JOIN remediation_r2_preparations p USING(source_task) '
            "WHERE json_extract(i.state,'$.stage')='issue_created'").fetchall()
    for source,raw,saved in rows:
        parent=json.loads(raw);state=json.loads(saved) if saved else {}
        if parent.get('r2_issue_hold') or state.get('stage') in ('blocked','base_qualified'):continue
        if not parent.get('r1_gate') or parent.get('steps',{}).get('R1',{}).get('stage')!='approved':continue
        with b.db() as con:
            if issues.dependency_busy(con,parent):continue
        category=None
        if state and time.time()-state['started_at']>=1800:category='r2_preparation_observation_deadline'
        else:
            try:prepare(b,source)
            except (TimeoutError,ConnectionError,urllib.error.URLError):continue
            except Exception as error:
                if type(error).__name__=='DockerOperationTimeout':continue
                category='r2_preparation_precondition_failed'
        if category:
            with b.db() as con:
                row=con.execute('SELECT state FROM remediation_r2_preparations WHERE source_task=?',(source,)).fetchone()
                if row:
                    latest=json.loads(row[0])
                    if latest['stage']=='base_qualified':continue
                    latest.update(stage='blocked',category=category,owner='techlead',
                        required_action='inspect exact original base, approved Red and preserved Docker job; no identical retry')
                    con.execute('UPDATE remediation_r2_preparations SET state=? WHERE source_task=?',(json.dumps(latest,sort_keys=True),source))
            issues.publish_hold(b,source,category,
                required_action='inspect exact original base, approved Red and preserved Docker preparation job; no identical retry')
