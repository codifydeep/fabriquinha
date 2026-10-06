"""Bounded real Hermes tool execution; disposable container only, no live data.

This component evaluation is NOT the end-to-end team rehearsal.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

root=Path('/tmp/hermes-tdd-eval')
root.mkdir(exist_ok=False)
home=root/'profile'
home.mkdir()
work=root/'work'
work.mkdir()
(home/'config.yaml').write_text('''model:
  default: qwen3.5:9b
  provider: ollama-local
providers:
  ollama-local:
    api: http://host.docker.internal:11434/v1
    discover_models: false
    models: [qwen3.5:9b]
agent:
  reasoning_effort: medium
  max_turns: 12
terminal:
  backend: local
  timeout: 30
auxiliary:
  title_generation: {enabled: false}
''')
test=work/'test_score.py'
test.write_text('''import unittest
from score import winner
class ExistingRegression(unittest.TestCase):
    def test_no_winner(self):
        self.assertIsNone(winner(0,0))
''')
(work/'score.py').write_text('def winner(a,b):\n    return None\n')
baseline=hashlib.sha256(test.read_bytes()).hexdigest()
prompt='''Work only in /tmp/hermes-tdd-eval/work. Use real terminal/file tools.
Implement winner(a,b): return "A" if a>=12, else "B" if b>=12, else None.
Preserve test_score.py byte-for-byte. First create test_new_score.py covering
A wins, B wins and neither wins, run python -m unittest discover and save the
actual failing output to red.log. Only after observing failure modify score.py.
Run the complete unittest suite again and save actual output to green.log.
Do not fake logs. Do not install packages, access network, delegate or ask humans.
If a tool denies permission, stop and report the denial. Never switch tools,
unset environment variables or alter permissions to bypass it.
Finish with a brief report of commands and results. You have 12 tool iterations.
'''
env=dict(os.environ,HERMES_HOME=str(home),TERMINAL_CWD=str(work),
    HERMES_WRITE_SAFE_ROOT=str(work),PYTHONUNBUFFERED='1')
started=time.monotonic()
timed_out=False
with (root/'agent.log').open('w') as log:
    try:
        result=subprocess.run(['/opt/hermes/.venv/bin/hermes','chat','--oneshot','--ignore-rules',
            '--provider','ollama-local','-m','qwen3.5:9b','-t','terminal,file',
            '--max-turns','12','--run-budget','300','--in',str(work),'-q',prompt],
            env=env,cwd=work,stdout=log,stderr=subprocess.STDOUT,timeout=330)
        code=result.returncode
    except subprocess.TimeoutExpired:
        timed_out=True
        code=None
checks=subprocess.run(['/opt/hermes/.venv/bin/python','-m','unittest','discover','-v'],
    cwd=work,capture_output=True,text=True,timeout=30)
oracle=subprocess.run(['/opt/hermes/.venv/bin/python','-c',
    'from score import winner; assert [winner(12,0),winner(0,12),winner(0,0)]==["A","B",None]'],
    cwd=work,capture_output=True,text=True,timeout=30)
report=dict(component_only=True,model='qwen3.5:9b',seconds=round(time.monotonic()-started,2),
    agent_exit_code=code,timed_out=timed_out,existing_test_unchanged=hashlib.sha256(test.read_bytes()).hexdigest()==baseline,
    suite_exit_code=checks.returncode,oracle_exit_code=oracle.returncode,
    new_test_exists=(work/'test_new_score.py').exists(),red_log_exists=(work/'red.log').exists(),
    green_log_exists=(work/'green.log').exists(),suite_output=checks.stdout+checks.stderr)
report['permission_denial_observed']='Write denied:' in (root/'agent.log').read_text()
red=(work/'red.log').read_text() if (work/'red.log').exists() else ''
green=(work/'green.log').read_text() if (work/'green.log').exists() else ''
report['red_contains_failure']='FAILED (' in red
report['green_contains_success']='\nOK' in green
report['component_pass']=all([code==0,not timed_out,report['existing_test_unchanged'],
    checks.returncode==0,oracle.returncode==0,report['new_test_exists'],
    report['red_contains_failure'],report['green_contains_success'],
    not report['permission_denial_observed']])
(root/'result.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2),flush=True)
