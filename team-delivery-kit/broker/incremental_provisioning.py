"""Controller-only unassigned unit issues and immutable first-unit provisioning.

No model calls, assignment or activation. Later units require the accepted prior
Green snapshot and cannot copy the original base as a shortcut.
"""
import json
import os
import re
import time
import urllib.request
try:
    import incremental_checkpoints as ledger,incremental_dispatch as dispatch
except ImportError:
    from broker import incremental_checkpoints as ledger,incremental_dispatch as dispatch


def initialize(con):
    con.execute('CREATE TABLE IF NOT EXISTS incremental_provisioning('
        'source_task TEXT,unit TEXT,revision INTEGER,plan TEXT,state TEXT,'
        'PRIMARY KEY(source_task,unit,revision))')


def plan(config,parent_config,unit,revision,parent_issue):
    criteria={c:parent_config['criteria'][c] for c in unit['criteria']}
    marker=ledger.digest(dict(source_task=config['source_task'],unit=unit['id'],revision=revision,
        proposal_sha256=config['proposal_sha256'],criteria=criteria))
    title='Delivery unit '+unit['id']+' r'+str(revision)+' '+marker[:12]
    description=('CONTROLLER UNIT '+marker+'\nParent: '+config['issue_id']+
        '\nProposal: '+config['proposal_sha256']+'\nObjective: '+unit['objective']+
        '\nAcceptance criteria (unchanged subset of approved scope):\n'+
        '\n'.join(c+': '+criteria[c] for c in unit['criteria'])+
        '\nDependencies: '+(','.join(unit['depends_on']) or 'verified original base')+
        '\nTDD: tests only until controller Red and independent test approval. Preserve all existing tests. '
        'Use the complete pinned suite. No skip, weaker assertions, removed tests or changed discovery. '
        'This unit is not the complete release. No merge, deploy or homologation authorization.')
    if len(description)>7000:raise ValueError('bounded unit brief required')
    return dict(title=title,description=description,parent_issue_id=config['issue_id'],
        project_id=parent_issue.get('project_id'),stage=int(unit['id'][1:]),status='todo')


class NativeIssues:
    def __init__(self,settings):self.settings=settings
    def request(self,path,body=None):
        headers={'Authorization':'Bearer '+self.settings['token'],
                 'X-Workspace-ID':self.settings['workspace_id'],'Content-Type':'application/json'}
        req=urllib.request.Request('http://backend:8080/api'+path,headers=headers,
            data=json.dumps(body).encode() if body is not None else None)
        with urllib.request.urlopen(req,timeout=10) as response:return json.load(response)
    def ensure(self,desired,*,allow_create=True):
        issues=[];offset=0
        while True:
            page=self.request('/issues?limit=100&offset='+str(offset))
            if not isinstance(page,dict) or not isinstance(page.get('issues'),list):
                raise ValueError('native issue pagination required')
            if type(page.get('total')) is not int or not 0<=page['total']<=2000:
                raise ValueError('bounded complete native issue lookup required')
            issues+=page['issues']
            if len({i['id'] for i in issues})!=len(issues):raise ValueError('native pagination repetition')
            if len(issues)>=page['total']:break
            if not page['issues']:raise ValueError('native pagination incomplete')
            offset+=len(page['issues'])
        matches=[i for i in issues if i.get('title')==desired['title']]
        if len(matches)>1:raise ValueError('duplicate incremental unit issue')
        if not matches and not allow_create:return None
        result=matches[0] if matches else self.request('/issues',desired)
        if (any(result.get(k)!=desired[k] for k in ('title','description','parent_issue_id','project_id','stage'))
                or result.get('workspace_id')!=self.settings['workspace_id']
                or result.get('assignee_id') is not None
                or result.get('status') in ('done','cancelled')):
            raise ValueError('fresh unassigned native unit issue required')
        return result


