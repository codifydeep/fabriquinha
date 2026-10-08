"""One metered typed technical-decision canary; no product task or tool execution."""
import argparse
import json
import subprocess
import uuid
from model_policy_smoke import command as smoke_command
from model_policy import MODEL,PLACEHOLDER_KEY

PROBE='''import json,hashlib,urllib.request
execution=__EXECUTION__
body={"model":__MODEL__,"stream":False,"max_tokens":512,"provider":{"require_parameters":True},
 "messages":[{"role":"user","content":"This is a synthetic transport qualification, not a product incident. Submit action escalate_cto, reason Transport qualification only; no product action authorized., optional_files []. Do not execute tools or change files.\\nDELIVERY_STRUCTURED_DECISION_V1:technical\\nDELIVERY_TYPED_DECISION_V1\\n"}]}
request=urllib.request.Request("http://model-proxy:8080/executions/"+execution+"/api/v1/chat/completions",
 data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":__AUTH__})
with urllib.request.urlopen(request,timeout=110) as response:raw=response.read()
record=json.loads(raw)
assert record["model"]==__MODEL__ and len(record["choices"])==1
choice=record["choices"][0]
assert choice["finish_reason"]=="stop" and not choice["message"].get("tool_calls")
decision=json.loads(choice["message"]["content"])
assert set(decision)=={"action","reason","optional_files"}
assert decision["action"]=="escalate_cto" and decision["optional_files"]==[]
assert isinstance(decision["reason"],str) and 1<=len(decision["reason"])<=1200
print(json.dumps({"execution_id":execution,"response_sha256":hashlib.sha256(raw).hexdigest()}))
'''


def command(namespace,image,execution):
    if str(uuid.UUID(execution))!=execution:raise ValueError('canonical synthetic execution required')
    cmd=smoke_command(namespace,image)
    cmd[-1]=PROBE.replace('__MODEL__',repr(MODEL)).replace('__AUTH__',repr('Bearer '+PLACEHOLDER_KEY)).replace('__EXECUTION__',repr(execution))
    return cmd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args();execution=str(uuid.uuid4())
    payload=json.loads(subprocess.check_output(command(args.namespace,args.image,execution),text=True,timeout=240))
    name=args.namespace+'-execution-broker-1'
    labels=json.loads(subprocess.check_output(['docker','inspect','--format','{{json .Config.Labels}}',name],text=True,timeout=10))
    if labels.get('com.docker.compose.project')!=args.namespace or labels.get('com.docker.compose.service')!='execution-broker':
        raise ValueError('owned controller qualification target required')
    script='import broker as b,provider_diagnosis_recovery as r,json,sys;v=r.register(b,json.loads(sys.argv[1]));print(json.dumps({"execution_id":v["execution_id"],"proxy_image":v["proxy_image"],"operation":v["operation"],"worker_tool_executed":v["worker_tool_executed"],"delivery_approval":v["delivery_approval"]}))'
    subprocess.run(['docker','exec','-w','/',name,'python','-c',script,json.dumps(payload)],check=True,timeout=40)


if __name__=='__main__':main()
