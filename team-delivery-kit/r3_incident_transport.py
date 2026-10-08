"""Changed-input diagnosis after a proven local native-envelope rejection.

Never resets a failed task or authorizes publication. One new evidence identity
still requires normal diagnosis, independent review and fixed experiments.
"""
import hashlib
import json
from pathlib import Path
from portable_remediation_intake import digest, read
from release_eval import command, save_receipt

ERROR_SHA = '600a782478224712683956e0c31360e0e2f297791e1747f2cc64b041b47ba00c'

REPORT = '''import broker as b,json,sys
tasks=json.loads(sys.argv[1]);result=[]
with b.db() as con:
 active=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]
 for task in tasks:
  rows=con.execute("SELECT request_id FROM native_bindings WHERE task_id=?",(task,)).fetchall()
  if len(rows)!=1:raise ValueError('one failed binding required')
  execution=rows[0][0]
  lease=con.execute("SELECT status FROM leases WHERE request_id=?",(execution,)).fetchone()
  receipt=con.execute("SELECT receipt FROM acp_failure_receipts WHERE request_id=? AND method='session/prompt'",(execution,)).fetchone()
  if not lease or lease[0]!='closed' or not receipt:raise ValueError('closed failed transport required')
  result.append(dict(task=task,execution=execution,receipt=json.loads(receipt[0])))
print(json.dumps(dict(active=active,failures=result)))
'''

CANARY = '''import json,sys,hashlib;from pathlib import Path
from r3_incident_contract import request_contract
notes=json.loads(sys.argv[1]);schemas=[request_contract(dict(messages=[dict(role='user',content=n)])) for n in notes]
assert all(s and s['properties']['execution_authorized']['enum']==[False] for s in schemas)
print(json.dumps(dict(contract_sha256=hashlib.sha256(Path('/r3_incident_contract.py').read_bytes()).hexdigest(),qualified=len(schemas),execution_authorized=False)))
'''


def qualify_report(report, tasks):
    if report.get('active') != 0 or len(report.get('failures', [])) != 2:
        raise ValueError('idle exact two failed diagnostics required')
    if [row.get('task') for row in report['failures']] != tasks:
        raise ValueError('failed diagnostic identity drift')
    for row in report['failures']:
        receipt=row['receipt'];rejections=row['rejections']
        if (receipt.get('method')!='session/prompt' or receipt.get('approval') is not False
                or receipt.get('code')!=-32603 or len(rejections)!=1):
            raise ValueError('local rejection before paid call required')
        rejection=rejections[0]
        if (rejection.get('execution_id')!=row['execution'] or rejection.get('stage')!='contract'
                or rejection.get('origin',{}).get('module')!='decision_schema'
                or rejection.get('error_sha256')!=ERROR_SHA
                or rejection.get('retry_authorized') is not False
                or rejection.get('delivery_approval') is not False):
            raise ValueError('exact native envelope rejection required')


def recover_evidence(private, evidence, state, *, instance='delivery-kit-port2'):
    from r3_incident_runtime import Effects
    if (state.get('stage')!='blocked' or state.get('category')!='invalid_incident_submission'
            or state.get('escalated') is not True or 'experiment_history' in evidence):
        return None
    root=Path(private);saved=read(root/'r3-incidents'/(digest(evidence)+'.json'))
    if saved['state']!=state or saved['config']['evidence']!=evidence:
        raise ValueError('current immutable incident required')
    config=saved['config'];fx=Effects(instance);prior=state['escalation']
    states=[dict(state,stage='awaiting_diagnose',escalated=False,
                 task_id=prior['prior_task'],wakeup_id=prior['prior_wakeup']),
            dict(state,stage='awaiting_diagnose')]
    tasks=[];notes=[]
    for index,selected in enumerate(states):
        task=fx.task(config,selected,selected['task_id'])
        actor=config['cto' if index else 'techlead']
        if (task.get('status')!='failed' or task.get('id')!=selected['task_id']
                or task.get('issue_id')!=state['issue_id'] or task.get('agent_id')!=actor
                or task.get('wakeup_id')!=selected['wakeup_id']):
            raise ValueError('original failed independent diagnostic required')
        tasks.append(task['id']);notes.append(task['handoff_note'])
    folder=root/'r3-transport-recoveries'
    if folder.is_symlink():raise ValueError('unsafe transport recovery storage')
    path=folder/(digest(evidence)+'.json')
    previous=read(path) if path.exists() else None
    report=previous['report'] if previous else json.loads(command(
        'docker','exec','-w','/',instance+'-execution-broker-1','python','-c',REPORT,json.dumps(tasks)))
    if not previous:
        for row in report['failures']:
            row['rejections']=json.loads(command('docker','exec','-w','/',instance+'-model-proxy-1',
                'python','-c','import json,sys;from proxy_request_rejections import read;'
                'print(json.dumps(read("/meter/calls.json",sys.argv[1])))',row['execution']))
    qualify_report(report,tasks)
    proxy=instance+'-model-proxy-1'
    labels=json.loads(command('docker','inspect','--format','{{json .Config.Labels}}',proxy))
    if (labels.get('com.docker.compose.project')!=instance
            or labels.get('com.docker.compose.service')!='model-proxy'):
        raise ValueError('owned running proxy required')
    image=command('docker','inspect','--format','{{.Image}}',proxy).strip()
    expected=command('docker','image','inspect','--format','{{.Id}}',
                     'delivery-kit-model-proxy:20261008.100').strip()
    if image!=expected: return None  # Do not wake against unchanged transport.
    canary=json.loads(command('docker','exec','-w','/',proxy,'python','-c',CANARY,json.dumps(notes)))
    source=hashlib.sha256(Path(__file__).with_name('r3_incident_contract.py').read_bytes()).hexdigest()
    if canary!={'contract_sha256':source,'qualified':2,'execution_authorized':False}:
        raise ValueError('installed native-envelope qualification drift')
    proof=dict(operation='changed_native_envelope_diagnosis_v1',incident_sha256=digest(evidence),
               proxy_image=image,contract_sha256=source,report=report,canary=canary,
               failed_tasks_preserved=True,execution_authorized=False,release_homologated=False)
    if previous:
        if previous!=proof:raise ValueError('immutable transport recovery drift')
    else:save_receipt(path,proof)
    # New inputs, not another attempt against the original evidence identity.
    return {**evidence,'facts':{**evidence['facts'],'F03':'incident_envelope_transport_qualified'}}
