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


def seeded_tool_receipts(notifications, allow_syntax_recovery=False):
    """Measure the actual pinned ACP stream, not the review-only read extractor."""
    starts = {}
    completed = set()
    syntax_rejected = set()
    invalid = False
    for frame in notifications:
        if not isinstance(frame, dict) or frame.get('method') != 'session/update':
            continue
        params = frame.get('params')
        update = params.get('update') if isinstance(params, dict) else None
        if not isinstance(update, dict):
            continue
        identifier = update.get('toolCallId')
        if not isinstance(identifier, str) or not identifier:
            continue
        if update.get('sessionUpdate') == 'tool_call':
            title, kind = update.get('title'), update.get('kind')
            tool = ('patch' if title == 'patch (replace): /workspace/tests/test_new.py' and kind == 'edit'
                    else 'read_file' if title in ('read: /workspace/app.py',
                        'read: /workspace/tests/test_new.py') and kind == 'read' else 'forbidden')
            if identifier in starts:
                invalid = True
            starts[identifier] = tool
        elif update.get('sessionUpdate') == 'tool_call_update' and update.get('status') == 'completed':
            if identifier not in starts or identifier in completed or identifier in syntax_rejected:
                invalid = True
            completed.add(identifier)
        elif update.get('sessionUpdate') == 'tool_call_update' and update.get('status') == 'failed':
            text='\n'.join(c.get('content',{}).get('text','') for c in update.get('content',[])
                if isinstance(c,dict) and c.get('type')=='content' and isinstance(c.get('content'),dict))
            if (not allow_syntax_recovery or starts.get(identifier)!='patch'
                    or identifier in completed or identifier in syntax_rejected
                    or 'fenced Python syntax rejected' not in text or 'No bytes were changed.' not in text):
                invalid=True
            else:syntax_rejected.add(identifier)
    patches = {key for key, tool in starts.items() if tool == 'patch'}
    result=dict(actual_patch_calls=len(patches),
                actual_read_calls=sum(tool == 'read_file' for tool in starts.values()),
                paired_patch_results=len(patches & completed),
                tool_protocol_valid=not invalid and set(starts) == completed | syntax_rejected
                    and all(tool != 'forbidden' for tool in starts.values()))
    if allow_syntax_recovery:
        result['syntax_rejected_patch_calls']=len(syntax_rejected)
        if len(syntax_rejected)>1:result['tool_protocol_valid']=False
    return result


