"""Two metered transport-only probes; no tool execution or product writes."""
import argparse
import subprocess
from model_policy_smoke import command as smoke_command
from model_policy import MODEL,PLACEHOLDER_KEY

PROBE='''import json,urllib.request,urllib.error
model=__MODEL__
results=[]
for strict in (True,False):
 function={"name":"qualification_source_proposal","description":"Return a proposal only; never execute.",
  "parameters":{"type":"object","properties":{"path":{"type":"string","enum":["/qualification/test.py"]},
   "lines":{"type":"array","minItems":1,"maxItems":128,"items":{"type":"string","maxLength":512}}},
   "required":["path","lines"],"additionalProperties":False}}
 if strict:function["strict"]=True
 body={"model":model,"stream":False,"max_tokens":256,"provider":{"require_parameters":True},
  "messages":[{"role":"user","content":"Propose exactly these three Python lines: import unittest; class T(unittest.TestCase):; one indented def test_value(self): self.assertEqual(1, 2). Do not execute."}],
  "tools":[{"type":"function","function":function}],"tool_choice":{"type":"function","function":{"name":"qualification_source_proposal"}}}
 request=urllib.request.Request("http://model-proxy:8080/api/v1/chat/completions",data=json.dumps(body).encode(),
  headers={"Content-Type":"application/json","Authorization":__AUTH__})
 try:
  with urllib.request.urlopen(request,timeout=110) as response:record=json.load(response)
  calls=record["choices"][0]["message"].get("tool_calls",[])
  assert len(calls)==1 and calls[0]["function"]["name"]=="qualification_source_proposal"
  args=json.loads(calls[0]["function"]["arguments"])
  assert set(args)=={"path","lines"} and args["path"]=="/qualification/test.py"
  assert isinstance(args["lines"],list) and 1<=len(args["lines"])<=128
  assert all(isinstance(s,str) and len(s)<=512 and "\\n" not in s for s in args["lines"])
  results.append({"strict_hint":strict,"status":200,"arguments_valid":True})
 except urllib.error.HTTPError as error:results.append({"strict_hint":strict,"status":error.code,"arguments_valid":False})
print(json.dumps({"model":model,"probes":results,"scope":"transport_only","tool_executed":False,
 "files_written":False,"delivery_approved":False}))
'''


def command(namespace,image):
    cmd=smoke_command(namespace,image)
    cmd[-1]=PROBE.replace('__MODEL__',repr(MODEL)).replace('__AUTH__',repr('Bearer '+PLACEHOLDER_KEY))
    return cmd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args();subprocess.run(command(args.namespace,args.image),check=True,timeout=240)


if __name__=='__main__':main()
