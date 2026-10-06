"""Actual ACP fixture, never a product retry or delivery approval.

Only one pre-created disposable test is writable. The real transport and
installed worker/proxy are used; no credentials or Docker socket enter it.
"""
import inspect
import json
import subprocess
import argparse

from evalctl import PRIVATE, PROJECT
from release_eval import save_receipt
from start_eval import read_model_budget


def valid_artifact(record):
    return (record.get('baseline_unchanged') is True
            and record.get('credentials_absent') is True
            and record.get('bytes', 0) > 0
            and record.get('test_methods', 0) > 0
            and record.get('syntax_valid') is True)


def remote_probe(decomposition=False,unterminated=False,allocation=False,deterministic=False):
    import hashlib
    import json
    import struct
    import threading
    import time
    import uuid
    import broker as b
    from acp_transport import Transport
    from model_policy import MODEL
    from artifact_read_evidence import observations
    from read_stream_receipts import extract
    from test_decomposition import parse_proposal,validate_result

    if b.PREFIX != 'delivery-kit-port2' or b.MODEL_NETWORK != 'delivery-kit-port2_model':
        raise ValueError('isolated probe namespace required')
    with b.db() as con:
        if con.execute("SELECT 1 FROM leases WHERE status IN ('creating','starting','running') LIMIT 1").fetchone():
            raise ValueError('probe requires idle workers')
    identifier = str(uuid.uuid4())
    name = b.PREFIX + '-acp-artifact-job-' + identifier
    owner = b.PREFIX + '-acp-artifact-probe-v1'
    result = {'schema': 'acp-decomposition-probe-v4' if deterministic else 'acp-decomposition-probe-v3' if allocation else 'acp-decomposition-probe-v2' if unterminated else 'acp-decomposition-probe-v1' if decomposition else 'acp-artifact-probe-v1', 'status': 'failed',
              'execution_id': identifier, 'worker_image': b.IMAGE, 'model': MODEL,
              'delivery_approval': False, 'product_retry': False}
    setup = """from pathlib import Path
import time
p=Path('/workspace'); (p/'tests').mkdir()
(p/'app.py').write_text('VALUE = 0\\n')
(p/'tests/test_old.py').write_text('import unittest\\nfrom app import VALUE\\nclass Old(unittest.TestCase):\\n    def test_baseline(self): self.assertEqual(VALUE, 0)\\n')
(p/'tests/test_new.py').touch()
for f in (p/'app.py',p/'tests/test_old.py'): f.chmod(0o444)
(p/'tests/test_new.py').chmod(0o666)
(p/'tests').chmod(0o555); p.chmod(0o555)
print('fixture-ready',flush=True)
time.sleep(180)
"""
    if decomposition:
        setup=setup.replace("p=Path('/workspace')", "p=Path('/evidence/candidate')")
        setup=setup.replace("(p/'tests/test_new.py').touch()", "(p/'tests/test_new.py').write_text('def helper(): return 0\\n')")
        setup=setup.replace("chmod(0o666)","chmod(0o444)")
        if unterminated:setup=setup.replace("return 0\\n')","return 0')")
    verify = """import ast,hashlib,json,os
from pathlib import Path
p=Path('/workspace'); raw=(p/'tests/test_new.py').read_bytes()
try:
 t=ast.parse(raw); methods=sum(isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)) and n.name.startswith('test_') for n in ast.walk(t)); syntax=True
except SyntaxError: methods=0;syntax=False
old='import unittest\\nfrom app import VALUE\\nclass Old(unittest.TestCase):\\n    def test_baseline(self): self.assertEqual(VALUE, 0)\\n'
print(json.dumps({'uid':os.getuid(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'test_methods':methods,'syntax_valid':syntax,
 'baseline_unchanged':(p/'app.py').read_text()=='VALUE = 0\\n' and (p/'tests/test_old.py').read_text()==old,
 'credentials_absent':not any(Path(x).exists() for x in ['/var/run/docker.sock','/broker-state/token','/eval-state/.multica/config.json','/secret/openrouter.key','/run/secrets/openrouter_api_key'])}))
"""
    if decomposition:
        verify=verify.replace("p=Path('/workspace')", "p=Path('/evidence/candidate')")
    transport = None
    timer = None
    created = False
    def stop():
        b.docker('POST', '/containers/' + name + '/stop?t=1')
    try:
        b.docker('POST', '/containers/create?name=' + name, {
            'Image': b.IMAGE, 'User': '0:0', 'Entrypoint': ['python'], 'Cmd': ['-c', setup],
            'WorkingDir': '/tmp', 'Env': ['HOME=/tmp', 'HERMES_CONTROLLER_DENIAL_MESSAGES=1'],
            'Labels': {'delivery-kit.owner': owner, 'delivery-kit.request': identifier},
            'HostConfig': {'ReadonlyRootfs': True, 'NetworkMode': b.MODEL_NETWORK,
                'CapDrop': ['ALL'], 'SecurityOpt': ['no-new-privileges'],
                'Memory': 536870912, 'NanoCpus': 1000000000, 'PidsLimit': 64,
                'Tmpfs': {'/tmp': 'rw,nosuid,nodev,size=64m,mode=1777',
                          ('/evidence/candidate' if decomposition else '/workspace'): 'rw,nosuid,nodev,size=1m,mode=0777'}}})
        created = True
        b.docker('POST', '/containers/' + name + '/start')
        for _ in range(30):
            if b.docker_stdout(name).strip() == 'fixture-ready':
                break
            time.sleep(.2)
        else:
            raise RuntimeError('fixture not ready')
        timer = threading.Timer(120, stop); timer.daemon = True; timer.start()
        transport = Transport(b.docker, name, mode='planning' if decomposition else 'implementation',
                              editable_paths=[] if decomposition else ['/workspace/tests/test_new.py'])
        def exchange(i, method, params):
            response = transport.exchange({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params})
            if response.get('error'):
                raise RuntimeError('ACP protocol error')
            return response
        exchange(1, 'initialize', {})
        session = exchange(2, 'session/new', {'model': MODEL})['result']['sessionId']
        prompt = ('Write ONLY /workspace/tests/test_new.py. Read app.py first, then use write_file '
                  'to create a Python unittest.TestCase containing test_value_next that imports VALUE '
                  'from app and asserts VALUE equals 1. This is tests-only: do not implement, run '
                  'commands, modify old tests, or claim Red. Stop after writing.\n'
                  'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
                  'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\n')
        if decomposition:
            prompt=('Read all three immutable files below, then propose two sequential test units '
                'U1 and U2 covering C01 and C02 exactly once. C01: test VALUE equals1; '
                'C02: retain the existing baseline test. This is a synthetic transport probe, '
                'not permission to write, execute, approve or deliver. Return ONLY JSON '
                'action=propose_test_decomposition,reason,optional_files=[],units containing '
                'id,depends_on,criteria,objective. U1 depends_on=[], U2 depends_on=["U1"].\n'
                'DELIVERY_STRUCTURED_DECISION_V1:technical\nDELIVERY_TEST_DECOMPOSITION_V1\n'
                'DELIVERY_DECOMPOSITION_CRITERION:C01\nDELIVERY_DECOMPOSITION_CRITERION:C02\n'
                'DELIVERY_REVIEW_READ_PATH:/evidence/candidate/app.py\n'
                'DELIVERY_REVIEW_READ_PATH:/evidence/candidate/tests/test_old.py\n'
                'DELIVERY_REVIEW_READ_PATH:/evidence/candidate/tests/test_new.py\n')
            if allocation:
                prompt=prompt.replace('DELIVERY_TEST_DECOMPOSITION_V1','DELIVERY_TEST_DECOMPOSITION_V2')
                prompt=prompt.replace('id,depends_on,criteria,objective.','id,depends_on,objective and assignments with ALL C01..C22 mapped to unit IDs.')
                prompt+='\nSynthetic C03..C22: preserve baseline, immutable reads and isolation for each criterion. '
                prompt+='Assign C01..C11 to U1 and C12..C22 to U2.\n'
                prompt+=''.join('DELIVERY_DECOMPOSITION_CRITERION:C'+str(i).zfill(2)+'\n' for i in range(3,23))
            if deterministic:prompt+='DELIVERY_DETERMINISTIC_READ_V1\n'
        response = exchange(3, 'session/prompt', {'sessionId': session,
                            'prompt': [{'type': 'text', 'text': prompt}]})
        result['prompt_completed'] = True
        result['notification_count'] = len(response.get('_broker_notifications', []))
        # Fixed controller inspection, not an agent-supplied shell or command.
        execution = b.docker('POST', '/containers/' + name + '/exec', {
            'AttachStdout': True, 'AttachStderr': False, 'User': '10000:10000',
            'Cmd': ['python', '-c', verify]})['Id']
        conn = b.DockerConnection('localhost', timeout=10)
        try:
            conn.request('POST', '/v1.45/exec/' + execution + '/start',
                         json.dumps({'Detach': False, 'Tty': False}), {'Content-Type': 'application/json'})
            reply = conn.getresponse(); data = reply.read(8193)
            if reply.status != 200 or len(data) > 8192:
                raise RuntimeError('inspection unavailable')
            output = b''; offset = 0
            while offset < len(data):
                size = struct.unpack('>I', data[offset+4:offset+8])[0]
                if data[offset] != 1 or offset + 8 + size > len(data):
                    raise RuntimeError('invalid inspection frame')
                output += data[offset+8:offset+8+size]; offset += 8+size
            record = json.loads(output)
        finally:
            conn.close()
        result['inspection'] = record
        if decomposition:
            notifications=response.get('_broker_notifications',[])
            text=''.join((f.get('params',{}).get('update',{}).get('content') or {}).get('text','')
                for f in notifications if f.get('params',{}).get('update',{}).get('sessionUpdate')=='agent_message_chunk')
            messages=[m for pair in extract(notifications) for m in pair]
            reads=observations(messages)
            task={'id':identifier,'agent_id':'fixture-cto','status':'completed','result':{'output':text}}
            config={'source_task':'fixture','cto':'fixture-cto','diagnostic_sha256':'a'*64,
                'required_files':['app.py','tests/test_old.py','tests/test_new.py'],
                'criteria':{'C01':'Test VALUE equals1','C02':'Preserve existing baseline'}}
            if allocation:
                config['proposal_contract']='criterion-allocation-v2'
                config['criteria'].update({'C'+str(i).zfill(2):'Preserve fixture invariants' for i in range(3,23)})
            decision=parse_proposal(task,[])
            certificate=validate_result(config,task,decision,reads)
            expected=b'def helper(): return 0'+(b'' if unterminated else b'\n')
            unchanged=record['sha256']==hashlib.sha256(expected).hexdigest()
            result.update(full_reads_verified=True,proposal_valid=True,unit_count=len(decision['units']),
                proposal_sha256=certificate['proposal_sha256'],fixture_unchanged=unchanged)
            if unterminated:
                result.update(schema='acp-decomposition-probe-v2',unterminated_fixture=True,
                              read_contract='logical-lines-eof-v1')
            if allocation:
                result.update(schema='acp-decomposition-probe-v3',proposal_contract='criterion-allocation-v2',
                              criteria_count=22,allocated_criteria_count=certificate['allocated_criteria_count'])
            if deterministic:result.update(schema='acp-decomposition-probe-v4',deterministic_reads=True)
            result['status']='passed' if (record['uid']==10000 and record['baseline_unchanged']
                and record['credentials_absent'] and unchanged) else 'failed'
        else:
            result['status'] = 'passed' if valid_artifact(record) and record['uid'] == 10000 else 'failed'
    except Exception as error:
        result['failure_category'] = type(error).__name__  # never raw model/transport data
    finally:
        if timer:
            timer.cancel()
        if transport:
            transport.close()
        if created:
            container = b.docker('GET', '/containers/' + name + '/json')
            labels = (container or {}).get('Config', {}).get('Labels', {})
            if labels.get('delivery-kit.owner') != owner or labels.get('delivery-kit.request') != identifier:
                raise RuntimeError('cleanup identity mismatch')
            stop()
            b.docker('DELETE', '/containers/' + name + '?force=false')
            result['fixture_removed'] = True
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--decomposition',action='store_true')
    parser.add_argument('--unterminated',action='store_true');parser.add_argument('--allocation',action='store_true')
    parser.add_argument('--deterministic',action='store_true');args=parser.parse_args()
    if args.unterminated and not args.decomposition:raise ValueError('EOF fixture requires decomposition mode')
    if args.allocation and not (args.decomposition and args.unterminated):raise ValueError('allocation requires immutable EOF fixture')
    if args.deterministic and not args.allocation:raise ValueError('deterministic reads require allocation fixture')
    if PROJECT != 'delivery-kit-port2' or read_model_budget()['remaining'] < 4:
        raise ValueError('isolated ACP probe reserve required')
    budget_before=read_model_budget()['calls'] if args.deterministic else None
    source = 'import json\n' + inspect.getsource(valid_artifact) + '\n' + inspect.getsource(remote_probe)
    source += '\nprint(json.dumps(remote_probe(decomposition='+str(args.decomposition)+',unterminated='+str(args.unterminated)+',allocation='+str(args.allocation)+',deterministic='+str(args.deterministic)+')))\n'
    proxy_image = subprocess.check_output(['docker', 'inspect', PROJECT + '-model-proxy-1',
                                          '--format', '{{.Image}}'], text=True).strip()
    process = subprocess.run(['docker', 'exec', '-i', '-e', 'PYTHONPATH=/',
                        PROJECT + '-execution-broker-1', 'python', '-c', source],
                        text=True, capture_output=True)
    if process.returncode:
        raise RuntimeError('fixed ACP probe infrastructure failed; no raw output forwarded')
    result = json.loads(process.stdout)
    result['proxy_image'] = proxy_image
    result['budget_after'] = read_model_budget()
    if args.deterministic:
        code='import json,deterministic_read_dispatch as d,model_proxy as m; print(json.dumps(d.status(m.COUNTER_PATH,'+repr(result['execution_id'])+')))'
        p=subprocess.run(['docker','exec','-e','PYTHONPATH=/',PROJECT+'-model-proxy-1','python','-c',code],capture_output=True,text=True)
        result['decision_model_calls']=result['budget_after']['calls']-budget_before
        if p.returncode:
            result.update(status='failed',failure_category='DeterministicDispatchInspectionUnavailable')
        else:
            evidence=json.loads(p.stdout)
            result.update(controller_read_requests=evidence['controller_read_requests'],dispatch_provenance=evidence['provenance'])
            if result['controller_read_requests']!=3 or result['decision_model_calls']!=1:result['status']='failed'
    save_receipt(PRIVATE / 'provider-probes' / ('acp-' + result['execution_id'] + '.json'), result)
    save_receipt(PRIVATE / ('acp-decomposition-probe.json' if args.decomposition else 'acp-artifact-probe.json'), result)
    print(json.dumps(result))
    return 0 if result['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
