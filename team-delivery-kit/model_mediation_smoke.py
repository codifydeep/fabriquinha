"""Synthetic nonauthorizing CTO mediation transport probe, one metered call."""
import argparse
import json
import subprocess
import uuid
from model_policy_smoke import command as smoke_command
from model_policy import MODEL,PLACEHOLDER_KEY
from mediation_transport_fixture import body as fixture_body

PROBE='''import json,urllib.request,urllib.error
execution=__EXECUTION__
body=json.loads(__BODY__)
body.update(model=__MODEL__,stream=False,max_tokens=1024,provider={"require_parameters":True})
request=urllib.request.Request("http://model-proxy:8080/executions/"+execution+"/api/v1/chat/completions",
 data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":__AUTH__})
result={"execution_id":execution,"scope":"synthetic_mediation_transport_only",
 "actual_artifact_read":False,"delivery_approval":False,"worker_tool_executed":False}
try:
 with urllib.request.urlopen(request,timeout=110) as response:record=json.load(response)
except urllib.error.HTTPError as error:
 result.update(status=error.code,transport_passed=False)
else:
 choice=record["choices"][0];decision=json.loads(choice["message"]["content"]);findings=decision.get("findings",[])
 result.update(status=200,transport_passed=(record.get("model")==__MODEL__ and
  choice.get("finish_reason")=="stop" and not choice["message"].get("tool_calls") and
  decision.get("action")=="request_review_reconsideration" and decision.get("optional_files")==[] and
  len(findings)==1 and findings[0].get("kind")=="review_disagreement" and
  findings[0].get("tree")=="candidate" and findings[0].get("path")=="tests/test_fixture.py" and
  findings[0].get("test")=="Cases.test_actual" and findings[0].get("line")==3 and
  findings[0].get("quote")=="self.assertTrue(True)"))
print(json.dumps(result))
'''


def command(namespace,image,execution):
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical synthetic execution required')
    cmd=smoke_command(namespace,image)
    cmd[-1]=PROBE.replace('__MODEL__',repr(MODEL)).replace('__AUTH__',repr('Bearer '+PLACEHOLDER_KEY)).replace('__EXECUTION__',repr(execution)).replace('__BODY__',repr(json.dumps(fixture_body())))
    return cmd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args()
    result=json.loads(subprocess.check_output(command(args.namespace,args.image,str(uuid.uuid4())),text=True,timeout=240))
    print(json.dumps(result))
    if not result['transport_passed']:raise SystemExit(1)


if __name__=='__main__':main()
