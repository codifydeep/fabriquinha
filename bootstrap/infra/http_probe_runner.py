"""Bounded Docker probe lifecycle with durable phase evidence and owned cleanup."""
import json
import subprocess
import time
import uuid
from review_controller import bounded_run

class ProbeFailure(RuntimeError):
    def __init__(self,detail):
        self.detail=detail
        super().__init__(json.dumps(detail))

def run_probe(image,target,commit,baseline,script,project,record):
    history=[]
    for attempt in (1,2):
        name=project+'-probe-'+uuid.uuid4().hex[:12]
        state=dict(name=name,attempt=attempt,commit=commit,phase='create',events=[],passed=False)
        def command(phase,args,timeout):
            state['phase']=phase; record(state)
            start=time.monotonic()
            try:
                result=bounded_run(args,timeout=timeout)
                state['events'].append(dict(phase=phase,seconds=round(time.monotonic()-start,3),returncode=result.returncode,output=result.stdout[-4000:]))
                record(state)
                if result.returncode: raise RuntimeError(phase+' command failed')
                return result.stdout
            except Exception as exc:
                state['events'].append(dict(phase=phase,seconds=round(time.monotonic()-start,3),error=type(exc).__name__))
                record(state); raise
        failure=None; functional=False; cleanup_ok=False
        try:
            command('create',['docker','create','--name',name,'--network','container:'+target,'--read-only','--cap-drop','ALL',
                '--security-opt','no-new-privileges','--pids-limit','32','--memory','128m','--user','65534:65534','--tmpfs','/opt/data:rw,noexec,nosuid,size=1m',
                '--label','com.docker.compose.project='+project,'--label','com.docker.compose.service=http-probe',
                '--label','hermes.probe.id='+name,'-e','EXPECTED_COMMIT='+commit,'-e','BASELINE_ONLY='+('1' if baseline else '0'),
                '--entrypoint','/usr/bin/python3',image,'-B','-c',script],20)
            command('start',['docker','start',name],20)
            code=command('http_execution',['docker','wait',name],35).strip()
            output=command('collect',['docker','logs',name],10)
            if code!='0':
                functional=True; raise ValueError('HTTP probe failed; see preserved probe output')
            functional=True
            result=json.loads(output)
            if not result.get('passed') or result.get('commit')!=commit or result.get('checks')!=(1 if baseline else 10):
                functional=True; raise ValueError('invalid HTTP receipt')
            state.update(passed=True,phase='validated'); record(state)
        except Exception as exc:
            failure=dict(category='http_validation_failed' if functional else 'probe_infrastructure_failure',phase=state['phase'],error=type(exc).__name__,detail=str(exc)[:1000])
        finally:
            # Recover create-response loss by inspecting the exact unique name.
            try:
                found=bounded_run(['docker','inspect',name],timeout=5)
                if found.returncode==0:
                    obj=json.loads(found.stdout)[0]
                    if obj['Config']['Labels'].get('hermes.probe.id')!=name: raise PermissionError('probe ownership mismatch')
                    cleanup=bounded_run(['docker','rm','-f',name],timeout=10)
                    cleanup_ok=cleanup.returncode==0
                else: cleanup_ok='No such' in found.stdout
            except Exception as exc: state['cleanup_error']=type(exc).__name__
            state['cleanup_ok']=cleanup_ok; record(state)
        history.append(dict(state))
        if not cleanup_ok:
            raise ProbeFailure(dict(category='probe_cleanup_failed',attempts=history,block_required=True,next_action='Tech Lead/CTO must reconcile this exact probe before retrying.'))
        if failure is None: return dict(result,lifecycle=history)
        if functional or attempt==2:
            raise ProbeFailure(dict(failure,attempts=history,block_required=True,next_action='Tech Lead/CTO: diagnose the recorded phase; no unchanged retries or use of old validation receipts.'))
        # One infrastructure retry only, after recording evidence and cleanup.
