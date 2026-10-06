"""Operator acceptance: real probe and one injected pre-start timeout, no approval."""
import json
import os
import subprocess
from unittest.mock import patch
from review_controller import Controller
from e2e_controller import CONTAINER, FIXTURE
import http_probe_runner as probes
c=Controller(os.environ['REVIEW_BOARD'],'/deliveries',os.environ['HERMES_EXECUTION_ATTEMPT'],'hermes_review_deliveries',os.environ['REVIEW_IMAGE'])
normal=c.e2e.http()
print(json.dumps(dict(test='normal',receipt=normal)),flush=True)
real=probes.bounded_run
injected=False
def once(args,timeout):
    global injected
    if args[:2]==['docker','start'] and not injected:
        injected=True
        raise subprocess.TimeoutExpired(args,timeout)
    return real(args,timeout=timeout)
with patch.object(probes,'bounded_run',side_effect=once):
    recovered=probes.run_probe(c.image,CONTAINER,normal['commit'],False,(FIXTURE/'http_probe.py').read_text(),'truco-online-rehearsal-test',lambda state:c.e2e.put('operator-probe-test:'+state['name'],state))
assert injected and recovered['passed'] and len(recovered['lifecycle'])==2
assert all(x['cleanup_ok'] for x in recovered['lifecycle'])
print(json.dumps(dict(test='injected_start_timeout',receipt=recovered)),flush=True)
