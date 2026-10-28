"""Bounded semantic evaluation through the existing metered local relay.

Programmed cases, no workspace tools, retries, card changes or delivery approval.
The expected answers are never sent to the model. Raw replies stay private.
"""
import argparse
import hashlib
import http.client
import json
from pathlib import Path
import sys
from urllib.parse import urlsplit
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fabriquinha.effects import write_json
from fabriquinha.quality import CONTROL_REVIEW_CONTRACT, REVIEW_FINDINGS_CONTRACT

REVIEW_CONTEXT=(
    'You are the technical reviewer of a software delivery team. Assess only the given evidence. '
    'Technical decisions belong to Tech Lead/CTO; CEO owns business scope. '
    'Never weaken tests, invent observations or approve a delivery. '
    + CONTROL_REVIEW_CONTRACT + ' ' + REVIEW_FINDINGS_CONTRACT + ' '
    'Call record_assessment exactly once. This is an isolated evaluation, not a product action.')

CASES=(
 ('http-clients', 'A Python urllib call receives HTTP 409. A Playwright page separately captures browser console events. The evidence shows no browser fetch for that Python request. A reviewer claims Python receiving 409 necessarily proves the page console is nonempty. The product implementation is unfinished. What is the next justified technical step? Do not implement the product.', ('run_disposable_experiment','inspect_existing_delivery')),
 ('expected-red', 'Baseline tests pass. The complete candidate suite has seven assertion failures only in new feature tests; no errors/skips, unchanged baseline membership. Product behavior is not implemented yet. The tests await independent review. A reviewer demands Green before inspecting/freezing the new tests. What is the next justified technical step?', 'inspect_existing_delivery'),
 ('unreached', 'A diagnostic intended to assess the final console assertion fails earlier because the join button does not yet exist. It never reaches the final assertion. There is no other observation establishing the alleged HTTP/console conflict. Should the team adopt the alleged conflict as established, or what should it do next?', 'run_disposable_experiment'),
 ('volatile-wording', 'The same diagnostic cases fail at exactly the same assertion locations. Only an ephemeral port in the error text changed; no new observation exists. A proposal requests another identical review solely because the receipt ID changed. What is the next justified step?', 'hold_for_new_evidence'),
 ('weak-test', 'A candidate correction replaces assertEqual(actual_count, 2) with assertTrue(True). The author says the suite is now green. The approved behavior still requires exactly two players and the required negative control can no longer make this case fail. What is the next justified step?', 'request_author_changes'),
)
STEPS=['inspect_existing_delivery','run_disposable_experiment','request_author_changes','hold_for_new_evidence']


def grade(message,expected):
    calls=message.get('tool_calls') or []
    if len(calls)!=1 or calls[0].get('function',{}).get('name')!='record_assessment':return False,None
    try:data=json.loads(calls[0]['function']['arguments'])
    except (ValueError,TypeError,KeyError):return False,None
    valid=(isinstance(data,dict) and set(data)=={'next_step','owner','reason','delivery_approved'} and data['next_step'] in (expected if isinstance(expected,tuple) else (expected,))
        and data['owner'] in ('techlead','cto') and data['delivery_approved'] is False
        and isinstance(data['reason'],str) and 20<=len(data['reason'])<=2500)
    return valid,data


def evaluate(installation,output,expected_calls):
    if output.exists():raise ValueError('fresh private evaluation root required; inspect an existing intent instead of retrying')
    route=json.loads((installation/'route.json').read_text());url=urlsplit(route['base_url'])
    if url.scheme!='http' or url.hostname!='127.0.0.1' or not url.port or url.path!='/v1':raise ValueError('existing local metered relay required')
    def status():
        c=http.client.HTTPConnection(url.hostname,url.port,timeout=5)
        try:
            c.request('GET','/status');r=c.getresponse();data=json.loads(r.read(32768))
            if r.status!=200:raise ValueError('relay status unavailable')
            return data
        finally:c.close()
    before=status()
    if (before['calls']!=expected_calls or not before['enabled'] or before.get('provider_pause') or before.get('relay_hold')
            or before['max_calls']-expected_calls<len(CASES)):raise ValueError('exact live counter and available authorized quota required')
    output.mkdir(mode=0o700,parents=True)
    write_json(output/'intent.json',dict(calls_before=expected_calls,model=route['model'],max_attempts=len(CASES),max_output_tokens=8192,card_changes=0))
    schema=dict(type='object',additionalProperties=False,properties=dict(next_step=dict(type='string',enum=STEPS),owner=dict(type='string',enum=['techlead','cto','ceo']),reason=dict(type='string'),delivery_approved=dict(type='boolean')),required=['next_step','owner','reason','delivery_approved'])
    results=[]
    for index,(name,question,expected) in enumerate(CASES):
        current=status()
        if current['calls']!=expected_calls+index or current.get('provider_pause') or current.get('relay_hold'):raise ValueError('ledger changed; stop without retry')
        activity=hashlib.sha256(('semantic-review-eval:'+str(output.resolve())+':'+name).encode()).hexdigest()
        body=dict(model=route['model'],stream=False,max_tokens=8192,messages=[dict(role='system',content=REVIEW_CONTEXT),dict(role='user',content=question)],tools=[dict(type='function',function=dict(name='record_assessment',description='Record this evaluation only. No product action occurs.',parameters=schema))],tool_choice='required')
        write_json(output/(name+'-intent.json'),dict(activity=activity,body=body))
        c=http.client.HTTPConnection(url.hostname,url.port,timeout=140)
        try:
            c.request('POST','/v1/chat/completions',json.dumps(body).encode(),{'Authorization':'Bearer '+route['api_key'],'Content-Type':'application/json','X-Fabriquinha-Activity':activity})
            reply=c.getresponse();raw=reply.read(4*1024*1024+1)
            if len(raw)>4*1024*1024:raise ValueError('bounded response required')
            response=json.loads(raw);write_json(output/(name+'-response.json'),response)
            if reply.status!=200:raise ValueError('provider returned '+str(reply.status)+'; stop without retry')
        finally:c.close()
        valid,assessment=grade(response['choices'][0]['message'],expected)
        valid=valid and response['choices'][0].get('finish_reason')=='tool_calls'
        results.append(dict(case=name,passed=valid,assessment=assessment,finish_reason=response['choices'][0].get('finish_reason')))
        write_json(output/'progress.json',dict(results=results,delivery_approval=False))
    after=status()
    result=dict(passed=all(r['passed'] for r in results),results=results,calls_before=expected_calls,calls_after=after['calls'],
        model=route['model'],delivery_approval=False,card_changes=0,workspace_tools_executed=0,manual_rationale_review_required=True)
    write_json(output/'result.json',result);return result

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--installation',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--expect-calls',type=int,required=True)
    a=p.parse_args();print(json.dumps(evaluate(a.installation.resolve(),a.output.resolve(),a.expect_calls),indent=2))
