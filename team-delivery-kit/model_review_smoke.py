"""Synthetic immutable-review transport probe; never a product review receipt."""
import argparse
import json
import subprocess
import uuid
from model_policy_smoke import command as smoke_command
from model_policy import MODEL, PLACEHOLDER_KEY

PROBE = '''import json,urllib.request,urllib.error
execution=__EXECUTION__
sha="a"*64
path="/evidence/candidate/tests/test_fixture.py"
instruction=("Synthetic protocol fixture only: no file was actually read, no product review is authorized. "
 "Reject this constant-only fixture with one missing_coverage finding at line 3, "
 "test Cases.test_actual, quote self.assertTrue(True).\\n"
 "DELIVERY_STRUCTURED_DECISION_V1:test_review:"+sha+"\\nDELIVERY_TYPED_REVIEW_V1:"+sha+
 "\\nDELIVERY_TEST_FINDINGS_V1\\nDELIVERY_OBSERVED_FINDINGS_V1\\nDELIVERY_REVIEW_READ_PATH:"+path+"\\n")
body={"model":__MODEL__,"stream":False,"max_tokens":1024,"provider":{"require_parameters":True},
 "messages":[{"role":"user","content":instruction},
 {"role":"assistant","content":None,"tool_calls":[{"id":"synthetic-read","type":"function",
 "function":{"name":"read_file","arguments":json.dumps({"path":path,"offset":1,"limit":100})}}]},
 {"role":"tool","tool_call_id":"synthetic-read","content":json.dumps({"total_lines":3,
 "content":"1|class Cases:\\n2|    def test_actual(self):\\n3|        self.assertTrue(True)"})}]}
request=urllib.request.Request("http://model-proxy:8080/executions/"+execution+"/api/v1/chat/completions",
 data=json.dumps(body).encode(),headers={"Content-Type":"application/json","Authorization":__AUTH__})
result={"execution_id":execution,"scope":"synthetic_review_transport_only",
 "actual_artifact_read":False,"delivery_approval":False,"worker_tool_executed":False}
try:
 with urllib.request.urlopen(request,timeout=110) as response:record=json.load(response)
except urllib.error.HTTPError as error:
 result.update(status=error.code,transport_passed=False)
else:
 choice=record["choices"][0];decision=json.loads(choice["message"]["content"])
 finding=decision.get("findings",[])
 result.update(status=200,transport_passed=(record.get("model")==__MODEL__ and
  choice.get("finish_reason")=="stop" and not choice["message"].get("tool_calls") and
  decision.get("action")=="reject_test_revision" and decision.get("manifest_sha256")==sha and
  decision.get("optional_files")==[] and len(finding)==1 and
  finding[0].get("line")==3 and finding[0].get("quote")=="self.assertTrue(True)"))
print(json.dumps(result))
'''


def command(namespace, image, execution):
    if str(uuid.UUID(execution)) != execution:
        raise ValueError('canonical synthetic execution required')
    cmd = smoke_command(namespace, image)
    cmd[-1] = PROBE.replace('__MODEL__', repr(MODEL)).replace('__AUTH__', repr('Bearer '+PLACEHOLDER_KEY)).replace('__EXECUTION__', repr(execution))
    return cmd


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--namespace', required=True)
    parser.add_argument('--image', required=True)
    args = parser.parse_args()
    result = json.loads(subprocess.check_output(command(args.namespace, args.image, str(uuid.uuid4())), text=True, timeout=240))
    print(json.dumps(result))
    if not result['transport_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
