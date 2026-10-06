"""One changed-evidence CTO diagnosis; no product retry or forged decision."""
import hashlib,json,sqlite3,time
import broker as b
import handoffs,handoff_runtime,native,source_harness_completion as gate

ROOT='01a0fef6-392c-745d-a751-4b1edae92727'
ISSUE='01a107c0-5936-79be-bf32-6f59017be3eb'
SOURCE='01a107cf-4fdf-74e9-9974-a2623c3eed0d'
with b.LOCK,b.db() as con:
    assert not con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()
    row=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(SOURCE,)).fetchone()
    data=json.loads(row['data'])
    route=json.loads(con.execute('SELECT config FROM delivery_routes WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    assert route['enabled'] is False
    trial=json.loads(con.execute('SELECT config FROM test_revision_trials WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    red=json.loads(con.execute('SELECT receipt FROM test_first_red WHERE issue_id=?',(ISSUE,)).fetchone()[0])
    proof=json.loads(con.execute('SELECT receipt FROM source_harness_checks WHERE issue_id=? AND manifest_sha256=?',
        (ISSUE,red['red']['manifest_sha256'])).fetchone()[0])
    try: gate.qualify(proof,trial,red)
    except gate.IncompleteHarness: pass
    else: raise ValueError('blocked admission required')
    snapshot=con.execute("SELECT volume FROM snapshots WHERE task_id=? AND status='complete'",(SOURCE,)).fetchone()[0]

# Fixed offline inspection of the actual artifact the CTO will read.
name=b.PREFIX+'-admission-inspection-'+SOURCE
labels={'delivery-kit.owner':b.OWNER,'com.docker.compose.project':b.PREFIX,
    'com.docker.compose.service':'admission-inspection'}
probe='''import hashlib,json
from pathlib import Path
r=Path('/delivery');m=json.loads((r/'manifest.json').read_bytes())['files']
for p,item in m.items():
 f=r/p
 assert not f.is_symlink() and f.is_file()
 assert hashlib.sha256(f.read_bytes()).hexdigest()==item['sha256']
paths=['tests/test_incremental_u3.py','app/static/app.js','app/static/index.html']
print(json.dumps({p:hashlib.sha256((r/p).read_bytes()).hexdigest() for p in paths}))
'''
assert not b.docker('GET','/containers/'+name+'/json')
try:
    b.docker('POST','/containers/create?name='+name,dict(Image=b.OFFLINE_IMAGE,User='10000:10000',
        Entrypoint=['python3'],Cmd=['-c',probe],NetworkDisabled=True,Labels=labels,
        HostConfig=dict(ReadonlyRootfs=True,NetworkMode='none',CapDrop=['ALL'],SecurityOpt=['no-new-privileges'],
            Memory=268435456,PidsLimit=64,Mounts=[dict(Type='volume',Source=snapshot,Target='/delivery',ReadOnly=True)])))
    b.docker('POST','/containers/'+name+'/start');deadline=time.time()+30
    while time.time()<deadline:
        info=b.docker('GET','/containers/'+name+'/json')
        if info and not info['State']['Running']:
            assert info['State']['ExitCode']==0
            hashes=json.loads(b.docker_stdout(name,limit=4096));break
        time.sleep(.2)
    else:raise ValueError('inspection deadline')
finally:
    info=b.docker('GET','/containers/'+name+'/json')
    if info and all(info['Config']['Labels'].get(k)==v for k,v in labels.items()):
        b.docker('DELETE','/containers/'+name+'?force=true')
assert hashes['tests/test_incremental_u3.py']==proof['candidate_test_sha256']
with b.LOCK,b.db() as con:
    current=con.execute('SELECT * FROM delivery_handoffs WHERE source_task=?',(SOURCE,)).fetchone()
    assert current['data']==row['data']
    if not data.get('source_harness_admission'):
        backup=b.STATE/'u3-before-admission-escalation-20261004.sqlite'
        assert not backup.exists()
        with sqlite3.connect(backup) as target:
            con.backup(target);assert target.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        con.execute('CREATE TABLE IF NOT EXISTS admission_escalation_history(source_task TEXT PRIMARY KEY,receipt TEXT)')
        con.execute('INSERT INTO admission_escalation_history VALUES(?,?)',(SOURCE,json.dumps(dict(row),sort_keys=True)))
        for field in ('recipient_task','wakeup_id','dispatch_marker','dispatch_stage','dispatched_at','target','instruction','decision'):
            data.pop(field,None)
        sha=gate.proof_digest(proof)
        data.update(artifact_diagnosis=True,source_harness_admission=dict(proof=proof,trial=trial,red=red,
                candidate_volume=snapshot,source_task=SOURCE),
            validation_failure=dict(category='source_harness_admission_failure',source_task=SOURCE,volume=snapshot,
                output_sha256=sha,diagnostic_read_files=['app/static/app.js','app/static/index.html']),
            harness_diagnosis=dict(approval=False,source_task=SOURCE,output_sha256=sha,file_sha256=hashes,
                findings=['The candidate changes the preamble but DRIVER_BODY is byte-identical to the rejected predecessor.',
                    'No added negative-control test methods exist. The independent approval is preserved but cannot override admission.',
                    'The inverted beta/gamma chronology and current-first FIFO driver remain. A product retry cannot repair these contradictions.']),
            diagnostic_revision=sha+':source-admission-v1',trigger_task=SOURCE)
        handoffs.harness_diagnosis_instruction(data,route)
        handoffs.save(con,SOURCE,ISSUE,'diagnose_cto',route['cto'],data,time.time())
    settings=json.loads((b.STATE/'native.json').read_text())
    # Dispatch diagnosis only. The durable route remains disabled for product execution.
    stage=handoffs.reconcile(con,{**route,'enabled':True},native.issue_task_runs(settings,ISSUE),
        handoff_runtime.Effects(b.handoff_context(),settings))
    result=json.loads(con.execute('SELECT data FROM delivery_handoffs WHERE source_task=?',(SOURCE,)).fetchone()[0])
print(json.dumps(dict(stage=stage,wakeup_id=result.get('wakeup_id'),approval=False,product_route_enabled=False)))
