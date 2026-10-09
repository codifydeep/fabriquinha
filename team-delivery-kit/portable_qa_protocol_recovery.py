"""One read-only CTO recovery after a newly qualified provider protocol fix.

The old execution remains failed. A protocol fixture grants only one diagnostic
execution, never a product retry, write permission, QA waiver or delivery approval.
Unknown probe outcomes are durable and never blindly repeated.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess

from release_eval import save_receipt


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def read(path):
    if path.is_symlink() or not path.is_file() or path.stat().st_size>262144:
        raise ValueError('safe protocol recovery receipt required')
    return json.loads(path.read_text())


def failed_evidence(incident,original,cli):
    from evalctl import PROJECT
    child=cli('get',original['child_issue_id'])
    metadata=cli('metadata','list',child['id'])
    runs=cli('runs',child['id'])
    if (child.get('parent_issue_id')!=incident['child_issue_id']
            or child.get('assignee_id')!=original['cto_id'] or child.get('status')=='done'
            or metadata.get('qa_incident_key')!=incident['key']
            or metadata.get('qa_source_sha')!=incident['source_sha']
            or len(runs)!=1 or runs[0].get('agent_id')!=original['cto_id']
            or runs[0].get('status')!='failed'
            or runs[0].get('error')!='hermes session/prompt failed: session/prompt: Internal error '
                '(code=-32603, data={"broker_diagnostic": []})'):
        raise ValueError('exact failed read-only CTO transport required')
    task=runs[0]['id']
    program='''import broker as b,qa_artifacts,json,sys
task,actor,issue,root,sha=sys.argv[1:]
with b.db() as c:
 row=c.execute('SELECT n.request_id,g.mode,l.status FROM native_bindings n JOIN grants g USING(request_id) JOIN leases l USING(request_id) WHERE n.task_id=? AND n.agent_id=? AND n.issue_id=?',(task,actor,issue)).fetchone()
 if not row or tuple(row)[1:]!=('planning','closed'):raise ValueError('closed planning lease required')
 payload=json.loads(c.execute('SELECT payload FROM worker_creation_intents WHERE request_id=?',(row[0],)).fetchone()[0])
 if any(m.get('Target') not in ('/session-state','/evidence/candidate','/evidence/previous') or (m.get('Target')!='/session-state' and m.get('ReadOnly') is not True) for m in payload['HostConfig']['Mounts']):raise ValueError('read-only artifact mounts required')
 config=qa_artifacts.config_for(b.handoff_context(),issue,actor)
 if config['request']['root_issue_id']!=root or config['request']['source_sha']!=sha:raise ValueError('artifact source drift')
proof=qa_artifacts.verify_reads(b.handoff_context(),task)
print(json.dumps(dict(task_id=task,read_proof=proof,closed_planning=True,source_sha=sha,delivery_approval=False)))
'''
    result=json.loads(subprocess.check_output(['docker','exec','-w','/',PROJECT+'-execution-broker-1',
        'python','-c',program,task,original['cto_id'],child['id'],incident['parent_issue_id'],
        incident['source_sha']],text=True,timeout=30))
    if (result.get('task_id')!=task or result.get('source_sha')!=incident['source_sha']
            or result.get('closed_planning') is not True or result.get('delivery_approval') is not False
            or result.get('read_proof',{}).get('status')!='read_evidence_verified'):
        raise ValueError('failed diagnostic evidence drift')
    return result


def installed():
    from evalctl import PROJECT
    name=PROJECT+'-model-proxy-1'
    output=subprocess.check_output(['docker','inspect','--format',
        '{{json .Config.Labels}} {{.Image}} {{.State.Running}}',name],text=True,timeout=10)
    label_json,image,running=output.strip().rsplit(' ',2)
    labels=json.loads(label_json) or {}
    if (labels.get('com.docker.compose.project')!=PROJECT
            or labels.get('com.docker.compose.service')!='model-proxy'
            or running!='true' or not re.fullmatch(r'sha256:[a-f0-9]{64}',image)):
        raise ValueError('owned running immutable model proxy required')
    names=('structured_response_contract.py','provider_tool_routing.py','model_proxy.py')
    expected={p:hashlib.sha256(Path(__file__).with_name(p).read_bytes()).hexdigest() for p in names}
    actual=json.loads(subprocess.check_output(['docker','exec','-w','/',name,'python','-c',
        'from pathlib import Path;import hashlib,json;print(json.dumps({p:hashlib.sha256(Path("/"+p).read_bytes()).hexdigest() for p in '+repr(names)+'}))'],
        text=True,timeout=10))
    if actual!=expected:raise ValueError('qualified protocol source/image drift')
    return name,{'image':image,'modules':actual,
        'fixture_sha256':hashlib.sha256(Path(__file__).with_name('qa_protocol_canary.py').read_bytes()).hexdigest()}


def qualify(private, *, inspect=installed, execute=None):
    name,identity=inspect()
    key=digest(identity)
    path=Path(private)/'qa-protocol-qualifications'/(key+'.json')
    if path.exists():
        value=read(path)
        if value.get('identity')!=identity:raise ValueError('protocol qualification identity drift')
        if value.get('stage')!='qualified':
            raise ValueError('protocol qualification outcome unknown or rejected; no automatic replay')
        return key,value
    save_receipt(path,{'identity':identity,'stage':'probe_intent','delivery_approval':False})
    if execute is None:
        def execute():
            source=Path(__file__).with_name('qa_protocol_canary.py').read_text()
            return json.loads(subprocess.check_output(['docker','exec','-w','/',name,
                'python','-c',source,'--execute'],text=True,timeout=150))
    result=execute()
    if inspect()[1]!=identity:
        raise ValueError('protocol installation changed during fixture; outcome unknown')
    value={'identity':identity,'stage':'rejected','probe':result,'delivery_approval':False}
    if (result.get('kind')=='protocol_fixture_not_delivery_evidence'
            and result.get('status')==200 and result.get('local_validation')=='passed'
            and result.get('json_valid') is True and result.get('done_markers')==1
            and type(result.get('call')) is int and result['call']>0
            and re.fullmatch(r'[a-f0-9]{64}',str(result.get('sha256','')))):
        value['stage']='qualified'
    save_receipt(path,value)
    if value['stage']!='qualified':raise ValueError('protocol fixture rejected; no automatic replay')
    return key,value


def validate(private,incident,original,proof):
    if (not isinstance(proof,dict) or proof.get('incident_key')!=incident['key']
            or proof.get('source_sha')!=incident['source_sha']
            or proof.get('failed_issue_id')!=original['child_issue_id']
            or proof.get('cto_id')!=original['cto_id']
            or proof.get('delivery_approval') is not False
            or proof.get('author_retry_authorized') is not False
            or not proof.get('failed_task_id')
            or not re.fullmatch(r'[a-f0-9]{64}',str(proof.get('failure_evidence_sha256','')))
            or not re.fullmatch(r'[a-f0-9]{64}',str(proof.get('qualification_key','')))):
        raise ValueError('non-authorizing exact protocol recovery required')
    value=read(Path(private)/'qa-protocol-qualifications'/(proof['qualification_key']+'.json'))
    if (value.get('stage')!='qualified' or value.get('delivery_approval') is not False
            or digest(value)!=proof.get('qualification_sha256')):
        raise ValueError('durable protocol qualification required')


def recover(private,cli,*,incident,original,parent_contract,budget_ready,
            observe=failed_evidence,qualification=qualify,inspect=installed):
    if incident.get('phase')!='browser' or original.get('dispatch')!='cto_failed':return None
    if not budget_ready:return None
    failed=observe(incident,original,cli)
    if (failed.get('closed_planning') is not True or failed.get('delivery_approval') is not False
            or failed.get('source_sha')!=incident['source_sha']
            or failed.get('read_proof',{}).get('status')!='read_evidence_verified'
            or failed.get('read_proof',{}).get('task_id')!=failed.get('task_id')):
        raise ValueError('non-authorizing failed diagnostic proof required')
    prior_path=Path(private)/'qa-cto-protocol-recoveries'/(incident['key']+'.json')
    if prior_path.exists():
        prior=read(prior_path)
        proof=prior.get('protocol_recovery')
        if not isinstance(proof,dict) or proof.get('failed_task_id')!=failed['task_id']:
            raise ValueError('historical protocol recovery execution drift')
        value=read(Path(private)/'qa-protocol-qualifications'/(proof['qualification_key']+'.json'))
        if inspect()[1]!=value.get('identity') or proof.get('failure_evidence_sha256')!=digest(failed):
            raise ValueError('protocol recovery installation or failed evidence drift')
    else:
        key,evidence=qualification(private)
        proof={'incident_key':incident['key'],'source_sha':incident['source_sha'],
            'failed_issue_id':original['child_issue_id'],'failed_task_id':failed['task_id'],
            'cto_id':original['cto_id'],'qualification_key':key,'qualification_sha256':digest(evidence),
            'failure_evidence_sha256':digest(failed),
            'delivery_approval':False,'author_retry_authorized':False}
    validate(private,incident,original,proof)
    from portable_qa_cto import record
    return record(private,cli,incident=incident,parent_contract=parent_contract,
        cto_id=original['cto_id'],reason=original['reason'],budget_ready=budget_ready,
        protocol_recovery=proof)
