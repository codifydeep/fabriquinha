"""Nonapproving structural admission for source-diagnosed NEW harness repairs."""
import inspect
import json
import time
import hashlib


def proof_digest(proof):
    return hashlib.sha256(json.dumps(proof,sort_keys=True).encode()).hexdigest()


def validate_diagnosis(data,route):
    """An admission rejection is not an executed Green failure or a verdict."""
    failure=data['validation_failure'];diagnosis=data['harness_diagnosis']
    binding=data.get('source_harness_admission') or {}
    if set(binding)!={'proof','trial','red','candidate_volume','source_task'}:
        raise ValueError('exact frozen admission rejection required')
    names=binding['red'].get('red',{}).get('test_sha256',{})
    if (len(names)!=1 or set(names)!=set(route['test_first_files'])
            or binding['trial'].get('issue_id')!=route['issue_id']
            or binding['red'].get('issue_id')!=route['issue_id']
            or failure.get('output_sha256')!=proof_digest(binding['proof'])
            or failure.get('volume')!=binding['candidate_volume']
            or failure.get('source_task')!=binding['source_task']
            or diagnosis.get('file_sha256',{}).get(next(iter(names),' '))
                !=binding['proof'].get('candidate_test_sha256')):
        raise ValueError('exact frozen admission rejection required')
    try: qualify(binding['proof'],binding['trial'],binding['red'])
    except IncompleteHarness: return
    raise ValueError('passing structure cannot authorize admission recovery')


def analyze(previous, candidate):
    import ast
    import hashlib
    from pathlib import Path
    records=[]
    for path in (previous,candidate):
        raw=Path(path).read_bytes();tree=ast.parse(raw)
        constants={n.targets[0].id:n.value.value for n in tree.body
            if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name)
            and isinstance(n.value,ast.Constant) and isinstance(n.value.value,str)}
        driver=constants.get('DRIVER_BODY')
        methods={n.name for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name.startswith('test_')}
        records.append(dict(test_sha256=hashlib.sha256(raw).hexdigest(),methods=methods,
            driver_sha256=hashlib.sha256(driver.encode()).hexdigest() if driver else None,
            inverted_chronology=bool(driver and 'out.genA_newer = genAIdx > genBIdx;' in driver),
            current_first_fifo=bool(driver and 'resolveOldest([{ id: 3' in driver)))
    old,new=records
    return dict(operation='source_harness_structure_v1',approval=False,
        previous_test_sha256=old['test_sha256'],candidate_test_sha256=new['test_sha256'],
        previous_driver_sha256=old['driver_sha256'],candidate_driver_sha256=new['driver_sha256'],
        driver_changed=bool(new['driver_sha256'] and new['driver_sha256']!=old['driver_sha256']),
        added_methods=sorted(new['methods']-old['methods']),removed_methods=sorted(old['methods']-new['methods']),
        inverted_chronology=new['inverted_chronology'],current_first_fifo=new['current_first_fifo'],
        limitation='Structural checks do not prove negative-control semantics or Green.')


class IncompleteHarness(ValueError):
    def __init__(self,proof,issue):
        super().__init__('source-diagnosed harness repair incomplete')
        self.incident=dict(category='incomplete_source_harness_repair',owner='cto',issue_id=issue,
            required_action='complete_new_test_harness_before_product_handoff',approval=False,proof=proof)


def qualify(proof,trial,red):
    hashes=red['red']['test_sha256'];old=trial['old_red']['red']['test_sha256']
    if (len(hashes)!=1 or set(hashes)!=set(old) or proof.get('approval') is not False
            or proof.get('operation')!='source_harness_structure_v1'
            or proof.get('candidate_test_sha256')!=next(iter(hashes.values()))
            or proof.get('previous_test_sha256')!=next(iter(old.values()))):
        raise ValueError('exact nonapproving frozen harness comparison required')
    driver_ok=bool(proof.get('driver_changed'))
    if trial.get('controls_completion_only'):
        expected=trial.get('qualified_driver_sha256')
        driver_ok=bool(expected and proof.get('previous_driver_sha256')==expected
            and proof.get('candidate_driver_sha256')==expected and not proof.get('driver_changed'))
    if (not driver_ok or proof.get('removed_methods')
            or len(proof.get('added_methods',[]))<2 or proof.get('inverted_chronology')
            or proof.get('current_first_fifo')):
        raise IncompleteHarness(proof,trial['issue_id'])


def enforce(b,trial,red):
    if not trial.get('source_harness_diagnosis'): return
    names=red['red']['test_sha256']
    if len(names)!=1: raise ValueError('single source-diagnosed NEW harness required')
    path=next(iter(names))
    with b.db() as con:
        con.execute('CREATE TABLE IF NOT EXISTS source_harness_checks(issue_id TEXT,manifest_sha256 TEXT,receipt TEXT,PRIMARY KEY(issue_id,manifest_sha256))')
        key=(trial['issue_id'],red['red']['manifest_sha256'])
        saved=con.execute('SELECT receipt FROM source_harness_checks WHERE issue_id=? AND manifest_sha256=?',key).fetchone()
    if saved:
        qualify(json.loads(saved[0]),trial,red);return
    name=b.PREFIX+'-source-harness-check-'+red['task_id']
    labels={'delivery-kit.owner':b.OWNER,'delivery-kit.issue-id':trial['issue_id'],
        'com.docker.compose.project':b.PREFIX,'com.docker.compose.service':'source-harness-check'}
    for volume in (red['volume'],trial['old_red']['volume']):
        info=b.docker('GET','/volumes/'+volume)
        if not info or info.get('Labels',{}).get('delivery-kit.owner')!=b.OWNER:
            raise ValueError('owned readonly harness snapshots required')
    if b.docker('GET','/containers/'+name+'/json'): raise ValueError('interrupted source harness check')
    runner=inspect.getsource(analyze)+'\nimport json,os;print(json.dumps(analyze("/previous/"+os.environ["TEST"],"/candidate/"+os.environ["TEST"])))'
    try:
        b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='10000:10000',
            Entrypoint=['python3'],Cmd=['-c',runner],Env=['TEST='+path],NetworkDisabled=True,Labels=labels,
            HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
                Memory=268435456,PidsLimit=64,Mounts=[dict(Type='volume',Source=red['volume'],Target='/candidate',ReadOnly=True),
                dict(Type='volume',Source=trial['old_red']['volume'],Target='/previous',ReadOnly=True)])))
        b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
        while time.time()<deadline:
            info=b.docker('GET','/containers/'+name+'/json')
            if info and not info['State']['Running']:
                if info['State']['ExitCode']: raise ValueError('fixed source harness check failed')
                proof=json.loads(b.docker_stdout(name,limit=8192));break
            time.sleep(.2)
        else: raise ValueError('source harness check deadline')
    finally:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items()):
            b.docker('DELETE','/containers/'+name+'?force=true')
    with b.db() as con:
        con.execute('INSERT INTO source_harness_checks VALUES(?,?,?)',(*key,json.dumps(proof,sort_keys=True)))
    qualify(proof,trial,red)
