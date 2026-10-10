"""One metered synthetic qualification; no product mounts or actual artifact reads."""
import argparse
import json
import subprocess
import uuid
from model_policy_smoke import command as smoke_command
from model_policy import MODEL,PLACEHOLDER_KEY
from optional_files_transport_fixture import body as fixture_body

PROBE='''import json,urllib.request,urllib.error
execution=__EXECUTION__
body=json.loads(__BODY__)
body.update(model=__MODEL__,stream=False,max_tokens=1024,provider={"require_parameters":True})
request=urllib.request.Request("http://model-proxy:8080/executions/"+execution+"/api/v1/chat/completions",
 data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":__AUTH__})
result={"execution_id":execution,"scope":"synthetic_optional_files_transport_only",
 "actual_artifact_read":False,"delivery_approval":False,"worker_tool_executed":False}
try:
 with urllib.request.urlopen(request,timeout=110) as response:record=json.load(response)
except urllib.error.HTTPError as error:result.update(status=error.code,transport_passed=False)
else:
 choice=record["choices"][0];decision=json.loads(choice["message"]["content"])
 result.update(status=200,transport_passed=(record.get("model")==__MODEL__ and
  choice.get("finish_reason")=="stop" and not choice["message"].get("tool_calls") and
  set(decision)=={"action","reason","optional_files"} and decision.get("action")=="escalate_cto" and
  decision.get("optional_files")==[] and isinstance(decision.get("reason"),str) and 1<=len(decision["reason"])<=1200))
print(json.dumps(result))
'''


def command(namespace,image,execution):
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical synthetic execution required')
    cmd=smoke_command(namespace,image)
    cmd[-1]=PROBE.replace('__MODEL__',repr(MODEL)).replace('__AUTH__',repr('Bearer '+PLACEHOLDER_KEY)).replace(
        '__EXECUTION__',repr(execution)).replace('__BODY__',repr(json.dumps(fixture_body())))
    return cmd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args();result=json.loads(subprocess.check_output(command(args.namespace,args.image,str(uuid.uuid4())),
        text=True,timeout=240));print(json.dumps(result))
    if not result['transport_passed']:raise SystemExit(1)


if __name__=='__main__':main()
