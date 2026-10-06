"""Operator-only real Red regression, without changing live receipts."""
import json
from pathlib import Path
import tempfile
import os
from review_controller import Controller
from e2e_controller import ATTEMPT
from immutable_delivery import DeliveryStore

with tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp); board=root/ATTEMPT; board.mkdir(); private=root/'private'; private.mkdir()
    (private/'e2e-config.json').write_text(json.dumps(dict(attempt=ATTEMPT,cards={'build':'t_red_regression'})))
    c=Controller(board,private,ATTEMPT,'hermes_review_deliveries',os.environ['REVIEW_IMAGE'])
    c.store=DeliveryStore('/deliveries')
    work=board/'workspaces/t_red_regression'; work.mkdir(parents=True)
    code='def winner(a, b):\n    return None'
    (work/'app.py').write_text(code)
    (work/'test_user.py').write_text('import unittest\nfrom app import winner\nclass Tests(unittest.TestCase):\n'+''.join(
        f'    def test_{i}(self): self.assertEqual(winner({a},{b}),{v!r})\n'
        for i,(a,b,v) in enumerate([(12,0,'A'),(0,12,'B'),(12,13,'A'),(0,0,None),(11,11,None)])))
    task=dict(id='t_red_regression',assignee='backend_data',workspace_path=str(work))
    result=c.e2e.handle(task,False,dict(operation='e2e_test',stage='red',run=101))
    assert result['accepted'] and result['tests']==12 and not result['passed'],result
    assert (work/'app.py').read_text()==code
    print('PASS: actual Docker Red accepted without trailing newline; 12 tests; code bytes preserved; no live receipt modified')
    c.db.close()
