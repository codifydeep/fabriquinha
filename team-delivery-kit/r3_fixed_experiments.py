"""Controller-fixed read-only experiments, distinct from resume authorization."""
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
from portable_remediation_intake import digest,read
from release_eval import save_receipt,command,approved_submission
from portable_remediation_gate import qualify
from r3_incident_runtime import Effects as IncidentEffects,validate_decision
from remediation_publication_schedule import Effects as PublicationEffects

EXPERIMENTS={'observe_existing_controller','verify_frozen_delivery','verify_github_ci','verify_local_deployment'}
OBSERVATIONS={'controller_absent','controller_present','controller_ambiguous','snapshot_hashes_match',
              'github_ci_exact_sha','local_deployment_exact_sha','delivery_receipt_unavailable'}
ROOT=Path(__file__).resolve().parent


def experiment_identity(evidence,state,bundle):
    return digest(dict(incident=digest(evidence),proposal=digest(state['proposal']),review=digest(state['review']),
                       review_task=state['review_task'],bundle=digest(bundle),experiment=state['proposal']['experiment']))


class Effects:
    def __init__(self,private,instance):self.private=Path(private);self.instance=instance
    def now(self):return time.time()
    def verify(self,evidence,state,bundle):
        from start_eval import cli
        from evalctl import PROJECT
        from bootstrap_multica import PRIVATE
        if PROJECT!=self.instance or PRIVATE.resolve()!=self.private.resolve():
            raise ValueError('fixed current instance and private storage required')
        saved=read(self.private/'r3-incidents'/(state['incident_sha256']+'.json'))
        config=saved['config']
        if saved['state']!=state or config['evidence']!=evidence:raise ValueError('current exact incident required')
        context=bundle['context'];proof=context['remediation_expected']
        if (evidence['bundle_sha256']!=digest(bundle) or evidence['r2_proof_sha256']!=digest(proof)
                or evidence['root_issue']!=context['remediation_parent']['issue_id']
                or evidence['source_task']!=proof['source_task'] or bundle.get('original_depth')!=2):
            raise ValueError('original exact immutable experiment lineage required')
        parent=cli('get',evidence['root_issue'])
        if parent.get('id')!=evidence['root_issue'] or parent.get('status') not in ('todo','in_progress','blocked'):
            raise ValueError('active exact original parent required')
        fx=IncidentEffects(self.instance)
        author={**state,'stage':'awaiting_diagnose','task_id':state['diagnosis_task'],'wakeup_id':state['diagnosis_wakeup']}
        reviewer={**state,'stage':'awaiting_review','task_id':state['review_task']}
        for selected,key in ((author,'proposal'),(reviewer,'review')):
            if validate_decision(config,selected,fx.task(config,selected,selected['task_id']))!=state[key]:
                raise ValueError('current native independent experiment review required')
    def receipt(self,bundle):
        path=self.private/'release-receipts'/(bundle['context']['label']+'.json')
        if not path.exists() and not path.is_symlink():return None
        value=read(path)
        if any(value.get(k)!=v for k,v in bundle['context'].items()):raise ValueError('experiment delivery context drift')
        return value
    def run(self,experiment,bundle,journal):
        context=bundle['context'];proof=context['remediation_expected'];delivery=proof['delivery']
        if experiment=='observe_existing_controller':
            processes=PublicationEffects(self.instance).processes(context['label'])
            count=len(processes)
            return dict(status='passed',observation='controller_absent' if not count else
                        'controller_present' if count==1 else 'controller_ambiguous',process_count=count)
        if experiment=='verify_frozen_delivery':
            spec=bundle['spec']
            if approved_submission(context['issue_id'],spec['implementer_registry'],spec['reviewer_registry'])!=delivery:
                raise ValueError('current frozen independent approval changed')
            qualify(command,self.instance,context,delivery,previous=proof)
            return self.snapshot(delivery,journal)
        receipt=self.receipt(bundle)
        if receipt is None or not receipt.get('merge_sha'):
            return dict(status='unavailable',observation='delivery_receipt_unavailable')
        sha=receipt['merge_sha']
        if not re.fullmatch('[a-f0-9]{40}',sha):raise ValueError('exact delivered SHA required')
        contract=read(self.private/'r3-experiments'/(context['label']+'.contract.json'))
        if digest(contract)!=context['contract_sha256']:raise ValueError('experiment original contract drift')
        from project_selection import current
        if current()['repository']!=contract['repository']:raise ValueError('fixed current experiment repository required')
        if experiment=='verify_github_ci':
            from dependent_sequence import verify_recovery_ci
            if type(receipt.get('pr_number')) is not int or receipt['pr_number']<1:raise ValueError('exact reviewed PR number required')
            pr=json.loads(command('gh','pr','view',str(receipt['pr_number']),'-R',contract['repository'],
                                  '--json','state,mergeCommit'))
            if pr.get('state')!='MERGED' or (pr.get('mergeCommit') or {}).get('oid')!=sha:
                raise ValueError('experiment PR merge identity changed')
            verify_recovery_ci(receipt,{'contract':contract})
            return dict(status='passed',observation='github_ci_exact_sha',source_sha=sha)
        if experiment=='verify_local_deployment':
            from portable_qualification import verify_docker_deployment
            deployment=receipt.get('deployment',{})
            if deployment.get('source_sha')!=sha:raise ValueError('experiment deployment SHA changed')
            info=json.loads(command('docker','inspect',deployment['container']))
            if len(info)!=1 or info[0]['Config'].get('Labels',{}).get('com.docker.compose.project')!=self.instance+'-homologation':
                raise ValueError('owned homologation deployment required')
            verify_docker_deployment(deployment['container'],deployment['url'],sha,contract)
            return dict(status='passed',observation='local_deployment_exact_sha',source_sha=sha)
        raise ValueError('fixed experiment only')
    def snapshot(self,delivery,journal):
        from docker_grouping import args
        volume=delivery['volume'];source=delivery['source_task']
        if volume!=self.instance+'-snapshot-'+source:raise ValueError('exact frozen snapshot volume required')
        details=json.loads(command('docker','volume','inspect',volume))
        if (len(details)!=1 or details[0].get('Labels',{}).get('delivery-kit.owner')!=self.instance+'-broker-v1'
                or details[0].get('Labels',{}).get('delivery-kit.source-task')!=source):
            raise ValueError('frozen snapshot ownership drift')
        image=command('docker','inspect','--format','{{.Image}}',self.instance+'-execution-broker-1')
        if not re.fullmatch('sha256:[a-f0-9]{64}',image):raise ValueError('immutable probe image required')
        program=(ROOT/'r3_snapshot_probe.py').read_text()+"\nimport sys;print(json.dumps(probe('/delivery',sys.argv[1])))\n"
        result=subprocess.run(['docker','run','--rm','--name',self.job_name(journal),
            *args('r3-snapshot-probe',namespace=self.instance),'--label','delivery-kit.owner='+self.instance+'-r3-probe',
            '--label','delivery-kit.experiment='+journal['identity'],'--network','none','--read-only','--user','10000:10000',
            '--cap-drop','ALL','--security-opt','no-new-privileges','--memory','128m','--cpus','0.5','--pids-limit','32',
            '--tmpfs','/tmp:size=16m,mode=1777','--mount','type=volume,source='+volume+',target=/delivery,readonly',
            '--entrypoint','python',image,'-c',program,delivery['manifest_sha256']],capture_output=True,text=True,timeout=45)
        if result.returncode:raise ValueError('frozen snapshot physical hash verification failed')
        if len(result.stdout)>4096:raise ValueError('bounded hash result required')
        return json.loads(result.stdout)
    def job_name(self,journal):return self.instance+'-r3-probe-'+journal['identity'][:16]
    def observe(self,experiment,bundle,journal):
        # No automatic repeat after a lost acknowledgment, even for a read-only
        # probe. Missing --rm output is not reconstructed as successful evidence.
        return None


