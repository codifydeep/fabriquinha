"""Native same-run duplicate denial, no model transport or Docker jobs."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from qualify_hermes_delivery import create_trial
from fabriquinha.effects import write_json
from fabriquinha.kanban_lane import native
from fabriquinha.runtime import Runtime, worker_alive


def qualify(root,upstream,image):
    task,_=create_trial(root,upstream,image,namespace='delivery-kit-hermes-identity')
    Runtime(root,upstream);kb,kbc,dispatch=native()
    owner=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'],stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
    number=None
    try:
        with kbc.connect_closing() as conn:
            claimed=kb.claim_task(conn,task);number=claimed.current_run_id
            assert dispatch.adopt_worker_pid(conn,task,number,owner.pid)
            row=conn.execute('SELECT * FROM task_runs WHERE id=?',(number,)).fetchone()
            assert worker_alive(row)
        log=root/'duplicate-worker.log'
        with os.fdopen(os.open(log,os.O_CREAT|os.O_WRONLY,0o600),'wb') as stream:
            result=subprocess.run([sys.executable,'-m','fabriquinha.runtime','worker','--root',str(root),
                '--upstream',str(upstream),'--task',task,'--run',str(number)],stdin=subprocess.DEVNULL,
                stdout=stream,stderr=subprocess.STDOUT,timeout=30)
        assert result.returncode!=0 and 'belongs to another worker process' in log.read_text()
        with kbc.connect_closing() as conn:
            current=kb.get_task(conn,task)
            assert current.status=='running' and current.current_run_id==number and current.worker_pid==owner.pid
            assert conn.execute("SELECT COUNT(*) FROM task_events WHERE task_id=? AND kind='blocked'",(task,)).fetchone()[0]==0
        assert owner.poll() is None
        assert not list((root/'private/effects').glob('*.json'))
        proof=dict(same_run_duplicate_refused=True,original_worker_and_claim_preserved=True,
            duplicate_did_not_block_owner=True,model_calls=0,docker_jobs=0,delivery_approval=False,migration=False)
    finally:
        if owner.poll() is None:owner.terminate()
        owner.wait(timeout=10)
        if number:
            with kbc.connect_closing() as conn:
                kb.block_task(conn,task,reason='Identity fixture ended; no product delivery approval',
                              kind='capability',expected_run_id=number)
    with kbc.connect_closing() as conn:
        assert conn.execute('SELECT COUNT(*) FROM task_runs WHERE ended_at IS NULL').fetchone()[0]==0
    write_json(root/'receipt.json',proof);print(json.dumps(proof,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',type=Path,required=True);parser.add_argument('--upstream',type=Path,required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    qualify(args.root.resolve(),args.upstream.resolve(),args.image)
