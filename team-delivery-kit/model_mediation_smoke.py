"""Synthetic nonauthorizing CTO mediation transport probe, one metered call."""
import argparse
import json
import subprocess
import uuid
from model_policy_smoke import command as smoke_command
from model_policy import MODEL,PLACEHOLDER_KEY

PROBE='''import json,urllib.request,urllib.error
execution=__EXECUTION__
path="/evidence/candidate/tests/test_fixture.py"
instruction=("SYNTHETIC transport fixture only. No product or real artifact is involved. "
 "Return request_review_reconsideration because the cited check exists. "
 "Use exactly one review_disagreement finding, tree candidate, path tests/test_fixture.py, "
 "test Cases.test_actual, line 3, quote self.assertTrue(True). optional_files=[]. "
 "Keep reason short. This cannot approve any delivery.\\n"
 "DELIVERY_STRUCTURED_DECISION_V1:technical\\nDELIVERY_TYPED_DECISION_V1\\n"
 "DELIVERY_TYPED_TEST_DIAGNOSIS_V1\\nDELIVERY_REVIEW_RECONSIDERATION_V1\\n"
 "DELIVERY_TEST_FINDINGS_V1\\nDELIVERY_OBSERVED_FINDINGS_V1\\nDELIVERY_REVIEW_READ_PATH:"+path+"\\n")
body={"model":__MODEL__,"stream":False,"max_tokens":1024,"provider":{"require_parameters":True},
 "messages":[{"role":"user","content":instruction},
 {"role":"assistant","content":None,"tool_calls":[{"id":"synthetic-read","type":"function",
 "function":{"name":"read_file","arguments":json.dumps({"path":path,"offset":1,"limit":100})}}]},
 {"role":"tool","tool_call_id":"synthetic-read","content":json.dumps({"total_lines":3,
 "content":"1|class Cases:\\n2|    def test_actual(self):\\n3|        self.assertTrue(True)"})}]}
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
    cmd[-1]=PROBE.replace('__MODEL__',repr(MODEL)).replace('__AUTH__',repr('Bearer '+PLACEHOLDER_KEY)).replace('__EXECUTION__',repr(execution))
    return cmd


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--namespace',required=True);parser.add_argument('--image',required=True)
    args=parser.parse_args()
    result=json.loads(subprocess.check_output(command(args.namespace,args.image,str(uuid.uuid4())),text=True,timeout=240))
    print(json.dumps(result))
    if not result['transport_passed']:raise SystemExit(1)


if __name__=='__main__':main()
