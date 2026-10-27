"""Public preparation + native SDK config and Kanban per-profile admission.

No model, relay, GitHub mutation or Docker jobs. The fairness callback records
admission without spawning a worker; this is not a delivery or paid-run proof.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from prepare_hermes_project import prepare
from fabriquinha.effects import write_json
from fabriquinha.profile_policy import configuration,contract,report,inspect_profile,native_effective,ProfileRefused,admission
from fabriquinha.runtime import Runtime
from fabriquinha.kanban_lane import native


def qualify(root,upstream,image,browser_image):
    root=Path(root).resolve();upstream=Path(upstream).resolve()
    value=json.loads((ROOT/'examples/python-http/project.example.json').read_bytes())
    value.update(namespace='delivery-kit-profile-preparation',validation_image=image,browser_image=browser_image)
    prepared=prepare(root,upstream,value,'fixture/profile-admission',19498,1,max_output_tokens=4096)
    runtime=Runtime(root,upstream);before=report(runtime.project,root)
    assert before['errors']==[] and len(before['profiles'])==9
    assert all(state['ready'] and state['effective_checked'] for state in before['profiles'].values())
    write_json(root/'profiles-before.json',before)
    assert json.loads((root/'installation.json').read_bytes())['profile_contract']==contract()
    home=root/'home/profiles/frontend';logs=io.StringIO()
    (home/'config.yaml').write_text('{')
    assert inspect_profile(root,'frontend')['ready'] is False
    # Exercise the actual native fallback too: even an existing good backup is
    # rejected by our adapter, never accepted as the current profile's policy.
    with contextlib.redirect_stderr(logs):
        try:native_effective(home)
        except ProfileRefused as error:assert error.code=='ProfileConfigFallbackRefused'
        else:raise AssertionError('native last-known-good fallback was not refused')
    write_json(root/'native-fallback.json',dict(stderr=logs.getvalue(),refused=True))
    write_json(home/'config.yaml',configuration())
    assert inspect_profile(root,'frontend')['ready']
    bad_home=root/'home/profiles/backend_data';drift=configuration()
    drift['auxiliary']['compression']={'base_url':'https://outside.invalid','model':'unqualified/model'}
    write_json(bad_home/'config.yaml',drift)
    assert not admission(runtime.project,root,'backend_data')['ready']
    assert admission(runtime.project,root,'frontend')['ready']
    restarted=Runtime(root,upstream)
    assert restarted.status()['profiles']['profiles']['backend_data']['ready'] is False
    kb,kbc,dispatch=native();started=[]
    from tools.process_registry import RestartSafeScopeUnavailable
    def spawn(task,workspace,*,board=None):
        state=admission(runtime.project,root,task.assignee)
        if not state['ready']:raise RestartSafeScopeUnavailable('profile deferred: '+','.join(state['errors']))
        started.append(task.id)
        return None  # Explicit stub: no model or worker process.
    with kbc.connect_closing() as conn:
        tasks=[]
        try:
            for actor in ('backend_data','frontend'):
                work=root/'work'/actor;work.mkdir(mode=0o700,parents=True)
                tasks.append(kb.create_task(conn,title='Profile admission fixture only: '+actor,
                    body=json.dumps(dict(version=1,kind='tests',release='profile-fixture',inputs={})),
                    assignee=actor,workspace_kind='dir',workspace_path=str(work),completion_contract='local-only',max_retries=2))
            result=dispatch.dispatch_once(conn,spawn_fn=spawn,max_spawn=2,max_in_progress=2,max_in_progress_per_profile=1)
            assert started==[tasks[1]] and [entry[0] for entry in result.spawned]==[tasks[1]]
            refused=kb.get_task(conn,tasks[0]);latest=kb.latest_run(conn,tasks[0])
            assert refused.status=='ready' and refused.consecutive_failures==0 and latest.outcome=='spawn_failed'
            assert 'ProfileConfigDrift' in refused.last_failure_error
        finally:
            # Only this fixture's callback can own these claims, and it never
            # creates a process. Preserve anything with an unexpected PID.
            for task in tasks:
                current=kb.get_task(conn,task)
                if current.status=='running':
                    assert current.worker_pid is None
                    kb.reclaim_task(conn,task,reason='qualification callback ended; no worker was started')
        assert conn.execute('SELECT COUNT(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]==0
    write_json(bad_home/'config.yaml',configuration())
    after=report(runtime.project,root);assert all(state['ready'] for state in after['profiles'].values())
    assert runtime.control.read()['paused'] and not json.loads((root/'provider-policy.json').read_bytes())['enabled']
    write_json(root/'profiles-after.json',after)
    receipt=dict(prepared=prepared['prepared'],managed_profiles=len(after['profiles']),profile_contract=contract(),
        effective_native_config_verified=True,native_last_known_good_refused=True,
        bad_profile_deferred_good_profile_admitted=True,native_functional_failure_budget_unchanged=True,
        drift_survived_restart=True,restored_profile_admission=True,operational_pause_preserved=True,
        provider_disabled=True,fairness_worker_spawn_stub=True,native_open_runs=0,
        model_calls=0,github_mutations=0,docker_jobs=0,delivery_approval=False,complete_installer=False)
    write_json(root/'receipt.json',receipt);print(json.dumps(receipt,indent=2));return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);parser.add_argument('--browser-image',required=True)
    args=parser.parse_args();qualify(args.root,args.upstream,args.image,args.browser_image)