def validate_result(value,experiment,bundle):
    allowed={'status','observation','process_count','manifest_sha256','file_count','total_bytes','source_sha'}
    if (not isinstance(value,dict) or not {'status','observation'}<=set(value) or not set(value)<=allowed
            or value['status'] not in ('passed','unavailable') or value['observation'] not in OBSERVATIONS):
        raise ValueError('bounded fixed observation required')
    for key in ('process_count','file_count','total_bytes'):
        if key in value and (type(value[key]) is not int or not 0<=value[key]<=134217728):raise ValueError('bounded count required')
    for key,size in (('manifest_sha256',64),('source_sha',40)):
        if key in value and not re.fullmatch('[a-f0-9]{'+str(size)+'}',str(value[key])):raise ValueError('exact hash required')
    if value['status']=='unavailable':
        if (value!={'status':'unavailable','observation':'delivery_receipt_unavailable'} or experiment not in
                ('verify_github_ci','verify_local_deployment')):
            raise ValueError('exact unavailable verification result required')
        return value
    if experiment=='observe_existing_controller':
        count=value.get('process_count')
        expected='controller_absent' if count==0 else 'controller_present' if count==1 else 'controller_ambiguous'
        if set(value)!={'status','observation','process_count'} or value['observation']!=expected:
            raise ValueError('exact controller observation required')
    elif experiment=='verify_frozen_delivery':
        if (set(value)!={'status','observation','manifest_sha256','file_count','total_bytes'}
                or value['observation']!='snapshot_hashes_match' or not 1<=value['file_count']<=2048
                or value['manifest_sha256']!=bundle['context']['remediation_expected']['delivery']['manifest_sha256']):
            raise ValueError('exact frozen physical hash result required')
    elif (set(value)!={'status','observation','source_sha'} or value['observation']!=
            ('github_ci_exact_sha' if experiment=='verify_github_ci' else 'local_deployment_exact_sha')):
        raise ValueError('exact selected verification result required')
    return value