def remote_probe(decomposition=False,unterminated=False,allocation=False,deterministic=False,seeded_patch=False):
    import hashlib
    import json
    import struct
    import threading
    import time
    import uuid
    import broker as b
    from acp_transport import Transport, failure_diagnostics
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
    result = {'schema': 'acp-seeded-patch-probe-v1' if seeded_patch else 'acp-decomposition-probe-v4' if deterministic else 'acp-decomposition-probe-v3' if allocation else 'acp-decomposition-probe-v2' if unterminated else 'acp-decomposition-probe-v1' if decomposition else 'acp-artifact-probe-v1', 'status': 'failed',
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
    if seeded_patch:
        if decomposition:raise ValueError('seeded patch and decomposition are separate probes')
        initial="import unittest\nQUERY = 'calls.length'\nclass Probe(unittest.TestCase):\n    def test_fixture(self): self.assertEqual(QUERY, 'calls.length')\n"
        setup=setup.replace("(p/'tests/test_new.py').touch()","(p/'tests/test_new.py').write_text("+repr(initial)+")")
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
    if seeded_patch:
        expected=initial.replace("QUERY = 'calls.length'","QUERY = 'calls.filter(c => c.url === \"/service-mode\").length'")
        verify=verify.replace('import ast,hashlib,json,os','import ast,hashlib,json,os,base64')
        verify=verify.replace("'uid':os.getuid()","'fixture_base64':base64.b64encode(raw).decode(),'expected_patch_applied':raw=="+repr(expected.encode())+",'uid':os.getuid()")
    if decomposition:
        verify=verify.replace("p=Path('/workspace')", "p=Path('/evidence/candidate')")
    transport = None
    timer = None
    created = False
    private_evidence = {'notifications': []}
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
            response = transport.exchange({'jsonrpc': '2.0', 'id': i, 'method': method, 'params': params},
                on_notification=private_evidence['notifications'].append if seeded_patch else None)
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
        if seeded_patch:
            prompt=('Synthetic seeded-patch transport probe. Read app.py and the entire NEW test. '
                'Use ONE actual patch call to replace exactly QUERY = '+repr('calls.length')+
                ' with QUERY = '+repr('calls.filter(c => c.url === "/service-mode").length')+'. '
                'Preserve every other byte, including all assertions. Do not run commands or tests, '
                'modify baseline files, approve or claim Red. Stop after one verified patch. '
                'This is a disposable fixture, not a product retry.\n'
                'DELIVERY_TEST_ARTIFACT_V1:/workspace/tests/test_new.py\n'
                'DELIVERY_TEST_SOURCE_V1:/workspace/app.py\n'
                'DELIVERY_TEST_REVISION_V1:/workspace/tests/test_new.py\n'
                'DELIVERY_SEEDED_EDIT_REQUIRED_V1:/workspace/tests/test_new.py\n')
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
        if seeded_patch:
            private_evidence['notifications'] = response.get('_broker_notifications', [])
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
            private_evidence['fixture_base64'] = record.pop('fixture_base64', None)
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
            if seeded_patch:
                receipts=seeded_tool_receipts(response.get('_broker_notifications',[]),allow_syntax_recovery=True)
                result.update(synthetic_fixture=True,historical_failure_cause_proven=False,
                    **receipts,red_verified=False)
                if (record.get('expected_patch_applied') is not True
                        or receipts['actual_patch_calls']!=1+receipts['syntax_rejected_patch_calls']
                        or receipts['paired_patch_results']!=1 or receipts['actual_read_calls']<2
                        or not receipts['tool_protocol_valid']):
                    result['status']='failed'
    except Exception as error:
        result['failure_category'] = type(error).__name__  # never raw model/transport data
        if seeded_patch:
            result.update(seeded_tool_receipts(private_evidence['notifications']))
            if transport:
                result['transport_diagnostics'] = failure_diagnostics(transport.stderr_tail)
                private_evidence['stderr_base64'] = __import__('base64').b64encode(transport.stderr_tail).decode()
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
            if seeded_patch:
                from pathlib import Path
                frozen=b.STATE/'synthetic-probe-evidence';frozen.mkdir(mode=0o700,exist_ok=True)
                if frozen.is_symlink():raise ValueError('unsafe probe evidence directory')
                stopped=b.docker('GET','/containers/'+container['Id']+'/json')
                if stopped['State']['Running'] or stopped['Id']!=container['Id']:
                    raise ValueError('exact stopped owned fixture required')
                log=b.docker_stdout(container['Id'],limit=16384)
                archive=frozen/(identifier+'.json')
                with archive.open('x') as stream:
                    json.dump(dict(result=result,container_id=container['Id'],
                        container_log=log,private_evidence=private_evidence,
                        source_fixture_only=True),stream,sort_keys=True)
                archive.chmod(0o600)
            b.docker('DELETE', '/containers/' + name + '?force=false')
            result['fixture_removed'] = True
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--decomposition',action='store_true')
    parser.add_argument('--unterminated',action='store_true');parser.add_argument('--allocation',action='store_true')
    parser.add_argument('--deterministic',action='store_true')
    parser.add_argument('--seeded-patch',action='store_true');args=parser.parse_args()
    if args.seeded_patch and args.decomposition:raise ValueError('separate fixture modes required')
    if args.unterminated and not args.decomposition:raise ValueError('EOF fixture requires decomposition mode')
    if args.allocation and not (args.decomposition and args.unterminated):raise ValueError('allocation requires immutable EOF fixture')
    if args.deterministic and not args.allocation:raise ValueError('deterministic reads require allocation fixture')
    if PROJECT != 'delivery-kit-port2' or read_model_budget()['remaining'] < 4:
        raise ValueError('isolated ACP probe reserve required')
    budget_before=read_model_budget()['calls'] if args.deterministic else None
    source = 'import json\n' + inspect.getsource(valid_artifact) + '\n' + inspect.getsource(seeded_tool_receipts) + '\n' + inspect.getsource(remote_probe)
    source += '\nprint(json.dumps(remote_probe(decomposition='+str(args.decomposition)+',unterminated='+str(args.unterminated)+',allocation='+str(args.allocation)+',deterministic='+str(args.deterministic)+',seeded_patch='+str(args.seeded_patch)+')))\n'
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
    save_receipt(PRIVATE / ('acp-seeded-patch-probe.json' if args.seeded_patch else 'acp-decomposition-probe.json' if args.decomposition else 'acp-artifact-probe.json'), result)
    print(json.dumps(result))
    return 0 if result['status']=='passed' else 1


if __name__ == '__main__':
    raise SystemExit(main())
