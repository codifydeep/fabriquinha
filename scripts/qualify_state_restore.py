"""Offline recovery rehearsal on synthetic state; never starts restored workers.

Not a production backup command: the fixture has no credentials, external
routes, active leases, or running gateway. Keep this boundary explicit.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import subprocess
import signal
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fabriquinha.effects import write_json
from fabriquinha.runtime import Runtime, Owner
from fabriquinha.kanban_lane import native
from fabriquinha.provider import Ledger,Held


def manifest(root):
    result={}
    for path in sorted(root.rglob('*')):
        if path.is_symlink():raise ValueError('symlink is not a qualified backup entry')
        if path.is_file():result[str(path.relative_to(root))]=hashlib.sha256(path.read_bytes()).hexdigest()
        elif not path.is_dir():raise ValueError('special file is not a qualified backup entry')
    return result


def qualify(root,upstream,*,source_cycle=None):
    root=Path(root).resolve()
    if root.exists():raise ValueError('fresh private root required')
    if root.is_relative_to(ROOT):
        if subprocess.run(['git','-C',str(ROOT),'check-ignore','--quiet',str(root)]).returncode:
            raise ValueError('private ignored destination required')
    root.mkdir(parents=True,mode=0o700)
    source=root/'original';source.mkdir(mode=0o700)
    write_json(source/'project.json',dict(version=1,namespace='delivery-kit-restore-fixture',
        repository='https://github.com/example/product',branch='release/restore-fixture',
        validation_image='sha256:'+'a'*64,tests_dir='tests',reviewers={'backend':'lead','lead':'cto'},qualification=True))
    runtime=Runtime(source,upstream);pause=runtime.control.pause()
    kb,kbc,_=native()
    with kbc.connect_closing() as conn:
        card=kb.create_task(conn,title='Offline restoration fixture',assignee='backend',
            body='Synthetic pending work; never dispatch this fixture.',initial_status='blocked',completion_contract='local-only')
        conn.commit()
    workspace=root/'artifact';workspace.mkdir();(workspace/'evidence.txt').write_text('Preserved synthetic evidence\n')
    snapshot=runtime.store.capture(workspace)
    receipt=runtime.store.record('restore-fixture',{'task':card},{'snapshot':snapshot})
    notice=runtime.outbox.enqueue('restore-fixture',{'text':'Pending synthetic notification'})
    # Synthetic meter only. The real provider volume is never copied/reset here.
    meter=source/'fixture-meter';meter.mkdir(mode=0o700)
    write_json(meter/'calls.json',{'calls':7})
    write_json(meter/'relay-hold.json',{'category':'transport_unknown','call_number':7})
    ledger=Ledger(meter,10);meter_before=ledger.state()

    # Freeze under the same exclusive owner used by the service. No worker or
    # channel is ever started in this fixture; production needs those drained too.
    with Owner(source):
        with sqlite3.connect(source/'home/kanban.db') as conn:
            assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
            assert conn.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]==0
            conn.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        before=manifest(source)
        backup=root/'backup';shutil.copytree(source,backup)
        assert manifest(source)==before==manifest(backup)
    restored=root/'restored';shutil.copytree(backup,restored)
    assert manifest(restored)==before
    recovered=Runtime(restored,upstream)
    assert recovered.control.read()['paused'] and recovered.control.read()['episode']==pause['episode']
    assert recovered.store.receipt(receipt)['payload']['snapshot']==snapshot
    assert (recovered.store.tree(snapshot)/'evidence.txt').read_text()=='Preserved synthetic evidence\n'
    records=recovered.outbox.records()
    assert len(records)==1 and records[0]['key']==notice and records[0]['state']=='queued' and records[0]['attempts']==0
    kb,kbc,_=native()
    with kbc.connect_closing() as conn:
        assert kb.get_task(conn,card).status=='blocked'
        assert conn.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert conn.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]==0
    recovered_meter=Ledger(restored/'fixture-meter',10)
    assert recovered_meter.state()==meter_before
    try:recovered_meter.reserve()
    except Held as error:assert error.code=='transport_unknown'
    else:raise AssertionError('restored uncertain send allowed a new reservation')
    assert recovered_meter.state()==meter_before
    for target in (source,restored):
        assert not (target/'route.json').exists() and not (target/'notifications.json').exists()
    # Start the real restored dispatcher while fenced, then restart it. The
    # fixture has no transport or model route, and must never acquire a worker.
    env={key:os.environ[key] for key in ('PATH','HOME','TMPDIR','LANG') if key in os.environ}
    env.update(PYTHONPATH=str(ROOT/'src'),PYTHONDONTWRITEBYTECODE='1',PYTHONNOUSERSITE='1')
    args=[sys.executable,'-B','-m','fabriquinha.runtime','serve','--root',str(restored),
          '--upstream',str(Path(upstream).resolve()),'--interval','0.1']
    cycles=[None,None]
    if source_cycle:
        from fabriquinha.source import verify
        if len(source_cycle)!=2:raise ValueError('explicit before/after source pair required')
        for path,expected in source_cycle:verify(Path(path),expected)
        cycles=[source_cycle[0],source_cycle[1],source_cycle[0]]
    pids=[]
    for index,source_binding in enumerate(cycles):
        if source_binding:
            from run_hermes_runtime import command
            args,env=command(Path(source_binding[0]),source_binding[1],Path(sys.executable),restored,
                Path(upstream),'serve',interval=.1)

        with (root/('restored-service-'+str(index)+'.log')).open('xb') as log:
            service=subprocess.Popen(args,env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT)
        try:
            deadline=time.monotonic()+45
            while True:
                if service.poll() is not None:raise RuntimeError('restored service exited; inspect private log')
                status_path=restored/'status.json'
                status=json.loads(status_path.read_bytes()) if status_path.exists() else {}
                if status.get('dispatcher_pid')==service.pid and status.get('dispatcher_state')=='running':break
                if time.monotonic()>deadline:raise TimeoutError('restored dispatcher readiness not observed')
                time.sleep(.1)
            assert status['board']['control']['paused'] and status['board']['control']['episode']==pause['episode']
            assert status['board']['control']['drained']
            duplicate=subprocess.run(args,env=env,capture_output=True,timeout=15)
            assert duplicate.returncode!=0
            pids.append(service.pid)
        finally:
            if service.poll() is None:service.send_signal(signal.SIGTERM)
            service.wait(timeout=15)
        assert service.returncode==0
    with sqlite3.connect(restored/'home/kanban.db') as conn:
        assert conn.execute('SELECT COUNT(*) FROM task_runs').fetchone()[0]==0
    restored_notice=next(x for x in recovered.outbox.records() if x['key']==notice)
    assert restored_notice['state']=='queued' and restored_notice['attempts']==0
    assert len(set(pids))==len(cycles)
    assert recovered_meter.state()==meter_before
    assert recovered.control.read()['episode']==pause['episode'] and recovered.control.read()['paused']
    recovered.store.tree(snapshot);recovered.store.receipt(receipt)

    result=dict(sqlite_integrity=True,blocked_card_preserved=True,snapshot_verified=True,receipt_verified=True,
        queued_notification_preserved=True,pause_episode_preserved=True,files_verified=len(before),
        model_calls=0,workers_started=0,external_effects=0,production_restore_qualified=False,
        provider_counter_restore_qualified=False,synthetic_offline_restore=True,restored_dispatcher_restarted_paused=True,duplicate_owner_refused=True,
        synthetic_counter_preserved=True,uncertain_send_hold_preserved=True,reservation_while_held_refused=True)
    if source_cycle:result.update(paused_source_upgrade_and_rollback=True,source_digests=[item[1] for item in cycles])
    write_json(root/'receipt.json',result)
    print(json.dumps(result,indent=2))
    return result

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--source-cycle',nargs=2,action='append',metavar=('PATH','DIGEST'))
    args=parser.parse_args()
    os.umask(0o077)
    qualify(args.root,args.upstream,source_cycle=args.source_cycle)
