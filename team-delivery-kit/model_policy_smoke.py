"""Two bounded real model calls through the isolated, metered proxy only."""
import argparse
import json
import re
import subprocess
from docker_grouping import args as grouped_args
from model_policy import MODEL, PLACEHOLDER_KEY

PROBE = '''import json,urllib.request
model=__MODEL__
def call(extra):
 body=dict(model=model,messages=[{"role":"user","content":"Return READY as requested. No other work."}],
           stream=False,max_tokens=128)
 body.update(extra)
 request=urllib.request.Request("http://model-proxy:8080/api/v1/chat/completions",
   data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":__AUTH__})
 with urllib.request.urlopen(request,timeout=110) as response:result=json.load(response)
 assert result.get("model")==model,"unexpected returned model"
 return result["choices"][0]["message"]
text=call({})
assert text.get("content","").strip()=="READY","text response not exact"
tool={"type":"function","function":{"name":"qualification_result",
 "description":"Return the qualification status.","parameters":{"type":"object",
 "properties":{"status":{"type":"string","enum":["READY"]}},"required":["status"],"additionalProperties":False}}}
message=call({"tools":[tool],"tool_choice":{"type":"function","function":{"name":"qualification_result"}}})
calls=message.get("tool_calls",[])
assert len(calls)==1 and calls[0]["function"]["name"]=="qualification_result","tool calling failed"
assert json.loads(calls[0]["function"]["arguments"])=={"status":"READY"},"structured arguments failed"
print(json.dumps({"model":model,"text":"passed","forced_tool":"passed","provider_key_in_worker":False,
 "scope":"transport_only_not_delivery"}))
'''


def command(namespace, image):
    if not re.fullmatch(r'delivery-kit-[a-z0-9-]{1,48}',namespace):raise ValueError('exact namespace required')
    if not re.fullmatch(r'sha256:[a-f0-9]{64}',image):raise ValueError('immutable worker image required')
    probe=PROBE.replace('__MODEL__',repr(MODEL)).replace('__AUTH__',repr('Bearer '+PLACEHOLDER_KEY))
    return ['docker','run','--rm','--network',namespace+'_model',
            *grouped_args('model-policy-smoke',namespace=namespace),
            '--read-only','--cap-drop','ALL','--security-opt','no-new-privileges',
            '--user','10000:10000','--pids-limit','64','--memory','128m',
            '--entrypoint','python',image,'-c',probe]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True)
    parser.add_argument('--image',required=True);args=parser.parse_args()
    subprocess.run(command(args.namespace,args.image),check=True,timeout=240)


if __name__=='__main__':main()
