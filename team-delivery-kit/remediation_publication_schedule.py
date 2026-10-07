"""Supervise only publication of approved R2; never respawn an agent."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from portable_remediation_intake import candidate,read_input,bundle,prepare,read,digest
from remediation_parent_delivery import publish,verify_live
from release_eval import approved_submission,command,save_receipt

ROOT=Path(__file__).resolve().parent
SCRIPT=ROOT/'portable_delivery.py'


class Effects:
    def __init__(self,instance):self.instance=instance
    def candidate(self,root):return candidate(command,self.instance,root)
    def approved(self,issue,spec):return approved_submission(issue,spec['implementer_registry'],spec['reviewer_registry'])
    def input(self,issue,delivery):return read_input(command,self.instance,issue,delivery)
    def parent(self,issue):
        from start_eval import cli
        return cli('get',issue)
    def now(self):return time.time()
    def processes(self,label):
        rows=subprocess.check_output(['ps','-axo','pid=,command='],text=True)
        matches=[]
        for line in rows.splitlines():
            parts=line.strip().split(None,1)
            if len(parts)!=2 or not parts[0].isdigit():continue
            suffix=' -u '+str(SCRIPT)+' --managed-label '+label
            if (parts[1].endswith(suffix)
                    and Path(parts[1][:-len(suffix)]).resolve()==Path(sys.executable).resolve()):
                matches.append(int(parts[0]))
        return matches
    def launch(self,paths,stage,project,label):
        env={**os.environ,'DELIVERY_KIT_RUN_SPEC':str(paths['spec'].resolve()),
             'DELIVERY_KIT_DELIVERY_CONTRACT':str(stage['contract_path'].resolve()),
             'DELIVERY_KIT_PROJECT_CONFIG':str(project.resolve()),
             'DELIVERY_KIT_TEST_REVISION_DEPTH':'2'}
        for key in ('DELIVERY_KIT_EXISTING_ISSUE_ID','DELIVERY_KIT_EXPECTED_PLAN_SHA',
                    'DELIVERY_KIT_TEST_FIRST','DELIVERY_KIT_TEST_REVISION_PARENT','DELIVERY_KIT_CONTROLLED_WORKER_LOSS'):
            env.pop(key,None)
        log_path=paths['intent'].with_name(label+'.log')
        descriptor=os.open(log_path,os.O_WRONLY|os.O_CREAT|os.O_APPEND|os.O_NOFOLLOW,0o600)
        with os.fdopen(descriptor,'a') as log:
            process=subprocess.Popen([sys.executable,'-u',str(SCRIPT),'--managed-label',label],
                cwd=ROOT,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=log,start_new_session=True)
        return process.pid
    def status(self,private,label):
        path=private/'autonomy-status'/(label+'.json')
        return read(path) if path.exists() or path.is_symlink() else None
    def receipt(self,private,label):
        path=private/'release-receipts'/(label+'.json')
        return read(path) if path.exists() or path.is_symlink() else None
    def publish(self,paths,receipt,stage):
        from start_eval import cli
        return publish(paths,receipt,cli,
            lambda value,prepared:verify_live(stage,value,prepared,instance=self.instance))


def reconcile(private,stage,parent,project,*,instance='delivery-kit-port2',effects=None):
    """Persist one launch intent. Missing/unknown handles demand diagnosis."""
    private=Path(private);project=Path(project);fx=effects or Effects(instance)
    issue=fx.candidate(parent['issue_id'])
    if issue is None:
        directory=private/'remediation-publication'
        if directory.is_symlink():raise ValueError('unsafe R3 controller directory')
        previous=[]
        for path in directory.glob('REMEDIATION*.json'):
            if path.name.endswith(('.run.json','.parent.json','.controller.json')):continue
            intake=read(path)
            if intake.get('bundle',{}).get('context',{}).get('remediation_parent')==parent:
                previous.append((path,intake))
        if len(previous)>1:raise ValueError('ambiguous existing R3 intake')
        if not previous:return None
        path,intake=previous[0];label=intake['bundle']['context']['label']
        controller=path.with_name(label+'.controller.json')
        if not controller.exists():return None
        state=read(controller)
        if state.get('stage') in ('blocked','parent_projected'):return state
        state={**state,'stage':'blocked','owner':'techlead','category':'r3_dependency_not_qualified',
            'next_action':'diagnose R2 approval and existing R3 controller; no relaunch', 'release_homologated':False}
        save_receipt(controller,state);return state
    current=fx.parent(parent['issue_id'])
    if current.get('id')!=parent['issue_id'] or current.get('status') not in ('todo','in_progress','blocked','done'):
        raise ValueError('uncancelled original parent required for R3 supervision')
    delivery=fx.approved(issue,stage['spec'])
    prepared=bundle(parent,stage['spec'],stage['contract'],fx.input(issue,delivery))
    paths=prepare(private,prepared);label=prepared['context']['label']
    path=paths['intent'].with_name(label+'.controller.json')
    descriptor=os.open(path.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        identity=digest(dict(bundle=prepared,project=str(project.resolve()),contract_path=str(stage['contract_path'].resolve()),instance=instance))
        state=read(path) if path.exists() or path.is_symlink() else None
        if state and state.get('identity')!=identity:raise ValueError('immutable R3 controller binding changed')
        def save(value):
            save_receipt(path,value);return value
        def hold(category):
            return save({**(state or {}),'identity':identity,'stage':'blocked','owner':'techlead',
                'category':category,'next_action':'diagnose exact publication state; preserve receipts and process; no identical relaunch',
                'release_homologated':False})
        receipt=fx.receipt(private,label)
        if receipt and receipt.get('stage')=='deployed_qa_passed':
            result=fx.publish(paths,receipt,stage)
            return save({**(state or {}),'identity':identity,'stage':result['stage'],
                'parent_projection':result,'release_homologated':False})
        if state and state.get('stage')=='blocked':return state
        if state and state.get('stage')=='parent_projected':return hold('r3_delivery_receipt_disappeared')
        if state is None:
            existing=fx.processes(label)
            if existing:return hold('unrecorded_r3_controller')
            state=save(dict(identity=identity,stage='launch_intent',launch_attempted=True,
                started_at=fx.now(),progress_at=fx.now(),release_homologated=False))
            try:pid=fx.launch(paths,stage,project,label)
            except Exception:
                return save({**state,'stage':'launch_observation_pending'})
            if type(pid) is not int or pid<=0:return hold('invalid_r3_launch_handle')
            return save({**state,'stage':'running','pid':pid})
        processes=fx.processes(label)
        if len(processes)>1:return hold('ambiguous_r3_controller')
        if not processes:return hold('r3_controller_handle_missing')
        if state.get('pid') not in (None,processes[0]):return hold('r3_controller_identity_changed')
        status=fx.status(private,label)
        if status and status.get('label')!=label:return hold('r3_status_identity_changed')
        progress=digest({k:v for k,v in (status or {}).items() if k!='updated_at'})
        if status and progress!=state.get('progress_sha256'):
            state={**state,'progress_at':fx.now(),'progress_sha256':progress}
        age=fx.now()-state['progress_at']
        if age>=1800:return hold('r3_progress_deadline')
        return save({**state,'stage':'running','pid':processes[0],'attention_required':age>=600})
