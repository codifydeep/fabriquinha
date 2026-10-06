"""Read a disposable worker identity as its owner, without elevated capabilities."""
import subprocess
import sys
from e2e_fault import identity
p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)'],user=10000,group=10000,
    env={'HERMES_KANBAN_TASK':'t_identity_fixture','HERMES_KANBAN_RUN_ID':'123','HERMES_KANBAN_CLAIM_LOCK':'fixture'})
try:
    env,start=identity(p.pid)
    assert env[b'HERMES_KANBAN_TASK']==b't_identity_fixture' and start
    print('PASS real /proc identity read for uid 10000 without SYS_PTRACE')
finally:
    p.terminate(); p.wait(timeout=5)
