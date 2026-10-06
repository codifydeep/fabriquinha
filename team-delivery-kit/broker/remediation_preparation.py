"""Durable R1 preparation. No worker grants, product writes or historic reset."""
import json
import hashlib
import time
try:
    import remediation_execution as execution
except ImportError:
    from broker import remediation_execution as execution


def validate_proof(value,proof):
    base=value['base'];seed=value['previous_new_test_delivery']
    if (proof.get('operation')!='remediation_original_base_seed_v1'
            or proof.get('base_sha')!=base['base_sha'] or proof.get('manifest_sha256')!=base['manifest_sha256']
            or proof.get('contract_sha256')!=value['contract_sha256']
            or proof.get('previous_manifest_sha256')!=seed['manifest_sha256']
            or proof.get('seed_test_sha256')!=seed['test_sha256']
            or not proof.get('baseline_test_sha256') or proof.get('baseline_unchanged') is not True
            or proof.get('snapshot_permissions_unchanged') is not True
            or proof.get('product_unchanged') is not True or proof.get('red_executed') is not False
            or proof.get('execution_authorized') is not False or proof.get('release_homologated') is not False):
            raise ValueError('exact unchanged original base and preserved seed required')


def payload(b,value,issue,volume,phase='copy'):
    if phase not in ('copy','seed'):raise ValueError('fixed preparation phase required')
    seed=value['previous_new_test_delivery']
    env=['PYTHONDONTWRITEBYTECODE=1','EXPECTED_BASE_MANIFEST_SHA256='+value['base']['manifest_sha256']]
    mounts=[dict(Type='volume',Source=value['base']['volume'],Target='/source',ReadOnly=True),
            dict(Type='volume',Source=volume,Target='/target',ReadOnly=phase=='seed')]
    if phase=='seed':
        env.append('REVISION_SEED_JSON='+json.dumps({k:seed[k] for k in ('manifest_sha256','test_sha256')},sort_keys=True))
        mounts.append(dict(Type='volume',Source=seed['volume'],Target='/previous',ReadOnly=True))
    return dict(Image=b.IMAGE,User='0:0' if phase=='copy' else '10000:10000',Entrypoint=['python'],Cmd=['/remediation_workspace_probe.py',phase],
        Env=env,
        NetworkDisabled=True,Labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':issue,
            'delivery-kit.run-id':value['run_id'],'delivery-kit.operation':'remediation-original-base-'+phase},
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,PidsLimit=64,Tmpfs={'/workspace':'size=16m,mode=1777','/opt/data':'size=1m,mode=1777'},Mounts=mounts))


def validate_job(b,info,expected):
    c,h=info.get('Config',{}),info.get('HostConfig',{})
    labels=c.get('Labels',{})
    image=b.docker('GET','/images/'+expected['Image']+'/json')
    env=dict(e.split('=',1) for e in image['Config'].get('Env',[]))
    env.update(dict(e.split('=',1) for e in expected['Env']))
    actual_env=dict(e.split('=',1) for e in c.get('Env',[]))
    if (info.get('Image')!=expected['Image'] or any(c.get(k)!=expected[k] for k in ('User','Entrypoint','Cmd'))
            or actual_env!=env or any(any(word in key.upper() for word in ('TOKEN','SECRET','API_KEY','PASSWORD')) for key in actual_env)
            or any(labels.get(k)!=v for k,v in expected['Labels'].items())
            or labels.get('com.docker.compose.project')!=b.PREFIX+'-tests'
            or h.get('NetworkMode')!='none' or h.get('ReadonlyRootfs') is not True
            or h.get('Privileged') or h.get('Binds') or h.get('Devices')
            or h.get('CapAdd') or h.get('CapDrop')!=['ALL']
            or h.get('Tmpfs')!=expected['HostConfig']['Tmpfs']):
        raise ValueError('fixed owned offline preparation job required')
    wanted={(m['Source'],m['Target'],not m['ReadOnly']) for m in expected['HostConfig']['Mounts']}
    actual={(m.get('Name'),m.get('Destination'),m.get('RW')) for m in info.get('Mounts',[]) if m.get('Type')=='volume'}
    if actual!=wanted or any(m.get('Type') not in ('volume','tmpfs') for m in info.get('Mounts',[])):
        raise ValueError('preparation mounts drift')