def execute(private,evidence,state,bundle,*,instance='delivery-kit-port2',effects=None,contract=None):
    """A reviewed experiment produces evidence, never grants resume authority."""
    private=Path(private);fx=effects or Effects(private,instance)
    proposal=state.get('proposal',{});experiment=proposal.get('experiment')
    if (private.is_symlink() or not private.is_dir() or state.get('stage')!='experiment_pending'
            or state.get('execution_authorized') is not False or state.get('release_homologated') is not False
            or proposal.get('action')!='request_experiment' or experiment not in EXPERIMENTS
            or state.get('review',{}).get('decision')!='approve_experiment'
            or state.get('incident_sha256')!=digest(evidence) or state.get('proposal_sha256')!=digest(proposal)
            or evidence.get('bundle_sha256')!=digest(bundle)):
        raise ValueError('exact independently reviewed fixed experiment required')
    directory=private/'r3-experiments'
    if directory.is_symlink():raise ValueError('unsafe experiment directory')
    directory.mkdir(mode=0o700,exist_ok=True)
    identity=experiment_identity(evidence,state,bundle)
    path=directory/(identity+'.json')
    descriptor=os.open(directory/(identity+'.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    with os.fdopen(descriptor,'w') as lock:
        fcntl.flock(lock.fileno(),fcntl.LOCK_EX)
        journal=read(path) if path.exists() or path.is_symlink() else None
        def save(value):save_receipt(path,value);return value
        if journal and journal.get('identity')!=identity:raise ValueError('immutable experiment drift')
        if journal and journal['stage'] in ('experiment_recorded','blocked'):return journal
        if journal is None:
            journal=dict(operation='r3_fixed_experiment_v1',identity=identity,incident_sha256=digest(evidence),
                experiment=experiment,stage='verification_pending',started_at=fx.now(),owner='controller',
                execution_authorized=False,release_homologated=False)
            fresh=True
        else:fresh=False
        try:fx.verify(evidence,state,bundle)
        except (ValueError,KeyError,subprocess.CalledProcessError):
            return save({**journal,'stage':'blocked','owner':'cto','category':'independent_review_not_current'})
        except (TimeoutError,OSError):
            return save({**journal,'stage':'blocked','owner':'cto','category':'independent_review_unobservable'})
        if not fresh:
            result=fx.observe(experiment,bundle,journal)
            if result is None:
                if fx.now()-journal['started_at']<1800:return journal
                return save({**journal,'stage':'blocked','owner':'cto','category':'experiment_result_unobservable'})
        else:
            if contract is not None:
                if digest(contract)!=bundle['context']['contract_sha256']:raise ValueError('exact original experiment contract required')
                target=directory/(bundle['context']['label']+'.contract.json')
                if target.exists() or target.is_symlink():
                    if read(target)!=contract:raise ValueError('immutable experiment contract drift')
                else:save_receipt(target,contract)
            journal=save({**journal,'stage':'execution_intent'})
            try:result=fx.run(experiment,bundle,journal)
            except (TimeoutError,OSError,subprocess.TimeoutExpired):
                return save({**journal,'stage':'observation_pending','owner':'cto'})
            except (ValueError,KeyError,subprocess.CalledProcessError):
                return save({**journal,'stage':'blocked','owner':'cto','category':'fixed_verification_failed'})
        try:result=validate_result(result,experiment,bundle)
        except ValueError:return save({**journal,'stage':'blocked','owner':'cto','category':'invalid_fixed_observation'})
        return save({**journal,'stage':'experiment_recorded','result':result,'result_sha256':digest(result),
                     'owner':'cto','next_action':'evaluate new evidence; independent resume verification still required'})