def ensure_issues(con,source,parent_issue,effects):
    initialize(con)
    row=con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone()
    if not row:raise ValueError('accepted checkpoint ledger required')
    config,state=map(json.loads,row)
    if state['execution_authorized']:raise ValueError('paused provisioning required')
    parent=json.loads(con.execute('SELECT config FROM test_decompositions WHERE source_task=?',(source,)).fetchone()[0])
    results=[]
    for unit in config['units']:
        revision=state['units'][unit['id']]['revision'];key=(source,unit['id'],revision)
        desired=plan(config,parent,unit,revision,parent_issue)
        previous=con.execute('SELECT plan,state FROM incremental_provisioning WHERE source_task=? AND unit=? AND revision=?',key).fetchone()
        if previous:
            if json.loads(previous[0])!=desired:raise ValueError('immutable unit brief drift')
            saved=json.loads(previous[1])
            if saved['stage']=='issue_created':results.append(saved);continue
            if saved['stage']=='blocked':raise ValueError('unit provisioning requires diagnosis')
        else:
            saved=dict(stage='issue_intent',at=time.time())
            con.execute('INSERT INTO incremental_provisioning VALUES(?,?,?,?,?)',
                (*key,json.dumps(desired,sort_keys=True),json.dumps(saved,sort_keys=True)));con.commit()
        try:
            issue=effects.ensure(desired)
        except Exception as error:
            category=type(error).__name__;count=saved.get('same_failure_count',0)+1 if saved.get('last_failure')==category else 1
            saved.update(last_failure=category,same_failure_count=count)
            if count>=2:saved.update(stage='blocked',owner='cto',required_action='reconcile_native_unit_issue')
            con.execute('UPDATE incremental_provisioning SET state=? WHERE source_task=? AND unit=? AND revision=?',
                        (json.dumps(saved,sort_keys=True),*key));con.commit();raise
        saved.update(stage='issue_created',issue_id=issue['id'],identifier=issue['identifier'])
        con.execute('UPDATE incremental_provisioning SET state=? WHERE source_task=? AND unit=? AND revision=?',
                    (json.dumps(saved,sort_keys=True),*key));con.commit();results.append(saved)
    return results


def provision_first(b,source):
    with b.LOCK,b.db() as con:
        initialize(con)
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1']
        if state['execution_authorized'] or unit['stage']!='awaiting_red':raise ValueError('paused first unit required')
        if unit.get('binding'):return unit['binding']
        created=con.execute('SELECT state FROM incremental_provisioning WHERE source_task=? AND unit=? AND revision=?',
                            (source,'U1',unit['revision'])).fetchone()
        saved=json.loads(created[0]) if created else {}
        if saved.get('stage')!='issue_created':raise ValueError('first unit issue required')
        issue=saved['issue_id'];base=b.issue_base(config['issue_id'])
        proof=json.loads(con.execute("SELECT receipt FROM initial_base_validations WHERE source_task=? AND status='passed'",(source,)).fetchone()[0])
        parent_route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(config['issue_id'],)).fetchone()[0])
        if len(parent_route.get('test_first_files',[]))!=1:raise ValueError('exact first-unit test declaration required')
        receipt=dict(checkpoint_manifest_sha256=unit['base_manifest_sha256'],base_manifest_sha256=base['manifest_sha256'],
            contract_sha256=proof['contract_sha256'],base_sha=base['base_sha'],baseline_test_sha256=proof['baseline_test_sha256'],
            new_test=parent_route['test_first_files'][0],suite_sha256=proof['suite_sha256'])
        if base['manifest_sha256']!=unit['base_manifest_sha256']:raise ValueError('original first-unit base drift')
        volume=b.PREFIX+'-base-'+issue
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':issue,'delivery-kit.base-sha':base['base_sha'],
                'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'incremental-unit-base'}
        existing=b.docker('GET','/volumes/'+volume)
        if existing and any(existing.get('Labels',{}).get(k)!=v for k,v in labels.items()):raise ValueError('foreign unit base volume')
        if not existing:b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
        name=b.PREFIX+'-unit-base-copy-'+issue
        old=b.docker('GET','/containers/'+name+'/json')
        if old:raise ValueError('interrupted unit copy requires diagnosis')
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='0:0',
                Entrypoint=['python3'],Cmd=['-c',
                    'import json,os;from base_copy import main;from initial_base_inspect import inspect;'
                    'main();print(json.dumps(inspect("/target",os.environ["EXPECTED_BASE_MANIFEST_SHA256"]),sort_keys=True))'],
                Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1',
                     'EXPECTED_BASE_MANIFEST_SHA256='+base['manifest_sha256']],NetworkDisabled=True,Labels=labels,
                HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                    Memory=268435456,PidsLimit=96,Mounts=[dict(Type='volume',Source=base['volume'],Target='/source',ReadOnly=True),
                        dict(Type='volume',Source=volume,Target='/target',ReadOnly=False)])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']!=0:raise ValueError('unit base copy failed')
                    copied=json.loads(b.docker_stdout(name))
                    if copied['manifest_sha256']!=receipt['base_manifest_sha256'] or copied['baseline_test_sha256']!=receipt['baseline_test_sha256']:
                        raise ValueError('copied unit base validation mismatch')
                    break
                time.sleep(.1)
            else:raise TimeoutError('unit base copy deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config'].get('Labels',{}).get(k)==v for k,v in labels.items()):
                b.docker('DELETE','/containers/'+info['Id']+'?force=true')
        b.register_issue_base(dict(issue_id=issue,base_sha=base['base_sha'],volume=volume,manifest_sha256=base['manifest_sha256']))
        paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(config['issue_id'],))]
        command=con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(config['issue_id'],)).fetchone()[0]
        b.register_issue_editables(dict(issue_id=issue,paths=paths,test_command=command))
        route=dict(parent_route,issue_id=issue,enabled=False)
        b.handoff_runtime.register(b,route)
        state=dispatch.bind(con,source,'U1',issue,receipt,ledger.digest(proof))
        return state['units']['U1']['binding']


