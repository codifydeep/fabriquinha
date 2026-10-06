"""Fixed live verification, executed with no credentials/socket."""
import json
import os
import urllib.request
import urllib.error

def fetch(path):
    try:
        with urllib.request.urlopen('http://127.0.0.1:8080'+path,timeout=3) as response:
            return response.status,json.load(response)
    except urllib.error.HTTPError as exc: return exc.code,json.load(exc)

expected=os.environ['EXPECTED_COMMIT']
code,data=fetch('/health'); assert code==200 and data==dict(status='ok',commit=expected)
count=1
if os.environ.get('BASELINE_ONLY')!='1':
    for a,b,value in [(0,0,None),(12,0,'A'),(0,12,'B'),(12,13,'A'),(11,11,None)]:
        code,data=fetch(f'/winner?a={a}&b={b}')
        assert code==200 and data==dict(winner=value,commit=expected); count+=1
    for path,expected_code in [('/winner?a=-1&b=0',400),('/winner?a=x&b=0',400),('/winner?a=1',400),('/missing',404)]:
        assert fetch(path)[0]==expected_code; count+=1
print(json.dumps(dict(passed=True,checks=count,commit=expected)))
