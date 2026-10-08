"""One bounded paid inference through the model-only network, without provider credentials."""
import subprocess
from docker_grouping import args as docker_group_args

from evalctl import process_env
from model_policy import MODEL

PROBE = '''import json,urllib.request,urllib.error
try:
 urllib.request.urlopen('https://openrouter.ai',timeout=3)
 raise SystemExit('direct Internet unexpectedly reachable')
except (urllib.error.URLError,TimeoutError,OSError):
 pass
body={'model':__APPROVED_MODEL__,'messages':[{'role':'user','content':'Reply with only READY.'}],
      'max_tokens':16,'stream':False}
request=urllib.request.Request('http://model-proxy:8080/api/v1/chat/completions',
 data=json.dumps(body).encode(),headers={'Authorization':'Bearer offline-placeholder-not-a-credential',
 'Content-Type':'application/json'})
try:
 with urllib.request.urlopen(request,timeout=110) as response:
  result=json.load(response)
except urllib.error.HTTPError as error:
 raise SystemExit('model proxy HTTP '+str(error.code)) from None
choices=result.get('choices') or []
if not choices:
 raise SystemExit('no model choice returned')
print(json.dumps({'direct_internet':False,'model_response':True,
                  'reply_nonempty':bool((choices[0].get('message') or {}).get('content')),
                  'key_in_worker':False}))
'''
PROBE = PROBE.replace('__APPROVED_MODEL__', repr(MODEL))


def main():
    subprocess.run(['docker', 'run', '--rm', '--network', 'delivery-kit-eval_model',
                    *docker_group_args('model-smoke'),
                    '--read-only', '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges',
                    '--user', '10000:10000', '--pids-limit', '64', '--memory', '256m',
                    '--label', 'delivery-kit.owner=delivery-kit-eval-model-smoke',
                    '--entrypoint', 'python', 'delivery-kit-hermes-runtime:20260921.1',
                    '-c', PROBE], env=process_env(), check=True, timeout=120)


if __name__ == '__main__':
    main()