def activate_first(b,source):
    """Operator-only bounded U1 trial; no authority for dependent unit execution."""
    try:import incremental_evidence as evidence
    except ImportError:from broker import incremental_evidence as evidence
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        unit=state['units']['U1'];binding=unit.get('binding')
        if not binding or unit['stage']!='awaiting_red':raise ValueError('bound tests-only first unit required')
        if state.get('activation'):
            if state.get('execution_units')!=['U1']:raise ValueError('activation scope drift')
            return state['activation']
        if state['execution_authorized']:raise ValueError('unrecorded activation requires diagnosis')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running')").fetchone():
            raise ValueError('idle activation window required')
        if con.execute("SELECT 1 FROM sqlite_master WHERE name='incremental_runtime_incidents'").fetchone():
            if con.execute('SELECT 1 FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone():
                raise ValueError('open runtime incident prevents activation')
        evidence._prior_suite(con,binding['prior_suite'],config,unit)
        issue=binding['issue_id'];actual=b.issue_base(issue)
        if actual['manifest_sha256']!=binding['materialization']['base_manifest_sha256']:
            raise ValueError('first unit installed base drift')
        if not dispatch.owns(con,issue):raise ValueError('single unit coordinator required')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(issue,)).fetchone()[0])
        if unit.get('test_repair'):
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='test_revision_trials'").fetchone():
                raise ValueError('test repair registration must precede activation')
            trial = con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?', (issue,)).fetchone()
            trial_config = json.loads(trial[0]) if trial else {}
            if (trial_config.get('parent_issue') != unit['test_repair']['parent_issue']
                    or trial_config.get('cto_decision') != unit['test_repair']['decision_task']):
                raise ValueError('test repair registration must precede activation')
        if route['enabled']:raise ValueError('paused unit route required')
        if (route['author']!=config['policy']['author'] or route['reviewer']!=config['policy']['delivery_reviewer']
                or route['techlead']!=config['policy']['test_reviewer']
                or route['contract_sha256']!=binding['materialization']['contract_sha256']):
            raise ValueError('unit role or contract drift')
        activation=dict(source_task=source,issue_id=issue,units=['U1'],mode='tests_only',
            proposal_sha256=config['proposal_sha256'],binding_sha256=ledger.digest(binding),
            initial_suite_sha256=binding['prior_suite'],delivery_approval=False)
        with ledger._atomic(con):
            route['enabled']=True
            state.update(execution_authorized=True,execution_units=['U1'],stage='active_first_unit',activation=activation)
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),issue))
            con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return activation


