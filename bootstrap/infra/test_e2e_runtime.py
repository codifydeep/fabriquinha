"""Operator-only acceptance inside the existing controller; no GitHub writes.

Uses a separate Compose project/port and an in-memory receipt database. These
fixture receipts are never accepted as the real E2E run's evidence.
"""
import json
import sqlite3
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
import e2e_controller as module
from immutable_delivery import DeliveryStore

assert Path('/var/run/docker.sock').exists(), 'run only in the authorized controller'
with tempfile.TemporaryDirectory() as tmp:
    board=Path(tmp)/module.ATTEMPT; board.mkdir()
    db=sqlite3.connect(':memory:'); db.row_factory=sqlite3.Row
    controller=SimpleNamespace(board=board,store=DeliveryStore('/deliveries'),attempt=module.ATTEMPT,
        image='estudo-hermes-saas:0.21.21',volume='hermes_review_deliveries',db=db)
    engine=module.E2E(controller)
    assert engine.enabled
    engine.config=dict(attempt=module.ATTEMPT,cards={'build':'t_e2e_acceptance'})
    task=dict(id='t_e2e_acceptance',assignee='backend_data')
    code='def winner(a, b):\n    return "A" if a >= 12 else "B" if b >= 12 else None\n'
    tests='import unittest\nfrom app import winner\nclass Tests(unittest.TestCase):\n'+''.join(f'    def test_{i}(self): self.assertEqual(winner({a},{b}),{v!r})\n' for i,(a,b,v) in enumerate([(12,0,'A'),(0,12,'B'),(12,13,'A'),(0,0,None),(11,11,None)]))
    revision=engine.capture(task,101,dict({'app.py':code,'test_user.py':tests}))
    result=engine.tests(task['id'],revision); assert result['passed'] and result['tests']==12,result
    print('PASS: actual isolated 12-test suite, readonly snapshot, no credentials/socket',flush=True)
    # Fake commit identifiers are fixture-only, never written to durable controller state.
    engine.put('base',dict(sha='1'*40))
    engine.put('published',dict(revision=revision,merge_sha='2'*40,merged=True,approval={'fixture_only':True}))
    project='truco-online-rehearsal-acceptance'; container=project+'-api'
    with patch.object(module,'PROJECT',project),patch.object(module,'CONTAINER',container),patch.object(module,'PORT',18762),patch.object(engine,'pull',return_value={}):
        try:
            result=engine.deploy()
            assert result['passed'] and result['first']['checks']==10 and result['final']['checks']==10 and result['rollback']['checks']==1
            print('PASS: actual Docker build, HTTP checks, rollback and restored candidate on acceptance-only port 18762',flush=True)
        finally:
            inspect=subprocess.run(['docker','inspect',container],capture_output=True,text=True)
            if inspect.returncode==0 and json.loads(inspect.stdout)[0]['Config']['Labels'].get('hermes.attempt')==module.ATTEMPT:
                subprocess.run(['docker','rm','-f',container],check=True)
            inspect=subprocess.run(['docker','network','inspect',project+'_default'],capture_output=True,text=True)
            if inspect.returncode==0 and json.loads(inspect.stdout)[0]['Labels'].get('hermes.attempt')==module.ATTEMPT:
                subprocess.run(['docker','network','rm',project+'_default'],check=True)
    db.close()
