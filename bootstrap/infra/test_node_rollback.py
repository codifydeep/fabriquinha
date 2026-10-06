"""Authorized failed-candidate deployment drill; always restore known-good service.

Fault is invalid runtime configuration, not a fictitious new Git version.
Only the two fixed rehearsal container names may be stopped/started.
"""
import json,sqlite3,subprocess,time,urllib.request
from pathlib import Path
from product_qa_probe import probe

ROOT=Path('/private/tmp/hermes-product-agent-trial-01')
BASELINE='truco-online-adapter-homologation'
CANDIDATE='truco-online-adapter-failed-candidate-01'
URL='http://127.0.0.1:18876'

def docker(*args):
    return subprocess.run(['docker',*args],check=True,capture_output=True,text=True,timeout=30).stdout.strip()

def main():
    journal=sqlite3.connect(ROOT/'node-publication.db')
    journal.execute('CREATE TABLE IF NOT EXISTS rollback_events(seq INTEGER PRIMARY KEY,event TEXT,payload TEXT,at REAL)');journal.commit()
    old=journal.execute("SELECT value FROM receipts WHERE key='failed-candidate-rollback'").fetchone()
    if old:print(old[0]);return
    if journal.execute('SELECT 1 FROM rollback_events').fetchone():raise RuntimeError('Existing incomplete drill: diagnose, do not repeat blindly')
    commit=json.loads(journal.execute("SELECT value FROM receipts WHERE key='merge'").fetchone()[0])['merge']
    with sqlite3.connect('file:/private/tmp/hermes-node-qa-review/verdict.db?mode=ro',uri=True) as qa:
        verdict=json.loads(qa.execute('SELECT verdict FROM verdicts ORDER BY run DESC LIMIT 1').fetchone()[0])
        checks=json.loads(qa.execute('SELECT receipt FROM qa_checks WHERE run=?',(verdict['run'],)).fetchone()[0])
    with sqlite3.connect('file:/private/tmp/hermes-node-qa-review/board/kanban.db?mode=ro',uri=True) as board:
        assert board.execute("SELECT status FROM tasks WHERE id='t_89c9edd7'").fetchone()==('done',)
    assert verdict['decision']=='approve' and verdict['reviewer']=='quality_security' and verdict['head']==commit
    assert checks['passed'] and checks['commit']==commit and len(checks['cases'])==12
    before=probe(URL,commit);assert before['passed']
    baseline=json.loads(docker('inspect',BASELINE))[0]
    assert baseline['State']['Running'] and 'APP_COMMIT='+commit in baseline['Config']['Env']
    assert baseline['Config']['Labels']['com.docker.compose.service']=='adapter-homologation'
    assert baseline['HostConfig']['PortBindings']=={'8080/tcp':[{'HostIp':'127.0.0.1','HostPort':'18876'}]}
    source=ROOT/('deploy-'+commit)
    assert any(m['Source']==str(source) and m['Destination']=='/app' and not m['RW'] for m in baseline['Mounts'])
    assert not docker('ps','-aq','--filter','name=^/'+CANDIDATE+'$'),'candidate already exists'
    def record(event,**payload):
        with journal:journal.execute('INSERT INTO rollback_events(event,payload,at) VALUES(?,?,?)',(event,json.dumps(payload),time.time()))
    record('preflight_passed',commit=commit,qa_run=verdict['run'])
    docker('create','--name',CANDIDATE,'--pull=never','--network=bridge','--read-only','--cap-drop=ALL',
           '--security-opt=no-new-privileges','--pids-limit=64','--memory=128m','--cpus=0.5','--user=10000:10000',
           '--label','com.docker.compose.project=truco-online','--label','com.docker.compose.service=rollback-fault-candidate',
           '--mount',f'type=bind,src={source},dst=/app,readonly','--workdir=/app','-e','APP_COMMIT=FAULT_INJECTION_INVALID_COMMIT',
           '-p','127.0.0.1:18876:8080','--entrypoint=node',baseline['Image'],'service.mjs')
    failure=None;started=time.monotonic()
    try:
        record('switch_intent',candidate=CANDIDATE,baseline=BASELINE)
        docker('stop','--timeout','5',BASELINE)
        docker('start',CANDIDATE)
        for _ in range(20):
            state=json.loads(docker('inspect',CANDIDATE))[0]['State']
            if not state['Running']:break
            time.sleep(0.25)
        assert not state['Running'] and state['ExitCode']!=0,'fault did not trigger'
        logs=docker('logs',CANDIDATE)
        # docker logs writes stderr separately; process exit plus health failure
        # is the evidence, not the presence of a particular log string.
        try:urllib.request.urlopen(URL+'/health',timeout=2)
        except OSError:pass
        else:raise AssertionError('failed candidate unexpectedly healthy')
        failure=dict(exit_code=state['ExitCode'],kind='invalid_runtime_commit_configuration')
        record('candidate_failed',**failure)
    finally:
        record('rollback_intent',baseline=BASELINE)
        state=json.loads(docker('inspect',CANDIDATE))[0]['State']
        if state['Running']:docker('stop','--timeout','5',CANDIDATE)
        docker('start',BASELINE)
        restored=None
        for _ in range(20):
            try:
                restored=probe(URL,commit)
                if restored['passed']:break
            except OSError:pass
            time.sleep(0.5)
        assert restored and restored['passed'],'rollback failed: operator intervention required'
        record('baseline_restored',commit=commit,cases=len(restored['cases']))
    assert failure
    result=dict(commit=commit,url=URL,failed_candidate=CANDIDATE,failure=failure,
                known_good_qa_run=verdict['run'],restored_cases=restored['cases'],passed=True,
                recovery_seconds=round(time.monotonic()-started,2),
                scope='failed deployment configuration rollback to QA-approved baseline',
                rollback_between_distinct_git_versions=False,release_homologated=False)
    with journal:journal.execute('INSERT INTO receipts VALUES(?,?)',('failed-candidate-rollback',json.dumps(result)))
    print(json.dumps({k:v for k,v in result.items() if k!='restored_cases'}));journal.close()

if __name__=='__main__':main()
