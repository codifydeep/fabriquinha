"""Lowest-priority post-delivery nomination/curation; never a delivery gate.

The caller must have just revalidated the delivery sequence. This module also
checks all receipts and native source provenance before admitting memory work.
"""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time

from release_eval import save_receipt

IDLE_PROGRAM='''import broker as b,controller_maintenance as m,json,time
active=m.native_active(b)
with b.db() as con:
 leases=con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','active','closing')").fetchone()[0]
 launching=con.execute("SELECT count(*) FROM grants g LEFT JOIN leases l USING(request_id) WHERE g.used=1 AND g.deadline>? AND l.request_id IS NULL",(time.time(),)).fetchone()[0]
 print(json.dumps({'idle':not active and not leases and not launching and m.current(con) is None}))
'''


def native_idle(namespace):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('owned instance required')
    broker=namespace+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format',
        '{{json .Config.Labels}}',broker],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned post-delivery controller required')
    value=json.loads(subprocess.check_output(['docker','exec','-w','/',broker,'python','-c',IDLE_PROGRAM],
                                           text=True,timeout=60))
    if set(value)!={'idle'} or type(value['idle']) is not bool:raise ValueError('native idle proof missing')
    return value['idle']


def advance(path,identity,*,qualify,nominate,curate):
    """Every tick revalidates delivery; intent is durable before nomination."""
    path=Path(path)
    if path.is_symlink() or (path.exists() and path.stat().st_size>65536):raise ValueError('bounded memory flow required')
    evidence=qualify()  # A local terminal flag alone must never start memory work.
    digest=hashlib.sha256(json.dumps({'identity':identity,'evidence':evidence},sort_keys=True).encode()).hexdigest()
    state=json.loads(path.read_text()) if path.exists() else {
        'identity_sha256':digest,'stage':'nomination_intent','owner':'techlead','delivery_approval':False}
    if state.get('identity_sha256')!=digest:raise ValueError('post-delivery memory identity drift')
    if state['stage'] in ('approved','rejected','blocked'):return state
    save_receipt(path,state)
    try:
        if not state.get('nomination'):
            state['nomination']=nominate();state['stage']='nominated';save_receipt(path,state)
        result=curate(state['nomination'])
        state.update(stage=result['stage'],curation=result)
        if result['stage']=='blocked':
            state.update(owner='cto',next_action='Diagnose the exact memory curation; product delivery remains independently verified')
        elif result['stage'] in ('approved','rejected'):
            state.pop('owner',None);state.pop('next_action',None)
    except Exception as error:
        state.update(stage='blocked',owner='cto',category=type(error).__name__,
                     next_action='Diagnose post-delivery memory provenance/admission; do not replay the author or approve the release')
    save_receipt(path,state)
    return state


def run(config,private,namespace):
    from dependent_sequence import read_json,load_plan,read_stage_delivery
    from delivery_memory import facts,read_receipt,record
    from memory_native import nominate_cto
    from memory_curation import tick,AdmissionDeferred
    from memory_curation_cli import publish_terminal
    from planning_intake import issue_for
    from start_eval import cli,read_model_budget,MIN_MODEL_CALLS_FOR_NEW_RELEASE
    root=Path(private)
    pipeline=read_json(root/'brief-delivery'/(config['name']+'.json'))
    if (not pipeline or pipeline.get('stage')!='qualified' or pipeline.get('identity')!=config['sha256']
            or pipeline.get('completed')!=['planning','materializing','compiling','executing']):
        return {'stage':'not_eligible','delivery_approval':False}
    plan=load_plan(Path(__file__).parent/'projects'/(config['prefix']+'.sequence.json'))
    planning=read_json(root/'planning-intake'/(config['name']+'.json'))
    if (not planning or planning.get('stage')!='plan_ready'
            or planning.get('configuration_sha256')!=config['selection']['configuration_sha256']):
        raise ValueError('exact completed planning source required')
    repository='https://github.com/'+config['stages'][0]['contract']['repository']
    registry=read_json(root/'planning-agents.json')
    def qualify():
        sequence=read_json(root/'dependent-sequences'/(plan['name']+'.json'))
        if (not sequence or sequence.get('stage')!='done'
                or sequence.get('completed')!=[stage['spec']['label'] for stage in plan['stages']]):
            raise ValueError('completed delivery sequence required')
        evidence=[]
        for stage in plan['stages']:
            receipt=read_stage_delivery(root,stage)
            label=receipt['label'];facts(receipt,repository,label)
            raw,actual=read_receipt(root,label)
            gates=('merge_sha','delivery','frozen_tests','deployment','browser_qa','pr_url','main_ci_run')
            if any(actual.get(key)!=receipt.get(key) for key in gates):
                raise ValueError('memory receipt differs from resolved delivery gates')
            evidence.append(hashlib.sha256(raw).hexdigest())
            record(root,repository,namespace,label)
        return evidence
    def nominate():
        return nominate_cto(root,repository,namespace,planning,registry['agents']['cto'],cli)
    def create(*args,**kwargs):
        if not native_idle(namespace):raise AdmissionDeferred('capacity')
        if read_model_budget()['remaining']<MIN_MODEL_CALLS_FOR_NEW_RELEASE:raise AdmissionDeferred('budget')
        return issue_for(*args,**kwargs)
    def curate(key):
        result=tick(root,repository,namespace,key,registry['agents']['techlead'],cli=cli,
                    create=create,now=int(time.time()))
        publish_terminal(result,cli)
        return result
    identity={'config':config['sha256'],'repository':repository,'namespace':namespace,
              'source':planning['outputs']['cto']}
    return advance(root/'release-memory'/(config['name']+'.json'),identity,
                   qualify=qualify,nominate=nominate,curate=curate)
