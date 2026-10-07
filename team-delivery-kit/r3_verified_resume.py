"""One fixed controller restart after current independent technical clearance.

This is not an agent capability, a retry-budget reset, or a delivery approval.
Persist the effect intent before verification and before launching; after an
uncertain acknowledgment, observe the same identity instead of repeating it.
"""
import fcntl
import os
from pathlib import Path
import re
import subprocess
from portable_remediation_intake import digest,read,prepare,bundle as make_bundle
from release_eval import save_receipt,command
from remediation_publication_schedule import Effects as PublicationEffects


def verify_lineage(private,evidence,bundle):
    from r3_post_experiment import next_evidence
    from r3_fixed_experiments import experiment_identity
    current=evidence;seen=set()
    while 'previous_incident_sha256' in current:
        previous=current['previous_incident_sha256']
        if previous in seen or len(seen)>=4:raise ValueError('bounded immutable experiment lineage required')
        seen.add(previous)
        saved=read(private/'r3-incidents'/(previous+'.json'))
        origin=saved['config']['evidence'];state=saved['state']
        if digest(origin)!=previous:raise ValueError('original incident hash changed')
        journal=read(private/'r3-experiments'/(experiment_identity(origin,state,bundle)+'.json'))
        if next_evidence(origin,state,bundle,journal)!=current:raise ValueError('post-experiment evidence changed')
        current=origin
    if not seen:raise ValueError('actual experiment evidence required before resume')


class Effects:
    def __init__(self,private,instance):
        self.private=Path(private);self.instance=instance;self.publication=PublicationEffects(instance)
    def now(self):return self.publication.now()
    def processes(self,label):return self.publication.processes(label)
    def launch(self,*args):return self.publication.launch(*args)
    def verify(self,evidence,state,bundle,stage,project,clearance):
        from r3_fixed_experiments import Effects as ExperimentEffects,validate_result
        fx=ExperimentEffects(self.private,self.instance)
        fx.verify(evidence,state,bundle)
        verify_lineage(self.private,evidence,bundle)
        context=bundle['context'];parent=context['remediation_parent'];proof=context['remediation_expected']
        if self.publication.candidate(parent['issue_id'])!=context['issue_id']:
            raise ValueError('current qualified R2 issue required')
        if self.publication.approved(context['issue_id'],stage['spec'])!=proof['delivery']:
            raise ValueError('current exact R2 independent approval required')
        current=make_bundle(parent,stage['spec'],stage['contract'],
                            self.publication.input(context['issue_id'],proof['delivery']))
        identity=digest(dict(bundle=current,project=str(Path(project).resolve()),
                            contract_path=str(stage['contract_path'].resolve()),instance=self.instance))
        if current!=bundle or identity!=evidence['controller_identity']:
            raise ValueError('original controller inputs changed')
        program='''import sys;sys.path.insert(0,"/")
import broker as b,json
with b.LOCK,b.db() as con:
 print(json.dumps(con.execute("SELECT count(*) FROM leases WHERE status IN ('creating','starting','running','closing')").fetchone()[0]))
'''
        active=json_load_count(command('docker','exec',self.instance+'-execution-broker-1','python','-c',program))
        count=len(self.processes(context['label']))
        if active or count:raise ValueError('idle worker capacity and absent exact controller required')
        fx.receipt(bundle)  # Existing delivery evidence must retain its exact context.
        result=validate_result(fx.snapshot(proof['delivery'],{'identity':clearance}),'verify_frozen_delivery',bundle)
        # Close the window after the potentially slow physical verification.
        if json_load_count(command('docker','exec',self.instance+'-execution-broker-1','python','-c',program)) or self.processes(context['label']):
            raise ValueError('capacity or controller changed during verification')
        fx.verify(evidence,state,bundle)
        if self.publication.approved(context['issue_id'],stage['spec'])!=proof['delivery']:
            raise ValueError('independent R2 approval changed during verification')
        return dict(operation='verified_r3_resume_inputs_v1',bundle_sha256=digest(bundle),
                    physical_manifest_sha256=result['manifest_sha256'],active_leases=active,
                    controller_count=count,original_depth=2,release_homologated=False)


def json_load_count(value):
    import json
    count=json.loads(value)
    if type(count) is not int or count<0:raise ValueError('exact worker count required')
    return count