def capture_identity_failure(b,source):
    """Preserve an authentic old root/DAC denial before replacing the image."""
    with b.LOCK,b.db() as c:
        value,s=map(json.loads,c.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
        if s.get('identity_split_failure'):return s['identity_split_failure']
        if (s['stage']!='r1_preparation_blocked' or s.get('category')!='ValueError'
                or s.get('identity_split_recovery') or s.get('execution_authorized') is not False
                or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
            raise ValueError('idle exact legacy preparation failure required')
        old=s['preparation'];info=b.docker('GET','/containers/'+old['name']+'/json')
        cfg=info['Config'];labels=cfg.get('Labels',{});h=info['HostConfig']
        if (info['Image']!='sha256:81ea475c793efbb1fcd59ee7d674a7529bfe1abceeeac4a00998410cde2fb99b'
                or info['State']['Running'] or info['State']['ExitCode']!=1 or cfg.get('User')!='0:0'
                or cfg.get('Cmd')!=['/remediation_workspace_probe.py'] or cfg.get('Entrypoint')!=['python']
                or labels.get('delivery-kit.owner')!=b.OWNER or labels.get('delivery-kit.issue-id')!=s['issue_id']
                or labels.get('delivery-kit.run-id')!=value['run_id'] or labels.get('com.docker.compose.project')!=b.PREFIX+'-tests'
                or h.get('NetworkMode')!='none' or h.get('CapDrop')!=['ALL'] or h.get('CapAdd') or h.get('Privileged')):
            raise ValueError('preserved fixed old identity-denied job required')
        mounts={m.get('Destination'):m for m in info['Mounts'] if m.get('Type')=='volume'}
        if (set(mounts)!={'/source','/previous','/target'} or mounts['/previous'].get('RW') is not False
                or mounts['/previous'].get('Name')!=value['previous_new_test_delivery']['volume']
                or mounts['/source'].get('RW') is not False or mounts['/source'].get('Name')!=value['base']['volume']):
            raise ValueError('unchanged immutable source mounts required')
        log=b.docker_stdout(info['Id'],include_stderr=True)
        if "PermissionError: [Errno 13] Permission denied: '/previous/manifest.json'" not in log:
            raise ValueError('observed exact snapshot read denial required')
        proof=dict(operation='preserved_root_snapshot_identity_denial_v1',container_id=info['Id'],image=info['Image'],
            stderr_sha256=hashlib.sha256(log.encode()).hexdigest(),source_uid='0:0',required_uid='10000:10000',
            permissions_changed=False,execution_authorized=False)
        c.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',
                  (json.dumps({**s,'identity_split_failure':proof},sort_keys=True),source))
        return proof


def resume_split_identity(b,source):
    with b.LOCK:
        execution.register(b,source)
        with b.db() as c:
            value,s=map(json.loads,c.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
            if s.get('identity_split_recovery'):return s
            proof=s.get('identity_split_failure') or {}
            if (s['stage']!='r1_preparation_blocked' or proof.get('operation')!='preserved_root_snapshot_identity_denial_v1'
                    or b.IMAGE==proof.get('image') or proof.get('permissions_changed') is not False
                    or s.get('execution_authorized') is not False
                    or c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()):
                raise ValueError('one qualified changed-identity preparation required')
            info=b.docker('GET','/containers/'+proof['container_id']+'/json')
            if not info or info['State']['Running'] or info['State']['ExitCode']!=1 or info['Image']!=proof['image']:
                raise ValueError('unchanged failed preparation required')
            new={**s,'stage':'r1_provision_pending','preparation_phase':'copy',
                'identity_split_recovery':dict(previous=s,failed_job=proof['container_id'],
                    copy_uid='0:0',seed_uid='10000:10000',attempt_limit=1,permissions_changed=False),
                'required_action':'copy_original_then_validate_seed_with_worker_identity'}
            new.pop('category',None)
            c.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
            return new


def prepare(b,source):
    with b.LOCK:
        execution.register(b,source)
        with b.db() as c:
            value,s=map(json.loads,c.execute('SELECT contract,state FROM remediation_executions WHERE source_task=?',(source,)).fetchone())
            if s['stage']=='r1_base_qualified':return s
            if s['stage'] not in ('r1_provision_pending','r1_seed_provision_pending','r1_base_job_intent','r1_base_job_created','r1_base_job_start_pending','r1_base_job_running'):
                raise ValueError('pending R1 base preparation required')
            if c.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone():raise ValueError('idle preparation required')
        phase=s.get('preparation_phase','copy')
        issue=s['issue_id'];volume=b.PREFIX+'-base-'+issue;name=b.PREFIX+'-remediation-'+phase+'-'+issue
        labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':issue,'delivery-kit.base-sha':value['base']['base_sha']}
        # Volume names are exact. Existing foreign resources are never touched.
        base=b.docker('GET','/volumes/'+value['base']['volume'])
        prior=b.docker('GET','/volumes/'+value['previous_new_test_delivery']['volume'])
        if (not base or base.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
                or not prior or prior.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER
                or prior['Labels'].get('delivery-kit.test-first-task')!=value['previous_new_test_delivery']['task_id']):
            raise ValueError('owned preserved source volumes required')
        target=b.docker('GET','/volumes/'+volume)
        if target and any(target.get('Labels',{}).get(k)!=v for k,v in labels.items()):raise ValueError('foreign R1 base volume')
        if not target:b.docker('POST','/volumes/create',dict(Name=volume,Labels=labels))
        expected=payload(b,value,issue,volume,phase)
        def save(stage,**extra):
            nonlocal s
            new={**s,'stage':stage,**extra}
            with b.db() as c:
                if json.loads(c.execute('SELECT state FROM remediation_executions WHERE source_task=?',(source,)).fetchone()[0])!=s:raise ValueError('concurrent R1 preparation')
                c.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(new,sort_keys=True),source))
            s=new
        info=b.docker('GET','/containers/'+name+'/json')
        if s['stage'] in ('r1_provision_pending','r1_seed_provision_pending'):
            if info:raise ValueError('unrecorded preparation job requires reconciliation')
            save('r1_base_job_intent',preparation_phase=phase,preparation=dict(name=name,image=b.IMAGE,volume=volume,payload_sha256=execution.planning.digest(expected)))
            b.docker('POST','/containers/create?name='+name,expected)
            info=b.docker('GET','/containers/'+name+'/json')
            if not info:raise ValueError('preparation create handle missing; no repeated POST')
        if not info:raise ValueError('preparation handle absent; observe only, no repeated POST')
        validate_job(b,info,expected)
        if s['stage']=='r1_base_job_intent':save('r1_base_job_created')
        if s['stage']=='r1_base_job_created':
            save('r1_base_job_start_pending')
            b.docker('POST','/containers/'+info['Id']+'/start')
            info=b.docker('GET','/containers/'+info['Id']+'/json')
        if info['State']['Running']:
            save('r1_base_job_running',preparation={**s['preparation'],'container_id':info['Id']})
            return s
        if info['State'].get('Status')=='created':raise ValueError('uncertain preparation start; inspect before retry')
        if info['State']['ExitCode']!=0:raise ValueError('fixed R1 preparation failed; preserve job evidence')
        proof=json.loads(b.docker_stdout(info['Id']))
        if phase=='copy':
            if (proof.get('operation')!='remediation_original_base_copy_v2'
                    or proof.get('base_sha')!=value['base']['base_sha'] or proof.get('manifest_sha256')!=value['base']['manifest_sha256']
                    or proof.get('contract_sha256')!=value['contract_sha256'] or not proof.get('baseline_test_sha256')
                    or proof.get('baseline_unchanged') is not True or proof.get('product_unchanged') is not True
                    or proof.get('red_executed') is not False or proof.get('execution_authorized') is not False):
                raise ValueError('exact original base copy receipt required')
            save('r1_seed_provision_pending',preparation_phase='seed',copy_preparation={**s['preparation'],
                'container_id':info['Id'],'proof':proof},required_action='qualify_seed_as_worker_uid_without_changing_snapshot_permissions')
            return s
        validate_proof(value,proof)
        if proof['baseline_test_sha256']!=s['copy_preparation']['proof']['baseline_test_sha256']:
            raise ValueError('copy and seed baseline inventories diverged')
        b.register_issue_base(dict(issue_id=issue,base_sha=value['base']['base_sha'],volume=volume,manifest_sha256=value['base']['manifest_sha256']))
        save('r1_base_qualified',preparation={**s['preparation'],'container_id':info['Id'],'proof':proof,'qualified_at':time.time()},
             required_action='install_tests_only_runtime_guard_and_preserved_seed_binding_before_dispatch')
        return s


def tick(b):
    """Observe only preparations already authorized/started by the controller."""
    with b.db() as c:
        execution.initialize(c)
        rows=c.execute('SELECT source_task,state FROM remediation_executions').fetchall()
    for row in rows:
        state=json.loads(row['state'])
        if state['stage'] not in ('r1_seed_provision_pending','r1_base_job_intent','r1_base_job_created','r1_base_job_start_pending','r1_base_job_running'):continue
        try:prepare(b,row['source_task'])
        except (TimeoutError,ConnectionError):
            continue  # transient observation is not a terminal job or permission to recreate
        except Exception as error:
            if type(error).__name__ in ('DockerOperationTimeout','URLError'):
                continue  # uncertain Docker/API observation retains the same handle
            with b.db() as c:
                latest=json.loads(c.execute('SELECT state FROM remediation_executions WHERE source_task=?',(row['source_task'],)).fetchone()[0])
                if latest['stage']=='r1_base_qualified':continue
                latest.update(stage='r1_preparation_blocked',category=type(error).__name__,
                    required_action='CTO inspect exact preserved preparation job; no identical restart')
                c.execute('UPDATE remediation_executions SET state=? WHERE source_task=?',(json.dumps(latest,sort_keys=True),row['source_task']))
