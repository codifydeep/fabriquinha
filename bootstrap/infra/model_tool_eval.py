"""Small isolated Ollama tool-protocol evaluation; never executes model calls.

This is a component benchmark, NOT a Hermes end-to-end acceptance test.
No downloads, model switching, external services or real Kanban mutations.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.request

CASES = [
    ('handoff', 'The artifact commit:abc exists. Send card t_demo from backend_data to techlead for independent review. Call handoff with task t_demo, recipient techlead, artifact commit:abc.',
     'handoff', {'task':'t_demo','recipient':'techlead','artifact':'commit:abc'}),
    ('test_failure', 'Tests exited 1. Do not report success or remove tests. Record a blocked card t_demo with owner techlead. Call block with task t_demo and owner techlead.',
     'block', {'task':'t_demo','owner':'techlead'}),
    ('architecture', 'A technical architecture choice is unresolved. Route card t_demo to the CTO, not the CEO. Call escalate with task t_demo and owner cto.',
     'escalate', {'task':'t_demo','owner':'cto'}),
]


def evaluate(url, model, output):
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for name, prompt, function, expected in CASES:
        parameters = {'type':'object','properties':{key:{'type':'string'} for key in expected},
                      'required':list(expected), 'additionalProperties':False}
        payload = {'model':model,'stream':False,'think':False,
            'messages':[{'role':'system','content':'You are a local software team agent. Use exactly one provided tool. Never simulate tool calls in prose.'},
                        {'role':'user','content':prompt}],
            'tools':[{'type':'function','function':{'name':function,'description':'Record the requested coordination action in an isolated fixture.', 'parameters':parameters}}],
            'options':{'temperature':0,'num_predict':256,'num_ctx':4096}}
        started = time.monotonic()
        result = {'case':name,'model':model,'success':False,'interventions':0}
        try:
            request = urllib.request.Request(url.rstrip('/') + '/api/chat', data=json.dumps(payload).encode(), headers={'Content-Type':'application/json'})
            with urllib.request.urlopen(request, timeout=180) as response:
                data = json.load(response)
            calls = data.get('message',{}).get('tool_calls',[])
            result['success'] = len(calls) == 1 and calls[0].get('function',{}).get('name') == function and calls[0]['function'].get('arguments') == expected
            result['tool_calls'] = calls
            result['prose_without_tool'] = bool(data.get('message',{}).get('content')) and not calls
            result['eval_count'] = data.get('eval_count')
            result['eval_duration_ns'] = data.get('eval_duration')
        except Exception as exc:
            result['error'] = type(exc).__name__
        result['seconds'] = round(time.monotonic() - started, 3)
        results.append(result)
        (output / 'tool-protocol.json').write_text(json.dumps({'model':model,'isolated':True,'not_end_to_end':True,'results':results},indent=2))
        print(json.dumps(result), flush=True)
    return all(row['success'] for row in results)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url',default='http://host.docker.internal:11434')
    parser.add_argument('--model',default='qwen3.5:9b')
    parser.add_argument('--output',type=Path,required=True)
    args = parser.parse_args()
    raise SystemExit(0 if evaluate(args.url,args.model,args.output) else 1)