def provision_next(b,source,unit_id,new_test):
    """Operator-only materialization from an approved immediate predecessor."""
    import uuid
    try:import incremental_evidence as evidence
    except ImportError:from broker import incremental_evidence as evidence
    with b.LOCK:
        with b.db() as con:
            config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
            ids=[u['id'] for u in config['units']]
            if unit_id not in ids or ids.index(unit_id)==0:raise ValueError('dependent unit required')
            unit=state['units'][unit_id];previous=state['units'][ids[ids.index(unit_id)-1]]
            if unit['stage']!='awaiting_red' or previous['stage']!='checkpointed':raise ValueError('approved predecessor required')
            if unit.get('binding'):
                if unit['binding']['materialization']['new_test']!=new_test:raise ValueError('new test declaration drift')
                return unit['binding']
            if con.execute("SELECT 1 FROM leases WHERE status IN ('running','creating','starting')").fetchone():raise ValueError('idle provisioning window required')
            saved=json.loads(con.execute('SELECT state FROM incremental_provisioning WHERE source_task=? AND unit=? AND revision=?',(source,unit_id,unit['revision'])).fetchone()[0])
            if saved['stage']!='issue_created':raise ValueError('existing dependent issue required')
            issue=saved['issue_id'];author=previous['delivery_source_task'];review=previous['delivery_review_task']
            approval=con.execute('SELECT * FROM reviews WHERE source_task_id=? AND review_task_id=?',(author,review)).fetchone()
            if (not approval or approval['status']!='approved' or approval['reviewer_agent_id']!=config['policy']['delivery_reviewer']
                    or approval['manifest_sha256']!=unit['base_manifest_sha256']):raise ValueError('exact independent predecessor review required')
            snapshot=dict(con.execute("SELECT * FROM snapshots WHERE task_id=? AND status='complete'",(author,)).fetchone())
            proofs=[json.loads(r[0]) for r in con.execute("SELECT receipt FROM review_suite_rpc WHERE source_task=? AND status='passed'",(author,))]
            proofs=[p for p in proofs if p.get('manifest_sha256')==unit['base_manifest_sha256']]
            if len(proofs)!=1:raise ValueError('unique predecessor full suite required')
            prior_suite=ledger.digest(proofs[0]);evidence._prior_suite(con,prior_suite,config,unit)
            parent_route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(previous['binding']['issue_id'],)).fetchone()[0])
            base=b.issue_base(previous['binding']['issue_id'])
        volume=b.PREFIX+'-base-'+issue
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':issue,'delivery-kit.base-sha':base['base_sha'],
                'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'incremental-unit-base'}
        existing=b.docker('GET','/volumes/'+volume)
        if existing and any(existing.get('Labels',{}).get(k)!=v for k,v in labels.items()):raise ValueError('foreign dependent base volume')
        if not existing:b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
        name=b.PREFIX+'-dependent-base-'+uuid.uuid4().hex[:12]
        helper_image=os.environ.get('BROKER_PROVISION_IMAGE','')
        if not re.fullmatch(r'sha256:[a-f0-9]{64}',helper_image):raise ValueError('immutable provisioning helper required')
        code=('import json,os;from incremental_base import materialize;from initial_base_inspect import inspect;'
              'inspect("/previous-base",os.environ["PREVIOUS_BASE"]);'
              'previous=json.load(open("/previous-base/contract.json"));'
              'r=materialize("/checkpoint","/revision",previous,os.environ["NEW_TEST"],os.environ["CHECKPOINT"],os.environ["BASE_SHA"],resume=True);'
              'print(json.dumps(dict(materialization=r,spec=inspect("/revision",r["base_manifest_sha256"])),sort_keys=True))')
        try:
            b.docker('POST','/containers/create?name='+name,dict(Image=helper_image,User='10000:10000',Entrypoint=['python3'],Cmd=['-c',code],
                Env=['PYTHONPATH=/','PYTHONDONTWRITEBYTECODE=1','NEW_TEST='+new_test,'CHECKPOINT='+unit['base_manifest_sha256'],'BASE_SHA='+base['base_sha'],'PREVIOUS_BASE='+base['manifest_sha256']],
                NetworkDisabled=True,Labels=labels,HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],Memory=268435456,PidsLimit=96,
                    Mounts=[dict(Type='volume',Source=snapshot['volume'],Target='/checkpoint',ReadOnly=True),
                            dict(Type='volume',Source=base['volume'],Target='/previous-base',ReadOnly=True),
                            dict(Type='volume',Source=volume,Target='/revision',ReadOnly=False)])))
            b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
            while time.time()<deadline:
                info=b.docker('GET','/containers/'+name+'/json')
                if not info['State']['Running']:
                    if info['State']['ExitCode']!=0:raise ValueError('dependent base materialization failed')
                    result=json.loads(b.docker_stdout(name));break
                time.sleep(.1)
            else:raise TimeoutError('dependent base materialization deadline')
        finally:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and all(info['Config'].get('Labels',{}).get(k)==v for k,v in labels.items()):b.docker('DELETE','/containers/'+info['Id']+'?force=true')
        receipt=result['materialization']
        if receipt['baseline_test_sha256']!=unit['baseline_test_sha256']:raise ValueError('dependent baseline test drift')
        suite=b.run_portable_suite(volume,source,result['spec'],suite_evidence=True)
        if suite['tests']!=unit['prior_test_count']:raise ValueError('dependent base suite count drift')
        b.register_issue_base(dict(issue_id=issue,base_sha=base['base_sha'],volume=volume,manifest_sha256=receipt['base_manifest_sha256']))
        # Only previous product editables plus the genuinely new test remain writable.
        with b.db() as con:
            paths=[r[0] for r in con.execute('SELECT path FROM issue_editables WHERE issue_id=?',(previous['binding']['issue_id'],)) if r[0].removeprefix('/workspace/') not in unit['baseline_test_sha256']]
            command=con.execute('SELECT command FROM issue_test_commands WHERE issue_id=?',(previous['binding']['issue_id'],)).fetchone()[0]
        b.register_issue_editables(dict(issue_id=issue,paths=sorted(set(paths)|{'/workspace/'+new_test}),test_command=command))
        route=dict(parent_route,issue_id=issue,enabled=False,test_first_files=[new_test],contract_sha256=receipt['contract_sha256'])
        b.handoff_runtime.register(b,route)
        with b.db() as con:return dispatch.bind(con,source,unit_id,issue,receipt,prior_suite)['units'][unit_id]['binding']


