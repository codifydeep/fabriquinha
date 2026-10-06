"""Fixed HTTP suite; no agent-supplied URL, shell or cases."""
import json,urllib.request,urllib.error

CASES=[('/health',200,None),('/capacity?n=0',200,False),('/capacity?n=1',200,True),
       ('/capacity?n=2',200,False),('/capacity?n=-1',200,False),('/capacity?n=100',200,False),
       ('/capacity?n=abc',400,None),('/capacity?n=1.5',400,None),('/capacity',400,None),
       ('/capacity?n=1&n=2',400,None),('/capacity?n=1&other=2',400,None),('/unknown',404,None)]

def validate(fetch,commit):
    results=[]
    for path,expected,value in CASES:
        code,body=fetch(path)
        ok=code==expected and body.get('commit')==commit
        if value is not None:ok=ok and body.get('capacity') is value
        if path=='/health':ok=ok and body.get('status')=='ok'
        results.append(dict(path=path,passed=ok,status=code,body=body))
    return dict(commit=commit,passed=all(r['passed'] for r in results),cases=results,release_homologated=False)

def probe(endpoint,commit):
    def fetch(path):
        try:
            with urllib.request.urlopen(endpoint+path,timeout=5) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)
    return validate(fetch,commit)