def resume(private,incoming,bundle,stage,project,*,instance='delivery-kit-port2',effects=None):
    from r3_incident_runtime import validate_evidence
    private=Path(private);project=Path(project)
    if private.is_symlink() or not private.is_dir():raise ValueError('private controller storage required')
    incident=incoming.get('incident_sha256')
    if not re.fullmatch('[a-f0-9]{64}',str(incident)):raise ValueError('exact persisted incident required')
    if (private/'r3-incidents').is_symlink():raise ValueError('unsafe incident directory')
    saved=read(private/'r3-incidents'/(incident+'.json'));state=saved['state'];evidence=validate_evidence(saved['config']['evidence'])
    if ({k:v for k,v in incoming.items() if k!='experiment'}!=state or digest(evidence)!=incident
            or state.get('stage')!='resume_verification_pending' or state.get('post_experiment') is not True
            or state.get('escalated') is not True or state.get('execution_authorized') is not False
            or state.get('release_homologated') is not False or state.get('proposal',{}).get('action')!='propose_resume'
            or state.get('proposal',{}).get('experiment')!='none' or state.get('review',{}).get('decision')!='approve_resume'
            or 'controller_episode_sha256' not in evidence or 'experiment_history' not in evidence
            or evidence['bundle_sha256']!=digest(bundle) or bundle.get('original_depth')!=2
            or bundle.get('execution_authorized') is not False or bundle.get('release_homologated') is not False):
        raise ValueError('exact independently reviewed post-experiment recommendation required')
    context=bundle['context'];proof=context['remediation_expected']
    if (evidence['root_issue']!=context['remediation_parent']['issue_id']
            or evidence['source_task']!=proof['source_task'] or evidence['r2_proof_sha256']!=digest(proof)):
        raise ValueError('original exact R2 lineage required')
    paths=prepare(private,bundle);path=paths['intent'].with_name(context['label']+'.controller.json')
    fx=effects or Effects(private,instance)
    descriptor=os.open(path.with_suffix('.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        controller=read(path)
        def save(value):save_receipt(path,value);return value
        def hold(category):
            return save({**controller,'stage':'blocked','owner':'cto','category':category,
                         'next_action':'diagnose this exact resume attempt; no identical relaunch',
                         'release_homologated':False})
        if controller.get('resume_incident_sha256')==incident:
            if (controller.get('identity')!=evidence['controller_identity']
                    or digest(controller.get('previous_hold'))!=evidence['controller_episode_sha256']
                    or controller.get('release_homologated') is not False):
                raise ValueError('persisted exact resume attempt changed')
            if controller['stage']=='blocked':return controller
            if controller['stage']=='resume_verification_intent':return hold('authorized_resume_verification_unobservable')
            processes=fx.processes(context['label'])
            if len(processes)>1:return hold('authorized_resume_handle_ambiguous')
            if not processes:return hold('authorized_resume_handle_missing')
            if controller.get('pid') not in (None,processes[0]):return hold('authorized_resume_identity_changed')
            return save({**controller,'stage':'running','pid':processes[0]})
        if (controller.get('stage')!='blocked' or digest(controller)!=evidence['controller_episode_sha256']
                or controller.get('identity')!=evidence['controller_identity']):
            raise ValueError('approved exact original hold changed')
        previous=controller
        controller=save({**controller,'stage':'resume_verification_intent','owner':'controller',
                         'resume_incident_sha256':incident,'previous_hold':previous,
                         'controller_resume_authorized':False,'release_homologated':False})
        try:
            verification=fx.verify(evidence,state,bundle,stage,project,incident)
            expected=dict(operation='verified_r3_resume_inputs_v1',bundle_sha256=digest(bundle),
                          physical_manifest_sha256=proof['delivery']['manifest_sha256'],active_leases=0,
                          controller_count=0,original_depth=2,release_homologated=False)
            if (verification!=expected or type(verification.get('active_leases')) is not int
                    or type(verification.get('controller_count')) is not int or type(verification.get('original_depth')) is not int
                    or verification.get('release_homologated') is not False or fx.processes(context['label'])):
                raise ValueError('exact fresh fixed resume verification required')
        except (ValueError,KeyError,TimeoutError,OSError,subprocess.SubprocessError):
            return hold('authorized_resume_verification_failed')
        controller=save({**controller,'stage':'resume_launch_intent','resume_verification':verification,
                         'controller_resume_authorized':True,'pid':None,'progress_at':fx.now()})
        try:pid=fx.launch(paths,stage,project,context['label'])
        except (TimeoutError,OSError,subprocess.SubprocessError):
            return save({**controller,'stage':'resume_observation_pending'})
        if type(pid) is not int or pid<=0:return hold('authorized_resume_handle_invalid')
        return save({**controller,'stage':'running','pid':pid})