def activate_next(b,source,unit_id):
    """Explicit operator approval for one bound dependent unit, tests-only first."""
    try:import incremental_evidence as evidence
    except ImportError:from broker import incremental_evidence as evidence
    with b.LOCK,b.db() as con:
        config,state=map(json.loads,con.execute('SELECT config,state FROM incremental_checkpoints WHERE source_task=?',(source,)).fetchone())
        ids=[u['id'] for u in config['units']]
        if unit_id not in ids or ids.index(unit_id)==0:raise ValueError('dependent activation required')
        unit=state['units'][unit_id];prior=state['units'][ids[ids.index(unit_id)-1]]
        if unit['stage']!='awaiting_red' or not unit.get('binding') or prior['stage']!='checkpointed':raise ValueError('bound dependent unit required')
        if con.execute("SELECT 1 FROM leases WHERE status IN ('running','creating','starting','closing')").fetchone():raise ValueError('idle activation required')
        if con.execute('SELECT 1 FROM incremental_runtime_incidents WHERE source_task=?',(source,)).fetchone():raise ValueError('open runtime incident')
        binding=unit['binding'];evidence._prior_suite(con,binding['prior_suite'],config,unit)
        if b.issue_base(binding['issue_id'])['manifest_sha256']!=binding['materialization']['base_manifest_sha256']:raise ValueError('dependent base identity drift')
        route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(binding['issue_id'],)).fetchone()[0])
        if unit.get('test_repair'):
            if not con.execute("SELECT 1 FROM sqlite_master WHERE name='test_revision_trials'").fetchone():
                raise ValueError('test repair registration must precede activation')
            trial=con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(binding['issue_id'],)).fetchone()
            trial_config=json.loads(trial[0]) if trial else {}
            if (trial_config.get('parent_issue')!=unit['test_repair']['parent_issue']
                    or trial_config.get('cto_decision')!=unit['test_repair']['decision_task']):
                raise ValueError('test repair registration must precede activation')
        if (route['author']!=config['policy']['author'] or route['reviewer']!=config['policy']['delivery_reviewer']
                or route['techlead']!=config['policy']['test_reviewer'] or route['test_first_files']!=[binding['materialization']['new_test']]
                or route['contract_sha256']!=binding['materialization']['contract_sha256'] or not dispatch.owns(con,binding['issue_id'])):raise ValueError('dependent route identity drift')
        if unit_id in state.get('execution_units',[]):
            if not route['enabled']:raise ValueError('dependent activation drift')
            return state['dependent_activations'][unit_id]
        if route['enabled']:raise ValueError('paused dependent route required')
        activation=dict(source_task=source,unit=unit_id,mode='tests_only',binding_sha256=ledger.digest(binding),delivery_approval=False)
        route['enabled']=True;state['execution_units'].append(unit_id);state.setdefault('dependent_activations',{})[unit_id]=activation
        state['execution_authorized']=True
        with ledger._atomic(con):
            con.execute('UPDATE delivery_routes SET config=? WHERE issue_id=?',(json.dumps(route,sort_keys=True),binding['issue_id']))
            con.execute('UPDATE incremental_checkpoints SET state=? WHERE source_task=?',(json.dumps(state,sort_keys=True),source))
        return activation
